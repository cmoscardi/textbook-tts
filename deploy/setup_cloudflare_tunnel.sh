#!/usr/bin/env bash
set -euo pipefail

# Create a Cloudflare Tunnel and configure DNS for the ML service.
# This only needs to be run once. After setup, the tunnel token is saved
# to .env.production and cloudflared runs as a Docker service.
#
# Prerequisites:
#   - CF_API_TOKEN with permissions: Zone:DNS:Edit, Account:Cloudflare Tunnel:Edit
#   - CF_ZONE_ID and CF_ACCOUNT_ID in .env.production

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
ENV_FILE="$REPO_ROOT/.env.production"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: $ENV_FILE not found" >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

required_vars=(CF_API_TOKEN CF_ACCOUNT_ID CF_ZONE_ID)
for var in "${required_vars[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "Error: required variable '$var' is not set in $ENV_FILE" >&2
    exit 1
  fi
done

TUNNEL_NAME="ml-service"
TUNNEL_HOSTNAME="ml-tunnel.textbook-tts.com"
# cloudflared connects to ml-api on the Docker network
TUNNEL_ORIGIN="http://ml-api-prod:8001"

echo "=== Cloudflare Tunnel Setup ==="

# ---------- 1. Install cloudflared (if not present) ----------
if ! command -v cloudflared &>/dev/null; then
  echo "Installing cloudflared..."
  if [[ "$(uname)" == "Darwin" ]]; then
    brew install cloudflared
  else
    # Debian/Ubuntu
    curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
    sudo dpkg -i /tmp/cloudflared.deb
    rm /tmp/cloudflared.deb
  fi
fi
echo "cloudflared version: $(cloudflared --version)"

# ---------- 2. Create the tunnel ----------
echo "Creating tunnel '$TUNNEL_NAME'..."

# Check if tunnel already exists
EXISTING=$(curl --silent --show-error \
  --request GET \
  "https://api.cloudflare.com/client/v4/accounts/${CF_ACCOUNT_ID}/cfd_tunnel?name=${TUNNEL_NAME}&is_deleted=false" \
  --header "Authorization: Bearer ${CF_API_TOKEN}" \
  --header "Content-Type: application/json")

EXISTING_ID=$(echo "$EXISTING" | jq -r '.result[0].id // empty')

if [[ -n "$EXISTING_ID" ]]; then
  echo "Tunnel '$TUNNEL_NAME' already exists (ID: $EXISTING_ID)"
  TUNNEL_ID="$EXISTING_ID"
else
  # Generate a random 32-byte secret for the tunnel
  TUNNEL_SECRET=$(openssl rand -base64 32)

  CREATE_RESULT=$(curl --silent --show-error \
    --request POST \
    "https://api.cloudflare.com/client/v4/accounts/${CF_ACCOUNT_ID}/cfd_tunnel" \
    --header "Authorization: Bearer ${CF_API_TOKEN}" \
    --header "Content-Type: application/json" \
    --data "$(jq -n \
      --arg name "$TUNNEL_NAME" \
      --arg secret "$TUNNEL_SECRET" \
      '{name: $name, tunnel_secret: $secret, config_src: "cloudflare"}'
    )")

  TUNNEL_ID=$(echo "$CREATE_RESULT" | jq -r '.result.id // empty')
  if [[ -z "$TUNNEL_ID" ]]; then
    echo "Error creating tunnel:" >&2
    echo "$CREATE_RESULT" | jq . >&2
    exit 1
  fi
  echo "Created tunnel: $TUNNEL_ID"
fi

# ---------- 3. Configure the tunnel (ingress rules) ----------
echo "Configuring tunnel ingress..."
CONFIG_RESULT=$(curl --silent --show-error \
  --request PUT \
  "https://api.cloudflare.com/client/v4/accounts/${CF_ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}/configurations" \
  --header "Authorization: Bearer ${CF_API_TOKEN}" \
  --header "Content-Type: application/json" \
  --data "$(jq -n \
    --arg hostname "$TUNNEL_HOSTNAME" \
    --arg origin "$TUNNEL_ORIGIN" \
    '{config: {ingress: [
      {hostname: $hostname, service: $origin},
      {service: "http_status:404"}
    ]}}'
  )")

if echo "$CONFIG_RESULT" | jq -e '.success' >/dev/null 2>&1; then
  echo "Tunnel ingress configured."
else
  echo "Warning: tunnel config response:" >&2
  echo "$CONFIG_RESULT" | jq . >&2
fi

# ---------- 4. Create DNS CNAME record ----------
echo "Creating DNS record: $TUNNEL_HOSTNAME -> tunnel..."
DNS_RESULT=$(curl --silent --show-error \
  --request POST \
  "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/dns_records" \
  --header "Authorization: Bearer ${CF_API_TOKEN}" \
  --header "Content-Type: application/json" \
  --data "$(jq -n \
    --arg name "$TUNNEL_HOSTNAME" \
    --arg content "${TUNNEL_ID}.cfargotunnel.com" \
    '{type: "CNAME", name: $name, content: $content, proxied: true, ttl: 1}'
  )")

if echo "$DNS_RESULT" | jq -e '.success' >/dev/null 2>&1; then
  echo "DNS record created."
elif echo "$DNS_RESULT" | jq -r '.errors[0].message' 2>/dev/null | grep -qi "already exists"; then
  echo "DNS record already exists."
else
  echo "Warning: DNS response:" >&2
  echo "$DNS_RESULT" | jq . >&2
fi

# ---------- 5. Get the tunnel token ----------
echo "Fetching tunnel token..."
TOKEN_RESULT=$(curl --silent --show-error \
  --request GET \
  "https://api.cloudflare.com/client/v4/accounts/${CF_ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}/token" \
  --header "Authorization: Bearer ${CF_API_TOKEN}" \
  --header "Content-Type: application/json")

TUNNEL_TOKEN=$(echo "$TOKEN_RESULT" | jq -r '.result // empty')

if [[ -z "$TUNNEL_TOKEN" ]]; then
  echo "Error: could not retrieve tunnel token" >&2
  echo "$TOKEN_RESULT" | jq . >&2
  exit 1
fi

# ---------- 6. Save token to .env.production ----------
if grep -q '^CF_TUNNEL_TOKEN=' "$ENV_FILE"; then
  sed -i.bak "s|^CF_TUNNEL_TOKEN=.*|CF_TUNNEL_TOKEN=${TUNNEL_TOKEN}|" "$ENV_FILE"
  rm -f "${ENV_FILE}.bak"
  echo "Updated CF_TUNNEL_TOKEN in $ENV_FILE"
else
  echo "" >> "$ENV_FILE"
  echo "CF_TUNNEL_TOKEN=${TUNNEL_TOKEN}" >> "$ENV_FILE"
  echo "Appended CF_TUNNEL_TOKEN to $ENV_FILE"
fi

echo ""
echo "=== Setup Complete ==="
echo "Tunnel ID:   $TUNNEL_ID"
echo "Hostname:    $TUNNEL_HOSTNAME"
echo "Origin:      $TUNNEL_ORIGIN"
echo ""
echo "The tunnel token has been saved to .env.production."
echo "Run 'docker compose -f docker-compose.prod.yml up -d cloudflared' to start the tunnel."

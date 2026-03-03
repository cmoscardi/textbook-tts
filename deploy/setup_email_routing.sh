#!/usr/bin/env bash
set -euo pipefail

# Deploy the Cloudflare Email Worker and configure email routing.
# Runs wrangler inside Docker so no local Node.js install is needed.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
ENV_FILE="$REPO_ROOT/.env.production"
WORKER_DIR="$REPO_ROOT/cloudflare/email-worker"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: $ENV_FILE not found" >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

# Validate required variables
required_vars=(
  CF_API_TOKEN
  CF_ZONE_ID
  MLSERVICE_AUTH_KEY
)

for var in "${required_vars[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "Error: required variable '$var' is not set in $ENV_FILE" >&2
    exit 1
  fi
done

IMAGE_NAME="textbook-tts-email-worker"

# ---------- 1. Build the Docker image ----------
echo "Building email worker Docker image..."
docker build -t "$IMAGE_NAME" "$WORKER_DIR"

# ---------- 2. Deploy the worker ----------
echo "Deploying email worker to Cloudflare..."
docker run --rm \
  -e CLOUDFLARE_API_TOKEN="$CF_API_TOKEN" \
  "$IMAGE_NAME" \
  deploy

# ---------- 3. Set the MLSERVICE_AUTH_KEY secret ----------
echo "Setting MLSERVICE_AUTH_KEY secret..."
echo "$MLSERVICE_AUTH_KEY" | docker run --rm -i \
  -e CLOUDFLARE_API_TOKEN="$CF_API_TOKEN" \
  "$IMAGE_NAME" \
  secret put MLSERVICE_AUTH_KEY

# ---------- 4. Enable Email Routing on the zone (idempotent) ----------
echo "Enabling Email Routing..."
response=$(curl --silent --show-error --write-out "\n%{http_code}" \
  --request PUT \
  "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/email/routing/enable" \
  --header "Authorization: Bearer ${CF_API_TOKEN}" \
  --header "Content-Type: application/json" \
  --data '{"enabled": true}')

http_code="${response##*$'\n'}"
body="${response%$'\n'*}"

if [[ "$http_code" -ge 400 ]]; then
  echo "Warning: Enable email routing returned HTTP $http_code (may already be enabled)" >&2
  echo "$body" >&2
fi

# ---------- 5. Create routing rule: add@textbook-tts.com -> Worker ----------
echo "Creating email routing rule..."
response=$(curl --silent --show-error --write-out "\n%{http_code}" \
  --request POST \
  "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/email/routing/rules" \
  --header "Authorization: Bearer ${CF_API_TOKEN}" \
  --header "Content-Type: application/json" \
  --data '{
    "name": "Ingest to textbook-tts",
    "enabled": true,
    "matchers": [{"type": "literal", "field": "to", "value": "add@textbook-tts.com"}],
    "actions": [{"type": "worker", "value": ["textbook-tts-email-ingest"]}]
  }')

http_code="${response##*$'\n'}"
body="${response%$'\n'*}"

if [[ "$http_code" -ge 400 ]]; then
  echo "Error: Create routing rule returned HTTP $http_code" >&2
  echo "$body" >&2
  exit 1
fi

echo "Done. Email routing rule created:"
echo "$body" | jq '.result | {id, name, enabled, matchers, actions}' 2>/dev/null || echo "$body"

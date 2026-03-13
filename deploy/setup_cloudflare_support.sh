#!/usr/bin/env bash
set -euo pipefail

# Sets up a Cloudflare email routing rule to forward
# support@textbook-tts.com -> moscardi79+ttssupport@gmail.com

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
ENV_FILE="$REPO_ROOT/.env.production"

DEST_ADDRESS="moscardi79+ttssupport@gmail.com"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: $ENV_FILE not found" >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

for var in CF_API_TOKEN CF_ZONE_ID; do
  if [[ -z "${!var:-}" ]]; then
    echo "Error: required variable '$var' is not set in $ENV_FILE" >&2
    exit 1
  fi
done


# ---------- 1. Resolve account ID ----------
echo "Resolving account ID for zone..."
ACCOUNT_ID=$(curl --silent --fail \
  "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}" \
  --header "Authorization: Bearer ${CF_API_TOKEN}" \
  | jq -r '.result.account.id')

if [[ -z "$ACCOUNT_ID" || "$ACCOUNT_ID" == "null" ]]; then
  echo "Error: Could not resolve account ID from zone ${CF_ZONE_ID}" >&2
  exit 1
fi

# ---------- 2. Register destination address (triggers verification email) ----------
# If already registered, Cloudflare returns the existing record rather than an error.
echo "Registering destination address $DEST_ADDRESS ..."
response=$(curl --silent --show-error --write-out "\n%{http_code}" \
  --request POST \
  "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/email/routing/addresses" \
  --header "Authorization: Bearer ${CF_API_TOKEN}" \
  --header "Content-Type: application/json" \
  --data "{\"email\": \"$DEST_ADDRESS\"}")

http_code="${response##*$'\n'}"
body="${response%$'\n'*}"

if [[ "$http_code" -ge 400 ]]; then
  echo "Error: Could not register destination address (HTTP $http_code)" >&2
  echo "$body" >&2
  exit 1
fi

verified=$(echo "$body" | jq -r '.result.verified' 2>/dev/null || true)
if [[ "$verified" == "true" ]]; then
  echo "Destination address is already verified — no email needed."
else
  echo "Verification email sent to $DEST_ADDRESS — click the link in it before forwarding will work."
fi

# ---------- 3. Create the forwarding rule ----------
echo "Creating email routing rule: support@textbook-tts.com -> $DEST_ADDRESS ..."
response=$(curl --silent --show-error --write-out "\n%{http_code}" \
  --request POST \
  "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/email/routing/rules" \
  --header "Authorization: Bearer ${CF_API_TOKEN}" \
  --header "Content-Type: application/json" \
  --data "{
    \"name\": \"Forward support to Gmail\",
    \"enabled\": true,
    \"matchers\": [{\"type\": \"literal\", \"field\": \"to\", \"value\": \"support@textbook-tts.com\"}],
    \"actions\": [{\"type\": \"forward\", \"value\": [\"$DEST_ADDRESS\"]}]
  }")

http_code="${response##*$'\n'}"
body="${response%$'\n'*}"

if [[ "$http_code" -ge 400 ]]; then
  echo "Error: Create routing rule returned HTTP $http_code" >&2
  echo "$body" >&2
  exit 1
fi

echo "Done. Routing rule created:"
echo "$body" | jq '.result | {id, name, enabled, matchers, actions}' 2>/dev/null || echo "$body"

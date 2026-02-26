#!/usr/bin/env bash
set -euo pipefail

# Load environment variables from .env.production
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env.production"

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
  SUPABASE_ACCESS_TOKEN
  PROJECT_REF
  captcha_secret
)

for var in "${required_vars[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "Error: required variable '$var' is not set in $ENV_FILE" >&2
    exit 1
  fi
done

echo "Enabling Cloudflare Turnstile CAPTCHA for project $PROJECT_REF..."

response=$(curl --silent --show-error --fail-with-body \
  --request PATCH \
  --url "https://api.supabase.com/v1/projects/${PROJECT_REF}/config/auth" \
  --header "Authorization: Bearer ${SUPABASE_ACCESS_TOKEN}" \
  --header "Content-Type: application/json" \
  --data "$(jq -n \
    --arg secret "$captcha_secret" \
    '{
      security_captcha_enabled:  true,
      security_captcha_provider: "turnstile",
      security_captcha_secret:   $secret
    }'
  )"
)

echo "Done. CAPTCHA config:"
echo "$response" | jq '{security_captcha_enabled, security_captcha_provider}'

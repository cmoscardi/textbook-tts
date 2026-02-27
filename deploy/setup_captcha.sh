#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOCAL=false
if [[ "${1:-}" == "--local" ]]; then
  LOCAL=true
fi

# ---------------------------------------------------------------------------
# LOCAL: update supabase/config.toml with Cloudflare test secret
# ---------------------------------------------------------------------------
if $LOCAL; then
  CONFIG_FILE="$SCRIPT_DIR/../supabase/config.toml"

  if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Error: $CONFIG_FILE not found" >&2
    exit 1
  fi

  # Use Cloudflare's always-pass test secret for local dev
  local_secret="1x0000000000000000000000000000000AA"

  echo "Configuring Turnstile CAPTCHA in $CONFIG_FILE (local dev)..."

  python3 - "$CONFIG_FILE" "$local_secret" <<'PYEOF'
import sys, re

config_file, secret = sys.argv[1], sys.argv[2]
content = open(config_file).read()

block = f"""
[auth.captcha]
enabled = true
provider = "turnstile"
secret = "{secret}"
"""

# Remove any existing [auth.captcha] section (up to but not including next section)
content = re.sub(r'\n\[auth\.captcha\][^\[]*', '', content)
content = content.rstrip('\n') + '\n' + block

open(config_file, 'w').write(content)
PYEOF

  echo "Done. supabase/config.toml updated."
  echo "Restart your local Supabase instance to apply: supabase stop && supabase start"
  exit 0
fi

# ---------------------------------------------------------------------------
# PRODUCTION: call the Supabase Management API
# ---------------------------------------------------------------------------
ENV_FILE="$SCRIPT_DIR/../.env.production"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: $ENV_FILE not found" >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

required_vars=(SUPABASE_ACCESS_TOKEN PROJECT_REF captcha_secret)
for var in "${required_vars[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "Error: required variable '$var' is not set in $ENV_FILE" >&2
    exit 1
  fi
done

echo "Enabling Cloudflare Turnstile CAPTCHA for project $PROJECT_REF..."

response=$(curl --silent --show-error --write-out "\n%{http_code}" \
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

http_code="${response##*$'\n'}"
body="${response%$'\n'*}"

if [[ "$http_code" -ge 400 ]]; then
  echo "Error: API returned HTTP $http_code" >&2
  echo "$body" >&2
  exit 1
fi

echo "Done. CAPTCHA config:"
echo "$body" | jq '{security_captcha_enabled, security_captcha_provider}'

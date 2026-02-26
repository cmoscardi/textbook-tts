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
  smtp_admin_email
  smtp_host
  smtp_port
  smtp_user
  smtp_pass
  smtp_sender_name
)

for var in "${required_vars[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "Error: required variable '$var' is not set in $ENV_FILE" >&2
    exit 1
  fi
done

echo "Configuring SMTP for project $PROJECT_REF..."

response=$(curl --silent --show-error --fail-with-body \
  --request PATCH \
  --url "https://api.supabase.com/v1/projects/${PROJECT_REF}/config/auth" \
  --header "Authorization: Bearer ${SUPABASE_ACCESS_TOKEN}" \
  --header "Content-Type: application/json" \
  --data "$(jq -n \
    --arg admin_email  "$smtp_admin_email" \
    --arg host         "$smtp_host" \
    --argjson port     "$smtp_port" \
    --arg user         "$smtp_user" \
    --arg pass         "$smtp_pass" \
    --arg sender_name  "$smtp_sender_name" \
    '{
      smtp_admin_email: $admin_email,
      smtp_host:        $host,
      smtp_port:        $port,
      smtp_user:        $user,
      smtp_pass:        $pass,
      smtp_sender_name: $sender_name
    }'
  )"
)

echo "Done. Supabase auth config updated:"
echo "$response" | jq '{smtp_host, smtp_port, smtp_user, smtp_admin_email, smtp_sender_name}'

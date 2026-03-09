#!/bin/bash
# reset-subscription.sh
# Completely resets a user's subscription in Stripe and the local Supabase DB.
# Usage: ./reset-subscription.sh <email>

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <email>"
  exit 1
fi

EMAIL="$1"
ENV_FILE="$SCRIPT_DIR/.env.development"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: .env.development not found at $ENV_FILE"
  exit 1
fi

# Extract a plain (unquoted) value from .env.development
get_env() {
  grep "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'
}

STRIPE_KEY=$(get_env STRIPE_SECRET_KEY)
POSTGRES_PASSWORD=$(get_env POSTGRES_PASSWORD)
PGCONN="postgresql://postgres:${POSTGRES_PASSWORD}@localhost:54322/postgres"

stripe_delete() {
  local url="$1"
  local response
  response=$(curl -s -w "\n%{http_code}" -X DELETE "$url" -u "$STRIPE_KEY:")
  local body http_code
  body=$(echo "$response" | head -n -1)
  http_code=$(echo "$response" | tail -n 1)
  if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ]; then
    echo "  OK ($http_code)"
  else
    echo "  Warning: HTTP $http_code — $body"
  fi
}

echo "==> Looking up user: $EMAIL"

USER_ID=$(psql "$PGCONN" -t -A -c "SELECT id::text FROM auth.users WHERE email = E'$(printf '%s' "$EMAIL" | sed "s/'/''/g")' LIMIT 1")

if [ -z "$USER_ID" ]; then
  echo "Error: No user found with email '$EMAIL'"
  exit 1
fi
echo "    user_id: $USER_ID"

# Fetch Stripe IDs
read -r STRIPE_CUSTOMER_ID STRIPE_SUBSCRIPTION_ID < <(psql "$PGCONN" -t -A -F' ' \
  -c "SELECT coalesce(stripe_customer_id,''), coalesce(stripe_subscription_id,'')
      FROM user_profiles WHERE user_id = '$USER_ID' LIMIT 1")

echo "    stripe_customer_id:      ${STRIPE_CUSTOMER_ID:-none}"
echo "    stripe_subscription_id:  ${STRIPE_SUBSCRIPTION_ID:-none}"

# --- Stripe cleanup ---
if [ -n "$STRIPE_SUBSCRIPTION_ID" ]; then
  echo "==> Canceling Stripe subscription $STRIPE_SUBSCRIPTION_ID..."
  stripe_delete "https://api.stripe.com/v1/subscriptions/$STRIPE_SUBSCRIPTION_ID"
fi

if [ -n "$STRIPE_CUSTOMER_ID" ]; then
  echo "==> Deleting Stripe customer $STRIPE_CUSTOMER_ID..."
  stripe_delete "https://api.stripe.com/v1/customers/$STRIPE_CUSTOMER_ID"
fi

# --- DB cleanup ---
echo "==> Resetting user_profiles..."
psql "$PGCONN" -c "
  UPDATE user_profiles SET
    stripe_customer_id     = NULL,
    stripe_subscription_id = NULL,
    subscription_tier      = 'free',
    subscription_status    = NULL,
    current_period_start   = NULL,
    current_period_end     = NULL,
    cancel_at_period_end   = false
  WHERE user_id = '$USER_ID'
"

echo "==> Deleting usage_tracking records..."
psql "$PGCONN" -c "DELETE FROM usage_tracking WHERE user_id = '$USER_ID'"

echo ""
echo "Done. '$EMAIL' has been reset to free tier."

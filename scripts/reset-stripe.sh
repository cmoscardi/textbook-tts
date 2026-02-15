#!/usr/bin/env bash
set -euo pipefail

# Load variables from .env.development
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env.development"

get_env() {
  grep "^$1=" "$ENV_FILE" | cut -d= -f2- | tr -d '"'
}

STRIPE_SECRET_KEY=$(get_env STRIPE_SECRET_KEY)
POSTGRES_USER=$(get_env POSTGRES_USER)
POSTGRES_PASSWORD=$(get_env POSTGRES_PASSWORD)
POSTGRES_DB=$(get_env POSTGRES_DB)
# .env.development uses the Docker-internal hostname; from the host, use localhost:54322
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=54322

DB_URL="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@$POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB"

EMAIL="${1:-}"
if [ -z "$EMAIL" ]; then
  echo "Usage: $0 <email>"
  exit 1
fi

echo "==> Finding Stripe customer for $EMAIL..."
CUSTOMER_ID=$(stripe customers list --api-key "$STRIPE_SECRET_KEY" -d email="$EMAIL" --limit 1 | jq -r '.data[0].id // empty')

if [ -z "$CUSTOMER_ID" ]; then
  echo "No Stripe customer found for $EMAIL"
else
  echo "Found customer: $CUSTOMER_ID"

  echo "==> Cancelling active subscriptions..."
  SUB_IDS=$(stripe subscriptions list --api-key "$STRIPE_SECRET_KEY" -d "customer=$CUSTOMER_ID" | jq -r '.data[].id // empty')
  for SUB_ID in $SUB_IDS; do
    echo "  Cancelling $SUB_ID"
    stripe subscriptions cancel "$SUB_ID" --api-key "$STRIPE_SECRET_KEY" --confirm > /dev/null
  done

  echo "==> Deleting customer $CUSTOMER_ID..."
  stripe customers delete "$CUSTOMER_ID" --api-key "$STRIPE_SECRET_KEY" --confirm > /dev/null
fi

echo "==> Resetting user_profiles in local DB..."
psql "$DB_URL" -c "
  UPDATE user_profiles
  SET stripe_customer_id = NULL,
      stripe_subscription_id = NULL,
      subscription_tier = 'free',
      subscription_status = NULL,
      current_period_start = NULL,
      current_period_end = NULL,
      cancel_at_period_end = false
  WHERE stripe_customer_id = '$CUSTOMER_ID'
    OR user_id IN (SELECT id FROM auth.users WHERE email = '$EMAIL');
"

echo "==> Cleaning up stripe_events..."
psql "$DB_URL" -c "DELETE FROM stripe_events;"

echo "Done! You can retry checkout now."

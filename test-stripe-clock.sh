#!/bin/bash
# test-stripe-clock.sh
# Tests subscription lifecycle (renewal / cancellation) using a Stripe test clock.
#
# NOTE: Stripe test clocks require the customer to be created on the clock — you
# cannot retroactively attach an existing customer. This script creates a fresh
# test-clock-backed customer + subscription via the Stripe API, then writes the
# IDs directly into user_profiles. All webhook handling (renewal, cancellation,
# usage reset) is exercised normally from that point forward.
#
# Prerequisites:
#   stripe listen --forward-to http://localhost:54321/functions/v1/stripe-webhook
#   (must be running in another terminal for clock events to reach local functions)
#
# Usage: ./test-stripe-clock.sh <email>

set -euo pipefail
trap 'echo "Error on line $LINENO: $BASH_COMMAND" >&2' ERR

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <email>"
  exit 1
fi

EMAIL="$1"
ENV_FILE="$SCRIPT_DIR/.env.development"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: .env.development not found"
  exit 1
fi

get_env() {
  grep "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'
}

STRIPE_KEY=$(get_env STRIPE_SECRET_KEY)
STRIPE_PRICE_ID=$(get_env STRIPE_PRICE_ID_PRO)
POSTGRES_PASSWORD=$(get_env POSTGRES_PASSWORD)
PGCONN="postgresql://postgres:${POSTGRES_PASSWORD}@localhost:54322/postgres"

human_date() {
  date -r "$1" "+%Y-%m-%d %H:%M:%S" 2>/dev/null || date -d "@$1" "+%Y-%m-%d %H:%M:%S"
}

stripe_post() {
  local url="$1"; shift
  local response
  response=$(curl -s -X POST "$url" -u "$STRIPE_KEY:" "$@")
  if echo "$response" | jq -e '.error' > /dev/null 2>&1; then
    echo "Stripe error ($url): $(echo "$response" | jq -r '.error.message')" >&2
    exit 1
  fi
  echo "$response"
}

stripe_get() {
  curl -s "$1" -u "$STRIPE_KEY:"
}

# ── 1. Look up user ────────────────────────────────────────────────────────────
echo "==> Looking up user: $EMAIL"
USER_ID=$(psql "$PGCONN" -t -A \
  -c "SELECT id::text FROM auth.users WHERE email = E'$(printf '%s' "$EMAIL" | sed "s/'/''/g")' LIMIT 1")
if [ -z "$USER_ID" ]; then
  echo "Error: No user found with email '$EMAIL'"
  exit 1
fi
echo "    user_id: $USER_ID"

# ── 2. Create test clock ───────────────────────────────────────────────────────
FROZEN_TIME=$(date +%s)
echo "==> Creating test clock (frozen at $(human_date $FROZEN_TIME))..."
CLOCK=$(stripe_post "https://api.stripe.com/v1/test_helpers/test_clocks" \
  -d "frozen_time=$FROZEN_TIME" \
  -d "name=test-clock-${EMAIL}")
CLOCK_ID=$(echo "$CLOCK" | jq -r '.id')
echo "    clock_id: $CLOCK_ID"

# ── 3. Create customer on the clock ───────────────────────────────────────────
echo "==> Creating customer on test clock..."
CUSTOMER=$(stripe_post "https://api.stripe.com/v1/customers" \
  -d "email=$EMAIL" \
  -d "test_clock=$CLOCK_ID")
CUSTOMER_ID=$(echo "$CUSTOMER" | jq -r '.id')
echo "    customer_id: $CUSTOMER_ID"

# ── 4. Attach test card ────────────────────────────────────────────────────────
echo "==> Attaching test payment method (pm_card_visa)..."
PM=$(stripe_post "https://api.stripe.com/v1/payment_methods" \
  -d "type=card" \
  -d "card[token]=tok_visa")
PM_ID=$(echo "$PM" | jq -r '.id')

stripe_post "https://api.stripe.com/v1/payment_methods/$PM_ID/attach" \
  -d "customer=$CUSTOMER_ID" > /dev/null

stripe_post "https://api.stripe.com/v1/customers/$CUSTOMER_ID" \
  -d "invoice_settings[default_payment_method]=$PM_ID" > /dev/null

# ── 5. Create subscription ─────────────────────────────────────────────────────
echo "==> Creating subscription..."
SUB=$(stripe_post "https://api.stripe.com/v1/subscriptions" \
  -d "customer=$CUSTOMER_ID" \
  -d "items[0][price]=$STRIPE_PRICE_ID" \
  -d "default_payment_method=$PM_ID")
SUB_ID=$(echo "$SUB" | jq -r '.id')
SUB_STATUS=$(echo "$SUB" | jq -r '.status')
PERIOD_START=$(echo "$SUB" | jq -r '.items.data[0].current_period_start')
PERIOD_END=$(echo "$SUB" | jq -r '.items.data[0].current_period_end')

echo "    subscription_id: $SUB_ID"
echo "    status:          $SUB_STATUS"
echo "    period:          $(human_date $PERIOD_START) → $(human_date $PERIOD_END)"

# ── 6. Write into user_profiles and reset usage ────────────────────────────────
echo "==> Updating user_profiles and clearing usage_tracking..."
psql "$PGCONN" -c "
  UPDATE user_profiles SET
    stripe_customer_id     = '$CUSTOMER_ID',
    stripe_subscription_id = '$SUB_ID',
    subscription_tier      = 'pro',
    subscription_status    = '$SUB_STATUS',
    current_period_start   = to_timestamp($PERIOD_START),
    current_period_end     = to_timestamp($PERIOD_END),
    cancel_at_period_end   = false
  WHERE user_id = '$USER_ID'
"
psql "$PGCONN" -c "DELETE FROM usage_tracking WHERE user_id = '$USER_ID'" > /dev/null

# ── 7. Pause for optional cancellation ────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  User '$EMAIL' is now on Pro (test clock subscription)."
echo ""
echo "  Stripe dashboard:"
echo "    https://dashboard.stripe.com/test/customers/$CUSTOMER_ID"
echo ""
echo "  To test CANCELLATION at period end:"
echo "    → Cancel the subscription in the Stripe dashboard (at period end)."
echo "    → The cancel webhook will update user_profiles automatically."
echo ""
echo "  To test RENEWAL + usage reset:"
echo "    → Upload some files to test that the page quota resets."
echo ""
echo "  Press Enter when ready to advance the clock 1 day past period end..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
read -r

# ── 8. Advance the clock 1 day past period end ────────────────────────────────
NEW_TIME=$((PERIOD_END + 86400))
echo "==> Advancing clock to $(human_date $NEW_TIME) (1 day past period end)..."
stripe_post "https://api.stripe.com/v1/test_helpers/test_clocks/$CLOCK_ID/advance" \
  -d "frozen_time=$NEW_TIME" > /dev/null

# Poll until clock reaches 'ready' (Stripe processes all events synchronously)
echo "    Waiting for Stripe to finish processing events..."
for i in $(seq 1 30); do
  STATUS=$(stripe_get "https://api.stripe.com/v1/test_helpers/test_clocks/$CLOCK_ID" | jq -r '.status')
  if [ "$STATUS" = "ready" ]; then
    echo "    Clock ready — all events fired."
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "    Warning: clock still not ready after 60s."
  fi
  sleep 2
done

echo ""
echo "Done. Stripe has fired all billing events for the advanced time."
echo "Check your app to verify:"
echo "  • Renewal:      Pro plan, usage reset to 0, new period end ~1 month out"
echo "  • Cancellation: Free plan, stripe IDs cleared"
echo ""
echo "Cleanup:"
echo "  ./reset-subscription.sh $EMAIL"
echo "  Delete test clock: https://dashboard.stripe.com/test/test-clocks"

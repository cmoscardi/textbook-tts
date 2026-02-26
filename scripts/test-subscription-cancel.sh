#!/usr/bin/env bash
set -euo pipefail

# Test: Verify subscription cancellation triggers webhook downgrade to free tier
#
# Prerequisites: stripe listen must be running (via start.sh or manually)
# Usage: ./scripts/test-subscription-cancel.sh <email>

# --- Setup (same pattern as reset-stripe.sh) ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env.development"

get_env() {
  grep "^$1=" "$ENV_FILE" | cut -d= -f2- | tr -d '"'
}

STRIPE_SECRET_KEY=$(get_env STRIPE_SECRET_KEY)
POSTGRES_USER=$(get_env POSTGRES_USER)
POSTGRES_PASSWORD=$(get_env POSTGRES_PASSWORD)
POSTGRES_DB=$(get_env POSTGRES_DB)
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=54322

DB_URL="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@$POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

EMAIL="${1:-}"
if [ -z "$EMAIL" ]; then
  echo "Usage: $0 <email>"
  echo ""
  echo "Tests that cancelling a subscription triggers the webhook to downgrade the user."
  echo "Requires: stripe listen running, user with active pro subscription."
  exit 1
fi

# --- Step 1: Look up user in DB ---
echo "==> Looking up user profile for $EMAIL..."
BEFORE=$(psql "$DB_URL" -t -A -F'|' -c "
  SELECT up.subscription_tier, up.subscription_status, up.stripe_subscription_id,
         up.cancel_at_period_end, up.current_period_end
  FROM user_profiles up
  JOIN auth.users u ON u.id = up.user_id
  WHERE u.email = '$EMAIL'
  LIMIT 1;
")

if [ -z "$BEFORE" ]; then
  echo -e "${RED}FAIL:${NC} No user_profiles row found for $EMAIL"
  exit 1
fi

IFS='|' read -r TIER STATUS SUB_ID CANCEL_AT PERIOD_END <<< "$BEFORE"

echo "  tier:              $TIER"
echo "  status:            $STATUS"
echo "  subscription_id:   $SUB_ID"
echo "  cancel_at_period:  $CANCEL_AT"
echo "  period_end:        $PERIOD_END"
echo ""

# --- Step 2: Verify preconditions ---
if [ "$TIER" != "pro" ]; then
  echo -e "${RED}FAIL:${NC} User is not on pro tier (got: $TIER). Cannot test cancellation."
  exit 1
fi

if [ -z "$SUB_ID" ] || [ "$SUB_ID" = "" ]; then
  echo -e "${RED}FAIL:${NC} User has no stripe_subscription_id. Cannot cancel."
  exit 1
fi

echo -e "${GREEN}Preconditions OK:${NC} User is pro with subscription $SUB_ID"
echo ""

# --- Step 3: Cancel subscription immediately ---
# This triggers customer.subscription.deleted, the same event that fires
# when a cancel-at-period-end subscription expires.
echo "==> Cancelling subscription $SUB_ID (immediate)..."
stripe subscriptions cancel "$SUB_ID" --api-key "$STRIPE_SECRET_KEY" --confirm > /dev/null
echo "  Cancelled. Waiting for webhook delivery..."

# --- Step 4: Wait for webhook processing ---
sleep 3

# --- Step 5: Check after state ---
echo ""
echo "==> Checking user profile after cancellation..."
AFTER=$(psql "$DB_URL" -t -A -F'|' -c "
  SELECT up.subscription_tier, up.subscription_status, up.stripe_subscription_id,
         up.cancel_at_period_end, up.current_period_end
  FROM user_profiles up
  JOIN auth.users u ON u.id = up.user_id
  WHERE u.email = '$EMAIL'
  LIMIT 1;
")

IFS='|' read -r NEW_TIER NEW_STATUS NEW_SUB_ID NEW_CANCEL_AT NEW_PERIOD_END <<< "$AFTER"

echo "  tier:              $NEW_TIER"
echo "  status:            $NEW_STATUS"
echo "  subscription_id:   $NEW_SUB_ID"
echo "  cancel_at_period:  $NEW_CANCEL_AT"
echo "  period_end:        $NEW_PERIOD_END"
echo ""

# --- Step 6: Assertions ---
PASS=true

echo "==> Assertions:"

if [ "$NEW_TIER" = "free" ]; then
  echo -e "  ${GREEN}PASS:${NC} subscription_tier = 'free'"
else
  echo -e "  ${RED}FAIL:${NC} subscription_tier = '$NEW_TIER' (expected 'free')"
  PASS=false
fi

if [ -z "$NEW_STATUS" ] || [ "$NEW_STATUS" = "" ]; then
  echo -e "  ${GREEN}PASS:${NC} subscription_status IS NULL"
else
  echo -e "  ${RED}FAIL:${NC} subscription_status = '$NEW_STATUS' (expected NULL)"
  PASS=false
fi

if [ -z "$NEW_SUB_ID" ] || [ "$NEW_SUB_ID" = "" ]; then
  echo -e "  ${GREEN}PASS:${NC} stripe_subscription_id IS NULL"
else
  echo -e "  ${RED}FAIL:${NC} stripe_subscription_id = '$NEW_SUB_ID' (expected NULL)"
  PASS=false
fi

echo ""
if [ "$PASS" = true ]; then
  echo -e "${GREEN}ALL TESTS PASSED${NC} — subscription cancellation webhook works correctly."
else
  echo -e "${RED}SOME TESTS FAILED${NC} — check webhook logs (is stripe listen running?)."
  exit 1
fi

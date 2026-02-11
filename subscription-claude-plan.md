# Stripe Subscription Implementation Plan

## Overview

Add Stripe-based subscription functionality to textbook-tts with a freemium model:
- **Free Tier**: Configurable lifetime limit (default: 5 conversions total, ever)
- **Pro Tier**: Configurable limit with flexible period (weekly/monthly/lifetime) - $9.99/month
- Monthly Stripe billing, no trials (free tier is the trial)
- **All limits stored in database config table** for easy adjustment without code changes

---

## 1. Database Schema Changes

### Migration File: `supabase/migrations/20251221000000_add_stripe_subscription.sql`

**Create `subscription_config` table (NEW):**
```sql
CREATE TABLE subscription_config (
    config_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tier TEXT NOT NULL UNIQUE CHECK (tier IN ('free', 'pro')),
    conversion_limit INTEGER NOT NULL,
    period_type TEXT NOT NULL CHECK (period_type IN ('weekly', 'monthly', 'lifetime')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Insert default values
INSERT INTO subscription_config (tier, conversion_limit, period_type) VALUES
    ('free', 5, 'lifetime'),
    ('pro', 50, 'monthly');
```

**Extend `user_profiles` table:**
```sql
ALTER TABLE user_profiles
ADD COLUMN stripe_customer_id TEXT UNIQUE,
ADD COLUMN stripe_subscription_id TEXT UNIQUE,
ADD COLUMN subscription_tier TEXT NOT NULL DEFAULT 'free' CHECK (subscription_tier IN ('free', 'pro')),
ADD COLUMN subscription_status TEXT CHECK (subscription_status IN ('active', 'canceled', 'past_due', 'trialing', 'unpaid')),
ADD COLUMN current_period_start TIMESTAMP,
ADD COLUMN current_period_end TIMESTAMP,
ADD COLUMN cancel_at_period_end BOOLEAN DEFAULT false;
```

**Create `usage_tracking` table:**
```sql
CREATE TABLE usage_tracking (
    usage_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    period_type TEXT NOT NULL CHECK (period_type IN ('weekly', 'monthly', 'lifetime')),
    period_start TIMESTAMP NOT NULL,
    period_end TIMESTAMP,  -- NULL for lifetime limits
    conversions_used INTEGER NOT NULL DEFAULT 0,
    conversion_limit INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),

    -- For periodic limits, one record per user per period
    -- For lifetime limits, one record per user total
    UNIQUE(user_id, period_type, period_start)
);
```

**Create `stripe_events` table:**
```sql
CREATE TABLE stripe_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stripe_event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    event_data JSONB NOT NULL,
    processed BOOLEAN NOT NULL DEFAULT false,
    processed_at TIMESTAMP,
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

**Helper Functions:**
- `get_subscription_config(tier)` - Retrieves limit config for a tier
- `get_current_usage(user_id)` - Gets or creates current period usage based on tier config
  - Free tier: Single lifetime usage record
  - Pro tier: Weekly/monthly/lifetime based on config
- `can_user_convert(user_id)` - Returns true if user has quota available
- `increment_usage(user_id)` - Increments conversion counter

---

## 2. Stripe Setup

### Products/Prices to Create in Stripe Dashboard:
1. **Product**: "Textbook TTS Pro"
2. **Price**: $9.99/month recurring (save price ID as `STRIPE_PRICE_ID_PRO`)

### Environment Variables:

**Supabase secrets:**
```bash
STRIPE_SECRET_KEY=sk_test_... (or sk_live_...)
STRIPE_PUBLISHABLE_KEY=pk_test_... (or pk_live_...)
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID_PRO=price_...
```

**Frontend `.env`:**
```bash
VITE_STRIPE_PUBLISHABLE_KEY=pk_test_...
```

---

## 3. Backend Changes

### New Edge Functions:

**`supabase/functions/stripe-webhook/index.ts`**
- Validates Stripe webhook signature
- Logs all events to `stripe_events` table
- Handles events:
  - `checkout.session.completed` - Links customer to user
  - `customer.subscription.updated/created` - Updates tier, period dates, creates new usage record
  - `customer.subscription.deleted` - Downgrades to free tier
  - `invoice.payment_failed` - Marks account as past_due

**`supabase/functions/create-checkout-session/index.ts`**
- Creates/retrieves Stripe customer
- Creates Stripe Checkout session for Pro subscription
- Returns checkout URL to frontend

**`supabase/functions/create-portal-session/index.ts`**
- Creates Stripe Customer Portal session
- Returns portal URL for subscription management

### Modify Existing: `supabase/functions/convert-file/index.ts`

Add quota checking (after ownership verification, before ML service call):
```typescript
// Check quota
const { data: canConvert } = await supabase
  .rpc('can_user_convert', { p_user_id: user.id })

if (!canConvert) {
  return new Response(
    JSON.stringify({ error: 'Monthly conversion limit reached', ... }),
    { status: 429 }
  )
}

// Increment usage counter (before ML call to prevent race conditions)
await supabase.rpc('increment_usage', { p_user_id: user.id })

// ... call ML service
```

---

## 4. Frontend Changes

### Install Dependencies:
```bash
npm install @stripe/stripe-js
```

### New Components/Pages:

**`ocr-tts/src/pages/Billing.jsx`**
- Shows current subscription tier (Free/Pro)
- Displays usage with progress bar (adapts to period type: "X / Y conversions (lifetime)" or "X / Y conversions this month")
- "Upgrade to Pro" button → calls `create-checkout-session` edge function
- "Manage Subscription" button → opens Stripe Customer Portal
- Pricing comparison table (pulls limits from config via API)

**`ocr-tts/src/components/UsageBadge.jsx`**
- Small badge showing "X / Y conversions" (adds period label for clarity, e.g., "3/5 total")
- Color-coded: green (normal), orange (80%+), red (at limit)
- Clickable, links to billing page

### Updates to Existing Files:

**`ocr-tts/src/Layout.jsx`**
- Add "Billing" link to sidebar navigation
- Add `<UsageBadge />` to mobile header

**`ocr-tts/src/main.jsx`**
- Add route: `{ path: '/app/billing', element: <Billing /> }`

**`ocr-tts/src/pages/Files.jsx`**
- Fetch usage data with `supabase.rpc('get_current_usage')`
- Show banner when at limit: "Conversion Limit Reached - Upgrade to Pro" (adapts message based on period type)

**`ocr-tts/src/components/ConvertButton.jsx`**
- Handle 429 quota errors
- Show upgrade link: "Monthly limit reached. [Upgrade to Pro]"

---

## 5. Usage Tracking Logic

**Configuration System:**
- Limits stored in `subscription_config` table
- Each tier (free/pro) has: `conversion_limit` and `period_type`
- Admins can update config without code changes (future admin UI)

**Free Tier:**
- Period: **Lifetime** (configured in DB, default: 5 conversions total forever)
- Limit: Read from `subscription_config` where tier='free'
- Reset: Never - single usage record per user for all time
- Usage record: `period_type='lifetime'`, `period_start=account_created`, `period_end=NULL`

**Pro Tier:**
- Period: Configurable (weekly/monthly/lifetime in `subscription_config`)
- Limit: Read from `subscription_config` where tier='pro'
- Reset: Depends on period_type:
  - **Weekly**: Resets every 7 days from subscription start
  - **Monthly**: Resets on Stripe billing cycle
  - **Lifetime**: Never resets
- Webhook creates new usage record on period boundaries

**Enforcement:**
- Quota check happens in `convert-file` edge function
- Counter incremented BEFORE calling ML service (prevents race conditions)
- Frontend shows current usage everywhere
- Config changes apply immediately to new usage periods

---

## 6. Testing Strategy

### Local Development:
1. Use Stripe test mode keys
2. Test card: `4242 4242 4242 4242` (any future date/CVC)
3. Use Stripe CLI for webhook testing:
   ```bash
   stripe listen --forward-to http://localhost:54321/functions/v1/stripe-webhook
   ```

### Test Cases:
- [ ] New user starts on free tier (5 lifetime conversions from config)
- [ ] Usage counter increments correctly
- [ ] Conversion blocked after lifetime limit (free tier)
- [ ] Free tier limit never resets (lifetime tracking)
- [ ] Config changes apply to new usage periods
- [ ] Checkout flow creates Pro subscription
- [ ] Webhooks update database correctly
- [ ] Pro users get configured limit (50 monthly by default)
- [ ] Pro users with weekly period reset every 7 days
- [ ] Pro users with monthly period reset on billing cycle
- [ ] Pro users with lifetime period never reset
- [ ] Customer portal opens and works
- [ ] Cancellation works (access until period end)
- [ ] Failed payment sets past_due status
- [ ] Updating config table changes limits for new periods

---

## 7. Deployment Steps

1. **Run migration:**
   ```bash
   supabase db push
   ```

2. **Deploy edge functions:**
   ```bash
   supabase functions deploy stripe-webhook
   supabase functions deploy create-checkout-session
   supabase functions deploy create-portal-session
   ```

3. **Set production secrets:**
   ```bash
   supabase secrets set STRIPE_SECRET_KEY=sk_live_...
   supabase secrets set STRIPE_PUBLISHABLE_KEY=pk_live_...
   supabase secrets set STRIPE_WEBHOOK_SECRET=whsec_...
   supabase secrets set STRIPE_PRICE_ID_PRO=price_...
   ```

4. **Configure Stripe webhook endpoint:**
   - URL: `https://<project>.supabase.co/functions/v1/stripe-webhook`
   - Events to listen:
     - `checkout.session.completed`
     - `customer.subscription.updated`
     - `customer.subscription.created`
     - `customer.subscription.deleted`
     - `invoice.payment_failed`

5. **Enable Stripe Customer Portal:**
   - Stripe Dashboard > Settings > Billing > Customer Portal
   - Configure features (cancel, update payment method)

---

## 8. Critical Files to Modify

### Database:
- `supabase/migrations/20251221000000_add_stripe_subscription.sql` (new - includes `subscription_config` table)

### Backend:
- `supabase/functions/stripe-webhook/index.ts` (new)
- `supabase/functions/create-checkout-session/index.ts` (new)
- `supabase/functions/create-portal-session/index.ts` (new)
- `supabase/functions/convert-file/index.ts` (modify - add quota check)

### Frontend:
- `ocr-tts/src/pages/Billing.jsx` (new)
- `ocr-tts/src/components/UsageBadge.jsx` (new)
- `ocr-tts/src/Layout.jsx` (modify - add billing link + usage badge)
- `ocr-tts/src/main.jsx` (modify - add billing route)
- `ocr-tts/src/pages/Files.jsx` (modify - add upgrade banner)
- `ocr-tts/src/components/ConvertButton.jsx` (modify - quota error handling)

---

## 9. Monitoring

### Key Metrics:
- Active Pro subscribers: `SELECT COUNT(*) FROM user_profiles WHERE subscription_tier = 'pro' AND subscription_status = 'active'`
- Conversion rates: Track free→pro upgrades
- Usage patterns: Average conversions per tier
- Webhook health: Monitor `stripe_events.processed` status
- Failed payments: Track `past_due` accounts

### Webhook Monitoring Query:
```sql
SELECT event_type, COUNT(*) as total,
       SUM(CASE WHEN processed THEN 1 ELSE 0 END) as processed
FROM stripe_events
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY event_type;
```

---

## 10. Future Enhancements

1. **Admin UI for config management** - Web interface to update `subscription_config` limits
2. Annual billing option (discounted)
3. Enterprise tier (unlimited conversions)
4. Usage analytics dashboard
5. Email notifications (warnings, receipts)
6. Referral program with credits
7. Grace period for failed payments
8. Promo codes/coupons
9. Per-user limit overrides (stored in user_profiles for special cases)

-- Migration: Add Stripe Subscription Support with Configurable Limits
-- Description: Adds subscription tiers, usage tracking, and Stripe integration to support freemium model
-- Free tier: 10 pages lifetime (configurable), Pro tier: 500 pages/month (configurable)
-- All limits stored in database config table for easy adjustment

-- ============================================================================
-- 1. CREATE subscription_config TABLE
-- ============================================================================

-- Store configurable limits for each subscription tier
CREATE TABLE subscription_config (
    config_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tier TEXT NOT NULL UNIQUE CHECK (tier IN ('free', 'pro')),
    page_limit INTEGER NOT NULL,
    period_type TEXT NOT NULL CHECK (period_type IN ('weekly', 'monthly', 'lifetime')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Trigger to update updated_at
CREATE OR REPLACE FUNCTION update_subscription_config_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER subscription_config_updated_at
    BEFORE UPDATE ON subscription_config
    FOR EACH ROW
    EXECUTE FUNCTION update_subscription_config_updated_at();

-- Insert default values
INSERT INTO subscription_config (tier, page_limit, period_type) VALUES
    ('free', 10, 'lifetime'),
    ('pro', 500, 'monthly');

-- RLS policies - only service role can modify, authenticated users can read
ALTER TABLE subscription_config ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Anyone can view subscription config"
ON subscription_config FOR SELECT
TO authenticated
USING (true);

CREATE POLICY "Service role can manage config"
ON subscription_config FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

COMMENT ON TABLE subscription_config IS 'Configurable limits for subscription tiers. Free tier defaults to 10 lifetime pages, Pro tier to 500 monthly.';

-- ============================================================================
-- 2. EXTEND user_profiles TABLE
-- ============================================================================

-- Add subscription-related columns to user_profiles
ALTER TABLE user_profiles
ADD COLUMN stripe_customer_id TEXT UNIQUE,
ADD COLUMN stripe_subscription_id TEXT UNIQUE,
ADD COLUMN subscription_tier TEXT NOT NULL DEFAULT 'free' CHECK (subscription_tier IN ('free', 'pro')),
ADD COLUMN subscription_status TEXT CHECK (subscription_status IN ('active', 'canceled', 'past_due', 'trialing', 'unpaid')),
ADD COLUMN current_period_start TIMESTAMP,
ADD COLUMN current_period_end TIMESTAMP,
ADD COLUMN cancel_at_period_end BOOLEAN DEFAULT false;

-- Add indexes for frequent lookups
CREATE INDEX idx_user_profiles_stripe_customer_id ON user_profiles(stripe_customer_id);
CREATE INDEX idx_user_profiles_stripe_subscription_id ON user_profiles(stripe_subscription_id);
CREATE INDEX idx_user_profiles_subscription_tier ON user_profiles(subscription_tier);

-- Add comments
COMMENT ON COLUMN user_profiles.stripe_customer_id IS 'Stripe customer ID for payment processing';
COMMENT ON COLUMN user_profiles.stripe_subscription_id IS 'Active Stripe subscription ID';
COMMENT ON COLUMN user_profiles.subscription_tier IS 'Current subscription tier: free or pro';
COMMENT ON COLUMN user_profiles.subscription_status IS 'Stripe subscription status';
COMMENT ON COLUMN user_profiles.current_period_start IS 'Current billing period start (for Pro users)';
COMMENT ON COLUMN user_profiles.current_period_end IS 'Current billing period end (for Pro users)';
COMMENT ON COLUMN user_profiles.cancel_at_period_end IS 'Whether subscription will cancel at end of current period';

-- ============================================================================
-- 3. CREATE usage_tracking TABLE
-- ============================================================================

-- Track page usage per user per period (supports weekly, monthly, and lifetime tracking)
CREATE TABLE usage_tracking (
    usage_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    period_type TEXT NOT NULL CHECK (period_type IN ('weekly', 'monthly', 'lifetime')),
    period_start TIMESTAMP NOT NULL,
    period_end TIMESTAMP,  -- NULL for lifetime limits
    pages_used INTEGER NOT NULL DEFAULT 0,
    page_limit INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),

    -- For periodic limits (weekly/monthly), one record per user per period
    -- For lifetime limits, one record per user total
    UNIQUE(user_id, period_type, period_start)
);

-- Indexes
CREATE INDEX idx_usage_tracking_user_id ON usage_tracking(user_id);
CREATE INDEX idx_usage_tracking_period_type ON usage_tracking(period_type);
CREATE INDEX idx_usage_tracking_period ON usage_tracking(period_start, period_end);

-- Trigger to update updated_at
CREATE OR REPLACE FUNCTION update_usage_tracking_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER usage_tracking_updated_at
    BEFORE UPDATE ON usage_tracking
    FOR EACH ROW
    EXECUTE FUNCTION update_usage_tracking_updated_at();

-- RLS policies
ALTER TABLE usage_tracking ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own usage"
ON usage_tracking FOR SELECT
TO authenticated
USING (auth.uid() = user_id);

CREATE POLICY "Service role can manage all usage"
ON usage_tracking FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

COMMENT ON TABLE usage_tracking IS 'Tracks page parsing usage per user per period. Supports weekly, monthly, and lifetime tracking based on tier config.';

-- ============================================================================
-- 4. CREATE stripe_events TABLE
-- ============================================================================

-- Log all Stripe webhook events for audit and debugging
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

-- Indexes
CREATE INDEX idx_stripe_events_type ON stripe_events(event_type);
CREATE INDEX idx_stripe_events_processed ON stripe_events(processed);
CREATE INDEX idx_stripe_events_stripe_id ON stripe_events(stripe_event_id);
CREATE INDEX idx_stripe_events_created_at ON stripe_events(created_at);

-- RLS - only service role can access
ALTER TABLE stripe_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role can manage stripe events"
ON stripe_events FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

COMMENT ON TABLE stripe_events IS 'Audit log of all Stripe webhook events';

-- ============================================================================
-- 5. HELPER FUNCTIONS
-- ============================================================================

-- Function to get subscription config for a tier
CREATE OR REPLACE FUNCTION get_subscription_config(p_tier TEXT)
RETURNS subscription_config AS $$
DECLARE
    v_config subscription_config;
BEGIN
    SELECT * INTO v_config
    FROM subscription_config
    WHERE tier = p_tier;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Subscription config not found for tier: %', p_tier;
    END IF;

    RETURN v_config;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION get_subscription_config(TEXT) IS 'Retrieves the subscription configuration for a given tier';

-- Function to calculate period boundaries based on config and user status
CREATE OR REPLACE FUNCTION calculate_period_boundaries(
    p_period_type TEXT,
    p_current_period_start TIMESTAMP,
    p_current_period_end TIMESTAMP,
    p_created_at TIMESTAMP
) RETURNS TABLE(period_start TIMESTAMP, period_end TIMESTAMP) AS $$
BEGIN
    IF p_period_type = 'lifetime' THEN
        -- Lifetime: Use account creation as start, no end
        RETURN QUERY SELECT p_created_at, NULL::TIMESTAMP;

    ELSIF p_period_type = 'weekly' THEN
        -- Weekly: Use Stripe period if available, otherwise use current week
        IF p_current_period_start IS NOT NULL THEN
            RETURN QUERY SELECT p_current_period_start, p_current_period_end;
        ELSE
            RETURN QUERY SELECT
                date_trunc('week', NOW()),
                date_trunc('week', NOW() + INTERVAL '1 week');
        END IF;

    ELSIF p_period_type = 'monthly' THEN
        -- Monthly: Use Stripe period if available, otherwise use calendar month
        IF p_current_period_start IS NOT NULL THEN
            RETURN QUERY SELECT p_current_period_start, p_current_period_end;
        ELSE
            RETURN QUERY SELECT
                date_trunc('month', NOW()),
                date_trunc('month', NOW() + INTERVAL '1 month');
        END IF;

    ELSE
        RAISE EXCEPTION 'Invalid period_type: %', p_period_type;
    END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION calculate_period_boundaries IS 'Calculates period start/end based on period type and user subscription status';

-- Function to get or create current usage period for a user
CREATE OR REPLACE FUNCTION get_current_usage(p_user_id UUID)
RETURNS usage_tracking AS $$
DECLARE
    v_usage usage_tracking;
    v_profile user_profiles;
    v_config subscription_config;
    v_period_start TIMESTAMP;
    v_period_end TIMESTAMP;
BEGIN
    -- Get user profile
    SELECT * INTO v_profile
    FROM user_profiles
    WHERE user_id = p_user_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'User profile not found for user_id: %', p_user_id;
    END IF;

    -- Get config for user's tier
    v_config := get_subscription_config(v_profile.subscription_tier);

    -- Calculate period boundaries based on config and subscription status
    SELECT * INTO v_period_start, v_period_end
    FROM calculate_period_boundaries(
        v_config.period_type,
        v_profile.current_period_start,
        v_profile.current_period_end,
        v_profile.created_at
    );

    -- Get or create usage record for current period
    SELECT * INTO v_usage
    FROM usage_tracking
    WHERE user_id = p_user_id
    AND period_type = v_config.period_type
    AND period_start = v_period_start;

    IF NOT FOUND THEN
        -- Create new usage record for this period
        INSERT INTO usage_tracking (
            user_id,
            period_type,
            period_start,
            period_end,
            page_limit,
            pages_used
        )
        VALUES (
            p_user_id,
            v_config.period_type,
            v_period_start,
            v_period_end,
            v_config.page_limit,
            0
        )
        RETURNING * INTO v_usage;
    ELSE
        -- Update limit in case config changed
        UPDATE usage_tracking
        SET page_limit = v_config.page_limit,
            period_end = v_period_end  -- Update end date in case billing cycle changed
        WHERE usage_id = v_usage.usage_id
        RETURNING * INTO v_usage;
    END IF;

    RETURN v_usage;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION get_current_usage(UUID) IS 'Gets or creates the current usage record for a user based on their tier config. Free users get lifetime tracking, Pro users get period-based tracking.';

-- Function to check if user can parse a given number of pages (has quota available)
CREATE OR REPLACE FUNCTION can_user_parse(p_user_id UUID, p_page_count INTEGER)
RETURNS BOOLEAN AS $$
DECLARE
    v_usage usage_tracking;
BEGIN
    v_usage := get_current_usage(p_user_id);
    RETURN v_usage.pages_used + p_page_count <= v_usage.page_limit;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION can_user_parse(UUID, INTEGER) IS 'Returns true if user has enough page quota remaining for the given page count';

-- Function to increment page usage counter
CREATE OR REPLACE FUNCTION increment_page_usage(p_user_id UUID, p_page_count INTEGER)
RETURNS usage_tracking AS $$
DECLARE
    v_usage usage_tracking;
BEGIN
    -- Get current usage (creates record if doesn't exist)
    v_usage := get_current_usage(p_user_id);

    -- Check if user has quota available
    IF v_usage.pages_used + p_page_count > v_usage.page_limit THEN
        RAISE EXCEPTION 'Page limit reached. Used: %, Requested: %, Limit: %',
            v_usage.pages_used, p_page_count, v_usage.page_limit;
    END IF;

    -- Increment the counter by page count
    UPDATE usage_tracking
    SET pages_used = pages_used + p_page_count
    WHERE usage_id = v_usage.usage_id
    RETURNING * INTO v_usage;

    RETURN v_usage;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION increment_page_usage(UUID, INTEGER) IS 'Increments the page usage counter for the current period. Raises exception if limit would be exceeded.';

-- ============================================================================
-- 6. GRANT PERMISSIONS
-- ============================================================================

-- Grant execute permissions on functions
GRANT EXECUTE ON FUNCTION get_subscription_config(TEXT) TO authenticated;
GRANT EXECUTE ON FUNCTION calculate_period_boundaries(TEXT, TIMESTAMP, TIMESTAMP, TIMESTAMP) TO authenticated;
GRANT EXECUTE ON FUNCTION get_current_usage(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION can_user_parse(UUID, INTEGER) TO authenticated;
GRANT EXECUTE ON FUNCTION increment_page_usage(UUID, INTEGER) TO service_role;

-- Note: increment_page_usage is only granted to service_role to prevent abuse
-- It should only be called from the ML worker after proper authorization

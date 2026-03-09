-- Migration: Add Unlimited Subscription Tier
-- Description: Adds 'unlimited' tier that can be manually granted via grant_unlimited()

-- ============================================================================
-- 1. ALTER CHECK CONSTRAINTS to include 'unlimited'
-- ============================================================================

-- subscription_config.tier
ALTER TABLE subscription_config DROP CONSTRAINT subscription_config_tier_check;
ALTER TABLE subscription_config ADD CONSTRAINT subscription_config_tier_check
    CHECK (tier IN ('free', 'pro', 'unlimited'));

-- user_profiles.subscription_tier
ALTER TABLE user_profiles DROP CONSTRAINT user_profiles_subscription_tier_check;
ALTER TABLE user_profiles ADD CONSTRAINT user_profiles_subscription_tier_check
    CHECK (subscription_tier IN ('free', 'pro', 'unlimited'));

-- ============================================================================
-- 2. INSERT unlimited config row
-- ============================================================================

INSERT INTO subscription_config (tier, page_limit, period_type) VALUES
    ('unlimited', 999999999, 'lifetime');

-- ============================================================================
-- 3. CREATE grant_unlimited function
-- ============================================================================

CREATE OR REPLACE FUNCTION grant_unlimited(p_user_id UUID)
RETURNS VOID AS $$
BEGIN
    UPDATE user_profiles
    SET subscription_tier = 'unlimited'
    WHERE user_id = p_user_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'User profile not found for user_id: %', p_user_id;
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION grant_unlimited(UUID) IS 'Grants unlimited subscription tier to a user. Callable by service_role.';

GRANT EXECUTE ON FUNCTION grant_unlimited(UUID) TO service_role;

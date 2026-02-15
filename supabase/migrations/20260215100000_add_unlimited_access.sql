-- Migration: Add unlimited_access flag to user_profiles
-- Description: Allows granting select users free, unlimited access independent of Stripe subscriptions.
-- Usage is still tracked for visibility, but never blocked when unlimited_access = true.

-- ============================================================================
-- 1. ADD unlimited_access COLUMN
-- ============================================================================

ALTER TABLE user_profiles
ADD COLUMN unlimited_access BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN user_profiles.unlimited_access IS 'When true, user bypasses page quota limits. Usage is still tracked.';

-- ============================================================================
-- 2. UPDATE can_user_parse TO BYPASS LIMIT CHECK
-- ============================================================================

CREATE OR REPLACE FUNCTION can_user_parse(p_user_id UUID, p_page_count INTEGER)
RETURNS BOOLEAN AS $$
DECLARE
    v_usage usage_tracking;
    v_unlimited BOOLEAN;
BEGIN
    -- Check if user has unlimited access
    SELECT unlimited_access INTO v_unlimited
    FROM user_profiles
    WHERE user_id = p_user_id;

    IF v_unlimited THEN
        RETURN true;
    END IF;

    v_usage := get_current_usage(p_user_id);
    RETURN v_usage.pages_used + p_page_count <= v_usage.page_limit;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- 3. UPDATE increment_page_usage TO SKIP LIMIT CHECK (STILL TRACK USAGE)
-- ============================================================================

CREATE OR REPLACE FUNCTION increment_page_usage(p_user_id UUID, p_page_count INTEGER)
RETURNS usage_tracking AS $$
DECLARE
    v_usage usage_tracking;
    v_unlimited BOOLEAN;
BEGIN
    -- Get current usage (creates record if doesn't exist)
    v_usage := get_current_usage(p_user_id);

    -- Check if user has unlimited access
    SELECT unlimited_access INTO v_unlimited
    FROM user_profiles
    WHERE user_id = p_user_id;

    -- Only enforce limit if user does NOT have unlimited access
    IF NOT v_unlimited AND v_usage.pages_used + p_page_count > v_usage.page_limit THEN
        RAISE EXCEPTION 'Page limit reached. Used: %, Requested: %, Limit: %',
            v_usage.pages_used, p_page_count, v_usage.page_limit;
    END IF;

    -- Always increment the counter (for tracking)
    UPDATE usage_tracking
    SET pages_used = pages_used + p_page_count
    WHERE usage_id = v_usage.usage_id
    RETURNING * INTO v_usage;

    RETURN v_usage;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

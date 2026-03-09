-- Migration: Fix timestamp type mismatch in calculate_period_boundaries
-- NOW() returns timestamptz but the function declared TIMESTAMP (no tz) return type.
-- Cast NOW() to TIMESTAMP to match the declared return type and usage_tracking column types.

CREATE OR REPLACE FUNCTION calculate_period_boundaries(
    p_period_type TEXT,
    p_current_period_start TIMESTAMP,
    p_current_period_end TIMESTAMP,
    p_created_at TIMESTAMP
) RETURNS TABLE(period_start TIMESTAMP, period_end TIMESTAMP) AS $$
BEGIN
    IF p_period_type = 'lifetime' THEN
        RETURN QUERY SELECT p_created_at, NULL::TIMESTAMP;

    ELSIF p_period_type = 'weekly' THEN
        IF p_current_period_start IS NOT NULL THEN
            RETURN QUERY SELECT p_current_period_start, p_current_period_end;
        ELSE
            RETURN QUERY SELECT
                date_trunc('week', NOW()::TIMESTAMP),
                date_trunc('week', NOW()::TIMESTAMP + INTERVAL '1 week');
        END IF;

    ELSIF p_period_type = 'monthly' THEN
        IF p_current_period_start IS NOT NULL THEN
            RETURN QUERY SELECT p_current_period_start, p_current_period_end;
        ELSE
            RETURN QUERY SELECT
                date_trunc('month', NOW()::TIMESTAMP),
                date_trunc('month', NOW()::TIMESTAMP + INTERVAL '1 month');
        END IF;

    ELSE
        RAISE EXCEPTION 'Invalid period_type: %', p_period_type;
    END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Migration: Add get_user_by_email RPC function for email-to-parse ingestion
-- Allows looking up a user's ID from their email address (auth.users is in a
-- separate schema not queryable via the Supabase client's .from() method).

CREATE OR REPLACE FUNCTION get_user_by_email(email_addr TEXT)
RETURNS TABLE(user_id UUID) AS $$
  SELECT id AS user_id FROM auth.users WHERE email = email_addr LIMIT 1;
$$ LANGUAGE sql SECURITY DEFINER;

-- Only service_role should call this
REVOKE EXECUTE ON FUNCTION get_user_by_email FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION get_user_by_email TO service_role;

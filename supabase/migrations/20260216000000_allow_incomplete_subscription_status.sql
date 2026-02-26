ALTER TABLE user_profiles
  DROP CONSTRAINT user_profiles_subscription_status_check;

ALTER TABLE user_profiles
  ADD CONSTRAINT user_profiles_subscription_status_check
  CHECK (subscription_status IN (
    'active', 'canceled', 'past_due', 'trialing', 'unpaid',
    'incomplete', 'incomplete_expired'
  ));

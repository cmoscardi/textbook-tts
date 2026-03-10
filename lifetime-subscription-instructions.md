# Granting a Lifetime Unlimited Subscription

Run the following in the Supabase SQL editor (or via `psql`):

```sql
SELECT grant_unlimited('<user-uuid>');
```

To look up a user's UUID by email:

```sql
SELECT id FROM auth.users WHERE email = 'user@example.com';
```

## What this does

- Sets `user_profiles.subscription_tier = 'unlimited'`
- The `unlimited` tier has `page_limit = 999999999` and `period_type = 'lifetime'`
- The billing page will show "Unlimited Plan" with no upgrade prompt
- No Stripe subscription is created or required

## Notes

- This is manual only — there is no app flow for granting unlimited access
- The user's existing Stripe subscription (if any) should be cancelled first via the Stripe dashboard, then `reset-subscription.sh` run to clear the DB fields before granting unlimited
- Unlimited users are not affected by monthly resets — their quota is lifetime

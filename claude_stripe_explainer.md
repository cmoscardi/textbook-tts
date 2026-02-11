  Environment Variables You Need                                                        
                                                                                        
  There are 4 Stripe secrets to set on your Supabase edge functions. All are used       
  server-side only (in edge functions), not in the frontend.                            
                                                                                        
  1. STRIPE_SECRET_KEY                                                                  

  - Where to get it: Stripe Dashboard → Developers → API keys → "Secret key"            
  - Looks like: sk_test_... (test mode) or sk_live_... (production)                     
  - What it does: Authenticates your server-side calls to Stripe's API — creating       
  customers, checkout sessions, portal sessions, and verifying webhooks. All three of
  your edge functions (create-checkout-session, create-portal-session, stripe-webhook)
  use it.

  2. STRIPE_PRICE_ID_PRO

  - Where to get it: Stripe Dashboard → Product catalog → Create a product (e.g. "Pro
  Plan"), add a recurring price of $9.99/month → copy the Price ID
  - Looks like: price_1Abc123...
  - What it does: Tells Stripe which line item to put in the checkout session. Your
  create-checkout-session function uses it at checkout time. You create one Product with
   one Price in Stripe's UI, then reference that Price ID here.

  3. STRIPE_WEBHOOK_SECRET

  - Where to get it: Stripe Dashboard → Developers → Webhooks → Add endpoint → set URL
  to https://<your-project-ref>.supabase.co/functions/v1/stripe-webhook → select these
  events:
    - checkout.session.completed
    - customer.subscription.created
    - customer.subscription.updated
    - customer.subscription.deleted
    - invoice.payment_failed

  After creating the endpoint, click on it → Signing secret → Reveal
  - Looks like: whsec_...
  - What it does: Your stripe-webhook edge function uses this to verify that incoming
  webhook POSTs actually came from Stripe (not someone spoofing requests). Stripe signs
  every webhook payload with this secret.

  4. STRIPE_PUBLISHABLE_KEY (optional — not currently used)

  - Your frontend imports @stripe/stripe-js but the code actually redirects to
  Stripe-hosted Checkout (via the URL returned by the edge function), so you don't
  currently need a publishable key in the frontend. It would only matter if you embedded
   Stripe Elements directly.

  How to Set Them

  supabase secrets set STRIPE_SECRET_KEY=sk_test_... STRIPE_PRICE_ID_PRO=price_...
  STRIPE_WEBHOOK_SECRET=whsec_...

  How the Payment Flow Works

  Here's the end-to-end flow your code implements:

  1. User clicks "Upgrade to Pro" on Billing.jsx → calls the create-checkout-session
  edge function
  2. Edge function creates a Stripe Customer (if first time), then creates a Checkout
  Session with your Pro price → returns a Stripe-hosted checkout URL
  3. User is redirected to Stripe's checkout page, enters payment info
  4. On success, Stripe redirects user back to /app/billing?success=true and fires a
  checkout.session.completed webhook
  5. Your stripe-webhook function receives it, links the Stripe customer/subscription
  IDs to the user profile, and upgrades them to subscription_tier = 'pro'
  6. Ongoing, Stripe fires customer.subscription.updated on each renewal — your webhook
  updates the billing period dates (current_period_start/current_period_end), which the
  usage tracking functions use to reset monthly page counts
  7. If payment fails, invoice.payment_failed fires → you mark the user past_due
  8. If they cancel, customer.subscription.deleted fires → you downgrade them back to
  free
  9. Managing subscription (cancel, update card, etc.) uses the create-portal-session
  edge function, which redirects to Stripe's hosted Customer Portal

  One More Thing: Enable the Customer Portal

  In Stripe Dashboard → Settings → Billing → Customer portal, enable it and configure
  what customers can do (cancel, update payment method, etc.). Your
  create-portal-session function creates links to this portal.

  ---
  For testing, use test mode in Stripe (toggle at top of dashboard) and the sk_test_ /
  pk_test_ keys. Stripe provides test card numbers like 4242 4242 4242 4242 with any
  future expiry and any CVC.


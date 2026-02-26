import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'
import Stripe from 'https://esm.sh/stripe@14.21.0'

const stripe = new Stripe(Deno.env.get('STRIPE_SECRET_KEY') || '', {
  apiVersion: '2023-10-16',
  httpClient: Stripe.createFetchHttpClient(),
})

const webhookSecret = Deno.env.get('STRIPE_WEBHOOK_SECRET') || ''

serve(async (req) => {
  const signature = req.headers.get('stripe-signature')

  if (!signature) {
    return new Response('No signature', { status: 400 })
  }

  try {
    const body = await req.text()
    const event = await stripe.webhooks.constructEventAsync(body, signature, webhookSecret)

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL') ?? '',
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
    )

    // Log event
    const { error: logError } = await supabase.from('stripe_events').insert({
      stripe_event_id: event.id,
      event_type: event.type,
      event_data: event.data,
      processed: false
    })

    if (logError) {
      console.error('Error logging event:', logError)
    }

    // Handle event
    try {
      switch (event.type) {
        case 'checkout.session.completed':
          await handleCheckoutCompleted(event.data.object as Stripe.Checkout.Session, supabase)
          break

        case 'customer.subscription.updated':
        case 'customer.subscription.created':
          await handleSubscriptionUpdate(event.data.object as Stripe.Subscription, supabase)
          break

        case 'customer.subscription.deleted':
          await handleSubscriptionDeleted(event.data.object as Stripe.Subscription, supabase)
          break

        case 'invoice.payment_failed':
          await handlePaymentFailed(event.data.object as Stripe.Invoice, supabase)
          break
      }

      // Mark as processed
      await supabase.from('stripe_events')
        .update({ processed: true, processed_at: new Date().toISOString() })
        .eq('stripe_event_id', event.id)

    } catch (handlerError) {
      // Mark as failed with error message
      await supabase.from('stripe_events')
        .update({
          processed: false,
          error_message: handlerError instanceof Error ? handlerError.message : String(handlerError)
        })
        .eq('stripe_event_id', event.id)

      throw handlerError
    }

    return new Response(JSON.stringify({ received: true }), {
      headers: { 'Content-Type': 'application/json' },
      status: 200
    })
  } catch (err) {
    console.error('Webhook error:', err)
    return new Response(
      `Webhook Error: ${err instanceof Error ? err.message : String(err)}`,
      { status: 400 }
    )
  }
})

async function handleCheckoutCompleted(session: Stripe.Checkout.Session, supabase: any) {
  const customerId = session.customer as string
  const subscriptionId = session.subscription as string
  const userId = session.client_reference_id

  if (!userId) {
    console.warn('No client_reference_id in checkout session')
    return
  }

  // Link Stripe customer to user profile
  const { error } = await supabase.from('user_profiles')
    .update({
      stripe_customer_id: customerId,
      stripe_subscription_id: subscriptionId
    })
    .eq('user_id', userId)

  if (error) {
    console.error('Error updating user profile after checkout:', error)
    throw error
  }

  console.log(`Checkout completed for user ${userId}, customer ${customerId}`)
}

async function handleSubscriptionUpdate(subscription: Stripe.Subscription, supabase: any) {
  // Find user by subscription ID
  const { data: profile, error: profileError } = await supabase.from('user_profiles')
    .select('user_id, current_period_start, current_period_end, subscription_tier')
    .eq('stripe_subscription_id', subscription.id)
    .single()

  if (profileError || !profile) {
    console.warn(`No user found for subscription ${subscription.id}`)
    return
  }

  // Period fields may be on the subscription directly (older API versions)
  // or on subscription items (newer API versions)
  const item = subscription.items?.data?.[0]
  const periodStartTs = (subscription as any).current_period_start ?? item?.current_period_start
  const periodEndTs = (subscription as any).current_period_end ?? item?.current_period_end

  const periodStart = periodStartTs ? new Date(periodStartTs * 1000).toISOString() : null
  const periodEnd = periodEndTs ? new Date(periodEndTs * 1000).toISOString() : null

  const periodChanged = periodStart !== profile.current_period_start

  // Only grant pro tier for active/trialing subscriptions
  const activeTier = ['active', 'trialing'].includes(subscription.status)
    ? 'pro'
    : 'free'

  // Update user profile with subscription details
  const { error: updateError } = await supabase.from('user_profiles')
    .update({
      subscription_tier: activeTier,
      subscription_status: subscription.status,
      current_period_start: periodStart,
      current_period_end: periodEnd,
      cancel_at_period_end: subscription.cancel_at_period_end
    })
    .eq('stripe_subscription_id', subscription.id)

  if (updateError) {
    console.error('Error updating subscription:', updateError)
    throw updateError
  }

  // If billing period changed, create new usage tracking record
  // The get_current_usage function will handle this automatically on next call,
  // but we can pre-create it here for consistency
  if (periodChanged && periodStart && periodEnd) {
    // Get subscription config for pro tier
    const { data: config } = await supabase
      .from('subscription_config')
      .select('*')
      .eq('tier', 'pro')
      .single()

    if (config) {
      await supabase.from('usage_tracking').insert({
        user_id: profile.user_id,
        period_type: config.period_type,
        period_start: periodStart,
        period_end: periodEnd,
        conversion_limit: config.conversion_limit,
        conversions_used: 0
      })
      // Ignore errors here - the unique constraint will prevent duplicates
      // and get_current_usage will create if needed
    }
  }

  console.log(`Subscription updated for user ${profile.user_id}, status: ${subscription.status}`)
}

async function handleSubscriptionDeleted(subscription: Stripe.Subscription, supabase: any) {
  // Downgrade user to free tier
  const { error } = await supabase.from('user_profiles')
    .update({
      subscription_tier: 'free',
      subscription_status: null,
      stripe_subscription_id: null,
      current_period_start: null,
      current_period_end: null,
      cancel_at_period_end: false
    })
    .eq('stripe_subscription_id', subscription.id)

  if (error) {
    console.error('Error downgrading user after subscription deletion:', error)
    throw error
  }

  console.log(`Subscription deleted, user downgraded to free tier`)
}

async function handlePaymentFailed(invoice: Stripe.Invoice, supabase: any) {
  const subscriptionId = invoice.subscription as string

  if (!subscriptionId) {
    return
  }

  // Mark subscription as past_due
  const { error } = await supabase.from('user_profiles')
    .update({ subscription_status: 'past_due' })
    .eq('stripe_subscription_id', subscriptionId)

  if (error) {
    console.error('Error marking subscription as past_due:', error)
    throw error
  }

  console.log(`Payment failed for subscription ${subscriptionId}, marked as past_due`)
}

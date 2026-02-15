import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { supabase } from '../lib/supabase.js';
import { loadStripe } from '@stripe/stripe-js';

export default function Billing() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [portalLoading, setPortalLoading] = useState(false);
  const [profile, setProfile] = useState(null);
  const [usage, setUsage] = useState(null);
  const [config, setConfig] = useState({ free: null, pro: null });
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);

  useEffect(() => {
    fetchBillingData();

    // Check for success/cancel messages from Stripe
    if (searchParams.get('success') === 'true') {
      setSuccessMessage('Subscription activated successfully! Your upgrade may take a moment to process.');
    } else if (searchParams.get('canceled') === 'true') {
      setError('Checkout was canceled. You have not been charged.');
    }
  }, [searchParams]);

  const fetchBillingData = async () => {
    try {
      setLoading(true);
      const { data: { session } } = await supabase.auth.getSession();

      if (!session) {
        navigate('/');
        return;
      }

      // Fetch user profile
      const { data: profileData, error: profileError } = await supabase
        .from('user_profiles')
        .select('*')
        .eq('user_id', session.user.id)
        .single();

      if (profileError) throw profileError;
      setProfile(profileData);

      // Fetch current usage
      const { data: usageData, error: usageError } = await supabase
        .rpc('get_current_usage', { p_user_id: session.user.id });

      if (usageError) throw usageError;
      setUsage(usageData);

      // Fetch subscription configs
      const { data: configData, error: configError } = await supabase
        .from('subscription_config')
        .select('*');

      if (configError) throw configError;

      const configMap = {
        free: configData.find(c => c.tier === 'free'),
        pro: configData.find(c => c.tier === 'pro')
      };
      setConfig(configMap);

    } catch (err) {
      console.error('Error fetching billing data:', err);
      setError('Failed to load billing information');
    } finally {
      setLoading(false);
    }
  };

  const handleUpgrade = async () => {
    try {
      setCheckoutLoading(true);
      setError(null);

      const { data: { session } } = await supabase.auth.getSession();
      const { data, error } = await supabase.functions.invoke('create-checkout-session', {
        headers: {
          Authorization: `Bearer ${session.access_token}`
        }
      });

      if (error) throw error;

      if (data.url) {
        window.location.href = data.url;
      }
    } catch (err) {
      console.error('Error creating checkout session:', err);
      setError(err.message || 'Failed to start checkout process');
      setCheckoutLoading(false);
    }
  };

  const handleManageSubscription = async () => {
    try {
      setPortalLoading(true);
      setError(null);

      const { data: { session } } = await supabase.auth.getSession();
      const { data, error } = await supabase.functions.invoke('create-portal-session', {
        headers: {
          Authorization: `Bearer ${session.access_token}`
        }
      });

      if (error) throw error;

      if (data.url) {
        window.location.href = data.url;
      }
    } catch (err) {
      console.error('Error creating portal session:', err);
      setError(err.message || 'Failed to open subscription portal');
      setPortalLoading(false);
    }
  };

  const formatPeriodLabel = (periodType) => {
    if (periodType === 'lifetime') return 'total';
    if (periodType === 'monthly') return 'this month';
    if (periodType === 'weekly') return 'this week';
    return periodType;
  };

  const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    return new Date(dateString).toLocaleDateString();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-gray-600">Loading billing information...</div>
      </div>
    );
  }

  const isUnlimited = profile?.unlimited_access;
  const usagePercentage = usage ? (usage.pages_used / usage.page_limit) * 100 : 0;
  const isPro = profile?.subscription_tier === 'pro';
  const isActive = profile?.subscription_status === 'active';

  return (
    <div className="max-w-6xl mx-auto">
      <h1 className="text-3xl font-bold text-gray-900 mb-8">Billing & Subscription</h1>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-red-800">{error}</p>
        </div>
      )}

      {successMessage && (
        <div className="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg">
          <p className="text-green-800">{successMessage}</p>
        </div>
      )}

      {/* Current Plan Card */}
      <div className="bg-white rounded-lg shadow-md p-6 mb-8">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">
              {isUnlimited ? 'Unlimited Plan' : isPro ? 'Pro Plan' : 'Free Plan'}
            </h2>
            {isPro && !isUnlimited && (
              <p className="text-sm text-gray-600 mt-1">
                Status: <span className={`font-semibold ${isActive ? 'text-green-600' : 'text-yellow-600'}`}>
                  {profile.subscription_status || 'Active'}
                </span>
                {profile.cancel_at_period_end && (
                  <span className="ml-2 text-red-600">(Cancels at period end)</span>
                )}
              </p>
            )}
          </div>
          {isPro && !isUnlimited && (
            <button
              onClick={handleManageSubscription}
              disabled={portalLoading}
              className="px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {portalLoading ? 'Loading...' : 'Manage Subscription'}
            </button>
          )}
        </div>

        {/* Usage Progress */}
        <div className="mt-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-lg font-semibold text-gray-700">Usage</h3>
            <span className="text-sm text-gray-600">
              {isUnlimited
                ? `${usage?.pages_used || 0} pages used (unlimited)`
                : `${usage?.pages_used || 0} / ${usage?.page_limit || 0} pages (${formatPeriodLabel(usage?.period_type)})`
              }
            </span>
          </div>
          {!isUnlimited && (
            <div className="w-full bg-gray-200 rounded-full h-4 overflow-hidden">
              <div
                className={`h-full transition-all duration-300 ${
                  usagePercentage >= 100 ? 'bg-red-500' :
                  usagePercentage >= 80 ? 'bg-orange-500' :
                  'bg-green-500'
                }`}
                style={{ width: `${Math.min(usagePercentage, 100)}%` }}
              />
            </div>
          )}
          {!isUnlimited && usage?.period_end && (
            <p className="text-sm text-gray-500 mt-2">
              Resets on {formatDate(usage.period_end)}
            </p>
          )}
        </div>

        {!isUnlimited && isPro && profile.current_period_end && (
          <div className="mt-4 text-sm text-gray-600">
            <p>Current billing period ends: {formatDate(profile.current_period_end)}</p>
          </div>
        )}
      </div>

      {/* Pricing Comparison */}
      {!isPro && !isUnlimited && (
        <div className="bg-white rounded-lg shadow-md p-6">
          <h2 className="text-2xl font-bold text-gray-900 mb-6">Upgrade to Pro</h2>

          <div className="grid md:grid-cols-2 gap-6">
            {/* Free Tier */}
            <div className="border-2 border-gray-200 rounded-lg p-6">
              <div className="text-center mb-4">
                <h3 className="text-xl font-bold text-gray-900">Free</h3>
                <p className="text-3xl font-bold text-gray-900 mt-2">$0</p>
                <p className="text-sm text-gray-600">forever</p>
              </div>
              <ul className="space-y-3">
                <li className="flex items-start">
                  <svg className="w-5 h-5 text-green-500 mr-2 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                  </svg>
                  <span className="text-gray-700">
                    <strong>{config.free?.page_limit || 10}</strong> pages {formatPeriodLabel(config.free?.period_type)}
                  </span>
                </li>
                <li className="flex items-start">
                  <svg className="w-5 h-5 text-green-500 mr-2 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                  </svg>
                  <span className="text-gray-700">Basic features</span>
                </li>
              </ul>
              <button
                disabled
                className="w-full mt-6 px-4 py-2 bg-gray-300 text-gray-600 rounded-lg cursor-not-allowed"
              >
                Current Plan
              </button>
            </div>

            {/* Pro Tier */}
            <div className="border-2 border-blue-500 rounded-lg p-6 relative">
              <div className="absolute top-0 right-0 bg-blue-500 text-white px-3 py-1 rounded-bl-lg rounded-tr-lg text-sm font-semibold">
                Popular
              </div>
              <div className="text-center mb-4">
                <h3 className="text-xl font-bold text-gray-900">Pro</h3>
                <p className="text-3xl font-bold text-gray-900 mt-2">$9.99</p>
                <p className="text-sm text-gray-600">per month</p>
              </div>
              <ul className="space-y-3">
                <li className="flex items-start">
                  <svg className="w-5 h-5 text-green-500 mr-2 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                  </svg>
                  <span className="text-gray-700">
                    <strong>{config.pro?.page_limit || 500}</strong> pages {formatPeriodLabel(config.pro?.period_type)}
                  </span>
                </li>
                <li className="flex items-start">
                  <svg className="w-5 h-5 text-green-500 mr-2 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                  </svg>
                  <span className="text-gray-700">Priority support</span>
                </li>
                <li className="flex items-start">
                  <svg className="w-5 h-5 text-green-500 mr-2 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                  </svg>
                  <span className="text-gray-700">All future features</span>
                </li>
              </ul>
              <button
                onClick={handleUpgrade}
                disabled={checkoutLoading}
                className="w-full mt-6 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {checkoutLoading ? 'Loading...' : 'Upgrade to Pro'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { supabase } from '../lib/supabase.js';
import { useSession } from '../lib/SessionContext.jsx';

export default function UsageBadge() {
  const { session } = useSession();
  const [usage, setUsage] = useState(null);
  const [unlimited, setUnlimited] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (session?.user) {
      fetchUsage();
    }
  }, [session]);

  const fetchUsage = async () => {
    try {
      const [usageRes, profileRes] = await Promise.all([
        supabase.rpc('get_current_usage', { p_user_id: session.user.id }),
        supabase.from('user_profiles').select('unlimited_access').eq('user_id', session.user.id).single(),
      ]);

      if (usageRes.error) {
        console.error('Error fetching usage:', usageRes.error);
      } else {
        setUsage(usageRes.data);
      }

      if (!profileRes.error && profileRes.data) {
        setUnlimited(profileRes.data.unlimited_access);
      }
    } catch (err) {
      console.error('Error fetching usage:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading || !usage) {
    return null;
  }

  if (unlimited) {
    return (
      <Link
        to="/app/billing"
        className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-white text-sm font-medium transition-colors bg-purple-500 hover:bg-purple-600"
        title="View billing and usage details"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
        <span>Unlimited</span>
      </Link>
    );
  }

  const usagePercentage = (usage.pages_used / usage.page_limit) * 100;

  const getBadgeColor = () => {
    if (usagePercentage >= 100) return 'bg-red-500 hover:bg-red-600';
    if (usagePercentage >= 80) return 'bg-orange-500 hover:bg-orange-600';
    return 'bg-green-500 hover:bg-green-600';
  };

  const formatPeriodLabel = (periodType) => {
    if (periodType === 'lifetime') return 'total';
    if (periodType === 'monthly') return 'month';
    if (periodType === 'weekly') return 'week';
    return '';
  };

  return (
    <Link
      to="/app/billing"
      className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-white text-sm font-medium transition-colors ${getBadgeColor()}`}
      title="View billing and usage details"
    >
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
      </svg>
      <span>
        {usage.pages_used} / {usage.page_limit} pages {formatPeriodLabel(usage.period_type)}
      </span>
    </Link>
  );
}

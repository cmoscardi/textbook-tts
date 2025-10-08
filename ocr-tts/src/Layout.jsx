import { useState, useEffect } from "react";
import { Outlet, Link } from "react-router-dom";
import { Auth } from '@supabase/auth-ui-react'
import { ThemeSupa } from '@supabase/auth-ui-shared'
import { supabase } from './lib/supabase.js';
import { useSession } from './lib/SessionContext.jsx';

export default function Layout() {
  const { session, loading } = useSession();
  const [userEnabled, setUserEnabled] = useState(null);
  const [profileLoading, setProfileLoading] = useState(true);

  // Fetch user profile when session changes
  useEffect(() => {
    const fetchUserProfile = async () => {
      if (session?.user) {
        try {
          const { data, error } = await supabase
            .from('user_profiles')
            .select('enabled')
            .eq('user_id', session.user.id)
            .single();

          if (error) {
            console.error('Error fetching user profile:', error);
            setUserEnabled(false);
          } else {
            setUserEnabled(data.enabled);
          }
        } catch (err) {
          console.error('Error fetching user profile:', err);
          setUserEnabled(false); // Fallback to enabled
        }
      } else {
        setUserEnabled(null);
      }
      setProfileLoading(false);
    };

    fetchUserProfile();
  }, [session]);

  if (loading || profileLoading) {
    return <div>Loading...</div>;
  }

  if(!session) {
    return (
      <Auth
        supabaseClient={supabase}
        appearance={{ theme: ThemeSupa }}
        providers={[]}
        onlyThirdPartyProviders={false}
      />
    );
  }

  // Check if user is disabled
  if (session && userEnabled === false) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50">
        <div className="max-w-md w-full bg-white shadow-lg rounded-lg p-8 text-center">
          <div className="mb-6">
            <svg className="mx-auto h-16 w-16 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.732-.833-2.5 0L4.232 18.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 mb-4">Account Disabled</h1>
          <p className="text-gray-600 mb-6">
            Your account has been disabled. Please contact support for assistance.
          </p>
          <button
            onClick={() => supabase.auth.signOut()}
            className="w-full px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600 transition-colors"
          >
            Sign Out
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="w-full min-h-screen flex flex-col">

      {/* Main container with sidebar and content */}
      <div className="flex flex-1">
        {/* Vertical Toolbar */}
        <div className="bg-gray-200 border-r border-gray-300 w-48 p-3 flex flex-col justify-between">
          <div className="flex flex-col gap-3">
            <Link 
              to="/upload" 
              className="flex items-center gap-2 px-3 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
              Upload Files
            </Link>
            <Link 
              to="/files" 
              className="flex items-center gap-2 px-3 py-2 bg-green-500 text-white rounded hover:bg-green-600 transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Show Files
            </Link>
          </div>
          
          <button 
            onClick={() => supabase.auth.signOut()}
            className="flex items-center gap-2 px-3 py-2 bg-red-500 text-white rounded hover:bg-red-600 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            Logout
          </button>
        </div>

        {/* Page content */}
        <main className="flex-1 bg-gray-100">
          <div className="w-full p-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

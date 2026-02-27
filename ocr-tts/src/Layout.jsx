import { useState, useEffect, useRef } from "react";
import { Outlet, Link } from "react-router-dom";
import { Turnstile } from '@marsidev/react-turnstile';

import { supabase } from './lib/supabase.js';
import { useSession } from './lib/SessionContext.jsx';

function AuthForm() {
  const [mode, setMode] = useState('sign_in'); // 'sign_in' | 'sign_up' | 'forgot_password'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [captchaToken, setCaptchaToken] = useState('');
  const turnstileRef = useRef(null);

  const resetCaptcha = () => {
    turnstileRef.current?.reset();
    setCaptchaToken('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setMessage('');
    setSubmitting(true);

    try {
      if (mode === 'sign_in') {
        const { error } = await supabase.auth.signInWithPassword({
          email,
          password,
          options: { captchaToken },
        });
        if (error) throw error;

      } else if (mode === 'sign_up') {
        const { error } = await supabase.auth.signUp({
          email,
          password,
          options: { captchaToken },
        });
        if (error) throw error;
        setMessage('Check your email for a confirmation link.');

      } else if (mode === 'forgot_password') {
        const { error } = await supabase.auth.resetPasswordForEmail(email, {
          redirectTo: `${window.location.origin}/reset-password`,
          options: { captchaToken },
        });
        if (error) throw error;
        setMessage('Check your email for a password reset link.');
      }
    } catch (err) {
      setError(err.message);
      resetCaptcha();
    } finally {
      setSubmitting(false);
    }
  };

  const inputClass = "w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-400 text-sm";
  const btnClass = "w-full py-2 px-4 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors text-sm font-medium disabled:opacity-50";

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white p-8 rounded-lg shadow-md w-full max-w-sm">
        <h2 className="text-xl font-bold text-gray-800 mb-6">
          {mode === 'sign_in' ? 'Sign in' : mode === 'sign_up' ? 'Create account' : 'Reset password'}
        </h2>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <input
            type="email"
            placeholder="Email address"
            required
            value={email}
            onChange={e => setEmail(e.target.value)}
            className={inputClass}
          />

          {mode !== 'forgot_password' && (
            <input
              type="password"
              placeholder="Password"
              required
              value={password}
              onChange={e => setPassword(e.target.value)}
              className={inputClass}
            />
          )}

          <Turnstile
            ref={turnstileRef}
            siteKey={import.meta.env.VITE_TURNSTILE_SITE_KEY}
            onSuccess={setCaptchaToken}
            onExpire={resetCaptcha}
            onError={resetCaptcha}
          />

          {error && <p className="text-red-600 text-sm">{error}</p>}
          {message && <p className="text-green-600 text-sm">{message}</p>}

          <button type="submit" disabled={submitting || !captchaToken} className={btnClass}>
            {submitting ? 'Please wait...' : mode === 'sign_in' ? 'Sign in' : mode === 'sign_up' ? 'Sign up' : 'Send reset link'}
          </button>
        </form>

        <div className="mt-4 flex flex-col gap-2 text-sm text-center">
          {mode === 'sign_in' && (<>
            <button onClick={() => { setMode('sign_up'); setError(''); setMessage(''); resetCaptcha(); }} className="text-blue-600 hover:underline">Don't have an account? Sign up</button>
            <button onClick={() => { setMode('forgot_password'); setError(''); setMessage(''); resetCaptcha(); }} className="text-gray-500 hover:underline">Forgot your password?</button>
          </>)}
          {mode !== 'sign_in' && (
            <button onClick={() => { setMode('sign_in'); setError(''); setMessage(''); resetCaptcha(); }} className="text-blue-600 hover:underline">Already have an account? Sign in</button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Layout() {
  const { session, loading } = useSession();
  const [userEnabled, setUserEnabled] = useState(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

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
    return <AuthForm />;
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
      {/* Mobile Header with Hamburger */}
      <div className="md:hidden bg-gray-800 text-white px-4 py-3 flex items-center justify-between sticky top-0 z-40">
        <h1 className="text-lg font-semibold">Textbook TTS</h1>
        <button
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          className="p-2 rounded hover:bg-gray-700 transition-colors"
          aria-label="Toggle menu"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {mobileMenuOpen ? (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            ) : (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            )}
          </svg>
        </button>
      </div>

      {/* Desktop Header */}
      <div className="hidden md:flex bg-gray-800 text-white px-6 py-3 items-center justify-between">
        <h1 className="text-lg font-semibold">textbook-tts</h1>
        <button
          onClick={() => supabase.auth.signOut()}
          className="flex items-center gap-2 px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600 transition-colors"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
          </svg>
          Logout
        </button>
      </div>

      {/* Backdrop overlay for mobile menu */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 z-40 md:hidden"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      {/* Main container with sidebar and content */}
      <div className="flex flex-1 relative">
        {/* Vertical Sidebar */}
        <div className={`
          bg-gray-200 border-r border-gray-300 w-48 p-3 flex flex-col justify-between
          fixed md:static inset-y-0 left-0 z-50 transform transition-transform duration-300 ease-in-out
          ${mobileMenuOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}
          md:mt-0 mt-[52px]
        `}>
          <div className="flex flex-col gap-3">
            <Link
              to="/app"
              className="flex items-center gap-2 px-3 py-2 bg-green-500 text-white rounded hover:bg-green-600 transition-colors"
              onClick={() => setMobileMenuOpen(false)}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Files
            </Link>
          </div>

          <button
            onClick={() => {
              supabase.auth.signOut();
              setMobileMenuOpen(false);
            }}
            className="md:hidden flex items-center gap-2 px-3 py-2 bg-red-500 text-white rounded hover:bg-red-600 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            Logout
          </button>
        </div>

        {/* Page content */}
        <main className="flex-1 bg-gray-100 w-full">
          <div className="w-full p-4 md:p-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

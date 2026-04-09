import { Link, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { useSession } from "../lib/SessionContext.jsx";
import Footer from "../components/Footer.jsx";

export default function Landing() {
  const { session, loading } = useSession();
  const navigate = useNavigate();

  useEffect(() => {
    if (!loading && session) {
      navigate('/app', { replace: true });
    }
  }, [session, loading, navigate]);

  if (loading) {
    return null;
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white flex flex-col">
      <div className="flex justify-end px-8 py-6">
        <Link
          to="/app"
          className="inline-block px-6 py-2.5 border border-gray-500 hover:border-white text-white text-base font-semibold rounded-lg transition-colors hover:bg-white hover:text-gray-900"
        >
          Log in
        </Link>
      </div>
      <div className="flex-1 flex flex-col items-center justify-center px-4">
        <div className="max-w-2xl text-center">
          {/* Main headline */}
          <h1 className="text-5xl md:text-6xl font-bold mb-6">
            Turn your reading into audio
          </h1>

          {/* Subheadline */}
          <p className="text-xl md:text-2xl text-gray-400 mb-8">
            Upload text. Get audio. That's it.
          </p>

          {/* How it works - brief */}
          <div className="flex flex-col md:flex-row items-center justify-center gap-4 md:gap-8 text-gray-500 mb-12">
            <span className="flex items-center gap-2">
              <span className="text-2xl">1.</span> Upload PDF
            </span>
            <span className="hidden md:block text-gray-700">→</span>
            <span className="flex items-center gap-2">
              <span className="text-2xl">2.</span> We parse it
            </span>
            <span className="hidden md:block text-gray-700">→</span>
            <span className="flex items-center gap-2">
              <span className="text-2xl">3.</span> Download audio
            </span>
          </div>

          {/* CTA */}
          <Link
            to="/app?mode=sign_up"
            className="inline-block px-8 py-4 bg-blue-600 hover:bg-blue-700 text-white text-lg font-semibold rounded-lg transition-colors"
          >
            Get Started
          </Link>

          {/* Small note */}
          <p className="mt-8 text-gray-600 text-sm">
            Really, that's it.
          </p>
        </div>
      </div>
      <Footer />
    </div>
  );
}

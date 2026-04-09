import { Link, useNavigate } from "react-router-dom";
import { useEffect, useRef } from "react";
import { useSession } from "../lib/SessionContext.jsx";
import Footer from "../components/Footer.jsx";

export default function Landing() {
  const { session, loading } = useSession();
  const navigate = useNavigate();
  const moreInfoRef = useRef(null);

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
      {/* Hero Section */}
      <div className="flex-1 flex flex-col">
        <div className="flex justify-end px-8 py-6">
          <Link
            to="/app"
            className="inline-block px-6 py-2.5 border border-gray-500 hover:border-white text-white text-base font-semibold rounded-lg transition-colors hover:bg-white hover:text-gray-900"
          >
            Log in
          </Link>
        </div>

        <div className="flex-1 flex flex-col items-center justify-center px-4 pb-16">
          <div className="max-w-2xl text-center">
            <h1 className="text-5xl md:text-6xl font-bold mb-6">
              Turn your reading into audio
            </h1>

            <p className="text-xl md:text-2xl text-gray-400 mb-8">
              Upload text. Get audio. That's it.
            </p>

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
                <span className="text-2xl">3.</span> Listen
              </span>
            </div>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link
                to="/app?mode=sign_up"
                className="inline-block px-8 py-4 bg-blue-600 hover:bg-blue-700 text-white text-lg font-semibold rounded-lg transition-colors"
              >
                Get Started
              </Link>
              <button
                onClick={() => moreInfoRef.current?.scrollIntoView({ behavior: 'smooth' })}
                className="inline-block px-8 py-4 border border-gray-600 hover:border-gray-400 text-gray-300 hover:text-white text-lg font-semibold rounded-lg transition-colors"
              >
                Learn More
              </button>
            </div>

          </div>
        </div>
      </div>

      {/* More Info Section */}
      <div ref={moreInfoRef} className="bg-gray-800 border-t border-gray-700 px-6 py-20">
        <div className="max-w-4xl mx-auto">
          <h2 className="text-3xl md:text-4xl font-bold text-center mb-4">
            Make reading easy
          </h2>
          <p className="text-gray-400 text-center text-lg mb-16 max-w-xl mx-auto">
            Stop saving articles to read later. Start listening to them now.
          </p>

          {/* Feature grid */}
          <div className="grid md:grid-cols-3 gap-8 mb-16">
            <div className="bg-gray-900 rounded-xl p-6 border border-gray-700">
              <div className="text-3xl mb-4">📄</div>
              <h3 className="text-lg font-semibold mb-2">Upload PDFs</h3>
              <p className="text-gray-400 text-sm leading-relaxed">
                Drop in textbooks, papers, reports — anything as a PDF. We extract the text intelligently and convert it to natural-sounding audio.
              </p>
            </div>

            <div className="bg-gray-900 rounded-xl p-6 border border-gray-700">
              <div className="text-3xl mb-4">✉️</div>
              <h3 className="text-lg font-semibold mb-2">Forward emails</h3>
              <p className="text-gray-400 text-sm leading-relaxed">
                Got a newsletter you never get around to reading? Forward it to your personal inbox address and we'll have audio ready for you.
              </p>
            </div>

            <div className="bg-gray-900 rounded-xl p-6 border border-gray-700">
              <div className="text-3xl mb-4">🎧</div>
              <h3 className="text-lg font-semibold mb-2">Listen on your terms</h3>
              <p className="text-gray-400 text-sm leading-relaxed">
                Stream directly in the browser or download the audio file. Pick up where you left off, skip sections, listen at your own pace.
              </p>
            </div>
          </div>

          {/* Pricing */}
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-8 max-w-md mx-auto text-center mb-12">
            <div className="inline-block bg-blue-600 text-white text-xs font-semibold px-3 py-1 rounded-full mb-4 uppercase tracking-wide">
              Simple pricing
            </div>
            <div className="text-5xl font-bold mb-1">$5<span className="text-2xl text-gray-400 font-normal">/mo</span></div>
            <p className="text-gray-400 text-sm mb-6">500 pages per month</p>
            <ul className="text-left flex flex-col gap-3 mb-6 text-sm text-gray-300">
              <li className="flex items-center gap-2">
                <span className="text-green-400">✓</span> 10 pages free — no credit card required
              </li>
              <li className="flex items-center gap-2">
                <span className="text-green-400">✓</span> PDF uploads &amp; email forwarding
              </li>
              <li className="flex items-center gap-2">
                <span className="text-green-400">✓</span> High-quality, natural-sounding audio
              </li>
              <li className="flex items-center gap-2">
                <span className="text-green-400">✓</span> Stream or download
              </li>
            </ul>
          </div>

          {/* Bottom CTA */}
          <div className="text-center">
            <Link
              to="/app?mode=sign_up"
              className="inline-block px-10 py-4 bg-blue-600 hover:bg-blue-700 text-white text-lg font-semibold rounded-lg transition-colors"
            >
              Start for free
            </Link>
            <p className="mt-4 text-gray-600 text-sm">No credit card required to try it out.</p>
          </div>
        </div>
      </div>

      <Footer />
    </div>
  );
}

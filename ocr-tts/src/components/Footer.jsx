export default function Footer() {
  return (
    <footer className="bg-gray-800 text-gray-400 py-4 px-6 text-sm text-center flex-shrink-0">
      <a href="/privacy/" className="hover:text-white transition-colors">Privacy Policy</a>
      <span className="mx-3 text-gray-600">·</span>
      <a href="/cookies/" className="hover:text-white transition-colors">Cookie Policy</a>
      <span className="mx-3 text-gray-600">·</span>
      <a href="/terms/" className="hover:text-white transition-colors">Terms of Use</a>
    </footer>
  );
}

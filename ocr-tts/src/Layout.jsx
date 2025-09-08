import { Outlet, Link } from "react-router-dom";

export default function Layout() {
    return (
    <div className="w-full min-h-screen flex flex-col">
      {/* Navbar */}
      <nav className="bg-blue-600 text-white p-4 flex gap-6">
        <Link to="/" className="hover:underline">
          Home
        </Link>
        <Link to="/about" className="hover:underline">
          About
        </Link>
        <Link to="/contact" className="hover:underline">
          Contact
        </Link>
      </nav>

      {/* Main container with sidebar and content */}
      <div className="flex flex-1">
        {/* Vertical Toolbar */}
        <div className="bg-gray-200 border-r border-gray-300 w-48 p-3">
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

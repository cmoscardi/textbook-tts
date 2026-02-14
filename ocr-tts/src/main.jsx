// Polyfill URL.parse for Safari < 18.2
if (typeof URL.parse !== 'function') {
  URL.parse = function(url, base) {
    try {
      return new URL(url, base);
    } catch {
      return null;
    }
  };
}

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider, Navigate } from "react-router-dom";
import './index.css'
import App from './App.jsx'
import About from './pages/About.jsx'
import Upload from './pages/Upload.jsx'
import Files from './pages/Files.jsx'
import FileViewer from './pages/FileViewer.jsx'
import ResetPassword from './pages/ResetPassword.jsx'
import Landing from './pages/Landing.jsx'
import Layout from "./Layout.jsx";
import { SessionProvider } from './lib/SessionContext.jsx';

const router = createBrowserRouter([
  {
    path: "/",
    element: <Landing />,
  },
  {
    path: "/app",
    element: <Layout />,
    children: [
      { index: true, element: <Files /> },
      { path: "about", element: <About /> },
      { path: "upload", element: <Navigate to="/app" replace /> },
      { path: "files", element: <Files /> },
      { path: "view/:fileId", element: <FileViewer /> },
    ]
  },
  {
    path: "/reset-password",
    element: <ResetPassword />
  },
]);


createRoot(document.getElementById('root')).render(
  <StrictMode>
    <SessionProvider>
      <RouterProvider router={router} />
    </SessionProvider>
  </StrictMode>
)

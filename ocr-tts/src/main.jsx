import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import './index.css'
import App from './App.jsx'
import About from './pages/About.jsx'
import Upload from './pages/Upload.jsx'
import Files from './pages/Files.jsx'
import FileViewer from './pages/FileViewer.jsx'
import ResetPassword from './pages/ResetPassword.jsx'
import Layout from "./Layout.jsx";
import { SessionProvider } from './lib/SessionContext.jsx';

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Files /> }, // default "/" route
      { path: "about", element: <About /> },
      { path: "upload", element: <Upload /> },
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

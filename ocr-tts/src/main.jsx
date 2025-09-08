import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import './index.css'
import App from './App.jsx'
import About from './pages/About.jsx'
import Layout from "./Layout.jsx";

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <App /> }, // default "/" route
      { path: "about", element: <About /> },
    ]
  },
]);


createRoot(document.getElementById('root')).render(
  <RouterProvider router={router} />
)

import { Navigate } from 'react-router-dom';

// Deprecated: Upload functionality is now integrated into the Files page
// This redirect is kept for backwards compatibility
export default function Upload() {
  return <Navigate to="/app" replace />;
}

import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { Toaster } from 'sonner';
import LoadingScreen from './components/LoadingScreen/LoadingScreen';
import LandingPage from './pages/LandingPage/LandingPage';
import OAuthScreen from './pages/OAuthScreen/OAuthScreen';
import InitRepoScreen from './pages/InitRepoScreen/InitRepoScreen';
import MonitorScreen from './pages/MonitorScreen/MonitorScreen';

/**
 * Handles the post-OAuth redirect.
 * The backend sets a session cookie and redirects back to /.
 * If sessionStorage has a `postAuthRedirect`, we navigate there once
 * the auth state loads as authenticated.
 */
const PostAuthRedirectHandler: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (isLoading) return;
    const target = sessionStorage.getItem('postAuthRedirect');
    if (isAuthenticated && target) {
      sessionStorage.removeItem('postAuthRedirect');
      sessionStorage.setItem('firstLogin', 'true'); // triggers TelegramModal on /init
      navigate(target, { replace: true });
    }
  }, [isAuthenticated, isLoading, navigate, location]);

  return null;
};

const AppRoutes: React.FC = () => {
  const { isLoading } = useAuth();

  if (isLoading) {
    return <LoadingScreen />;
  }

  return (
    <>
      <PostAuthRedirectHandler />
      <Toaster position="top-right" richColors />
      <Routes>
        <Route path="/"        element={<LandingPage />} />
        <Route path="/oauth"   element={<OAuthScreen />} />
        <Route path="/init"    element={<InitRepoScreen />} />
        <Route path="/monitor" element={<MonitorScreen />} />
        {/* Fallback */}
        <Route path="*"        element={<LandingPage />} />
      </Routes>
    </>
  );
};

const App: React.FC = () => (
  <BrowserRouter>
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  </BrowserRouter>
);

export default App;

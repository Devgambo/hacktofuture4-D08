import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import Sidebar from '../../components/Sidebar/Sidebar';
import './OAuthScreen.css';

const API_BASE = 'http://localhost:8000';

export default function OAuthScreen() {
  const navigate = useNavigate();
  const location = useLocation();
  const [isProcessing, setIsProcessing] = useState(() => {
    const params = new URLSearchParams(location.search);
    return !!(params.get('github_id') && params.get('session_id'));
  });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const githubId = params.get('github_id');
    const sessionId = params.get('session_id');

    if (githubId && sessionId) {
      sessionStorage.setItem('easyops_auth_token', sessionId);
      sessionStorage.setItem('easyops_github_id', githubId);

      fetch(`${API_BASE}/api/user/info`, {
        headers: {
          'Authorization': `Bearer ${sessionId}`,
        },
      })
        .then((res) => {
          if (!res.ok) throw new Error('Failed to fetch user context');
          return res.json();
        })
        .then((data) => {
          sessionStorage.setItem('easyops_user_roles', JSON.stringify(data.roles || []));
          
          const redirectTo = sessionStorage.getItem('postAuthRedirect') || '/monitor';
          sessionStorage.removeItem('postAuthRedirect');
          
          setTimeout(() => {
            navigate(redirectTo);
          }, 800);
        })
        .catch((err) => {
          console.error(err);
          setError('Failed to establish user context. Please retry.');
          setIsProcessing(false);
        });
    }
  }, [location, navigate]);

  const handleAuthorize = () => {
    setIsProcessing(true);
    setError(null);
    window.location.href = `${API_BASE}/api/auth/github`;
  };

  return (
    <div className="oauth-page">
      <Sidebar />
      <main className="oauth-page__main">
        <div className="oauth-page__content">
          
          <div className="oauth-header">
            <div>
              <h1 className="oauth-header__title">Connection Request</h1>
              <p className="oauth-header__subtitle">
                SECURE_TUNNEL_ESTABLISHED // STATUS: {isProcessing ? 'HANDSHAKE_IN_PROGRESS' : 'PENDING'}
              </p>
            </div>
            <div className="oauth-header__connection">
              <img alt="AI Suite" className="oauth-header__icon" src="https://lh3.googleusercontent.com/aida-public/AB6AXuDJXWXarrrufiToE2YaauuLiAq-xXRPg5IjuDVzOZS2D3Dc4BtldmKuPsoNeMCELYxHXaM4sLQZqsWp2Fsm6OPAixNR2G0jUCiP4UkogpBk6n3YETXSv3XidLf-zW6M3XkVuDiZkWaGcgzguLfBzI-hG-H9ZKimqfqo3-uAxd3ax5DHWqIMhlxp_SBE9dTt3sLr6-id6K4BQTvyWsulc9HKIzYA1p-8bTVUdgRVcZikFL-KTQzvDmpx0vGG-rHkFdzIfUoWpj_7jhCW" />
              <span className="material-symbols-outlined text-outline">link</span>
              <img alt="GitHub" className="oauth-header__icon--github" src="https://lh3.googleusercontent.com/aida-public/AB6AXuCUV9pZ-J4cNKU610OMarfQ92l6mRXPBxs9GrwVhUosQXJeQ9bRRX1PL8oNSyW4Uv47feDV82WZKvYnRDsiwzD2rYQ277V61d9p-_PFymItdOwGCkGpb5kXujRPj3wTfT7MWDW_8R3sT882RabFEr3krn1noxom8MC72CA47WyIY9yPdGEhlFWMkbH9w9LxV8IK_6PMA7Xm_WGpdPuUcaBocAik1573Lmpkm40SfLIzBqQlvI9ohrNhZGFlyPB0r9cB-lRItpflUF9F" />
            </div>
          </div>

          {error && (
            <div className="bg-error-container text-on-error-container p-4 rounded-xl border border-error/20 flex gap-3 items-center">
              <span className="material-symbols-outlined">error</span>
              <span className="font-bold text-sm tracking-tight">{error}</span>
            </div>
          )}

          <div className="oauth-grid">
            <div className="oauth-auth-card">
              <div className="oauth-auth-card__id">AUTH_REQ_ID: 9X-22-KJ</div>
              <h2 className="oauth-auth-card__title">
                Authorize <span className="oauth-auth-card__title-highlight">AI Technical Suite</span>
              </h2>
              <p className="oauth-auth-card__desc">
                This application would like the following permissions for your GitHub account:
              </p>
              
              <ul className="oauth-permissions">
                <li className="oauth-permission">
                  <span className="material-symbols-outlined oauth-permission__icon">check_box</span>
                  <div>
                    <span className="oauth-permission__title">Personal User Data</span>
                    <span className="oauth-permission__desc">Full access to your profile information and email.</span>
                  </div>
                </li>
                <li className="oauth-permission">
                  <span className="material-symbols-outlined oauth-permission__icon">check_box</span>
                  <div>
                    <span className="oauth-permission__title">Repositories</span>
                    <span className="oauth-permission__desc">Read and write access to public and private repositories.</span>
                  </div>
                </li>
                <li className="oauth-permission">
                  <span className="material-symbols-outlined oauth-permission__icon">check_box</span>
                  <div>
                    <span className="oauth-permission__title">Webhooks</span>
                    <span className="oauth-permission__desc">Management of repository and organization webhooks.</span>
                  </div>
                </li>
              </ul>
              
              <div className="oauth-actions">
                <button
                  onClick={handleAuthorize}
                  disabled={isProcessing}
                  className="oauth-actions__btn-primary"
                >
                  {isProcessing ? 'AUTHORIZING...' : 'Authorize GitHub'}
                </button>
                <Link to="/" className="oauth-actions__btn-secondary">
                  Cancel
                </Link>
              </div>
              
              <div className="oauth-terms">
                <p className="oauth-terms__text">
                  By clicking "Authorize GitHub", you agree to the Terms of Service. AI Technical Suite will be redirected to:{' '}
                  <span className="oauth-terms__link">https://api.easyops.dev/auth/callback</span>
                </p>
              </div>
            </div>

            <div className="oauth-sidebar">
              <div className="oauth-bot-instructions">
                <div className="oauth-bot-instructions__header">
                  <span className="material-symbols-outlined oauth-bot-instructions__icon">terminal</span>
                  <h3 className="oauth-bot-instructions__title">Bot Integration Instructions</h3>
                </div>
                <div className="oauth-bot-instructions__steps">
                  <div className="oauth-bot-step">
                    <span className="oauth-bot-step__badge">1</span>
                    <p className="oauth-bot-step__id">SEARCH_TARGET</p>
                    <p className="oauth-bot-step__desc">
                      Search for <span className="underline">@easyops_devops_bot</span> on Telegram
                    </p>
                  </div>
                  <div className="oauth-bot-step">
                    <span className="oauth-bot-step__badge">2</span>
                    <p className="oauth-bot-step__id">EXECUTE_INIT</p>
                    <p className="font-bold m-0 text-white">Click <span className="text-primary-fixed">START</span> to initialize</p>
                  </div>
                </div>
              </div>
              
              <div className="oauth-secure-module">
                <div className="oauth-secure-module__bg" aria-hidden="true" />
                <div className="oauth-secure-module__overlay">
                  <span className="oauth-secure-module__label">Secure Module</span>
                  <h4 className="oauth-secure-module__title">DevOps Integration Bridge</h4>
                </div>
              </div>
            </div>

          </div>
        </div>
      </main>
    </div>
  );
}

import { useAuth } from '../../context/AuthContext';
import Topbar from '../../components/Topbar/Topbar';
import './OAuthScreen.css';

export default function OAuthScreen() {
  const { user } = useAuth();

  return (
    <div className="oauth-page">
      <main className="oauth-page__main">
        <Topbar title="Integrations" breadcrumb="System Security" />
        
        <div className="oauth-page__content">
          <div className="oauth-header">
            <div>
              <h1 className="oauth-header__title">Integrations</h1>
            </div>
          </div>

          <div className="integration-grid">
            {/* GitHub Integration Card */}
            <div className="formal-card">
              <div className="formal-card__main">
                <div className="formal-card__icon-wrapper bg-primary/10 text-primary">
                  <span className="material-symbols-outlined text-4xl">hub</span>
                </div>
                <div className="formal-card__header">
                  <h3 className="formal-card__title">GitHub Identity</h3>
                  <p className="formal-card__desc">Primary source control and agent authorization provider.</p>
                </div>
              </div>
              <div className="formal-card__info-box">
                <div className="info-item">
                  <span className="info-item__label">Connected as</span>
                  <span className="info-item__value">@{user?.login || 'anonymous'}</span>
                </div>
              </div>
            </div>

            {/* Telegram Integration Card */}
            <div className="formal-card formal-card--inactive">
              <div className="formal-card__main">
                <div className="formal-card__icon-wrapper bg-surface-container-highest text-on-surface-variant">
                  <span className="material-symbols-outlined text-4xl">send</span>
                </div>
                <div className="formal-card__header">
                  <h3 className="formal-card__title">Telegram Alerts</h3>
                  <p className="formal-card__desc">Low-latency notifications and autonomous PR recovery hooks.</p>
                </div>
              </div>

              <div className="formal-card__instructions">
                <div className="instruction-step">
                  <span className="instruction-step__num">01</span>
                  <span className="instruction-step__text">Invite <b>@easyops_devops_bot</b></span>
                </div>
                <div className="instruction-step">
                  <span className="instruction-step__num">02</span>
                  <span className="instruction-step__text">Execute <code>/link {user?.login}</code></span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

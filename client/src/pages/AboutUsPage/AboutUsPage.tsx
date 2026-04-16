import { useNavigate } from 'react-router-dom';
import logoSrc from '../../assets/logo.png';
import './AboutUsPage.css';

export default function AboutUsPage() {
  const navigate = useNavigate();

  return (
    <main className="about-page">
      <div className="about-page__bg-grid" aria-hidden="true" />
      <div className="about-page__glow-1" aria-hidden="true" />
      <div className="about-page__glow-2" aria-hidden="true" />

      <nav className="about-nav">
        <div className="about-nav__brand" onClick={() => navigate('/')} role="button" tabIndex={0}>
          <div className="about-nav__logo-container">
            <img src={logoSrc} alt="EasyOps Logo" className="about-nav__logo" />
          </div>
          <span className="about-nav__title">EasyOps</span>
        </div>
        <div className="about-nav__links">
          <button 
            className="about-nav__home-btn mr-4" 
            onClick={() => navigate('/about/architecture')}
            type="button"
          >
            ARCHITECTURE
          </button>
          <button 
            className="about-nav__home-btn mr-4" 
            onClick={() => navigate('/about/destructure')}
            type="button"
          >
            DESTRUCTURE
          </button>
          <button 
            className="about-nav__home-btn" 
            onClick={() => navigate('/')}
            type="button"
          >
            RETURN_HOME
          </button>
        </div>
      </nav>

      <section className="about-hero">
        <div className="about-hero__content">
          <div className="about-hero__badge">
            <span className="about-hero__badge-dot" aria-hidden="true" />
            MISSION_LOG
          </div>
          <h1 className="about-hero__title">
            REDEFINING <span className="text-primary">DEVOPS</span>
          </h1>
          <p className="about-hero__subtitle">
            EasyOps was built on the core belief that developers shouldn't be bogged down by recurring pipeline failures and repetitive architectural boilerplate.
          </p>
        </div>
      </section>

      <section className="about-details">
        <div className="about-grid">
          <div className="about-card group">
            <div className="about-card__icon">
              <span className="material-symbols-outlined">psychology</span>
            </div>
            <h3 className="about-card__title">The Vision</h3>
            <p className="about-card__desc">
              We envision a deterministic future where agents assist in resolving intricate deployment issues instantly. We turn downtime into uptime, fast.
            </p>
          </div>
          <div className="about-card group">
            <div className="about-card__icon">
              <span className="material-symbols-outlined">group</span>
            </div>
            <h3 className="about-card__title">The Team</h3>
            <p className="about-card__desc">
              Developed by a small collective of rigorous engineers tired of fragile CI/CD systems, committed to reliable, AI-driven automation workflows.
            </p>
          </div>
          <div className="about-card group">
            <div className="about-card__icon">
              <span className="material-symbols-outlined">code_blocks</span>
            </div>
            <h3 className="about-card__title">Open Architecture</h3>
            <p className="about-card__desc">
              Transparency at the core. Our approach guarantees predictable results with verifiable workflows that easily integrate into your GitHub environments.
            </p>
          </div>
        </div>
      </section>

      <section className="feature-section mt-64">
        <div className="feature-section__grid">
          <div className="featured-card group">
            <img 
              src="https://images.unsplash.com/photo-1550751827-4bd374c3f58b?auto=format&fit=crop&q=80" 
              alt="Cyber dashboard" 
              className="featured-card__img"
            />
            <div className="featured-card__gradient" />
            <div className="featured-card__content">
              <div className="featured-card__badge">
                <span className="material-symbols-outlined featured-card__badge-icon">
                  memory
                </span>
                <span className="featured-card__badge-text">Core Infrastructure</span>
              </div>
              <h2 className="featured-card__title">Deterministic Pipeline Repairs.</h2>
              <p className="featured-card__desc">
                Deploying advanced AI to actively monitor your CI run traces and GitHub Webhooks. When failure strikes, EasyOps instantly kicks off an autonomous fix branch.
              </p>
            </div>
          </div>
          
          <div className="sidebar-cards">
            <div className="resource-card group hover:border-primary/50 transition-colors">
              <span className="material-symbols-outlined resource-card__icon group-hover:text-primary transition-colors">
                speed
              </span>
              <div>
                <h3 className="resource-card__title">Low Latency Fixes</h3>
                <p className="resource-card__text">
                  Automatically spins up environments and generates PRS within seconds. 
                </p>
              </div>
              <div className="resource-card__footer">
                <span className="resource-card__metric">±10s</span>
                <span className="resource-card__metric-label">Repair SLA</span>
              </div>
            </div>

            <div className="security-card bg-primary/15 border-primary/40 hover:bg-primary/25 shadow-[0_0_30px_-5px_var(--color-primary)] transition-all">
              <div className="security-card__icon-wrapper">
                <div className="security-card__icon bg-primary shadow-lg shadow-primary/50">
                  <span className="material-symbols-outlined">psychology</span>
                </div>
                <div>
                  <div className="security-card__label text-primary font-black">Continuous Learning</div>
                  <h3 className="security-card__title text-white drop-shadow-md">Memory Layer</h3>
                </div>
              </div>
              <p className="security-card__desc text-on-surface">
                The longer you stay with it the smarter it will become - thanks to our dedicated memory layer keeping track of past fixes.
              </p>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}

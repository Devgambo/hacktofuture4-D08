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

      <section className="feature-section mt-12">
        <div className="feature-section__grid">
          <div className="featured-card">
            <img 
              src="https://images.unsplash.com/photo-1559757175-5700dde675bc?auto=format&fit=crop&q=80" 
              alt="Abstract brain architecture" 
              className="featured-card__img"
            />
            <div className="featured-card__gradient" />
            <div className="featured-card__content">
              <div className="featured-card__badge">
                <span className="material-symbols-outlined featured-card__badge-icon">
                  psychology
                </span>
                <span className="featured-card__badge-text">Core Intelligence</span>
              </div>
              <h2 className="featured-card__title">Episodic Memory Layer.</h2>
              <p className="featured-card__desc">
                Our Memory Layer is the collective consciousness of your codebase. By converting every resolved issue into a high-dimensional vector, the engine builds a cumulative intelligence that identifies root causes before the first test even fails.
              </p>
            </div>
          </div>
          
          <div className="sidebar-cards">
            <div className="resource-card hover:border-primary/50 transition-colors">
              <span className="material-symbols-outlined resource-card__icon text-primary transition-colors">
                precision_manufacturing
              </span>
              <div>
                <h3 className="resource-card__title">Accurate Fix W/O Changing <br /> Business Logic</h3>
                <p className="resource-card__text">
                  Leveraging RSI (Repo Structural Indexing) to ensure every fix aligns perfectly with your architecture.
                </p>
              </div>
              <div className="resource-card__footer">
                <span className="resource-card__metric-label">Repair Latency</span>
              </div>
            </div>

            <div className="security-card bg-primary/15 border-primary/40 hover:bg-primary/25 shadow-[0_0_30px_-5px_var(--color-primary)] transition-all">
              <div className="security-card__icon-wrapper">
                <div className="security-card__icon bg-primary shadow-lg shadow-primary/50">
                  <span className="material-symbols-outlined">auto_fix_high</span>
                </div>
                <div>
                  <div className="security-card__label text-primary font-black">Deterministic Repairs</div>
                  <h3 className="security-card__title text-white drop-shadow-md">Autonomous Recovery</h3>
                </div>
              </div>
              <p className="security-card__desc text-on-surface">
                Instant fix branches generated upon CI failure. No guesswork—just structural, verifiable patches that bring your pipeline back to green.
              </p>
            </div>

            <div className="resource-card hover:border-tertiary/50 transition-colors border-tertiary/20">
              <span className="material-symbols-outlined resource-card__icon text-tertiary transition-colors">
                lan
              </span>
              <div>
                <h3 className="resource-card__title">Multi-Cloud Heartbeat</h3>
                <p className="resource-card__text">
                  Loosely coupled orchestration for AWS, Azure, and GCP. Secure, secret-validated deployments.
                </p>
              </div>
              <div className="resource-card__footer">
                <span className="resource-card__metric-label">No Vendor Lock-in</span>
              </div>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}

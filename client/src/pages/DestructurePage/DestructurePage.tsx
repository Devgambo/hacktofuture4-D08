import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import logoSrc from '../../assets/logo.png';
import './DestructurePage.css';

const TABS = [
  { 
    id: 'rsi', 
    label: 'RSI (INDEX)', 
    title: 'Repo Structural Indexing',
    icon: 'format_list_bulleted'
  },
  { 
    id: 'ci', 
    label: 'CI (INTEGRATION)', 
    title: 'Continuous Intelligence',
    icon: 'neurology'
  },
  { 
    id: 'cd', 
    label: 'CD (DEPLOYMENT)', 
    title: 'Loosely Coupled CD',
    icon: 'lan'
  },
];

export default function DestructurePage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('rsi');

  return (
    <main className="dest-page">
      <div className="dest-page__bg-grid" aria-hidden="true" />
      <div className="dest-page__glow-1" aria-hidden="true" />
      <div className="dest-page__glow-2" aria-hidden="true" />

      <nav className="dest-nav">
        <div className="dest-nav__brand" onClick={() => navigate('/')} role="button" tabIndex={0}>
          <div className="dest-nav__logo-container">
            <img src={logoSrc} alt="EasyOps Logo" className="dest-nav__logo" />
          </div>
          <span className="dest-nav__title">EasyOps</span>
        </div>
        <div className="dest-nav__links">
          <button 
            className="dest-nav__btn mr-4" 
            onClick={() => navigate('/about')}
            type="button"
          >
            RETURN_TO_ABOUT
          </button>
          <button 
            className="dest-nav__btn" 
            onClick={() => navigate('/')}
            type="button"
          >
            RETURN_HOME
          </button>
        </div>
      </nav>

      <section className="dest-hero">
        <div className="dest-hero__content">
          <div className="dest-hero__badge">
            <span className="dest-hero__badge-dot" aria-hidden="true" />
            DESTRUCTURE_ANALYSIS
          </div>
          <h1 className="dest-hero__title">
            INSIDE THE <span className="text-primary">ENGINE</span>
          </h1>
          <p className="dest-hero__subtitle">
            A deep dive into how EasyOps parses, processes, and deploys high-fidelity fixes across complex architectures.
          </p>
        </div>
      </section>

      <section className="dest-tabs-section">
        <div className="dest-tabs-container">
          <div className="dest-tabs">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`dest-tab ${activeTab === tab.id ? 'dest-tab--active' : ''}`}
              >
                <span className="material-symbols-outlined dest-tab__icon">{tab.icon}</span>
                <span className="dest-tab__label">{tab.label}</span>
                {activeTab === tab.id && <div className="dest-tab__indicator" />}
              </button>
            ))}
          </div>
        </div>

        <div className="dest-viewer">
          {activeTab === 'rsi' && (
            <div className="dest-content animate-fade-in">
              <div className="dest-section-header">
                <h2 className="dest-section-title">REPOSITORY STRUCTURAL INDEXING</h2>
                <p className="dest-section-desc">
                  This is how we parse the repo to gain full contextual awareness. Our parser breaks down the codebase into four core structural layers.
                </p>
              </div>
              
              <div className="dest-grid">
                <div className="dest-card">
                  <div className="dest-card__num">01</div>
                  <h3 className="dest-card__title">rsi_file_map</h3>
                  <p className="dest-card__text">
                    The skeletal layout. Tracks every file's role, language, line counts, and high-level descriptions for instant file-system awareness.
                  </p>
                </div>
                <div className="dest-card">
                  <div className="dest-card__num">02</div>
                  <h3 className="dest-card__title">rsi_symbol_map</h3>
                  <p className="dest-card__text">
                    The cellular level. Maps every function and class definition with exact line ranges, providing granular symbol-level intelligence.
                  </p>
                </div>
                <div className="dest-card">
                  <div className="dest-card__num">03</div>
                  <h3 className="dest-card__title">rsi_imports</h3>
                  <p className="dest-card__text">
                    The nervous system. Visualizes the dependency graph between files to calculate the blast-radius of potential code changes.
                  </p>
                </div>
                <div className="dest-card">
                  <div className="dest-card__num">04</div>
                  <h3 className="dest-card__title">rsi_sensitivity</h3>
                  <p className="dest-card__text">
                    The immune system. Flags critical files and paths that require human validation or specific architectural approval.
                  </p>
                </div>
              </div>

              <div className="dest-info-box mt-12">
                <div className="dest-info-box__header">
                  <span className="material-symbols-outlined">summarize</span>
                  REPO SUMMARY
                </div>
                <p className="dest-info-box__text">
                  Post-indexing, we generate a high-level technical overview (Primary Language, Tech Stack, Entry Points) that serves as the project's tactical manual for AI agents.
                </p>
              </div>
            </div>
          )}

          {activeTab === 'ci' && (
            <div className="dest-content animate-fade-in">
              <div className="dest-section-header">
                <h2 className="dest-section-title">CONTINUOUS INTELLIGENCE</h2>
                <p className="dest-section-desc">
                  Our CI layer doesn't just run tests; it reasons about failure and orchestrates autonomous resolutions.
                </p>
              </div>

              <div className="dest-row-grid">
                <div className="dest-wide-card">
                  <div className="dest-wide-card__icon">
                    <span className="material-symbols-outlined">rate_review</span>
                  </div>
                  <div>
                    <h3 className="dest-wide-card__title">Pull Request Review</h3>
                    <p className="dest-wide-card__text">
                      Autonomous analysis of structural changes. Every PR is cross-referenced against the RSI to ensure architectural compliance and structural integrity before merging.
                    </p>
                  </div>
                </div>

                <div className="dest-wide-card">
                  <div className="dest-wide-card__icon">
                    <span className="material-symbols-outlined">error</span>
                  </div>
                  <div>
                    <h3 className="dest-wide-card__title">CI Error Handling & Repair</h3>
                    <p className="dest-wide-card__text">
                      Real-time monitoring of CI run traces. When a failure strikes, the engine maps error logs to previous fix jobs, triggering a targeted autonomous repair cycle.
                    </p>
                  </div>
                </div>

                <div className="dest-wide-card">
                  <div className="dest-wide-card__icon">
                    <span className="material-symbols-outlined">psychology</span>
                  </div>
                  <div>
                    <h3 className="dest-wide-card__title">Episodic Memory Retrieval</h3>
                    <p className="dest-wide-card__text">
                      Fixes are stored in a vector-indexed 'agent_memory'. When new errors occur, the system performs a cosine similarity search to retrieve similar past successes.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'cd' && (
            <div className="dest-content animate-fade-in">
              <div className="dest-section-header">
                <h2 className="dest-section-title">LOOSELY COUPLED DEPLOYMENT</h2>
                <p className="dest-section-desc">
                   A robust, multi-cloud integration layer designed to handle deployment signals from any major provider with zero vendor lock-in.
                </p>
              </div>

              <div className="dest-cd-visual">
                <div className="dest-cloud-grid">
                  <div className="dest-cloud-node">AZURE</div>
                  <div className="dest-cloud-node">GCP</div>
                  <div className="dest-cloud-node">AWS</div>
                </div>
                
                <div className="dest-flow-line">
                  <div className="dest-flow-label">WEBHOOK + CD_SECRET</div>
                  <div className="dest-flow-arrow"></div>
                </div>

                <div className="dest-engine-core">
                  <div className="dest-engine-core__glitch"></div>
                  EASY_OPS ENGINE
                </div>
              </div>

              <div className="dest-info-box mt-12 bg-primary/10 border-primary/30">
                <div className="dest-info-box__header text-primary">
                  <span className="material-symbols-outlined">security</span>
                  SECURE WEBHOOK ORCHESTRATION
                </div>
                <p className="dest-info-box__text">
                  We implement a loosely coupled structure that handles failures via webhooks. Signals from Azure, GCP, or AWS must include a validated 'cd_secret', triggering our pipeline to spin up repair environments instantly.
                </p>
              </div>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

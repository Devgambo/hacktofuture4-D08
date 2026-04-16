import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import logoSrc from '../../assets/logo.png';
import cdArchImg from '../../assets/cd_architecture.png';
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
                <div className="dest-section-desc">
                  <div className="dest-workflow-box">
                    <h4 className="dest-workflow-title">THE EXECUTION PIPELINE</h4>
                    <p className="text-on-surface-variant text-sm mb-8 leading-relaxed font-medium border-b border-outline-variant pb-6 text-left">
                      This is how we parse the repo to gain full contextual awareness. Our engine initiates a multi-pass deconstruction of the codebase to build a high-fidelity structural map.
                    </p>
                    <ul className="dest-workflow-list">
                      <li>
                        <span className="dest-workflow-step-title">01. DEEP SCAN</span>
                        Clones the branch and runs a multi-pass parser across the entire filesystem.
                      </li>
                      <li>
                        <span className="dest-workflow-step-title">02. ATOMIC MAPPING</span>
                        Deconstructs files into atomic symbols (functions/classes) with precise line-range metadata.
                      </li>
                      <li>
                        <span className="dest-workflow-step-title">03. GRAPH ASSEMBLY</span>
                        Links imports and exports into a directed dependency graph to measure 'blast radius'.
                      </li>
                      <li>
                        <span className="dest-workflow-step-title">04. CONTEXT PERSISTENCE</span>
                        Stores the resulting metadata into normalized RSI tables for sub-millisecond AI retrieval.
                      </li>
                    </ul>
                  </div>
                </div>
              </div>
              
              <div className="dest-grid -mt-8">
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

              <div className="dest-info-box mt-12 border-primary/40 bg-primary/5">
                <div className="dest-info-box__header text-primary text-left">
                  <span className="material-symbols-outlined">database</span>
                  REPO SUMMARY (rsi_repo_summary)
                </div>
                <p className="dest-info-box__text text-left">
                  Post-indexing, we generate a high-level technical overview (Primary Language, Tech Stack, Entry Points). <strong>Stored in the rsi_repo_summary table</strong>, this context is passed to the AI engine on every deployment to ensure total awareness of the codebase structure.
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
                    <span className="material-symbols-outlined">update</span>
                  </div>
                  <div>
                    <h3 className="dest-wide-card__title">Delta Updates & SHA Tracking</h3>
                    <p className="dest-wide-card__text">
                      Incremental repository updates using SHA-based diffing. The system identifies changed files by comparing commit hashes, removing stale metadata and fetching only the modified chunks. This keeps the RSI context current without needing a full re-index.
                    </p>
                  </div>
                </div>

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
                <div className="dest-section-desc">
                  <p>
                    A robust, multi-cloud integration layer designed to handle deployment signals from any major provider with zero vendor lock-in.
                  </p>
                </div>
              </div>

              <div 
                className="dest-cd-frame cursor-pointer relative" 
                onClick={() => window.open(cdArchImg, '_blank')}
              >
                <img src={cdArchImg} alt="CD Architecture" className="dest-cd-img" />
                <div className="dest-cd-overlay">
                  <span className="material-symbols-outlined">open_in_new</span>
                  <span>VIEW_FULL_ARCHITECTURE</span>
                </div>
              </div>

              <div className="dest-info-box mt-12 bg-primary/10 border-primary/30">
                <div className="dest-info-box__header text-primary text-left">
                  <span className="material-symbols-outlined">security</span>
                  SECURE MULTI-PROVIDER INTERACTION
                </div>
                <div className="dest-info-box__text text-left space-y-6">
                  <p>
                    Our <strong>Loosely Coupled</strong> architecture is built on a "Universal Listener" pattern. Instead of building rigid, provider-specific plugins, we use a standardized webhook interface that adapts to the heartbeat of any cloud environment.
                  </p>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div className="bg-surface-container-lowest/50 p-4 rounded-xl border border-outline-variant/30">
                      <h4 className="font-headline font-black text-xs text-primary mb-2">SECRET HANDSHAKE</h4>
                      <p className="text-xs leading-relaxed opacity-80">Every provider interaction is secured via a unique 'cd_secret'. This creates a trust-layer where signals from AWS, Azure, or GCP are validated before reaching the engine.</p>
                    </div>
                    <div className="bg-surface-container-lowest/50 p-4 rounded-xl border border-outline-variant/30">
                      <h4 className="font-headline font-black text-xs text-primary mb-2">AGNOSTIC REPAIR</h4>
                      <p className="text-xs leading-relaxed opacity-80">The system deconstructs failures independently of the host. A broken Lambda is treated with the same structural rigor as a failing Azure Function.</p>
                    </div>
                    <div className="bg-surface-container-lowest/50 p-4 rounded-xl border border-outline-variant/30">
                      <h4 className="font-headline font-black text-xs text-primary mb-2">EXTENSIBLE CORE</h4>
                      <p className="text-xs leading-relaxed opacity-80">New providers can be linked by simply mapping their webhook schema to our internal pulse format, allowing for infinite scalability across the cloud landscape.</p>
                    </div>
                  </div>
                  <p className="pt-4 border-t border-outline-variant/20 italic text-sm">
                    This decoupling ensures that EasyOps remains the central orchestration brain, while the cloud providers act merely as the execution endpoints.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

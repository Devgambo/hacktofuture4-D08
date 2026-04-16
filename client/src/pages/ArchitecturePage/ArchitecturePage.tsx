import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import logoSrc from '../../assets/logo.png';
import prReviewImg from '../../assets/pr_review.png';
import overallArchImg from '../../assets/overall_architecture.png';
import ciFailureImg from '../../assets/ci_failure.png';
import './ArchitecturePage.css';

const TABS = [
  { id: 'pr-review', label: 'PR REVIEW', image: prReviewImg },
  { id: 'overall', label: 'OVERALL ARCHITECTURE', image: overallArchImg },
  { id: 'ci-failure', label: 'CI FAILURE', image: ciFailureImg },
];

export default function ArchitecturePage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('overall');

  const activeImageData = TABS.find(tab => tab.id === activeTab);

  const handleOpenImage = () => {
    if (activeImageData) {
      window.open(activeImageData.image, '_blank');
    }
  };

  return (
    <main className="arch-page">
      <div className="arch-page__bg-grid" aria-hidden="true" />
      <div className="arch-page__glow-1" aria-hidden="true" />
      <div className="arch-page__glow-2" aria-hidden="true" />

      <nav className="arch-nav">
        <div className="arch-nav__brand" onClick={() => navigate('/')} role="button" tabIndex={0}>
          <div className="arch-nav__logo-container">
            <img src={logoSrc} alt="EasyOps Logo" className="arch-nav__logo" />
          </div>
          <span className="arch-nav__title">EasyOps</span>
        </div>
        <div className="arch-nav__links">
          <button 
            className="arch-nav__btn mr-4" 
            onClick={() => navigate('/about')}
            type="button"
          >
            RETURN_TO_ABOUT
          </button>
          <button 
            className="arch-nav__btn" 
            onClick={() => navigate('/')}
            type="button"
          >
            RETURN_HOME
          </button>
        </div>
      </nav>

      <section className="arch-hero">
        <div className="arch-hero__content">
          <div className="arch-hero__badge">
            <span className="arch-hero__badge-dot" aria-hidden="true" />
            SYSTEM_ARCHITECTURE
          </div>
          <h1 className="arch-hero__title">
            TECHNICAL <span className="text-primary">BLUEPRINTS</span>
          </h1>
          <p className="arch-hero__subtitle">
            Explore the inner workings of EasyOps' autonomous DevOps engine and how it orchestrates complex fix workflows.
          </p>
        </div>
      </section>

      <section className="arch-tabs-section">
        <div className="arch-tabs-container">
          <div className="arch-tabs">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`arch-tab ${activeTab === tab.id ? 'arch-tab--active' : ''}`}
              >
                <span className="arch-tab__label">{tab.label}</span>
                {activeTab === tab.id && <div className="arch-tab__indicator" />}
              </button>
            ))}
          </div>
        </div>

        <div className="arch-viewer">
          <div className="arch-viewer__frame">
            <div className="arch-viewer__header">
              <div className="arch-viewer__dots">
                <span className="arch-viewer__dot" />
                <span className="arch-viewer__dot" />
                <span className="arch-viewer__dot" />
              </div>
              <div className="arch-viewer__title">
                {activeImageData?.label}
              </div>
              <div className="arch-viewer__status">
                <span className="arch-viewer__status-dot" />
                LIVE_VIEW
              </div>
            </div>
            <div className="arch-viewer__content">
              {activeImageData && (
                <div 
                  className="arch-viewer__image-wrapper"
                  onClick={handleOpenImage}
                >
                  <img 
                    src={activeImageData.image} 
                    alt={activeImageData.label} 
                    className="arch-viewer__image"
                  />
                  <div className="arch-viewer__overlay">
                    <span className="material-symbols-outlined">open_in_new</span>
                    <span>VIEW_FULL_SIZE</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}

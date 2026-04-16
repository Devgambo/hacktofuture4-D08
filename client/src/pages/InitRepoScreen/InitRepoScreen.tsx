import React from 'react';
import { useNavigate } from 'react-router-dom';
import Sidebar from '../../components/Sidebar/Sidebar';
import Topbar from '../../components/Topbar/Topbar';
import './InitRepoScreen.css';

export default function InitRepoScreen() {
  const navigate = useNavigate();

  return (
    <div className="init-page">
      <Sidebar />
      <main className="init-page__main">
        <Topbar title="Repository Initialization" breadcrumb="Dashboard" />
        
        <div className="init-content">
          <div className="init-box-wrapper">
            <div className="init-box-glow" aria-hidden="true" />
            <div className="init-box">
              <div className="init-box__left">
                <div className="init-icon-container">
                  <div className="init-icon-ring" />
                  <div className="init-icon-solid" />
                  <div className="init-icon-inner">
                    <span className="material-symbols-outlined init-icon">folder_zip</span>
                  </div>
                </div>
                <div className="init-status">
                  <span className="init-status__badge">System Ready</span>
                  <p className="init-status__text">Awaiting technical parameters...</p>
                </div>
              </div>
              
              <div className="init-box__right">
                <h2 className="init-title">
                  NO ACTIVE REPOSITORY <br />
                  <span className="init-title__highlight">DETECTED.</span>
                </h2>
                <p className="init-desc">
                  Connect your local or cloud environment to EasyOps to start managing your technical suite. Your dashboard will populate with real-time logs, deployment status, and Telegram hooks once initialized.
                </p>
                <div className="init-actions">
                  <button onClick={() => navigate('/monitor')} className="init-btn-primary group" type="button">
                    <span className="init-btn-primary__content">
                      <span className="material-symbols-outlined init-btn-primary__icon">rocket_launch</span>
                      INITIALIZE REPOSITORY
                    </span>
                    <span className="material-symbols-outlined">chevron_right</span>
                  </button>
                  <button className="init-btn-secondary" type="button">
                    <span className="material-symbols-outlined">terminal</span>
                    <span className="init-btn-secondary__text">Clone via CLI</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
          
          <div className="init-cards">
            <div className="init-card group">
              <div className="init-card__icon-wrap init-card__icon--1">
                <span className="material-symbols-outlined">auto_stories</span>
              </div>
              <h3 className="init-card__title">Setup Guide</h3>
              <p className="init-card__desc">Learn how to configure your first deployment environment in under 5 minutes.</p>
            </div>
            <div className="init-card group">
              <div className="init-card__icon-wrap init-card__icon--2">
                <span className="material-symbols-outlined">snippet_folder</span>
              </div>
              <h3 className="init-card__title">Browse Templates</h3>
              <p className="init-card__desc">Don't start from scratch. Use our pre-built repository templates.</p>
            </div>
            <div className="init-card group">
              <div className="init-card__icon-wrap init-card__icon--3">
                <span className="material-symbols-outlined">support_agent</span>
              </div>
              <h3 className="init-card__title">Talk to Experts</h3>
              <p className="init-card__desc">Having trouble? Our technical support team is available 24/7.</p>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

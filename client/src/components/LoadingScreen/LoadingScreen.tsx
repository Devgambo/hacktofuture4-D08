import React from 'react';
import logoSrc from '../../assets/logo.png';
import './LoadingScreen.css';

const LoadingScreen: React.FC = () => (
  <div className="loading-screen" aria-live="polite" aria-busy="true">
    <div className="flex flex-col items-center">
      <div className="loading-screen__logo-container">
        <div className="loading-screen__logo-bg" />
        <img src={logoSrc} alt="EasyOps Logo" className="loading-screen__logo" />
      </div>
      <div className="loading-screen__bar">
        <div className="loading-screen__progress" />
      </div>
      <p className="text-xs font-bold tracking-[0.2em] text-[var(--color-on-surface-variant)] font-mono animate-pulse uppercase">INITIALIZING_SYSTEM_CORE</p>
    </div>
  </div>
);

export default LoadingScreen;

import React from 'react';
import Sidebar from '../../components/Sidebar/Sidebar';
import './MonitorScreen.css';

export default function MonitorScreen() {
  return (
    <div className="monitor-page">
      <Sidebar />
      <main className="monitor-main">
        <header className="monitor-header">
          <div className="monitor-header__content">
            <div>
              <div className="monitor-header__title-group">
                <span className="monitor-header__badge">Production</span>
                <h2 className="monitor-header__title">neural-engine-v4</h2>
              </div>
              <p className="monitor-header__desc">
                Core processing repository for asynchronous inference loops and autonomous shard management. Monitoring active deployment clusters in region-us-east-1.
              </p>
            </div>
            <div className="monitor-header__score-group">
              <span className="monitor-header__score-label">CONFIDENCE_SCORE</span>
              <div className="monitor-header__score">
                <span className="monitor-header__score-value">98</span>
                <span className="monitor-header__score-max">/100</span>
              </div>
            </div>
          </div>
        </header>

        <div className="monitor-grid">
          <div className="monitor-logs">
            <section className="log-panel">
              <div className="log-panel__header">
                <div className="log-panel__controls">
                  <div className="log-panel__dots">
                    <div className="log-panel__dot1" />
                    <div className="log-panel__dot2" />
                    <div className="log-panel__dot3" />
                  </div>
                  <span className="log-panel__title">LIVE_EVENT_MONITOR</span>
                </div>
                <div className="log-panel__status">
                  <span className="log-panel__pulse-group">
                    <span className="log-panel__pulse-ping" />
                    <span className="log-panel__pulse-dot" />
                  </span>
                  <span className="log-panel__status-text">TX_BUFFER: 0.04ms</span>
                </div>
              </div>
              <div className="log-panel__list">
                <div className="flex gap-4 opacity-50"><span className="w-24 shrink-0">[14:22:01.03]</span><span className="text-primary-fixed">SYSTEM:</span><span>Initializing neural handshake...</span></div>
                <div className="flex gap-4 opacity-50"><span className="w-24 shrink-0">[14:22:01.05]</span><span className="text-tertiary-fixed-dim">NETWORK:</span><span>Tunnel established via 10.0.84.221</span></div>
                <div className="flex gap-4"><span className="w-24 shrink-0 opacity-50">[14:22:01.09]</span><span className="text-secondary-fixed-dim">IO_DISK:</span><span>Reading config/shards.manifest.json [OK]</span></div>
                <div className="flex gap-4"><span className="w-24 shrink-0 opacity-50">[14:22:01.12]</span><span className="text-primary-fixed font-bold">EVENT:</span><span>Repository monitor attached to PID 4402</span></div>
                <div className="flex gap-4 bg-white/5 py-1 -mx-2 px-2"><span className="w-24 shrink-0 opacity-50 font-bold text-primary">[CRITICAL]</span><span className="text-surface-bright">Anomaly detected in shard_B. Re-routing through secondary gate.</span></div>
                <div className="flex gap-4"><span className="w-24 shrink-0 opacity-50">[14:22:03.11]</span><span className="text-primary-fixed">SYSTEM:</span><span>Heuristic analysis triggered. confidence=0.9841</span></div>
                <div className="flex gap-4"><span className="w-24 shrink-0 opacity-50">[14:22:04.22]</span><span className="text-primary-fixed">EVENT:</span><span>Model parameters updated to v4.2-alpha</span></div>
                <div className="flex gap-4 opacity-50"><span className="w-24 shrink-0">[14:22:05.15]</span><span className="text-primary-fixed">SYSTEM:</span><span>Heartbeat signal pulse... [OK]</span></div>
              </div>
            </section>
          </div>

          <div className="monitor-sidebar">
            <div className="stats-card">
              <h3 className="stats-card__title">Resource Allocation</h3>
              <div className="stats-card__content">
                <div className="stat-row">
                  <div className="stat-row__header">
                    <span className="stat-row__label">CPU UTILIZATION</span>
                    <span className="stat-row__value--primary">42.8%</span>
                  </div>
                  <div className="stat-bar">
                    <div className="stat-bar__fill--primary" style={{ width: '42.8%' }} />
                  </div>
                </div>
                <div className="stat-row">
                  <div className="stat-row__header">
                    <span className="stat-row__label">MEMORY SWAP</span>
                    <span className="stat-row__value--tertiary">14/64 GB</span>
                  </div>
                  <div className="stat-bar">
                    <div className="stat-bar__fill--tertiary" style={{ width: '22%' }} />
                  </div>
                </div>
              </div>
            </div>

            <div className="leads-card">
              <h3 className="leads-card__title">Active Leads</h3>
              <div className="leads-card__content">
                <div className="lead-item">
                  <img alt="Architect" className="lead-item__img" src="https://lh3.googleusercontent.com/aida-public/AB6AXuBe4kgT1ALOuyqjS_m10eseLVcdGq8ouZSqVNgxRRSf0ihJNp8pBu1r4KOW68DhUzwOv0cN4DLrGOr3TUqqqzeGHWLtV7EOFr4BpF4fmo2szBLx2iPXzNZ4_2FQOOSqkf5DRCVSnVQ5X9vZNi7DiexHms6sjNwgMhfWZvDTDKeYp39n6WUlb5WFigrnOGH6iNxnqZ0uQ-i2u6zmaXFtQ1PoQ5nrVl6neKqIZBsyK3djH9HZKvs5fuOM44_c9nzHZxEQUtR_4zY9dkzr" />
                  <div>
                    <p className="lead-item__name">Marcus Thorne</p>
                    <p className="lead-item__role">Sr. Engineer | @mthorne</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

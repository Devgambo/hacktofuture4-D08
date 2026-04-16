import { useState, useEffect, useRef, useMemo } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  fetchMonitoredRepos,
  connectEventStream,
  removeMonitoredRepo,
  type MonitoredRepo,
  type SSEEvent,
} from '../../api/api';
import './MonitorScreen.css';

// ── Event Logic (Functionality from client2) ────────────────────────────────

const EVENT_META: Record<string, { label: string; category: string; icon: string }> = {
  webhook_received:         { label: 'Webhook',        category: 'ci',    icon: 'webhook' },
  job_started:              { label: 'Job Started',    category: 'ci',    icon: 'dynamic_feed' },
  agent_step:               { label: 'Agent Step',     category: 'agent', icon: 'smart_toy' },
  job_completed:            { label: 'Job Done',       category: 'ci',    icon: 'check_circle' },
  job_failed:               { label: 'Job Failed',     category: 'ci',    icon: 'report' },
  pr_review_result:         { label: 'PR Review',      category: 'agent', icon: 'rate_review' },
  rsi_update_started:       { label: 'RSI Update',     category: 'rsi',   icon: 'database' },
  rsi_update_completed:     { label: 'RSI Synced',     category: 'rsi',   icon: 'database' },
  rsi_update_failed:        { label: 'RSI Failed',     category: 'rsi',   icon: 'report' },
  cold_start_started:       { label: 'Ingesting Repo', category: 'rsi',   icon: 'database' },
  cold_start_completed:     { label: 'Repo Ready',     category: 'rsi',   icon: 'database' },
  cold_start_failed:        { label: 'Ingest Failed',  category: 'rsi',   icon: 'report' },
};

const CATEGORIES = [
  { id: 'all',   label: 'ALL_TRAFFIC' },
  { id: 'agent', label: 'NEURAL_PROCESS' },
  { id: 'ci',    label: 'CI_PIPELINE' },
  { id: 'rsi',   label: 'ARCH_INDEX' },
];

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString('en-US', { hour12: false });
}

// function formatTime(iso: string) {
//   return new Date(iso).toLocaleTimeString('en-US', { hour12: false });
// }

export default function MonitorScreen() {
  const { user } = useAuth();
  const [monitoredRepos, setMonitoredRepos] = useState<MonitoredRepo[]>([]);
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [isLoadingRepos, setIsLoadingRepos] = useState(true);
  const [removingRepo, setRemovingRepo] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState('all');
  const logEndRef = useRef<HTMLDivElement>(null);

  // Fetch data on mount
  useEffect(() => {
    fetchMonitoredRepos()
      .then((data) => setMonitoredRepos(Array.isArray(data) ? data : []))
      .catch(console.error)
      .finally(() => setIsLoadingRepos(false));

    const es = connectEventStream((event) => {
      setEvents((prev) => [...prev.slice(-100), event]);
    });

    return () => es.close();
  }, []);

  // Auto-scroll logs
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events]);

  const filteredEvents = useMemo(() => {
    if (activeFilter === 'all') return events;
    return events.filter(ev => (EVENT_META[ev.type]?.category ?? 'ci') === activeFilter);
  }, [events, activeFilter]);

  const handleRemoveRepo = async (fullName: string) => {
    setRemovingRepo(fullName);
    try {
      await removeMonitoredRepo(fullName);
      setMonitoredRepos((prev) => prev.filter((r) => r.full_name !== fullName));
    } catch (err) {
      console.error('Failed to remove repo:', err);
    } finally {
      setRemovingRepo(null);
    }
  };

  return (
    <div className="monitor-page">
      <main className="monitor-main">
        {/* Header */}
        <header className="monitor-header">
          <div className="monitor-header__content">
            <div>
              <div className="monitor-header__title-group">
                <span className="monitor-header__badge">Live</span>
                <h2 className="monitor-header__title">
                  {user?.name ?? user?.login ?? 'Dashboard'}
                </h2>
              </div>
              <p className="monitor-header__desc">
                Monitoring {monitoredRepos.length} active repository · {events.length} events streamed
              </p>
            </div>
          </div>
        </header>

        <div className="monitor-grid">
          {isLoadingRepos ? (
            <div className="col-span-full py-20 text-center text-on-surface-variant animate-pulse font-mono text-sm leading-relaxed">
              [SYSTEM] Syncing monitoring state... Establishing agent uplink...
            </div>
          ) : monitoredRepos.length === 0 ? (
            <div className="col-span-full py-20 text-center flex flex-col items-center border-2 border-dashed border-outline-variant/30 rounded-3xl bg-surface-container-low/50 max-w-2xl mx-auto w-full">
               <div className="w-16 h-16 mb-4 rounded-full bg-surface-container-high flex items-center justify-center">
                 <span className="material-symbols-outlined text-3xl text-on-surface-variant/40">signal_cellular_nodata</span>
               </div>
               <h3 className="text-xl font-bold text-on-surface uppercase tracking-tight">No metrics in the monitor dashboard</h3>
               <p className="mt-2 text-on-surface-variant text-sm max-w-sm">Initialize a GitHub repository to see live metrics and pipeline health here.</p>
               <a href="/init" className="mt-8 px-12 py-4 bg-primary text-white text-xs font-black rounded-xl uppercase tracking-widest no-underline hover:bg-primary-container transition-all shadow-lg shadow-primary/25 inline-flex items-center justify-center min-w-[240px]">
                 Start Integration
               </a>
            </div>
          ) : (
            <>
              {/* Event Log with Filtering functionality like client2 */}
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
                      <span className="log-panel__status-text">
                        {events.length} ACTIVE_EVENTS
                      </span>
                    </div>
                  </div>

                  {/* Filter Tabs - Functionality like client2 */}
                  <div className="flex gap-2 bg-surface-container-highest/30 border-b border-outline-variant px-2 pt-2">
                    {CATEGORIES.map(cat => (
                      <button
                        key={cat.id}
                        onClick={() => setActiveFilter(cat.id)}
                        className={`px-4 py-2 text-[11px] font-black uppercase tracking-widest transition-all border-b-2 ${
                          activeFilter === cat.id 
                            ? 'border-primary text-primary bg-primary/5' 
                            : 'border-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high'
                        }`}
                      >
                        {cat.label}
                      </button>
                    ))}
                  </div>

                  <div className="log-panel__list">
                    {filteredEvents.length === 0 ? (
                      <div className="opacity-70 italic font-mono text-xs flex flex-col items-center justify-center h-full py-10">
                        <span className="material-symbols-outlined mb-2 text-2xl">search_off</span>
                        [SYSTEM] No {activeFilter !== 'all' ? activeFilter.toUpperCase() : ''} events captured.
                      </div>
                    ) : (
                      filteredEvents.map((ev, i) => {
                        const meta = EVENT_META[ev.type] || { label: ev.type, category: 'ci', icon: 'webhook' };
                        const evData = (ev.data ?? ev) as any;
                        const isReview = ev.type === 'pr_review_result';

                        return (
                          <div key={i} className={`flex gap-4 p-2 rounded-lg transition-colors group ${isReview ? 'bg-surface-container-low border border-outline-variant/40 p-4 my-1' : 'hover:bg-surface-container-high/50'}`}>
                            <span className="w-20 shrink-0 opacity-70 font-mono text-[11px] mt-0.5">
                              [{ev.timestamp ? formatTime(ev.timestamp) : '??:??:??'}]
                            </span>
                            <div className="flex flex-col gap-1 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="material-symbols-outlined text-sm text-primary opacity-80">
                                  {meta.icon}
                                </span>
                                <span className="text-primary font-black uppercase text-[11px] tracking-tight whitespace-nowrap">
                                  {meta.label}
                                </span>
                                {(ev.repo_full_name || evData.repo) && (
                                  <span className="px-1.5 py-0.5 rounded bg-surface-container-highest text-[10px] font-mono text-on-surface-variant">
                                    {ev.repo_full_name || evData.repo}
                                  </span>
                                )}
                                {isReview && evData.score != null && (
                                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-black tracking-wide ${
                                    evData.score >= 70 ? 'bg-tertiary/15 text-tertiary' : evData.score >= 40 ? 'bg-secondary-container text-on-secondary-container' : 'bg-error-container text-on-error-container'
                                  }`}>
                                    {evData.score}/100 · {evData.score_label}
                                  </span>
                                )}
                                {isReview && evData.merge_recommendation && (
                                  <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-wider opacity-70">
                                    {evData.merge_recommendation === 'approve' ? '✅ Approve' : evData.merge_recommendation === 'block' ? '🚫 Block' : '⚠️ Changes Requested'}
                                  </span>
                                )}
                              </div>

                              {/* Summary text */}
                              <span className="text-[12px] font-medium text-on-surface leading-tight">
                                {isReview && evData.summary
                                  ? evData.summary
                                  : ev.message || evData.detail || JSON.stringify(ev.data || {})}
                              </span>

                              {/* Top findings for review events */}
                              {isReview && Array.isArray(evData.top_findings) && evData.top_findings.length > 0 && (
                                <div className="mt-1 flex flex-col gap-0.5">
                                  {(evData.top_findings as Array<{severity: string; file: string; title: string}>).map((f, fi) => (
                                    <span key={fi} className="text-[11px] text-on-surface-variant leading-snug">
                                      {f.severity === 'critical' ? '🔴' : f.severity === 'warning' ? '🟠' : '🔵'}{' '}
                                      <span className="font-mono text-[10px]">{f.file}</span>{' '}
                                      — {f.title}
                                    </span>
                                  ))}
                                </div>
                              )}

                              {/* Review URL link */}
                              {isReview && evData.review_url && (
                                <a
                                  href={evData.review_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-[10px] text-primary underline mt-1 hover:opacity-80"
                                >
                                  View full review on GitHub →
                                </a>
                              )}
                            </div>
                          </div>
                        );
                      })
                    )}
                    <div ref={logEndRef} />
                  </div>
                </section>
              </div>

              {/* Sidebar: Monitored Repos & Stats */}
              <div className="monitor-sidebar">
                <div className="stats-card flex-1 flex flex-col min-h-0">
                  <div className="flex items-center justify-between mb-6 shrink-0">
                    <h3 className="stats-card__title !mb-0">Monitored Repositories</h3>
                    <span className="bg-surface-container-high text-on-surface-variant px-2 py-0.5 rounded text-[10px] font-bold tracking-wider uppercase border border-outline-variant">
                      {monitoredRepos.length} Monitored
                    </span>
                  </div>
                  <div className="stats-card__content flex-1 overflow-y-auto pr-2">
                    {monitoredRepos.map((repo) => (
                      <div key={repo.full_name} className="monitor-repo-item">
                        <div className="monitor-repo-item__info">
                          <p className="monitor-repo-item__name">{repo.full_name}</p>
                          <p className="monitor-repo-item__meta">
                            {repo.webhook_active ? 'Webhook active' : 'No webhook'}
                          </p>
                        </div>
                        <button
                          onClick={() => handleRemoveRepo(repo.full_name)}
                          disabled={removingRepo === repo.full_name}
                          className="monitor-repo-item__remove"
                          title="Remove from monitoring"
                          type="button"
                        >
                          <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>
                            {removingRepo === repo.full_name ? 'sync' : 'close'}
                          </span>
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

import { useState, useEffect, useRef, useMemo } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  fetchMonitoredRepos,
  fetchJobs,
  connectEventStream,
  removeMonitoredRepo,
  fetchMemoryStats,
  type MonitoredRepo,
  type Job,
  type SSEEvent,
  type MemoryStats,
} from '../../api/api';
import './MonitorScreen.css';

// ── Event Logic (Functionality from client2) ────────────────────────────────

const EVENT_META: Record<string, { label: string; category: string; icon: string }> = {
  webhook_received:         { label: 'Webhook',        category: 'ci',    icon: 'webhook' },
  job_started:              { label: 'Job Started',    category: 'ci',    icon: 'dynamic_feed' },
  agent_step:               { label: 'Agent Step',     category: 'agent', icon: 'smart_toy' },
  job_completed:            { label: 'Job Done',       category: 'ci',    icon: 'check_circle' },
  job_failed:               { label: 'Job Failed',     category: 'ci',    icon: 'report' },
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

function statusColor(status: Job['status']) {
  switch (status) {
    case 'completed': return 'text-green-600';
    case 'running':   return 'text-yellow-600';
    case 'failed':    return 'text-red-600';
    default:          return 'text-on-surface-variant';
  }
}

export default function MonitorScreen() {
  const { user } = useAuth();
  const [monitoredRepos, setMonitoredRepos] = useState<MonitoredRepo[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [isLoadingRepos, setIsLoadingRepos] = useState(true);
  const [isLoadingJobs, setIsLoadingJobs] = useState(true);
  const [memoryStats, setMemoryStats] = useState<MemoryStats | null>(null);
  const [removingRepo, setRemovingRepo] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState('all');
  const logEndRef = useRef<HTMLDivElement>(null);

  // Fetch data on mount
  useEffect(() => {
    fetchMonitoredRepos()
      .then((data) => setMonitoredRepos(Array.isArray(data) ? data : []))
      .catch(console.error)
      .finally(() => setIsLoadingRepos(false));

    fetchJobs()
      .then((data) => setJobs(Array.isArray(data) ? data : []))
      .catch(console.error)
      .finally(() => setIsLoadingJobs(false));

    fetchMemoryStats()
      .then(setMemoryStats)
      .catch(console.error);

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

  const safeJobs = Array.isArray(jobs) ? jobs : [];
  const totalJobs = safeJobs.length;
  const runningJobs = safeJobs.filter((j) => j.status === 'running').length;
  const failedJobs = safeJobs.filter((j) => j.status === 'failed').length;
  const completedJobs = safeJobs.filter((j) => j.status === 'completed').length;

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
            <div className="monitor-header__score-group">
              <span className="monitor-header__score-label">JOBS_TOTAL</span>
              <div className="monitor-header__score">
                <span className="monitor-header__score-value">{totalJobs}</span>
                <span className="monitor-header__score-max"> runs</span>
              </div>
            </div>
          </div>
        </header>

        {/* Stats bar */}
        <div className="monitor-stats-bar">
          <div className="monitor-stat-chip monitor-stat-chip--running">
            <span className="monitor-stat-chip__dot" />
            <span>{runningJobs} Running</span>
          </div>
          <div className="monitor-stat-chip monitor-stat-chip--ok">
            <span className="monitor-stat-chip__dot" />
            <span>{completedJobs} Completed</span>
          </div>
          <div className="monitor-stat-chip monitor-stat-chip--fail">
            <span className="monitor-stat-chip__dot" />
            <span>{failedJobs} Failed</span>
          </div>
          <div className="monitor-stat-chip">
            <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>hub</span>
            <span>{monitoredRepos.length} Monitored</span>
          </div>
        </div>

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
                  <div className="flex bg-surface-container-highest/30 border-b border-outline-variant px-2">
                    {CATEGORIES.map(cat => (
                      <button
                        key={cat.id}
                        onClick={() => setActiveFilter(cat.id)}
                        className={`px-4 py-2 text-[10px] font-black uppercase tracking-widest transition-all border-b-2 ${
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
                      <div className="opacity-50 italic font-mono text-xs flex flex-col items-center justify-center h-full py-10">
                        <span className="material-symbols-outlined mb-2 text-2xl">search_off</span>
                        [SYSTEM] No {activeFilter !== 'all' ? activeFilter.toUpperCase() : ''} events captured.
                      </div>
                    ) : (
                      filteredEvents.map((ev, i) => {
                        const meta = EVENT_META[ev.type] || { label: ev.type, category: 'ci', icon: 'webhook' };
                        return (
                          <div key={i} className="flex gap-4 p-2 hover:bg-surface-container-high/50 rounded-lg transition-colors group">
                            <span className="w-20 shrink-0 opacity-40 font-mono text-[10px] mt-0.5">
                              [{ev.timestamp ? formatTime(ev.timestamp) : '??:??:??'}]
                            </span>
                            <div className="flex flex-col gap-1 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="material-symbols-outlined text-sm text-primary opacity-70">
                                  {meta.icon}
                                </span>
                                <span className="text-primary-fixed font-black uppercase text-[10px] tracking-tight whitespace-nowrap">
                                  {meta.label}
                                </span>
                                {ev.repo_full_name && (
                                  <span className="px-1.5 py-0.5 rounded bg-surface-container-highest text-[9px] font-mono text-on-surface-variant">
                                    {ev.repo_full_name}
                                  </span>
                                )}
                              </div>
                              <span className="text-[11px] text-on-surface leading-tight">
                                {ev.message || (ev.data as any)?.detail || JSON.stringify(ev.data || {})}
                              </span>
                            </div>
                          </div>
                        );
                      })
                    )}
                    <div ref={logEndRef} />
                  </div>
                </section>

                {/* Jobs list */}
                <section className="log-panel mt-6">
                  <div className="log-panel__header">
                    <div className="log-panel__controls">
                      <div className="log-panel__dots">
                        <div className="log-panel__dot1" />
                        <div className="log-panel__dot2" />
                        <div className="log-panel__dot3" />
                      </div>
                      <span className="log-panel__title">RECENT_JOBS</span>
                    </div>
                  </div>
                  <div className="log-panel__list" style={{ maxHeight: '220px' }}>
                    {isLoadingJobs ? (
                      <div className="opacity-50 italic">Loading jobs...</div>
                    ) : jobs.length === 0 ? (
                      <div className="opacity-50 italic">No jobs yet. Initialize a repo and push a commit to trigger the agent.</div>
                    ) : (
                      jobs.slice(0, 20).map((job) => (
                        <div key={job.id} className="flex items-center gap-4 py-1 border-b border-white/5">
                          <span className="w-24 shrink-0 opacity-50 font-mono text-[11px]">
                            {formatTime(job.created_at)}
                          </span>
                          <span className="flex-1 truncate">{job.repo_full_name}</span>
                          <span className={`text-[10px] font-bold uppercase ${statusColor(job.status)}`}>
                            {job.status.replace(/_/g, ' ')}
                          </span>
                          <span className="opacity-40 text-[10px]">{job.type}</span>
                        </div>
                      ))
                    )}
                  </div>
                </section>
              </div>

              {/* Sidebar: Monitored Repos & Stats */}
              <div className="monitor-sidebar">
                <div className="stats-card">
                  <h3 className="stats-card__title">Monitored Repositories</h3>
                  <div className="stats-card__content">
                    {monitoredRepos.map((repo) => (
                      <div key={repo.id} className="monitor-repo-item">
                        <div className="monitor-repo-item__info">
                          <p className="monitor-repo-item__name">{repo.full_name}</p>
                          <p className="monitor-repo-item__meta">
                            Initialized {new Date(repo.initialized_at).toLocaleDateString()}
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

                {/* Agent Index Stats */}
                <div className="stats-card">
                  <h3 className="stats-card__title">Neural Core Index</h3>
                  <div className="stats-card__content">
                    <div className="stat-row">
                      <div className="stat-row__header">
                        <span className="stat-row__label">INDEXED_DOCUMENTS</span>
                        <span className="stat-row__value--primary">
                          {memoryStats?.total_documents ?? 0}
                        </span>
                      </div>
                      <div className="stat-bar">
                        <div
                          className="stat-bar__fill--primary"
                          style={{ width: `${Math.min(100, (memoryStats?.total_documents || 0) / 100)}%` }}
                        />
                      </div>
                    </div>
                    <div className="stat-row">
                      <div className="stat-row__header">
                        <span className="stat-row__label">ACTIVE_REPOSITORIES</span>
                        <span className="stat-row__value--tertiary">
                          {memoryStats?.total_repos ?? 0}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="stats-card">
                  <h3 className="stats-card__title">Pipeline Health</h3>
                  <div className="stats-card__content">
                    <div className="stat-row">
                      <div className="stat-row__header">
                        <span className="stat-row__label">SUCCESS RATE</span>
                        <span className="stat-row__value--primary">
                          {totalJobs > 0 ? Math.round((completedJobs / totalJobs) * 100) : 0}%
                        </span>
                      </div>
                      <div className="stat-bar">
                        <div
                          className="stat-bar__fill--primary"
                          style={{ width: totalJobs > 0 ? `${(completedJobs / totalJobs) * 100}%` : '0%' }}
                        />
                      </div>
                    </div>
                    <div className="stat-row">
                      <div className="stat-row__header">
                        <span className="stat-row__label">FAILURE RATE</span>
                        <span className="stat-row__value--tertiary">
                          {totalJobs > 0 ? Math.round((failedJobs / totalJobs) * 100) : 0}%
                        </span>
                      </div>
                      <div className="stat-bar">
                        <div
                          className="stat-bar__fill--tertiary"
                          style={{ width: totalJobs > 0 ? `${(failedJobs / totalJobs) * 100}%` : '0%' }}
                        />
                      </div>
                    </div>
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

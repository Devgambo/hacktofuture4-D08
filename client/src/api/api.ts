/**
 * API client for the DevOps Agent backend.
 * TypeScript port of api.js — adds full type safety and proper error handling.
 */

const API_BASE = 'http://localhost:8000';

const fetchOpts: RequestInit = {
  credentials: 'include', // send session cookie
};

// ── Response Types ─────────────────────────────────────────────────────────

export interface User {
  id: string;
  login: string;
  name: string;
  email: string;
  avatar_url: string;
}

export interface AuthContextData {
  user: User;
  repos: any[];
}

export interface Job {
  id: string;
  repo_full_name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  created_at: string;
  updated_at: string;
  type: string;
}

export interface HealthStatus {
  status: 'ok' | 'degraded' | 'down';
  version?: string;
}

export interface MonitoredRepo {
  id: string;
  full_name: string;
  owner: string;
  name: string;
  initialized_at: string;
  webhook_id?: number;
}

export interface MemoryStats {
  total_documents: number;
  total_repos: number;
  repos: Array<{
    repo_full_name: string;
    document_count: number;
  }>;
}

export interface WebhookUrlSetting {
  webhook_base_url: string;
}

export type SSEEventType =
  | 'webhook_received'
  | 'job_started'
  | 'job_completed'
  | 'job_failed'
  | 'agent_step'
  | 'rsi_update_started'
  | 'rsi_update_completed'
  | 'rsi_update_failed'
  | 'rsi_pr_reindex_started'
  | 'rsi_pr_reindex_completed'
  | 'rsi_pr_reindex_failed'
  | 'cold_start_started'
  | 'cold_start_completed'
  | 'cold_start_failed'
  | 'webhook_created'
  | 'rsi_removed'
  | 'memory_store_started'
  | 'memory_stored'
  | 'memory_store_failed';

export interface SSEEvent {
  type: SSEEventType;
  repo_full_name?: string;
  job_id?: string;
  message?: string;
  timestamp?: string;
  [key: string]: unknown;
}

// ── Auth ───────────────────────────────────────────────────────────────────

export async function fetchCurrentUser(): Promise<AuthContextData> {
  const res = await fetch(`${API_BASE}/api/auth/me`, fetchOpts);
  if (!res.ok) throw new Error('Not authenticated');
  return res.json() as Promise<AuthContextData>;
}

export async function logout(): Promise<void> {
  await fetch(`${API_BASE}/api/auth/logout`, {
    method: 'POST',
    ...fetchOpts,
  });
}

// ── Jobs ───────────────────────────────────────────────────────────────────

export async function fetchJobs(): Promise<Job[]> {
  const res = await fetch(`${API_BASE}/api/jobs`, fetchOpts);
  if (!res.ok) throw new Error(`Failed to fetch jobs: ${res.status}`);
  return res.json() as Promise<Job[]>;
}

// ── Health ─────────────────────────────────────────────────────────────────

export async function fetchHealth(): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE}/health`, fetchOpts);
  return res.json() as Promise<HealthStatus>;
}

// ── Repo Initialization ────────────────────────────────────────────────────

/**
 * Initialize a repo — creates webhook + starts RSI cold-start.
 */
export async function initializeRepo(repoFullName: string): Promise<MonitoredRepo> {
  const [owner, ...nameParts] = repoFullName.split('/');
  const repoName = nameParts.join('/');
  const res = await fetch(
    `${API_BASE}/api/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repoName)}/initialize`,
    { method: 'POST', ...fetchOpts }
  );
  if (!res.ok) throw new Error(`Failed to initialize repo: ${res.status}`);
  return res.json() as Promise<MonitoredRepo>;
}

// ── Monitored Repos ────────────────────────────────────────────────────────

export async function fetchMonitoredRepos(): Promise<MonitoredRepo[]> {
  const res = await fetch(`${API_BASE}/api/repos/monitored`, fetchOpts);
  if (!res.ok) throw new Error(`Failed to fetch monitored repos: ${res.status}`);
  return res.json() as Promise<MonitoredRepo[]>;
}

export async function removeMonitoredRepo(repoFullName: string): Promise<{ message: string }> {
  const [owner, ...nameParts] = repoFullName.split('/');
  const repoName = nameParts.join('/');
  const res = await fetch(
    `${API_BASE}/api/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repoName)}/monitoring`,
    { method: 'DELETE', ...fetchOpts }
  );
  if (!res.ok) throw new Error(`Failed to remove repo: ${res.status}`);
  return res.json() as Promise<{ message: string }>;
}

// ── Agent Memory ───────────────────────────────────────────────────────────

export async function fetchMemoryStats(): Promise<MemoryStats> {
  const res = await fetch(`${API_BASE}/api/memory/stats`, fetchOpts);
  if (!res.ok) throw new Error(`Failed to fetch memory stats: ${res.status}`);
  return res.json() as Promise<MemoryStats>;
}

// ── Webhook URL Settings ───────────────────────────────────────────────────

export async function fetchWebhookUrl(): Promise<WebhookUrlSetting> {
  const res = await fetch(`${API_BASE}/api/settings/webhook-url`, fetchOpts);
  if (!res.ok) throw new Error(`Failed to fetch webhook URL: ${res.status}`);
  return res.json() as Promise<WebhookUrlSetting>;
}

export async function updateWebhookUrl(webhookBaseUrl: string): Promise<WebhookUrlSetting> {
  const res = await fetch(`${API_BASE}/api/settings/webhook-url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ webhook_base_url: webhookBaseUrl }),
    ...fetchOpts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({} as { detail?: string }));
    throw new Error((err as { detail?: string }).detail ?? `Failed to update webhook URL: ${res.status}`);
  }
  return res.json() as Promise<WebhookUrlSetting>;
}

// ── GitHub Repos (for repo picker) ─────────────────────────────────────────

export interface UserRepo {
  id: number;
  full_name: string;
  name: string;
  owner: string;
  private: boolean;
  description: string | null;
  updated_at: string;
}

/**
 * Fetch authenticated user's GitHub repositories.
 * Supports an optional search query (matched server-side).
 */
export async function fetchUserRepos(search?: string): Promise<UserRepo[]> {
  const params = new URLSearchParams();
  if (search?.trim()) params.set('q', search.trim());
  const query = params.toString() ? `?${params.toString()}` : '';
  const res = await fetch(`${API_BASE}/api/github/repos${query}`, fetchOpts);
  if (!res.ok) throw new Error(`Failed to fetch repos: ${res.status}`);
  return res.json() as Promise<UserRepo[]>;
}

// ── SSE Event Stream ───────────────────────────────────────────────────────

/**
 * Connect to the SSE event stream and call onEvent for each parsed event.
 * Returns an EventSource so the caller can call .close() on cleanup.
 *
 * Note: Only uses per-type addEventListener (no onmessage) to avoid
 * double-processing events that have a named type.
 */
export function connectEventStream(onEvent: (event: SSEEvent) => void): EventSource {
  const es = new EventSource(`${API_BASE}/api/events`, { withCredentials: true });

  const eventTypes: SSEEventType[] = [
    'webhook_received', 'job_started', 'job_completed', 'job_failed',
    'agent_step',
    'rsi_update_started', 'rsi_update_completed', 'rsi_update_failed',
    'rsi_pr_reindex_started', 'rsi_pr_reindex_completed', 'rsi_pr_reindex_failed',
    'cold_start_started', 'cold_start_completed', 'cold_start_failed',
    'webhook_created', 'rsi_removed',
    'memory_store_started', 'memory_stored', 'memory_store_failed',
  ];

  eventTypes.forEach((type) => {
    es.addEventListener(type, (e: Event) => {
      try {
        const parsed = JSON.parse((e as MessageEvent).data) as SSEEvent;
        onEvent(parsed);
      } catch {
        /* skip malformed events */
      }
    });
  });

  es.onerror = () => {
    console.warn('SSE connection error — will auto-reconnect');
  };

  return es;
}

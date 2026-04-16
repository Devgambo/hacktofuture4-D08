/**
 * UI-specific types — component props and view-layer shapes.
 * API response types live in src/api/api.ts.
 */

// ── Component Props ─────────────────────────────────────────────────────────

export interface TopbarProps {
  title: string;
  breadcrumb: string;
}

export interface ResourceBarProps {
  label: string;
  value: string;
  percentage: number;
  color: 'primary' | 'tertiary' | 'secondary' | 'error';
}

// ── View Models (derived from API data for display) ─────────────────────────

export interface LogLine {
  id: string;
  timestamp: string;
  level: string;
  message: string;
  highlight?: boolean;
  dimmed?: boolean;
}

export type AsyncStatus = 'idle' | 'loading' | 'success' | 'error';

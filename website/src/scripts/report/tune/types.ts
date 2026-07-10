import type { AlertDirection, ChartMode, DetectorParams, DetectorType } from '../../demo/types';

// ---------------------------------------------------------------------------
// Payload contract — kept in lockstep with detectkit/tuning/payload.py
// ---------------------------------------------------------------------------

/** The detector seed (camelCase DetectorParams minus the alert-only knobs). */
export type DetectorSeed = Omit<DetectorParams, 'consecutiveAnomalies' | 'direction'>;

/** One of the metric's configured detectors (for the picker + preserve note). */
export interface DetectorEntry {
  /** slot in the metric's YAML `detectors:` list (what Apply rewrites/preserves). */
  index: number;
  type: string;
  /** true for mad/zscore/iqr/manual_bounds; false for prophet/timesfm (preserved, not tunable). */
  tunable: boolean;
  /** camelCase control seed for tunable detectors; null for non-tunable ones. */
  seed: DetectorSeed | null;
  /** compact one-line summary for display (e.g. `mad · threshold=3 · window=8640`). */
  summary: string;
}

export interface TunePoint {
  t: number;
  v: number | null;
}

export interface TunePayload {
  metric: string;
  project: string | null;
  description: string | null;
  interval_seconds: number;
  period: { start: number; end: number };
  points: TunePoint[];
  /** one seasonal-key map per point, aligned with `points` (empty when no seasonality). */
  seasonality: Array<Record<string, number>>;
  seasonality_columns: string[];
  detector: DetectorSeed;
  /** every configured detector, for the picker + the "preserved on Apply" note. */
  detectors?: DetectorEntry[];
  /** slot the cockpit opens on (first windowed, then first tunable); null = none tunable. */
  detector_index?: number | null;
  consecutive_anomalies: number;
  /** fraction alert rule seeds (issue #101): the first alert config's
   * anomaly_window pre-resolved to grid points + its share; null/absent = the
   * legacy consecutive-only rule. Both-or-neither, like the config model. */
  anomaly_window_points?: number | null;
  min_anomaly_share?: number | null;
  /** alert-layer direction the view filter seeds to ('any' = both). */
  direction?: AlertDirection;
  /** localhost POST endpoint for Apply; null = static read-only preview. */
  save_url: string | null;
  /** seeded incident spans ({start,end,label} naive-UTC strings) from incidents/<metric>/. */
  incidents?: Array<{ start: string; end: string; label?: string }>;
  /** seeded threshold-capture window(s) ({start,end} naive-UTC strings) — regime scope. */
  capture_windows?: Array<{ start: string; end: string }>;
  /** seeded per-alert review verdicts (span + 'valid'/'false') from the saved file. */
  alert_reviews?: Array<{ start: string; end: string; verdict: string }>;
  /** false-alert-rate (FDR) budget the quality bar flags when exceeded (fraction 0..1). */
  false_alert_budget?: number | null;
  /** localhost POST endpoint for Save labels; null = download instead (no server). */
  labels_save_url?: string | null;
  /** localhost POST endpoint for server-side Autotune; null = unavailable (static preview). */
  autotune_url?: string | null;
}

/** The server-side autotune result (mirrors detectkit/tuning/server.py `_run_autotune`). */
export interface AutotuneResult {
  detector: DetectorSeed;
  consecutive_anomalies: number | null;
  /** fraction rule the sweep adopted (points + share), null when not chosen. */
  anomaly_window_points?: number | null;
  min_anomaly_share?: number | null;
  seasonality: string[][] | null;
  score: number;
  scoring_metric: string;
  mode: string;
  n_points: number;
  n_candidates: number;
  labels_summary: Record<string, number>;
  cv_per_fold: number[];
  decision_log: Array<{ stage: string; message: string; fields?: Record<string, unknown> }>;
  winner: string;
}

/** UI mode: the chart's three layer-modes plus an Autotune panel (chart stays in 'tune'). */
export type UiMode = ChartMode | 'autotune';

// Per-type interval-width default (mirrors the detector classes / the demo).
// Partial: manual_bounds has no threshold / per-group default.
export const THRESHOLD_DEFAULT: Partial<Record<DetectorType, number>> = {
  mad: 3.0,
  zscore: 3.0,
  iqr: 1.5,
  autoreg: 3.0,
};
export const MIN_SAMPLES_PER_GROUP_DEFAULT: Partial<Record<DetectorType, number>> = {
  mad: 10,
  zscore: 3,
  iqr: 4,
};

export const ROOT_CLASS = 'dtk-tune';

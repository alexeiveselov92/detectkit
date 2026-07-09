// Contract for the `dtk ui` project-level cockpit.
//
// Two payload families:
//  - the BOOT payload (window.__DTK_UI_PAYLOAD__), baked by detectkit/ui/html.py
//    from the static metric list at server start;
//  - the live JSON contracts served by detectkit/ui/server.py's /api/* routes,
//    fetched by this renderer at runtime (never baked).
//
// Keep this file and detectkit/ui/server.py + overview.py in lockstep — same
// keys, same units. All timestamps are integer ms-epoch (UTC) unless noted.

// ----------------------------------------------------------------------------
// Boot payload
// ----------------------------------------------------------------------------

export interface BootMetric {
  name: string;
  dir: string;
  file: string;
  tags: string[];
  interval_seconds: number;
  enabled: boolean;
}

export type WindowPreset = '24h' | '7d' | '30d' | '90d' | 'all';

export interface BootPayload {
  project: string;
  initial_window: string;
  version: string;
  metrics: BootMetric[];
  generated_at: number;
}

// ----------------------------------------------------------------------------
// Overview (GET /api/overview?window=P)
// ----------------------------------------------------------------------------

export interface AlertRuleSummary {
  configs: number;
  enabled: number;
  min_detectors: number;
  direction: string;
  consecutive: number;
}

export interface AlertsSummary {
  anomaly: number;
  recovery: number;
  no_data: number;
  per_day: number | null;
  last_ts: number | null;
}

export interface QualitySummary {
  incidents: number;
  incidents_in_window: number;
  caught: number;
  recall: number | null;
  false_alerts: number;
  fdr: number | null;
  reviewed: number;
  reviewed_valid: number;
  reviewed_false: number;
  labels_file: string;
}

export interface OverviewMetric {
  name: string;
  dir: string;
  file: string;
  tags: string[];
  enabled: boolean;
  interval_seconds: number;
  detectors: string[];
  alert_rule: AlertRuleSummary | null;
  last_point: number | null;
  first_point_in_window: number | null;
  lag_seconds: number | null;
  locked: boolean;
  points: number;
  flagged: number;
  anomaly_rate: number | null;
  alerts: AlertsSummary;
  quality: QualitySummary | null;
  budget: number;
  /** [ms, mean value | null], at most ~160 buckets, ascending by time */
  spark: Array<[number, number | null]>;
  /** anomalous timestamps (ms), union across detectors, capped ~400 */
  spark_anoms: number[];
  error: string | null;
  /**
   * Client-only: never sent by the server. Set while the cockpit is still
   * waiting on this metric's `GET /api/stats/<name>` fetch (the row is a
   * boot-metadata-only placeholder — see `ui.ts`'s `buildPendingRow`) and
   * cleared once the real row lands (success or per-metric error).
   */
  pending?: boolean;
}

export interface OverviewWindow {
  preset: string;
  days: number | null;
}

export interface OverviewPayload {
  project: string;
  window: OverviewWindow;
  generated_at: number;
  now: number;
  metrics: OverviewMetric[];
}

// ----------------------------------------------------------------------------
// Jobs
// ----------------------------------------------------------------------------

export type JobKind = 'run' | 'autotune' | 'unlock' | 'tune';
export type JobStatus = 'running' | 'done' | 'failed' | 'stopped';

/** Job metadata without the (potentially large) line buffer. */
export interface JobSnapshot {
  id: string;
  kind: JobKind;
  label: string;
  status: JobStatus;
  returncode: number | null;
  url: string | null;
  started_at: number;
  finished_at: number | null;
}

export interface JobsListResponse {
  jobs: JobSnapshot[];
}

/** GET /api/job/<id>?offset=N response: a page of lines from `offset` on. */
export interface JobDetail {
  id: string;
  kind: JobKind;
  label: string;
  status: JobStatus;
  returncode: number | null;
  url: string | null;
  next_offset: number;
  lines: string[];
}

// ----------------------------------------------------------------------------
// Job-spawning requests
// ----------------------------------------------------------------------------

export type PipelineStep = 'load' | 'detect' | 'alert';

export interface RunRequest {
  select: string;
  steps: PipelineStep[];
  from: string | null;
  to: string | null;
  full_refresh: boolean;
  force: boolean;
}

export interface AutotuneRequest {
  select: string;
  from: string | null;
  to: string | null;
}

export interface UnlockRequest {
  select: string;
}

export interface TuneRequest {
  metric: string;
}

export interface JobIdResponse {
  job_id: string;
}

export interface TuneResponse {
  job_id: string;
  url: string;
}

export interface OkResponse {
  ok: boolean;
}

// ----------------------------------------------------------------------------
// Metric CRUD (GET /api/metrics, /api/metric-source/<name>; POST
// /api/metric-create, /api/metric/<name>/update, /api/metric/<name>/delete)
// ----------------------------------------------------------------------------

/** GET /api/metrics response: the refreshed session metric list (same shape as the boot payload's `metrics`). */
export interface MetricsListResponse {
  metrics: BootMetric[];
}

/** GET /api/metric-source/<name> response: the raw YAML text behind one metric's file, for the editor. */
export interface MetricSourceResponse {
  name: string;
  dir: string;
  file: string;
  text: string;
  /** Optimistic-concurrency token: echo it back on update so a stale editor can't clobber a newer save. */
  digest: string;
}

/** POST /api/metric-create body. */
export interface MetricCreateRequest {
  text: string;
  folder?: string;
}

/** POST /api/metric/<name>/update body. */
export interface MetricUpdateRequest {
  text: string;
  /** The `digest` from the metric-source response this editor was opened with. */
  digest?: string;
}

/**
 * Response shared by create/update/delete. Fields not sent by a given route
 * (e.g. `file` on update/delete, `renamed_from`/`archived`/`note` on create)
 * are simply absent — every caller only reads the fields its own route sends.
 */
export interface MetricMutationResponse {
  name: string;
  file?: string;
  renamed_from?: string | null;
  archived?: string | null;
  note?: string | null;
  metrics: BootMetric[];
}

// ----------------------------------------------------------------------------
// Renderer global entry
// ----------------------------------------------------------------------------

export interface DtkUiGlobal {
  render(payload: BootPayload, mount: HTMLElement): void;
}

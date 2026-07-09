// Thin fetch layer for the `dtk ui` cockpit's localhost server.
//
// Every route is token-guarded (GET and POST), so the token read from
// location.search rides on every request as a `?token=` query param. Errors
// come back as plain-text bodies (never in the HTTP status line — the server
// mirrors dtk tune's `_reply_error`), so failures surface the server's exact
// message text via `Error.message` for the caller to toast.

import type {
  AutotuneRequest,
  JobDetail,
  JobIdResponse,
  JobsListResponse,
  MetricCreateRequest,
  MetricMutationResponse,
  MetricSourceResponse,
  MetricsListResponse,
  MetricUpdateRequest,
  OkResponse,
  OverviewMetric,
  RunRequest,
  TuneRequest,
  TuneResponse,
  UnlockRequest,
} from './payload';

/** The one-shot session token, read once from the boot URL's query string. */
export const TOKEN: string = new URLSearchParams(location.search).get('token') || '';

function buildUrl(path: string, params?: Record<string, string>): string {
  const u = new URL(path, location.origin);
  u.searchParams.set('token', TOKEN);
  if (params) for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v);
  return u.toString();
}

/** Build a fully-qualified metric detail URL (used for the overlay iframe + "Open dashboard"-style links). */
export function metricUrl(name: string, windowPreset: string): string {
  return buildUrl(`/metric/${encodeURIComponent(name)}`, { window: windowPreset });
}

async function readError(res: Response): Promise<Error> {
  const text = await res.text().catch(() => '');
  return new Error(text || `HTTP ${res.status}`);
}

async function apiGet<T>(path: string, params?: Record<string, string>): Promise<T> {
  const res = await fetch(buildUrl(path, params));
  if (!res.ok) throw await readError(res);
  return res.json() as Promise<T>;
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(buildUrl(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await readError(res);
  return res.json() as Promise<T>;
}

// `/api/overview` (the monolithic all-metrics endpoint) is deliberately
// unused by the cockpit: on a production-sized project it serializes a full
// stats read for every metric on one DB connection, which can take minutes —
// long enough for the browser to abort the request while the page shows an
// endless spinner. `fetchMetricStats` below hits the per-metric endpoint
// instead, so the page can load incrementally (see ui.ts's `loadOverview`).

/** One metric's overview row — the incremental unit the cockpit fetches. */
export function fetchMetricStats(name: string, windowPreset: string): Promise<OverviewMetric> {
  return apiGet<OverviewMetric>(`/api/stats/${encodeURIComponent(name)}`, { window: windowPreset });
}

export function fetchJobs(): Promise<JobsListResponse> {
  return apiGet<JobsListResponse>('/api/jobs');
}

export function fetchJobDetail(id: string, offset: number): Promise<JobDetail> {
  return apiGet<JobDetail>(`/api/job/${encodeURIComponent(id)}`, { offset: String(offset) });
}

export function postRun(req: RunRequest): Promise<JobIdResponse> {
  return apiPost<JobIdResponse>('/api/run', req);
}

export function postAutotune(req: AutotuneRequest): Promise<JobIdResponse> {
  return apiPost<JobIdResponse>('/api/autotune', req);
}

export function postUnlock(req: UnlockRequest): Promise<JobIdResponse> {
  return apiPost<JobIdResponse>('/api/unlock', req);
}

export function postTune(req: TuneRequest): Promise<TuneResponse> {
  return apiPost<TuneResponse>('/api/tune', req);
}

export function postStopJob(id: string): Promise<OkResponse> {
  return apiPost<OkResponse>(`/api/job/${encodeURIComponent(id)}/stop`, {});
}

// ---- metric CRUD (see detectkit/ui/metric_files.py + server.py's metric_entries) ----

/** The refreshed session metric list (used to re-sync after a create/update/delete elsewhere). */
export function fetchMetricsList(): Promise<MetricsListResponse> {
  return apiGet<MetricsListResponse>('/api/metrics');
}

/** One metric's raw YAML text, for the editor overlay. */
export function fetchMetricSource(name: string): Promise<MetricSourceResponse> {
  return apiGet<MetricSourceResponse>(`/api/metric-source/${encodeURIComponent(name)}`);
}

export function postMetricCreate(req: MetricCreateRequest): Promise<MetricMutationResponse> {
  return apiPost<MetricMutationResponse>('/api/metric-create', req);
}

export function postMetricUpdate(name: string, req: MetricUpdateRequest): Promise<MetricMutationResponse> {
  return apiPost<MetricMutationResponse>(`/api/metric/${encodeURIComponent(name)}/update`, req);
}

/** Builds the required `{confirm: name}` body itself — the server refuses a delete without it. */
export function postMetricDelete(name: string): Promise<MetricMutationResponse> {
  return apiPost<MetricMutationResponse>(`/api/metric/${encodeURIComponent(name)}/delete`, {
    confirm: name,
  });
}

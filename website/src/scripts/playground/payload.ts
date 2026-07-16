// Synthetic-payload adapter for the interactive playground.
//
// The landing playground is now a literal instance of the shipped `dtk tune`
// cockpit (../report/tune) — same chart, same detector worker, same controls and
// quality bar — fed a SYNTHETIC metric instead of a real `_dtk_datapoints` series.
// This module is the one adapter that makes that possible: it turns a synth
// `Series` (../demo/synth) into the exact `TunePayload` the cockpit consumes, with
// the three server hooks (`save_url` / `labels_save_url` / `autotune_url`) nulled —
// the same shape `dtk tune --no-serve` produces, so every backend action degrades
// to its offline form (Apply → a preview note, Save → a download, Autotune → a
// "needs the live server" note) with no code path of its own.
//
// It sits ABOVE demo/ (like report/tune.ts), so demo/ stays the shared lower layer
// and nothing here leaks into the shipped bundles.

import type { AlertDirection, DetectorType, Series } from '../demo/types';
import type { DetectorSeed, TunePayload } from '../report/tune/types';

// Per-type seed defaults, mirroring the detector classes / the cockpit's
// THRESHOLD_DEFAULT + MIN_SAMPLES_PER_GROUP_DEFAULT (report/tune/types.ts). Kept
// here rather than imported so the playground layer owns its own opening config.
const THRESHOLD: Record<DetectorType, number> = {
  mad: 3,
  zscore: 3,
  iqr: 1.5,
  autoreg: 3,
  manual_bounds: 0,
};
const MIN_SAMPLES_PER_GROUP: Record<DetectorType, number> = {
  mad: 10,
  zscore: 3,
  iqr: 4,
  autoreg: 10,
  manual_bounds: 10,
};
// Windowed detectors open on a 10-day-ish window; autoreg opens narrower (its
// warm-up is 2·window+lags under the default-on clamp, so a huge window would dim
// the whole chart). Mirrors the demo's historical defaults + the Python
// _WINDOW_SIZE_DEFAULT (autoreg 200).
const WINDOW_SIZE: Record<DetectorType, number> = {
  mad: 240,
  zscore: 240,
  iqr: 240,
  autoreg: 200,
  manual_bounds: 0,
};

/**
 * A sensible opening seed for a detector type. `mad`/`zscore`/`iqr` open with
 * hour-of-day seasonality on (a tight per-hour band on a daily metric is the
 * clearest "wow"); autoreg forces its default-on clamp + a lags knob and no
 * seasonality (v1 rejects it); manual_bounds leaves the bounds null so the cockpit
 * derives them from the real value domain (p5/p95).
 */
export function defaultSeed(type: DetectorType, seasonal = true): DetectorSeed {
  const windowed = type === 'mad' || type === 'zscore' || type === 'iqr';
  return {
    type,
    threshold: THRESHOLD[type],
    windowSize: WINDOW_SIZE[type],
    minSamples: 30,
    inputType: 'values',
    smoothing: 'none',
    smoothingAlpha: 0.3,
    smoothingWindow: 10,
    windowWeights: 'none',
    halfLife: null,
    detrend: 'none',
    stabilization: type === 'autoreg' ? 'clamp' : 'none',
    seasonalityComponents: windowed && seasonal ? [['hour_of_day']] : null,
    minSamplesPerGroup: MIN_SAMPLES_PER_GROUP[type],
    lags: type === 'autoreg' ? 5 : undefined,
  };
}

/** A compact one-line summary for the (single-entry) detector picker. */
function seedSummary(seed: DetectorSeed): string {
  if (seed.type === 'manual_bounds') return 'manual_bounds';
  const parts = [seed.type, `threshold=${seed.threshold}`, `window=${seed.windowSize}`];
  if (seed.type === 'autoreg') parts.push(`lags=${seed.lags ?? 5}`);
  return parts.join(' · ');
}

/** Naive-UTC display string the cockpit parses back (`Date.parse(s.replace(' ','T')+'Z')`). */
function fmtUtc(ms: number): string {
  return new Date(ms).toISOString().slice(0, 19).replace('T', ' ');
}

/**
 * Turn the synth's ground-truth `truthAnomaly` mask into seeded incident spans, so
 * the injected incident shows pre-marked in Label mode and drives the cockpit's
 * live recall / false-alert metrics — the upgrade of the old scorecard's
 * caught/missed. Each contiguous truth run becomes one span padded half an interval
 * each side (matching the cockpit's lasso/threshold conventions, so a single
 * matching point reads as a full-interval incident an alert can land inside).
 */
function truthToIncidents(series: Series, kind: string): TunePayload['incidents'] {
  const truth = series.truthAnomaly;
  const half = (series.intervalSeconds * 1000) / 2;
  const spans: NonNullable<TunePayload['incidents']> = [];
  let runStart = -1;
  for (let i = 0; i <= truth.length; i++) {
    const on = i < truth.length && truth[i];
    if (on && runStart < 0) runStart = i;
    else if (!on && runStart >= 0) {
      spans.push({
        start: fmtUtc(series.timestamps[runStart] - half),
        end: fmtUtc(series.timestamps[i - 1] + half),
        label: `injected ${kind}`,
      });
      runStart = -1;
    }
  }
  return spans;
}

export interface SyntheticPayloadOptions {
  series: Series;
  seed: DetectorSeed;
  consecutive: number;
  /** fraction alert rule (issue #101): grid points + share, or nulls for the
   * classic consecutive-only rule. */
  windowPoints: number | null;
  share: number | null;
  direction: AlertDirection;
  /** the injected incident kind, used only to label the seeded ground-truth span. */
  incidentKind: string;
  /** short human line under the header (e.g. the synth shape). */
  description?: string | null;
}

/**
 * Build the cockpit payload from a synthetic series. The three `*_url` server hooks
 * are `null` — this is exactly the `dtk tune --no-serve` shape, which the cockpit
 * already supports fully client-side.
 */
export function buildSyntheticPayload(opts: SyntheticPayloadOptions): TunePayload {
  const { series, seed } = opts;
  const n = series.timestamps.length;
  return {
    metric: 'your metric',
    project: 'playground',
    description: opts.description ?? null,
    interval_seconds: series.intervalSeconds,
    period: { start: series.timestamps[0], end: series.timestamps[n - 1] },
    points: series.timestamps.map((t, i) => ({
      t,
      v: Number.isFinite(series.values[i]) ? series.values[i] : null,
    })),
    seasonality: series.seasonalityData ?? [],
    seasonality_columns: series.seasonalityColumns ?? [],
    detector: seed,
    detectors: [{ index: 0, type: seed.type, tunable: true, seed, summary: seedSummary(seed) }],
    detector_index: 0,
    consecutive_anomalies: opts.consecutive,
    anomaly_window_points: opts.windowPoints,
    min_anomaly_share: opts.share,
    direction: opts.direction,
    incidents: truthToIncidents(series, opts.incidentKind),
    // Offline (serverless) — every backend action degrades to its --no-serve form.
    save_url: null,
    labels_save_url: null,
    autotune_url: null,
    false_alert_budget: null,
  };
}

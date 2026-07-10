// tune.ts — the interactive manual-tuning renderer for `dtk tune`.
//
// The human-in-the-loop sibling of the report renderer. The Python tuning layer
// (detectkit/tuning/) bakes a TunePayload — the metric's REAL gap-filled series,
// the per-point seasonality keys, the current detector config and the alert
// consecutive window — into a self-contained HTML page and inlines this bundle.
// At load it assigns `window.__DTK_TUNE__ = { render }`.
//
// Unlike the read-only report, this view RECOMPUTES live: it reuses the same
// faithful TypeScript detector port (../demo/detector) and chart (../demo/chart)
// that power the landing playground, fed the real series instead of synthetic
// data. Turning a knob re-runs runDetector → chart.render in well under a frame.
// When the payload carries a `save_url` (the localhost server), an "Apply to
// metric" button POSTs the chosen config back; without it (a static preview) the
// sliders still recompute but there is no write-back.

import { createChart } from '../demo/chart';
import type {
  AlertDirection,
  ChartAlert,
  ChartHandle,
  ChartMode,
  Detrend,
  DetectorParams,
  DetectorType,
  Incident,
  LassoInfo,
  ScoredPoint,
  Series,
  Smoothing,
  Stabilization,
  ThresholdInfo,
  WindowWeights,
} from '../demo/types';

// The bundled detector worker source, injected as a string literal at build time
// (see website/scripts/gen-tune-bundle.mjs). Instantiated from a Blob URL so the
// report stays a single self-contained file with no external requests.
declare const __DTK_WORKER_SRC__: string;

/** Shape of the message the worker posts back after a `run`. */
interface WorkerResult {
  type: 'result';
  id: number;
  scored: ScoredPoint[];
  fires: number[];
  /** per-fire [startTs, endTs] of the whole grid-adjacent anomaly streak (ms). */
  fireSpans: Array<[number, number]>;
  eff: number;
  flagged: number;
}

// ---------------------------------------------------------------------------
// Payload contract — kept in lockstep with detectkit/tuning/payload.py
// ---------------------------------------------------------------------------

/** The detector seed (camelCase DetectorParams minus the alert-only knobs). */
type DetectorSeed = Omit<DetectorParams, 'consecutiveAnomalies' | 'direction'>;

/** One of the metric's configured detectors (for the picker + preserve note). */
interface DetectorEntry {
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

interface TunePoint {
  t: number;
  v: number | null;
}

interface TunePayload {
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
interface AutotuneResult {
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
type UiMode = ChartMode | 'autotune';

// Per-type interval-width default (mirrors the detector classes / the demo).
// Partial: manual_bounds has no threshold / per-group default.
const THRESHOLD_DEFAULT: Partial<Record<DetectorType, number>> = {
  mad: 3.0,
  zscore: 3.0,
  iqr: 1.5,
  autoreg: 3.0,
};
const MIN_SAMPLES_PER_GROUP_DEFAULT: Partial<Record<DetectorType, number>> = {
  mad: 10,
  zscore: 3,
  iqr: 4,
};

const ROOT_CLASS = 'dtk-tune';

// ---------------------------------------------------------------------------
// Small DOM helpers
// ---------------------------------------------------------------------------

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  cls?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

interface SegSpec {
  label: string;
  value: string;
}

/** A control label carrying an optional tooltip (native title + a faint ⓘ). */
function ctlLabel(text: string, hint?: string): HTMLElement {
  const lab = el('label', 'dtk-ctl-label', text);
  if (hint) {
    lab.title = hint;
    const q = el('span', 'dtk-ctl-info', 'ⓘ');
    q.title = hint;
    lab.appendChild(document.createTextNode(' '));
    lab.appendChild(q);
  }
  return lab;
}

/** A segmented button group. Returns the row element + a getter/setter. */
function segControl(
  label: string,
  options: SegSpec[],
  initial: string,
  onChange: (v: string) => void,
  hint?: string,
): { row: HTMLElement; get: () => string; set: (v: string) => void } {
  const row = el('div', 'dtk-ctl');
  row.appendChild(ctlLabel(label, hint));
  const group = el('div', 'dtk-seg');
  let current = initial;
  const buttons: HTMLButtonElement[] = [];
  const paint = (): void => {
    buttons.forEach((b) => b.classList.toggle('on', b.dataset.v === current));
  };
  options.forEach((opt) => {
    const b = el('button', 'dtk-seg-btn', opt.label);
    b.type = 'button';
    b.dataset.v = opt.value;
    b.onclick = (): void => {
      current = opt.value;
      paint();
      onChange(current);
    };
    buttons.push(b);
    group.appendChild(b);
  });
  paint();
  row.appendChild(group);
  return {
    row,
    get: () => current,
    set: (v: string) => {
      current = v;
      paint();
    },
  };
}

/** A labeled range slider with a live value echo. */
function rangeControl(
  label: string,
  opts: {
    min: number;
    max: number;
    step: number;
    value: number;
    fmt?: (v: number) => string;
    hint?: string;
  },
  onChange: (v: number) => void,
): { row: HTMLElement; get: () => number; set: (v: number) => void; setMax: (m: number) => void } {
  const row = el('div', 'dtk-ctl');
  const head = el('div', 'dtk-ctl-head');
  const lab = ctlLabel(label, opts.hint);
  const out = el('span', 'dtk-ctl-val');
  const fmt = opts.fmt ?? ((v: number): string => String(v));
  head.appendChild(lab);
  head.appendChild(out);
  row.appendChild(head);
  const input = el('input', 'dtk-range');
  input.type = 'range';
  input.min = String(opts.min);
  input.max = String(opts.max);
  input.step = String(opts.step);
  input.value = String(opts.value);
  out.textContent = fmt(opts.value);
  // Live value echo WHILE dragging (cheap), but fire the (expensive) onChange only
  // on `change` — i.e. when the drag is released — so pausing mid-drag with the
  // button still held doesn't kick off a recompute. Keyboard arrows fire both.
  input.oninput = (): void => {
    out.textContent = fmt(Number(input.value));
  };
  input.onchange = (): void => {
    const v = Number(input.value);
    out.textContent = fmt(v);
    onChange(v);
  };
  row.appendChild(input);
  return {
    row,
    get: () => Number(input.value),
    // Programmatic set (e.g. re-seeding from an autotune result). Updates the echo
    // but, like a chart-driven change, does NOT fire onChange — the caller drives
    // the recompute once after re-seeding every control.
    set: (v: number) => {
      input.value = String(v);
      out.textContent = fmt(Number(input.value));
    },
    setMax: (m: number) => {
      input.max = String(m);
      if (Number(input.value) > m) {
        input.value = String(m);
        out.textContent = fmt(m);
      }
    },
  };
}

// ---------------------------------------------------------------------------
// Effective-config readout + the snake_case apply body
// ---------------------------------------------------------------------------

/** Build the snake_case params written to YAML (omitting defaults/none). */
function applyParams(p: DetectorParams): Record<string, unknown> {
  if (p.type === 'manual_bounds') {
    // Stateless thresholds — no window/threshold/weights/etc. Both bounds are
    // always emitted by the tuner (the controls keep lower < upper).
    const mb: Record<string, unknown> = {};
    if (p.lowerBound != null) mb.lower_bound = p.lowerBound;
    if (p.upperBound != null) mb.upper_bound = p.upperBound;
    if (p.inputType !== 'values') mb.input_type = p.inputType;
    return mb;
  }
  if (p.type === 'autoreg') {
    // Prediction-based AR(p): its own param set — lags/threshold/window +
    // min_samples (emitted explicitly, clamped valid: the Python constructor
    // requires lags+2 <= min_samples <= window_size) + stabilization, which
    // is DEFAULT-ON for autoreg, so turning it off must be written as null.
    // Never seasonality/weights/detrend/smoothing (v1 has none; the detector
    // rejects truthy seasonality_components).
    const lags = Math.max(1, Math.round(p.lags ?? 5));
    const ar: Record<string, unknown> = {
      lags,
      threshold: p.threshold,
      window_size: p.windowSize,
      min_samples: Math.min(Math.max(p.minSamples, lags + 2), p.windowSize),
    };
    if (p.stabilization !== 'clamp') ar.stabilization = null;
    if (p.inputType !== 'values') ar.input_type = p.inputType;
    return ar;
  }
  const out: Record<string, unknown> = {
    threshold: p.threshold,
    window_size: p.windowSize,
  };
  if (p.windowWeights !== 'none') {
    out.window_weights = p.windowWeights;
    if (p.windowWeights === 'exponential' && p.halfLife != null) out.half_life = p.halfLife;
  }
  if (p.detrend !== 'none') out.detrend = p.detrend;
  if (p.stabilization && p.stabilization !== 'none') out.stabilization = p.stabilization;
  if (p.smoothing !== 'none') out.smoothing = p.smoothing;
  if (p.inputType !== 'values') out.input_type = p.inputType;
  if (p.seasonalityComponents && p.seasonalityComponents.length) {
    out.seasonality_components = p.seasonalityComponents;
    out.min_samples_per_group = p.minSamplesPerGroup;
  }
  return out;
}

function configText(
  p: DetectorParams,
  consecutive: number,
  windowPoints?: number | null,
  share?: number | null,
): string {
  const ap = applyParams(p);
  const parts = [`type: ${p.type}`];
  for (const [k, v] of Object.entries(ap)) {
    parts.push(`${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`);
  }
  if (p.direction && p.direction !== 'any') parts.push(`direction=${p.direction}`);
  parts.push(`consecutive_anomalies=${consecutive}`);
  if (windowPoints != null && share != null) {
    parts.push(`anomaly_window=${windowPoints}p`);
    parts.push(`min_anomaly_share=${share}`);
  }
  return parts.join('  ·  ');
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function render(payload: TunePayload, mount: HTMLElement): void {
  injectStyle();
  mount.classList.add(ROOT_CLASS);
  mount.innerHTML = '';
  const root = el('div', 'dtk-tune-root');
  mount.appendChild(root);

  // ---- series from the real persisted points -------------------------------
  const n = payload.points.length;
  const fullSeries: Series = {
    timestamps: payload.points.map((p) => p.t),
    values: payload.points.map((p) => (p.v == null ? NaN : p.v)),
    intervalSeconds: payload.interval_seconds,
    truthAnomaly: new Array(n).fill(false),
    seasonalityData: payload.seasonality_columns.length ? payload.seasonality : undefined,
    seasonalityColumns: payload.seasonality_columns.length
      ? payload.seasonality_columns
      : undefined,
  };
  // The active series fed to the detector + chart. The trim slider can shorten it
  // to the most-recent N points, so a very long/heavy metric recomputes faster
  // (cost is O(points × window)) once you've confirmed a smaller period suffices.
  let series: Series = fullSeries;
  const sliceSeries = (count: number): Series => {
    const start = Math.max(0, n - count);
    if (start <= 0) return fullSeries;
    return {
      timestamps: fullSeries.timestamps.slice(start),
      values: fullSeries.values.slice(start),
      intervalSeconds: fullSeries.intervalSeconds,
      truthAnomaly: fullSeries.truthAnomaly.slice(start),
      seasonalityData: fullSeries.seasonalityData
        ? fullSeries.seasonalityData.slice(start)
        : undefined,
      seasonalityColumns: fullSeries.seasonalityColumns,
    };
  };
  // ---- incident labels (the synced labeler shares this exact array) ---------
  // Parsed to ms from the seeded display strings; the labeler chart mutates this
  // SAME array in place (drag create/move/resize/delete) and the controls list
  // edits labels in place — one source of truth, so nothing diverges.
  const parseDisplayTs = (s: string): number => Date.parse(s.replace(' ', 'T') + 'Z');
  const incidents: Incident[] = (payload.incidents || [])
    .map((p) => ({ start: parseDisplayTs(p.start), end: parseDisplayTs(p.end), label: p.label || '' }))
    .filter((iv) => Number.isFinite(iv.start) && Number.isFinite(iv.end))
    .map((iv) => ({ start: Math.min(iv.start, iv.end), end: Math.max(iv.start, iv.end), label: iv.label }));
  // Seeded threshold-capture window (regime scope) from the saved labels file —
  // restored so re-opening keeps the painted scope. Only the first is used.
  const seedCaptureWin = ((): { start: number; end: number } | null => {
    const w = (payload.capture_windows || [])[0];
    if (!w) return null;
    const a = parseDisplayTs(w.start);
    const b = parseDisplayTs(w.end);
    if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
    return { start: Math.min(a, b), end: Math.max(a, b) };
  })();
  // Most-recent worker output, for the live metrics + the synced labeler chart.
  let lastFireTs: number[] = [];
  // Per-alert anomaly-streak spans (ms) — recall/FDR match incidents by OVERLAP
  // with these, not just the fire point (which lands consecutive-1 intervals in).
  let lastFireSpans: Array<[number, number]> = [];
  let lastScored: ScoredPoint[] = [];
  let lastAlerts: ChartAlert[] = [];

  // ---- per-alert review verdicts (validated / false alarm) -------------------
  // The user can confirm each fired alert right on the chart (Review mode / a click
  // on a marker). Stored by STREAK SPAN so a verdict survives a recompute that moves
  // the alerts — it re-binds by overlap, not by an exact timestamp. A 'valid' span
  // also counts as a VIRTUAL incident for recall/FDR (and is written as an incident
  // on Save, so confirming alerts also feeds dtk autotune). 'false' is an explicit
  // false-alarm mark (slate marker); it never rescues the alert from the FDR.
  type Verdict = 'valid' | 'false';
  const reviews: Array<{ start: number; end: number; verdict: Verdict }> = (payload.alert_reviews || [])
    .map((r) => ({
      start: parseDisplayTs(r.start),
      end: parseDisplayTs(r.end),
      verdict: (r.verdict === 'false' ? 'false' : 'valid') as Verdict,
    }))
    .filter((r) => Number.isFinite(r.start) && Number.isFinite(r.end));
  const spanTol = (): number => (payload.interval_seconds * 1000) / 2;
  const reviewFor = (s: number, e: number): Verdict | null => {
    const tol = spanTol();
    for (const r of reviews) if (e >= r.start - tol && s <= r.end + tol) return r.verdict;
    return null;
  };
  const setReview = (s: number, e: number, v: Verdict | null): void => {
    const tol = spanTol();
    for (let i = reviews.length - 1; i >= 0; i--) {
      const r = reviews[i];
      if (e >= r.start - tol && s <= r.end + tol) reviews.splice(i, 1);
    }
    if (v) reviews.push({ start: s, end: e, verdict: v });
  };
  // Confirming an alert valid IS marking an incident there: a valid verdict is the
  // user asserting "a real incident happened in this span". So a valid review is a
  // first-class ground-truth incident — derived from the STORED review span (not the
  // current fire span), so it stays in the ground truth even if the current knob
  // setting no longer fires there (that's a recall MISS the metrics should show) and
  // survives recompute. These show up as rows in the Marked-incidents list and feed
  // recall/FDR alongside the hand-marked incidents — the two are one set, not two.
  const overlapIv = (
    a: { start: number; end: number },
    b: { start: number; end: number },
  ): boolean => {
    const tol = spanTol();
    return a.end >= b.start - tol && a.start <= b.end + tol;
  };
  const validatedSpans = (): Incident[] =>
    reviews
      .filter((r) => r.verdict === 'valid')
      .map((r) => ({ start: r.start, end: r.end, label: 'confirmed alert' }));
  // Validated spans NOT already covered by a hand-marked incident (dedup by overlap)
  // — so the same real incident is never listed/scored/saved twice (e.g. after a
  // Save→reopen, where a confirmed alert is seeded both as an incident and a review).
  const validatedExtra = (): Incident[] =>
    validatedSpans().filter((v) => !incidents.some((iv) => overlapIv(v, iv)));
  // The full ground-truth incident set the live metrics, the list and Save all share.
  const groundTruth = (): Incident[] => [...incidents, ...validatedExtra()];
  // Deleting a hand-marked incident asserts "no real incident in this span", so any
  // confirmed-VALID alert overlapping it is retracted too (cleared to un-reviewed, like
  // unconfirmAlert). Otherwise that verdict — which validatedExtra() was hiding behind
  // the incident — RESURFACES as its own "confirmed alert" row, so the deleted incident
  // appears to turn INTO a confirmed alert instead of vanishing. (Seeded case: Save
  // writes each confirmed alert as both an incident AND a review, so on reopen every
  // incident is backed by one.) Leaves explicit 'false' verdicts alone. Returns whether
  // anything was cleared (→ the alert markers need repainting).
  const retractConfirmationFor = (iv: Incident): boolean => {
    let changed = false;
    for (let i = reviews.length - 1; i >= 0; i--) {
      if (reviews[i].verdict === 'valid' && overlapIv(reviews[i], iv)) {
        reviews.splice(i, 1);
        changed = true;
      }
    }
    return changed;
  };
  // Build the alert markers with their review-verdict color (red / green / slate).
  const buildAlerts = (): ChartAlert[] =>
    lastFireTs.map((t, i) => {
      const sp = lastFireSpans[i] ?? [t, t];
      const v = reviewFor(sp[0], sp[1]);
      return { t, kind: v === 'valid' ? 'anomaly-validated' : v === 'false' ? 'anomaly-false' : 'anomaly' };
    });

  // ---- mutable parameter state, seeded from the metric's current config -----
  // `seed` is the ACTIVE detector's seed — the picker (a multi-detector metric)
  // re-seeds it when you switch which detector you're tuning. readParams() reads
  // the passthrough knobs (minSamples/inputType/smoothing*/minSamplesPerGroup) off it.
  let seed = payload.detector;
  let consecutive = payload.consecutive_anomalies;
  // Fraction alert rule (issue #101): OR-ed with the consecutive rule, exactly
  // like the pipeline. 0/absent window ⇒ off (legacy consecutive-only); the
  // pair is both-or-neither (the share control only matters with a window).
  let anomalyWindowPoints = payload.anomaly_window_points ?? 0;
  let minAnomalyShare = payload.min_anomaly_share ?? 0.3;
  const shareWindowPoints = (): number | null =>
    anomalyWindowPoints >= 2 ? anomalyWindowPoints : null;
  const shareValue = (): number | null => (anomalyWindowPoints >= 2 ? minAnomalyShare : null);

  // ---- multi-detector picker state ------------------------------------------
  // The cockpit tunes ONE detector at a time but a metric can configure several
  // (e.g. a mad pattern detector + a manual_bounds floor). We open on `activeIndex`
  // (the slot the payload picked), remember each detector's live params across
  // switches (`editedParams`), and track which slots the user actually edited
  // (`dirty`). On Apply we write back ONLY the active + dirty slots — every other
  // detector is preserved verbatim by the server, so a retune can't silently drop a
  // floor and kill a min_detectors>=2 alert (the reported bug).
  const detectorEntries: DetectorEntry[] = payload.detectors || [];
  let activeIndex: number | null =
    typeof payload.detector_index === 'number' ? payload.detector_index : null;
  // The slot the cockpit opened on — "the detector you came to tune". It is written
  // on Apply even if you didn't move a knob (matching single-detector behaviour). A
  // detector you merely SWITCHED the picker to but never edited is NOT written, so a
  // lower-bound-only manual_bounds floor can't gain a phantom upper_bound just from
  // being looked at.
  const initialIndex: number | null = activeIndex;
  const dirty = new Set<number>();
  const editedParams = new Map<number, DetectorParams>();
  const markActiveDirty = (): void => {
    if (activeIndex != null) dirty.add(activeIndex);
  };

  // manual_bounds support: derive the value domain from the REAL series so the
  // lower/upper sliders have a sensible range, and seed default bounds. If the
  // metric already uses manual_bounds, its seeded bounds win; otherwise default
  // to the p5/p95 band so switching to manual_bounds shows feedback immediately.
  const finiteVals = fullSeries.values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  const dataMin = finiteVals.length ? finiteVals[0] : 0;
  const dataMax = finiteVals.length ? finiteVals[finiteVals.length - 1] : 1;
  const pct = (q: number): number =>
    finiteVals.length
      ? finiteVals[Math.min(finiteVals.length - 1, Math.max(0, Math.round(q * (finiteVals.length - 1))))]
      : 0;
  const boundPad = Math.max((dataMax - dataMin) * 0.05, 1e-9);
  const boundMin = dataMin - boundPad;
  const boundMax = dataMax + boundPad;
  const boundStep = Math.max((boundMax - boundMin) / 400, 1e-9);
  const seedLower = seed.lowerBound != null ? seed.lowerBound : pct(0.05);
  const seedUpper = seed.upperBound != null ? seed.upperBound : pct(0.95);
  // seasonality: each available column is assigned to a group id (0 = off).
  // Columns sharing a group are conjoined into one seasonal key; separate groups
  // apply independent (cumulative) corrections — the full string[][] the detector
  // supports, not just "all-separate" or "all-in-one".
  const seedGroups = seed.seasonalityComponents ?? [];
  const colGroup = new Map<string, number>();
  seedGroups.forEach((grp, gi) => grp.forEach((c) => colGroup.set(c, gi + 1)));

  const buildSeasonality = (): string[][] | null => {
    let maxG = 0;
    colGroup.forEach((g) => {
      if (g > maxG) maxG = g;
    });
    const groups: string[][] = [];
    for (let g = 1; g <= maxG; g++) {
      const cols = payload.seasonality_columns.filter((c) => colGroup.get(c) === g);
      if (cols.length) groups.push(cols);
    }
    return groups.length ? groups : null;
  };

  // Distinct seasonal keys present for a grouping (max across groups). Same-key
  // points recur once per this many positions, so the window must hold ~this many
  // × min_samples_per_group points before a group fills; below that the detector
  // silently falls back to the global band (seasonality has no effect).
  const seasonalCardinality = (groups: string[][] | null): number => {
    if (!groups || !payload.seasonality.length) return 0;
    let card = 0;
    for (const g of groups) {
      const seen = new Set<string>();
      for (const row of payload.seasonality) seen.add(g.map((c) => String(row?.[c] ?? '')).join('|'));
      card = Math.max(card, seen.size);
    }
    return card;
  };

  const readParams = (): DetectorParams => ({
    type: detectorCtl.get() as DetectorType,
    threshold: thresholdCtl.get(),
    windowSize: windowCtl.get(),
    minSamples: seed.minSamples,
    inputType: seed.inputType,
    smoothing: smoothingCtl.get() as Smoothing,
    smoothingAlpha: seed.smoothingAlpha,
    smoothingWindow: seed.smoothingWindow,
    windowWeights: weightsCtl.get() as WindowWeights,
    halfLife: weightsCtl.get() === 'exponential' ? halfLifeCtl.get() : null,
    detrend: detrendCtl.get() as Detrend,
    stabilization: stabilizationCtl.get() as Stabilization,
    seasonalityComponents: buildSeasonality(),
    minSamplesPerGroup:
      MIN_SAMPLES_PER_GROUP_DEFAULT[detectorCtl.get() as DetectorType] ?? seed.minSamplesPerGroup,
    consecutiveAnomalies: consecutive,
    direction: directionCtl.get() as AlertDirection,
    // Read from the bound sliders regardless of type; the windowed detectors
    // ignore these, the manual_bounds port reads them.
    lowerBound: lowerBoundCtl.get(),
    upperBound: upperBoundCtl.get(),
    // autoreg only — ignored by the other detectors.
    lags: lagsCtl.get(),
  });

  // ---- header ---------------------------------------------------------------
  const header = el('div', 'dtk-tune-header');
  const titleRow = el('div', 'dtk-tune-titlerow');
  titleRow.appendChild(el('h1', 'dtk-tune-title', payload.metric));
  const badge = el('span', 'dtk-tune-badge', payload.save_url ? 'manual tuning' : 'preview');
  titleRow.appendChild(badge);
  header.appendChild(titleRow);
  const sub = payload.project ? `${payload.project} · ` : '';
  header.appendChild(
    el(
      'div',
      'dtk-tune-sub',
      `${sub}${n} points · ${fmtInterval(payload.interval_seconds)} grid`,
    ),
  );
  if (payload.description) header.appendChild(el('div', 'dtk-tune-desc', payload.description));
  root.appendChild(header);

  // ---- alert-quality metrics bar (the "speedometer") -----------------------
  // Operator-facing numbers, recomputed live (real incidents / caught / alerts /
  // false / reviewed). Rides pinned in the HUD over the chart so it stays in view
  // across every mode — never scrolled past.
  const metricsBar = el('div', 'dtk-tune-metrics');

  // ---- cockpit layout: chart-windshield + always-visible control rail -------
  // The chart fills the screen as the windshield; the live metrics ride pinned in
  // a HUD strip over it, and every control lives in a right-hand RAIL that is
  // always visible with its own scroll. So you turn a knob and watch the band
  // change with no scrolling and no gaze-drop to a dock below. The rail is also
  // MODE-AWARE: it shows only the panel the current mode needs — the detector
  // knobs + effective config + Apply in Tune, the verdict actions in Review, the
  // capture tools + incident list + Save in Label — instead of every control at
  // once. Collapse it (⟩) to hand the chart the whole width.
  const cockpit = el('div', 'dtk-tune-cockpit');
  root.appendChild(cockpit);
  const stage = el('div', 'dtk-tune-stage');
  cockpit.appendChild(stage);
  // HUD over the chart: the speedometer leads, the mode switch sits at the right.
  const hud = el('div', 'dtk-tune-hud');
  hud.appendChild(metricsBar);
  stage.appendChild(hud);
  // Stage footer (hover readout + stat line + season warning) — created now,
  // filled below; attached right under the chart. (The legend is a TOP strip,
  // mounted above the chart, not here — see below.)
  const stageFoot = el('div', 'dtk-tune-stagefoot');

  // The control rail: a fixed header (mode-named + collapse), the scrolling control
  // column split into per-mode GROUPS, and a Tune-only action footer (effective
  // config + Apply) that never scrolls away.
  const rail = el('div', 'dtk-tune-rail');
  cockpit.appendChild(rail);
  const railHead = el('div', 'dtk-tune-railhead');
  const railTitle = el('span', 'dtk-rail-title', 'Tune · controls');
  const dockToggle = el('button', 'dtk-dock-toggle', '⟩');
  dockToggle.type = 'button';
  dockToggle.title = 'Collapse the control rail to give the chart the whole width.';
  railHead.appendChild(railTitle);
  railHead.appendChild(dockToggle);
  rail.appendChild(railHead);
  const controls = el('div', 'dtk-tune-controls');
  rail.appendChild(controls);
  // Controls split into ALWAYS-visible common groups + per-mode groups. The common
  // groups apply to every mode, so they stay put as you switch — `topCommon` (the
  // data window: Points shown) at the top, `alertCommon` (the alert rule — direction
  // + consecutive — and the y = 0 view toggle) at the bottom. setUiMode only toggles
  // the per-mode group sandwiched between them. Column order: topCommon · <mode> ·
  // alertCommon.
  const topCommon = el('div', 'dtk-rail-group');
  const tuneGroup = el('div', 'dtk-rail-group');
  const reviewGroup = el('div', 'dtk-rail-group');
  const labelGroup = el('div', 'dtk-rail-group');
  const autotuneGroup = el('div', 'dtk-rail-group');
  const alertCommon = el('div', 'dtk-rail-group');
  reviewGroup.style.display = 'none';
  labelGroup.style.display = 'none';
  autotuneGroup.style.display = 'none';
  controls.append(topCommon, tuneGroup, reviewGroup, labelGroup, autotuneGroup, alertCommon);
  // Tune-only footer (effective config + Apply); hidden in Review / Label.
  const railFoot = el('div', 'dtk-tune-railfoot');
  rail.appendChild(railFoot);
  // A slim tab on the chart's right edge re-opens the rail once collapsed.
  const railOpen = el('button', 'dtk-rail-open', '⚙');
  railOpen.type = 'button';
  railOpen.title = 'Show the control rail';
  railOpen.style.display = 'none';
  stage.appendChild(railOpen);

  const setDock = (open: boolean): void => {
    rail.style.display = open ? '' : 'none';
    railOpen.style.display = open ? 'none' : '';
    // The chart's ResizeObserver re-fits it when the rail hides/shows.
  };
  dockToggle.onclick = (): void => setDock(false);
  railOpen.onclick = (): void => setDock(true);

  // ---- trim slider (top of the rail — applies to every mode) ---------------
  // Shorten the active sample to the most-recent N points. The fitted period
  // shrinks and the live recompute speeds up (cost ∝ points × window). Echo is
  // live; the actual re-slice/recompute is debounced.
  const trimWrap = el('div', 'dtk-tune-trim');
  const trimHead = el('div', 'dtk-tune-trim-head');
  trimHead.appendChild(
    ctlLabel(
      'Points shown',
      'Trim the active sample to the most-recent N points. Fewer points recompute faster ' +
        '(cost grows with points × window) and make a shorter period easier to read — handy ' +
        'once you can see a smaller window/period is enough.',
    ),
  );
  const trimEcho = el('span', 'dtk-tune-trim-val');
  trimHead.appendChild(trimEcho);
  trimWrap.appendChild(trimHead);
  const trimInput = el('input', 'dtk-range');
  trimInput.type = 'range';
  trimInput.min = String(Math.min(n, 200));
  trimInput.max = String(n);
  trimInput.step = String(Math.max(1, Math.round(n / 200)));
  trimInput.value = String(n);
  trimWrap.appendChild(trimInput);
  topCommon.appendChild(trimWrap);

  // chart
  const chartWrap = el('div', 'dtk-tune-chart');
  const canvas = el('canvas');
  chartWrap.appendChild(canvas);
  // recompute spinner overlay (top-right of the chart)
  const spinner = el('div', 'dtk-tune-spin');
  spinner.appendChild(el('span', 'dtk-spin-ring'));
  spinner.appendChild(el('span', 'dtk-spin-txt', 'computing…'));
  chartWrap.appendChild(spinner);
  stage.appendChild(chartWrap);
  stage.appendChild(stageFoot);

  // ---- mode switch (Tune / Review / Label / Autotune) -----------------------
  // One chart, four jobs: the mode picks which layers lead and which interactions
  // are armed. 'tune' steers the band, 'review' confirms the fired alerts, 'label'
  // marks incidents, and 'autotune' runs the server-side search and re-seeds the
  // knobs with the winner (the chart leads with the band, like 'tune'). setUiMode
  // (defined once the tool bars exist) drives the chart + reveals the matching tools.
  const modeRow = el('div', 'dtk-tune-modes');
  const modeBtns: Partial<Record<UiMode, HTMLButtonElement>> = {};
  const MODES: Array<{ v: UiMode; label: string; hint: string }> = [
    { v: 'tune', label: 'Tune', hint: 'Steer the band — the confidence corridor leads; incidents recede to read-only context. Hover a point for its window.' },
    { v: 'review', label: 'Review alerts', hint: 'Confirm the fired alerts — click a marker to cycle un-reviewed → valid (green) → false (slate). The band ghosts so the alerts lead.' },
    { v: 'label', label: 'Label incidents', hint: 'Mark real incidents — drag a span, lasso the anomaly cloud, or threshold-capture. The band hides so incidents lead.' },
    { v: 'autotune', label: 'Autotune', hint: 'Let the autotune engine search for the best detector server-side, using your marked incidents as ground truth, then re-seed the knobs with the winner. Review the band, then Apply.' },
  ];
  MODES.forEach((md) => {
    const b = el('button', 'dtk-mode-btn', md.label);
    b.type = 'button';
    b.title = md.hint;
    b.dataset.v = md.v;
    b.onclick = (): void => setUiMode(md.v);
    modeBtns[md.v] = b;
    modeRow.appendChild(b);
  });
  // The mode switch rides in the HUD at the right of the chart (metrics already
  // mounted at its left), so switching modes never requires a scroll.
  hud.appendChild(modeRow);

  // Legend — a colour key for the chart, pinned at the TOP of the stage (right
  // under the HUD, above the chart) so it reads almost immediately and stays put
  // in EVERY mode (it lives in the stage, not the mode-aware rail). It leads with
  // the alert colours — red (fired), green (confirmed valid), slate (false alarm) —
  // the three markers a user most needs decoded while reviewing.
  const legend = el('div', 'dtk-tune-legend');
  const legItem = (sw: string, text: string, hint: string): void => {
    const item = el('span', 'dtk-leg-item');
    item.title = hint;
    item.appendChild(el('span', `dtk-leg-sw ${sw}`));
    item.appendChild(el('span', 'dtk-leg-txt', text));
    legend.appendChild(item);
  };
  legItem('alert', 'alert', 'A fired alert, not yet reviewed — enough consecutive anomalies to meet the rule.');
  legItem('alert-ok', 'valid alert', 'An alert you confirmed is real (click a marker in Review mode). Counts toward recall.');
  legItem('alert-no', 'false alarm', 'An alert you marked a false positive. Stays in the false-alert rate.');
  legItem('dot', 'anomaly', 'A point the detector flagged as anomalous (outside the band).');
  legItem('line', 'metric', 'The metric value over time.');
  legItem('band', 'expected range', "The detector's confidence band — values inside it read as normal.");
  legItem('center', 'band center', 'The expected value at the middle of the band.');
  // Mount it as a top strip between the HUD and the chart, not in the footer below.
  stage.insertBefore(legend, chartWrap);

  const readout = el('div', 'dtk-tune-readout');
  stageFoot.appendChild(readout);

  // Surfaces when the window is too small to fill the chosen seasonality, so the
  // band silently uses global (un-conditioned) statistics. Mirrors the Python
  // detector's runtime warning — without it a wide band reads like a bug.
  const seasonWarn = el('div', 'dtk-tune-warn');
  seasonWarn.style.display = 'none';
  stageFoot.appendChild(seasonWarn);
  const updateSeasonWarn = (params: DetectorParams): void => {
    const groups = params.seasonalityComponents;
    const card = seasonalCardinality(groups);
    const needed = params.minSamplesPerGroup * card;
    if (groups && card > 0 && params.windowSize < needed) {
      seasonWarn.textContent =
        `⚠ Seasonality inactive at this window: ${params.windowSize} < ${needed} ` +
        `(min_samples_per_group ${params.minSamplesPerGroup} × ${card} key${card === 1 ? '' : 's'}). ` +
        `Each point keeps only ~${Math.floor(params.windowSize / card)} same-key point(s), so the ` +
        `band falls back to global statistics (seasonality has no effect). Raise the window to ≥ ${needed}.`;
      seasonWarn.style.display = '';
    } else {
      seasonWarn.style.display = 'none';
    }
  };

  // ---- live alert-quality metrics ------------------------------------------
  interface Quality {
    realIncidents: number;
    caught: number;
    recall: number;
    totalAlerts: number;
    correctAlerts: number;
    falseAlerts: number;
    fdr: number;
    /** alerts the user confirmed valid. */
    validated: number;
    /** alerts with any verdict (valid or false) — review progress. */
    reviewed: number;
  }
  const computeQuality = (spans: Array<[number, number]>): Quality => {
    const tol = spanTol(); // ±½ interval grid tolerance
    // Only score incidents that overlap the active (possibly trimmed) series — an
    // incident outside the loaded window can never be caught, so counting it would
    // wrongly drag recall down. The list still shows every marked incident. The
    // ground-truth set is the hand-marked incidents PLUS the confirmed-valid alert
    // spans (a confirmed alert is the user asserting "a real incident happened
    // here"), deduped by overlap so neither is double-counted.
    const ts = series.timestamps;
    const lo = (ts.length ? ts[0] : 0) - tol;
    const hi = (ts.length ? ts[ts.length - 1] : 0) + tol;
    const inWindow = (iv: { start: number; end: number }): boolean => iv.end >= lo && iv.start <= hi;
    // Build the ground truth from the IN-WINDOW incidents, then dedup the confirmed
    // spans against THOSE — not the full set. Deduping against an out-of-window manual
    // incident (which is itself window-filtered away here) would drop an in-window
    // confirmed span too, silently losing a real region from recall. (The list and
    // Save keep the full-set dedup via groundTruth() — they show/save everything.)
    const manualIn = incidents.filter(inWindow);
    const validatedIn = validatedSpans()
      .filter(inWindow)
      .filter((v) => !manualIn.some((iv) => overlapIv(v, iv)));
    const ivs = [...manualIn, ...validatedIn];
    // An alert is "for" an incident when its anomaly STREAK overlaps the span (not
    // just the fire point, which sits consecutive-1 intervals into the streak).
    const overlaps = (sp: [number, number], iv: Incident): boolean =>
      sp[1] >= iv.start - tol && sp[0] <= iv.end + tol;
    let correct = 0;
    let validated = 0;
    let reviewed = 0;
    for (const sp of spans) {
      const v = reviewFor(sp[0], sp[1]);
      if (v) reviewed++;
      if (v === 'valid') validated++;
      // 'false' stays a false alarm even if it grazes an incident; 'valid' is always
      // correct (it overlaps its own virtual incident); else by incident overlap.
      if (v === 'valid' || (v !== 'false' && ivs.some((iv) => overlaps(sp, iv)))) correct++;
    }
    let caught = 0;
    for (const iv of ivs) if (spans.some((sp) => overlaps(sp, iv))) caught++;
    const total = spans.length;
    return {
      realIncidents: ivs.length,
      caught,
      recall: ivs.length ? caught / ivs.length : NaN,
      totalAlerts: total,
      correctAlerts: correct,
      falseAlerts: total - correct,
      fdr: total ? (total - correct) / total : NaN,
      validated,
      reviewed,
    };
  };
  const pctOrDash = (v: number): string => (Number.isFinite(v) ? `${Math.round(v * 100)}%` : '—');
  // The false-alert-rate budget the quality bar flags when exceeded (a fraction in
  // (0, 1]); resolved metric → project → built-in default by the payload builder.
  const budget =
    typeof payload.false_alert_budget === 'number' && payload.false_alert_budget > 0
      ? payload.false_alert_budget
      : null;
  const metricChip = (
    value: string,
    label: string,
    sub: string,
    color: string,
    opts?: { cls?: string; title?: string },
  ): string =>
    `<span class="dtk-m-chip${opts?.cls ? ' ' + opts.cls : ''}"${opts?.title ? ` title="${opts.title}"` : ''}>` +
    `<span class="dtk-m-dot" style="background:${color}"></span>` +
    `<span class="dtk-m-v">${value}</span><span class="dtk-m-l">${label}</span>` +
    (sub ? `<span class="dtk-m-sub">${sub}</span>` : '') +
    `</span>`;
  function renderMetrics(): void {
    const q = computeQuality(lastFireSpans);
    // Without any marked incidents there is no ground truth, so catch-rate and
    // false-alert rate are undefined (not "100% false") — prompt to mark some.
    const haveTruth = q.realIncidents > 0;
    // Over budget = we have ground truth, alerts fired, and the false-alert rate
    // exceeds the configured budget. A gentle, optional signal — it only colours an
    // already-computed number; labeling and tuning are never blocked by it.
    const budgetPct = budget != null ? `${Math.round(budget * 100)}%` : '';
    const overBudget =
      haveTruth && q.totalAlerts > 0 && budget != null && Number.isFinite(q.fdr) && q.fdr > budget;
    let falseSub: string;
    if (!haveTruth) falseSub = 'mark incidents to measure';
    else if (q.totalAlerts === 0) falseSub = 'no alerts';
    else if (q.falseAlerts === 0) falseSub = `${pctOrDash(q.fdr)} · all correct`;
    else {
      // "≈1 in N false": N = alerts / false-alerts (≥1). Keep a decimal below 10 so
      // a 73%-false rate reads "≈1 in 1.4 false", not a misleading round-down to 1.
      const ratio = q.totalAlerts / q.falseAlerts;
      const nStr = ratio >= 9.5 ? String(Math.round(ratio)) : String(Math.round(ratio * 10) / 10);
      falseSub = `${pctOrDash(q.fdr)} · ≈1 in ${nStr} false`;
    }
    // Append the budget verdict (non-intrusive: only flag when over).
    if (overBudget) falseSub += ` · ▲ over ${budgetPct} budget`;
    // Review progress: how many fired alerts you've confirmed/dismissed, and how
    // many you confirmed valid (the green markers).
    const reviewSub =
      q.totalAlerts === 0
        ? 'no alerts'
        : `${q.validated} valid${q.totalAlerts > q.reviewed ? ` · ${q.totalAlerts - q.reviewed} left` : ' · all reviewed'}`;
    const falseTitle = budget
      ? `Budget: at most ${budgetPct} of fired alerts false (false-alert rate / FDR). ` +
        'Set per metric or project via false_alert_budget. Labeling is optional — this just ' +
        'flags when you exceed the budget.'
      : '';
    metricsBar.innerHTML =
      metricChip(String(q.realIncidents), 'real incidents', '', 'var(--c)') +
      metricChip(
        haveTruth ? `${q.caught}/${q.realIncidents}` : '—',
        'caught',
        haveTruth ? `recall ${pctOrDash(q.recall)}` : 'mark or confirm',
        'var(--green)',
      ) +
      metricChip(String(q.totalAlerts), 'alerts', '', 'var(--c)') +
      metricChip(haveTruth ? String(q.falseAlerts) : '—', 'false alerts', falseSub, 'var(--anom)', {
        cls: overBudget ? 'over' : '',
        title: falseTitle,
      }) +
      metricChip(`${q.reviewed}/${q.totalAlerts}`, 'reviewed', reviewSub, 'var(--green)');
  }

  // Filled once the capture toolbars are built (the chart pushes preview state here
  // on every hover / window paint / knob change / lasso draw).
  let updateThresholdUI: (info: ThresholdInfo) => void = () => {};
  let updateLassoUI: (info: LassoInfo) => void = () => {};
  // ONE chart for the whole cockpit: band + anomaly dots + alert markers + incident
  // spans on a single windshield. The MODE (tune / review / label) decides which
  // layers lead and which recede, and which interactions are armed — so tuning,
  // confirming alerts and marking incidents share one canvas (no stacked half-charts).
  const chart: ChartHandle = createChart(canvas, {
    navigable: true,
    labeling: true,
    mode: 'tune',
    // Fit the y-axis to the data, not the band — so turning the Threshold slider
    // visibly widens/narrows the corridor relative to the metric instead of the
    // axis rescaling in lockstep and making the change look like a no-op.
    yFit: 'data',
    onHover: (info): void => {
      if (!info || !info.point || !info.point.scored) {
        readout.textContent = '';
        return;
      }
      const p = info.point;
      readout.textContent =
        `t=${fmtTs(p.timestamp)}  value=${fmtNum(p.value)}  ` +
        `band=[${fmtNum(p.lower)}, ${fmtNum(p.upper)}]` +
        (p.isAnomaly ? `  ⚠ ${p.direction} (sev ${p.severity.toFixed(2)})` : '');
    },
    onIncidentsChange: (_incidents, removed): void => {
      // The chart mutates `incidents` in place (shared ref); reflect it. If a span was
      // DELETED on the chart (✕ handle / Delete key), retract any confirmed-valid verdict
      // it overlapped (see retractConfirmationFor) so the incident is fully removed
      // instead of resurfacing as a "confirmed alert" — same as deleting it from the list.
      const retracted = removed ? retractConfirmationFor(removed) : false;
      if (retracted) repaintAlerts();
      else {
        refreshIncidentList();
        renderMetrics();
      }
    },
    onThresholdChange: (info): void => updateThresholdUI(info),
    onLassoChange: (info): void => updateLassoUI(info),
    onAlertReviewChange: (fireTs, verdict): void => {
      // Map the clicked marker back to its streak span and store the verdict by span.
      const idx = lastFireTs.indexOf(fireTs);
      const sp = idx >= 0 ? lastFireSpans[idx] : [fireTs, fireTs];
      setReview(sp[0], sp[1], verdict === 'unreviewed' ? null : (verdict as Verdict));
      repaintAlerts();
    },
  });
  chart.setIncidents(incidents);
  if (seedCaptureWin) chart.setCaptureWindow(seedCaptureWin);
  // Rebuild the alert markers' verdict colors, re-render the chart and refresh the
  // metrics — after a recompute (alerts moved) or a single review click.
  const repaintAlerts = (): void => {
    lastAlerts = buildAlerts();
    if (lastParams) {
      chart.render({ series, scored: lastScored, params: lastParams, alerts: lastAlerts, incidents });
    }
    renderMetrics();
    // A confirmed-valid alert IS an incident, so keep the list in lockstep with the
    // verdicts — confirming one in Review mode makes it show up in the incident list.
    refreshIncidentList();
  };

  // ---- threshold-capture toolbar (above the labeler chart) ------------------
  // Mark incidents fast: set a horizontal line and grab every contiguous span past
  // it in one click — the same tool as the autotune html labeler, here feeding the
  // synced incident labeler. All capture state lives in the labeler chart; this bar
  // just drives it and reflects the live run count + scope.
  const thWrap = el('div', 'dtk-th');
  const toolToggles = el('div', 'dtk-th-toggles');
  const thToggle = el('button', 'dtk-th-toggle', 'Threshold capture');
  thToggle.type = 'button';
  thToggle.title =
    'Mark incidents fast: set a horizontal line and grab every contiguous span above (or below) ' +
    'it. Click the chart to set the line, drag across it to limit the capture to a time window.';
  toolToggles.appendChild(thToggle);
  // Lasso anomalies: loop around a cloud of anomaly dots on the labeler chart →
  // each grid-adjacent run (small gaps bridged) becomes one incident span.
  const lassoToggle = el('button', 'dtk-th-toggle', 'Lasso anomalies');
  lassoToggle.type = 'button';
  lassoToggle.title =
    'Draw a freeform loop around a cloud of anomaly dots on the chart below — each run of ' +
    'consecutive anomalies (small gaps bridged) becomes one incident span. The ideal way to ' +
    'turn what the detector already flags into ground-truth incidents.';
  toolToggles.appendChild(lassoToggle);
  thWrap.appendChild(toolToggles);
  const thBar = el('div', 'dtk-th-bar');
  const thDirSel = el('select', 'dtk-th-sel');
  for (const [v, lbl] of [
    ['above', 'above the line'],
    ['below', 'below the line'],
  ] as const) {
    const o = el('option');
    o.value = v;
    o.textContent = lbl;
    thDirSel.appendChild(o);
  }
  const thValInput = el('input', 'dtk-th-num');
  thValInput.type = 'number';
  thValInput.step = 'any';
  thValInput.placeholder = 'hover chart';
  const thGapInput = el('input', 'dtk-th-num');
  thGapInput.type = 'number';
  thGapInput.min = '0';
  thGapInput.step = '1';
  thGapInput.value = '0';
  const thScope = el('span', 'dtk-th-scope');
  const thWinReset = el('button', 'dtk-inc-btn', '↺ whole view');
  thWinReset.type = 'button';
  thWinReset.style.display = 'none';
  const thAdd = el('button', 'dtk-apply-btn dtk-th-add', 'Add 0 spans');
  thAdd.type = 'button';
  thAdd.disabled = true;
  const thDone = el('button', 'dtk-inc-btn', 'Done');
  thDone.type = 'button';
  const thGrp = (labelText: string, control: HTMLElement): HTMLElement => {
    const w = el('label', 'dtk-th-grp');
    w.appendChild(el('span', 'dtk-th-lbl', labelText));
    w.appendChild(control);
    return w;
  };
  thBar.appendChild(thGrp('grab points', thDirSel));
  thBar.appendChild(thGrp('line value', thValInput));
  thBar.appendChild(thGrp('bridge gaps ≤', thGapInput));
  thBar.appendChild(thScope);
  thBar.appendChild(thWinReset);
  thBar.appendChild(thAdd);
  thBar.appendChild(thDone);
  thBar.style.display = 'none';
  thWrap.appendChild(thBar);

  // ---- lasso bar (live capture readout + done) ------------------------------
  const lassoBar = el('div', 'dtk-th-bar');
  const lassoInfo = el('span', 'dtk-th-scope', 'draw a loop around the anomaly dots on the chart below');
  const lassoDone = el('button', 'dtk-inc-btn', 'Done');
  lassoDone.type = 'button';
  lassoBar.appendChild(lassoInfo);
  lassoBar.appendChild(lassoDone);
  lassoBar.style.display = 'none';
  thWrap.appendChild(lassoBar);
  // The capture tools live in the Label panel of the rail (shown in Label mode).
  labelGroup.appendChild(thWrap);

  // ---- review bar (Review mode): confirm/clear all alerts at once -----------
  const reviewBar = el('div', 'dtk-th-bar dtk-tune-reviewbar');
  reviewBar.appendChild(
    el(
      'span',
      'dtk-th-scope',
      'Click a red alert marker to confirm it valid (green) or mark it a false alarm — cycle un-reviewed → valid → false.',
    ),
  );
  const confirmAllBtn = el('button', 'dtk-apply-btn dtk-th-add', 'Confirm all unreviewed valid');
  confirmAllBtn.type = 'button';
  confirmAllBtn.onclick = (): void => {
    for (const [s, e] of lastFireSpans) if (!reviewFor(s, e)) setReview(s, e, 'valid');
    repaintAlerts();
  };
  const clearReviewBtn = el('button', 'dtk-inc-btn', 'Clear verdicts');
  clearReviewBtn.type = 'button';
  clearReviewBtn.onclick = (): void => {
    reviews.length = 0;
    repaintAlerts();
  };
  reviewBar.appendChild(confirmAllBtn);
  reviewBar.appendChild(clearReviewBtn);
  reviewGroup.appendChild(reviewBar);

  // Drive the chart mode + reveal the matching tools. Defined here (after the tool
  // bars exist) and called by the mode buttons + on first paint.
  const RAIL_TITLES: Record<UiMode, string> = {
    tune: 'Tune · controls',
    review: 'Review · verdicts',
    label: 'Label · incidents',
    autotune: 'Autotune · search',
  };
  function setUiMode(md: UiMode): void {
    // The Autotune panel renders the chart exactly like Tune (band leads): it shows
    // the recomputed band after the engine re-seeds the knobs. So the chart only
    // knows the three layer-modes; 'autotune' maps to 'tune' for the chart.
    chart.setMode(md === 'autotune' ? 'tune' : md);
    (Object.keys(modeBtns) as UiMode[]).forEach((v) =>
      modeBtns[v]?.classList.toggle('on', v === md),
    );
    if (md !== 'label') {
      setThActive(false);
      setLassoActive(false);
    }
    // Swap the rail to the current mode's panel (and rename its header): detector
    // knobs + effective config + Apply in Tune, the verdict actions in Review, the
    // capture tools + incident list + Save in Label, the autotune search in Autotune
    // — never all the controls at once. The Tune-only action footer (effective config
    // + Apply) also rides in Autotune so the searched config can be applied in place.
    tuneGroup.style.display = md === 'tune' ? '' : 'none';
    reviewGroup.style.display = md === 'review' ? '' : 'none';
    labelGroup.style.display = md === 'label' ? '' : 'none';
    autotuneGroup.style.display = md === 'autotune' ? '' : 'none';
    railFoot.style.display = md === 'tune' || md === 'autotune' ? '' : 'none';
    railTitle.textContent = RAIL_TITLES[md];
  }

  let thActive = false;
  let lassoActive = false;
  // True only for the synchronous span of the value input's own oninput, so the UI
  // refresh below can tell a user keystroke apart from a chart-driven value change
  // (a chart click should win and write the input; typing must not be clobbered).
  let thTyping = false;
  const setThActive = (on: boolean): void => {
    thActive = on;
    thToggle.classList.toggle('on', on);
    thBar.style.display = on ? 'flex' : 'none';
    chart.setThresholdMode(on);
    if (on && lassoActive) setLassoActive(false); // mutually exclusive tools
  };
  // Lasso mode: commits incidents on mouseup via onIncidentsChange, so the bar is
  // just a live readout + Done. The chart enforces threshold/lasso exclusivity too.
  const setLassoActive = (on: boolean): void => {
    lassoActive = on;
    lassoToggle.classList.toggle('on', on);
    lassoBar.style.display = on ? 'flex' : 'none';
    chart.setLassoMode(on);
    if (on && thActive) setThActive(false);
  };
  thToggle.onclick = (): void => setThActive(!thActive);
  thDone.onclick = (): void => setThActive(false);
  lassoToggle.onclick = (): void => setLassoActive(!lassoActive);
  lassoDone.onclick = (): void => setLassoActive(false);
  thDirSel.onchange = (): void =>
    chart.setThresholdDirection(thDirSel.value as 'above' | 'below');
  thValInput.oninput = (): void => {
    const s = thValInput.value.trim();
    thTyping = true;
    chart.setThresholdValue(s !== '' && !isNaN(Number(s)) ? Number(s) : null);
    thTyping = false;
  };
  thGapInput.oninput = (): void => chart.setThresholdGap(Number(thGapInput.value) || 0);
  thWinReset.onclick = (): void => chart.clearCaptureWindow();
  thAdd.onclick = (): void => {
    chart.applyThreshold(); // commits spans → incidents (fires onIncidentsChange)
  };
  // Esc backs out of whichever capture tool is active; routed through the setters
  // so the toggle/bar state stays in sync with the chart.
  window.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape') return;
    if (thActive) setThActive(false);
    else if (lassoActive) setLassoActive(false);
  });
  updateLassoUI = (info): void => {
    lassoInfo.textContent = info.active
      ? `${info.anomalies} anomal${info.anomalies === 1 ? 'y' : 'ies'} → ` +
        `${info.incidents} incident${info.incidents === 1 ? '' : 's'} — release to add`
      : 'draw a loop around the anomaly dots on the chart below';
  };
  updateThresholdUI = (info): void => {
    thAdd.textContent = `Add ${info.runs} span${info.runs === 1 ? '' : 's'}`;
    thAdd.disabled = info.runs === 0;
    // Mirror a pinned line value into the input — including a chart click while the
    // input is focused — but never overwrite the digits the user is mid-typing.
    if (info.locked && info.value != null && !thTyping) {
      thValInput.value = String(Math.round(info.value * 1000) / 1000);
    }
    // The reset only makes sense for a COMMITTED window, not a window mid-drag.
    thWinReset.style.display = info.committed ? '' : 'none';
    thScope.textContent = info.window
      ? `scope: ${fmtDur(info.windowMs)} painted`
      : 'scope: current view — drag the chart to limit it';
  };

  // ---- detector worker + debounced recompute --------------------------------
  // runDetector is O(points x window) and re-runs from scratch on every change;
  // running it in a Worker keeps the UI responsive no matter the size. Post the
  // (large) series once, then only params per recompute. Stale results (an older
  // id) are dropped so only the latest knob state paints. Debounce so a slider
  // DRAG fires one recompute when it settles, not one per frame.
  // One blob URL, reused across (re)spawns — no per-spawn leak.
  const workerUrl = URL.createObjectURL(
    new Blob([__DTK_WORKER_SRC__], { type: 'text/javascript' }),
  );
  let worker: Worker;
  let reqId = 0;
  let inFlight = false;
  let lastParams: DetectorParams | null = null;
  const onWorkerMessage = (e: MessageEvent): void => {
    const res = e.data as WorkerResult;
    // Only the CURRENT request clears the in-flight flag. A stale message (an old
    // worker's result that slipped through before terminate, or an out-of-order id)
    // must NOT clear it — the live compute is still running, and clearing it here
    // would let the next knob-change queue behind that compute instead of killing it.
    if (res.type !== 'result' || res.id !== reqId || !lastParams) return; // ignore stale
    inFlight = false;
    spinner.classList.remove('on');
    const params = lastParams;
    lastScored = res.scored;
    lastFireTs = res.fires.map((i) => series.timestamps[i]);
    lastFireSpans = res.fireSpans;
    // Re-bind each fired alert to its stored review verdict (by streak-span overlap)
    // so a recompute that moves the alerts keeps the greens/slates it earned.
    lastAlerts = buildAlerts();
    chart.render({ series, scored: res.scored, params, alerts: lastAlerts, incidents });
    renderMetrics();
    statBar.textContent =
      `${res.flagged} flagged · ${res.fires.length} alert${res.fires.length === 1 ? '' : 's'} · ` +
      `warm-up ${res.eff} pts`;
    updateSeasonWarn(params);
    configEcho.textContent = configText(params, consecutive, shareWindowPoints(), shareValue());
  };
  const onWorkerError = (): void => {
    inFlight = false;
    spinner.classList.remove('on');
    statBar.textContent = 'recompute failed — see the browser console';
  };
  function spawnWorker(): void {
    worker = new Worker(workerUrl);
    worker.onmessage = onWorkerMessage;
    worker.onerror = onWorkerError;
    worker.postMessage({ type: 'series', series });
  }
  spawnWorker();
  const runRecompute = (): void => {
    lastParams = readParams();
    // Remember the active detector's live params so switching detectors (and Apply)
    // can write back every slot the user tuned, not just the one on screen.
    if (activeIndex != null) editedParams.set(activeIndex, lastParams);
    reqId += 1;
    // Kill an in-flight compute instead of queuing behind it: the worker is
    // single-threaded and would otherwise run the now-stale config to completion
    // (O(points × window) — seconds on a large window) before starting this one.
    // Terminate + respawn re-posts the (bounded) series, which is cheap by comparison.
    if (inFlight) {
      worker.terminate();
      spawnWorker();
    }
    inFlight = true;
    spinner.classList.add('on');
    worker.postMessage({
      type: 'run',
      id: reqId,
      params: lastParams,
      // Fraction alert rule — top-level (never DetectorParams: it changes which
      // alerts fire, not the band). null when off ⇒ legacy consecutive-only.
      anomalyWindowPoints: shareWindowPoints(),
      minAnomalyShare: shareValue(),
    });
  };

  // ---- trim: re-slice the active series, re-post, recompute -----------------
  const trimSpan = (count: number): string =>
    count > 1 ? fmtDur(fullSeries.timestamps[n - 1] - fullSeries.timestamps[n - count]) : '—';
  const setTrimEcho = (count: number): void => {
    trimEcho.textContent =
      count >= n ? `${n} pts · full (${trimSpan(n)})` : `${count} pts · ${trimSpan(count)}`;
  };
  setTrimEcho(n);
  function setActivePoints(count: number): void {
    series = sliceSeries(count);
    worker.postMessage({ type: 'series', series });
    recompute();
  }
  // Live echo while dragging; the (expensive) re-slice + re-post + recompute fires
  // only on release (`change`), not on every mid-drag pause.
  trimInput.oninput = (): void => {
    setTrimEcho(Number(trimInput.value));
  };
  trimInput.onchange = (): void => {
    setActivePoints(Number(trimInput.value));
  };
  let debounce = 0;
  const recompute = (): void => {
    if (debounce) window.clearTimeout(debounce);
    debounce = window.setTimeout(runRecompute, 130);
  };
  // A detector knob changed (as opposed to an alert-layer/view control): mark the
  // active detector dirty so Apply writes it back, then recompute. Programmatic
  // re-seeds (detector switch, autotune winner) call recompute() directly, so they
  // never mark dirty — only genuine user edits do.
  const detectorChanged = (): void => {
    markActiveDirty();
    recompute();
  };

  // ---- controls -------------------------------------------------------------
  // Multi-detector picker: when the metric configures more than one detector, let
  // the user choose WHICH one to tune here (the cockpit shows one band at a time)
  // and make it plain that the others are preserved on Apply. Hidden for the common
  // single-detector metric, so that UX is unchanged.
  const tunableEntries = detectorEntries.filter((d) => d.tunable);
  const preservedEntries = detectorEntries.filter((d) => !d.tunable);
  if (detectorEntries.length > 1) {
    const pickWrap = el('div', 'dtk-ctl dtk-tune-detpick');
    pickWrap.appendChild(
      ctlLabel(
        'Tuning detector',
        'This metric has several detectors. Pick which one to tune here; every other ' +
          'detector is preserved unchanged when you Apply — so a manual_bounds floor or a ' +
          'min_detectors≥2 quorum keeps working.',
      ),
    );
    if (tunableEntries.length > 1) {
      const seg = el('div', 'dtk-seg dtk-detpick-seg');
      const buttons: HTMLButtonElement[] = [];
      const paint = (): void =>
        buttons.forEach((b) => b.classList.toggle('on', Number(b.dataset.v) === activeIndex));
      tunableEntries.forEach((d) => {
        const b = el('button', 'dtk-seg-btn', `#${d.index + 1} ${d.type}`);
        b.type = 'button';
        b.dataset.v = String(d.index);
        b.title = d.summary;
        b.onclick = (): void => {
          switchDetector(d.index);
          paint();
        };
        buttons.push(b);
        seg.appendChild(b);
      });
      paint();
      pickWrap.appendChild(seg);
    }
    const noteParts: string[] = [];
    if (preservedEntries.length) {
      noteParts.push(
        `Preserved (not tunable here): ${preservedEntries.map((d) => d.summary).join('; ')}.`,
      );
    }
    noteParts.push('Apply rewrites only the detector(s) you tune and keeps the rest verbatim.');
    pickWrap.appendChild(el('div', 'dtk-tune-note', noteParts.join(' ')));
    tuneGroup.appendChild(pickWrap);
  }

  const detectorCtl = segControl(
    'Detector',
    [
      { label: 'MAD', value: 'mad' },
      { label: 'Z-Score', value: 'zscore' },
      { label: 'IQR', value: 'iqr' },
      { label: 'Autoreg', value: 'autoreg' },
      { label: 'Manual', value: 'manual_bounds' },
    ],
    seed.type,
    (v) => {
      // reset threshold to the new type's default for a sane starting point
      thresholdCtl_setDefault(THRESHOLD_DEFAULT[v as DetectorType] ?? 3.0);
      markActiveDirty();
      refreshVisibility();
      recompute();
    },
    'The statistic for the band: MAD (robust median, default), Z-Score (mean/std) or IQR ' +
      '(quartiles) — all windowed — Autoreg (predicts each point from its previous values and ' +
      'flags dynamics breaks) or Manual (fixed lower/upper thresholds, no window/history).',
  );
  tuneGroup.appendChild(detectorCtl.row);

  // manual_bounds: lower/upper threshold sliders (shown only for that detector).
  // The value domain is the real series range padded a little; both bounds are
  // always written on Apply (the Python detector requires lower < upper).
  const lowerBoundCtl = rangeControl(
    'Lower bound',
    {
      min: boundMin,
      max: boundMax,
      step: boundStep,
      value: seedLower,
      fmt: (v) => fmtNum(v),
      hint: 'Manual bounds: values below this read as anomalous. Drag in from the data range to ' +
        'see how many points fall outside (and how many alerts that yields).',
    },
    detectorChanged,
  );
  tuneGroup.appendChild(lowerBoundCtl.row);

  const upperBoundCtl = rangeControl(
    'Upper bound',
    {
      min: boundMin,
      max: boundMax,
      step: boundStep,
      value: seedUpper,
      fmt: (v) => fmtNum(v),
      hint: 'Manual bounds: values above this read as anomalous.',
    },
    detectorChanged,
  );
  tuneGroup.appendChild(upperBoundCtl.row);

  const thresholdCtl = rangeControl(
    'Threshold (σ-equivalent)',
    {
      min: 0.5,
      max: 10,
      step: 0.1,
      value: seed.threshold,
      fmt: (v) => v.toFixed(1),
      hint: 'Band half-width in σ-equivalents. Lower = tighter band = more flags; higher = ' +
        'wider band = fewer flags.',
    },
    detectorChanged,
  );
  tuneGroup.appendChild(thresholdCtl.row);
  const thresholdInput = thresholdCtl.row.querySelector<HTMLInputElement>('input');
  const thresholdOut = thresholdCtl.row.querySelector<HTMLElement>('.dtk-ctl-val');
  const thresholdCtl_setDefault = (v: number): void => {
    if (thresholdInput) thresholdInput.value = String(v);
    if (thresholdOut) thresholdOut.textContent = v.toFixed(1);
  };

  // Slider reach: enough to explore, capped at half the shown points so there's
  // always a scored region — but NEVER below the metric's actual window_size, so
  // the seeded value is always representable and Apply can't silently shrink the
  // metric's window. step=1 keeps the exact configured value addressable (a
  // step-5 grid would snap e.g. 168 → 170 and write the wrong window back).
  const windowReach = Math.max(50, Math.min(2000, Math.floor(n / 2)));
  const windowMax = Math.max(windowReach, seed.windowSize);
  const windowCtl = rangeControl(
    'Window size (points)',
    {
      min: Math.max(1, Math.min(10, seed.windowSize)),
      max: windowMax,
      step: 1,
      value: seed.windowSize,
      // Echo the wall-clock span the window covers on the metric grid (like the
      // "Points shown" trim), so "how much history is this" reads at a glance.
      fmt: (v) => `${v} · ${fmtDur(v * payload.interval_seconds * 1000)}`,
      hint: 'How many trailing points form the baseline window for each scored point. ' +
        'Larger = steadier baseline (more history); smaller = adapts faster to shifts.',
    },
    detectorChanged,
  );
  tuneGroup.appendChild(windowCtl.row);

  // autoreg: AR order (lags) — shown only for that detector.
  const lagsCtl = rangeControl(
    'Lags (AR order)',
    {
      min: 1,
      max: 24,
      step: 1,
      value: Math.max(1, Math.round(seed.lags ?? 5)),
      fmt: (v) => String(v),
      hint: 'Autoreg: how many immediately-preceding values predict the current one. More lags ' +
        'capture longer short-range patterns but need more history per fit.',
    },
    detectorChanged,
  );
  tuneGroup.appendChild(lagsCtl.row);

  const weightsCtl = segControl(
    'Recency weighting',
    [
      { label: 'none', value: 'none' },
      { label: 'exponential', value: 'exponential' },
      { label: 'linear', value: 'linear' },
    ],
    seed.windowWeights,
    () => {
      markActiveDirty();
      refreshVisibility();
      recompute();
    },
    'Weight recent points in the window more heavily: none (flat), exponential (half-life ' +
      'decay) or linear. Helps the baseline track a drifting level.',
  );
  tuneGroup.appendChild(weightsCtl.row);

  const halfLifeCtl = rangeControl(
    'Half-life (points)',
    {
      min: 1,
      max: windowMax,
      step: 1,
      value: seed.halfLife ?? Math.max(5, Math.round(seed.windowSize / 20)),
      // Same grid-span echo as the window: half-life in points is abstract, the
      // equivalent duration ("767 · 32d") makes the decay horizon concrete.
      fmt: (v) => `${v} · ${fmtDur(v * payload.interval_seconds * 1000)}`,
      hint: 'Exponential weighting only: the age (in points) at which a point counts half as ' +
        'much as the newest. Smaller = faster decay = fresher baseline.',
    },
    detectorChanged,
  );
  const halfLifeRow = halfLifeCtl.row;
  halfLifeRow.style.display = seed.windowWeights === 'exponential' ? '' : 'none';
  tuneGroup.appendChild(halfLifeRow);

  const detrendCtl = segControl(
    'Detrend',
    [
      { label: 'none', value: 'none' },
      { label: 'linear', value: 'linear' },
    ],
    seed.detrend,
    detectorChanged,
    'Remove a robust linear trend from each window before computing the band, so a steadily ' +
      'rising/falling metric is not flagged for the trend itself.',
  );
  tuneGroup.appendChild(detrendCtl.row);

  const stabilizationCtl = segControl(
    'Stabilization',
    [
      { label: 'none', value: 'none' },
      { label: 'clamp', value: 'clamp' },
    ],
    seed.stabilization ?? 'none',
    detectorChanged,
    'Anomaly-robust baseline: flagged points enter later windows clamped to the bound they ' +
      'violated, so a long incident cannot inflate the band and mask itself mid-incident.',
  );
  tuneGroup.appendChild(stabilizationCtl.row);

  const smoothingCtl = segControl(
    'Smoothing',
    [
      { label: 'none', value: 'none' },
      { label: 'EMA', value: 'ema' },
      { label: 'SMA', value: 'sma' },
    ],
    seed.smoothing,
    detectorChanged,
    'Smooth the series before detection (EMA or SMA) so single-point jitter does not flag. ' +
      'The detector judges the smoothed line; the raw values show as a faint ghost.',
  );
  tuneGroup.appendChild(smoothingCtl.row);

  // seasonality (only when the metric has seasonality columns).
  // Each column is assigned a group: Off, or G1/G2/G3… Columns sharing a group
  // are conjoined into ONE seasonal key (e.g. dow×hour); separate groups apply
  // independent corrections — the full string[][] grouping the detector supports.
  let seasonalityRow: HTMLElement | null = null;
  // Re-seed the per-column group assignment (e.g. from an autotune result). No-op
  // when the metric has no seasonality columns; overridden below when it does.
  let setSeasonalityGroups: (groups: string[][]) => void = () => {};
  if (payload.seasonality_columns.length) {
    const cols = payload.seasonality_columns;
    const row = el('div', 'dtk-ctl');
    seasonalityRow = row;
    row.appendChild(
      ctlLabel(
        'Seasonality groups',
        'Condition the band on seasonal keys. Pick a group per column: columns in the SAME ' +
          'group are combined into one key (e.g. dow×hour); separate groups each apply their ' +
          'own correction. Off = ignore that column.',
      ),
    );
    // Offer Off + as many groups as there are columns (each could stand alone).
    // Sized to the column count — never fewer — so any grouping a re-seed
    // (e.g. an autotune winner) hands back always has a matching button to show on.
    const groupCount = cols.length;
    const opts: SegSpec[] = [{ label: '—', value: '0' }];
    for (let gi = 1; gi <= groupCount; gi++) opts.push({ label: `G${gi}`, value: String(gi) });
    // One repaint per column row, collected so a re-seed can refresh them all.
    const seasonPaints: Array<() => void> = [];
    cols.forEach((col) => {
      const crow = el('div', 'dtk-season-row');
      crow.appendChild(el('span', 'dtk-season-col', col));
      const seg = el('div', 'dtk-seg dtk-season-seg');
      const buttons: HTMLButtonElement[] = [];
      const cur = (): number => colGroup.get(col) ?? 0;
      const paint = (): void =>
        buttons.forEach((b) => b.classList.toggle('on', Number(b.dataset.v) === cur()));
      seasonPaints.push(paint);
      opts.forEach((opt) => {
        const b = el('button', 'dtk-seg-btn', opt.label);
        b.type = 'button';
        b.dataset.v = opt.value;
        b.title = opt.value === '0' ? `ignore ${col}` : `put ${col} in group ${opt.value}`;
        b.onclick = (): void => {
          colGroup.set(col, Number(opt.value));
          paint();
          detectorChanged();
        };
        buttons.push(b);
        seg.appendChild(b);
      });
      paint();
      crow.appendChild(seg);
      row.appendChild(crow);
    });
    tuneGroup.appendChild(row);
    setSeasonalityGroups = (groups: string[][]): void => {
      colGroup.clear();
      groups.forEach((grp, gi) => grp.forEach((c) => colGroup.set(c, gi + 1)));
      seasonPaints.forEach((p) => p());
    };
  }

  // Direction filter (alert-layer / view): which anomalies show + count as alerts.
  const directionCtl = segControl(
    'Direction',
    [
      { label: 'both', value: 'any' },
      { label: 'up', value: 'up' },
      { label: 'down', value: 'down' },
    ],
    payload.direction ?? 'any',
    recompute,
    'Which anomalies to show and count toward alerts: both directions, only spikes ABOVE the ' +
      'band (up) or only drops BELOW it (down). A preview filter mirroring the alert direction ' +
      'policy — it never changes the band itself.',
  );
  alertCommon.appendChild(directionCtl.row);

  const consecutiveCtl = rangeControl(
    'Alert: consecutive anomalies',
    {
      min: 1,
      max: 10,
      step: 1,
      value: consecutive,
      fmt: (v) => String(v),
      hint: 'How many anomalies in a row are required before an alert fires. Higher = fewer, ' +
        'more-confident alerts (the ▼ markers on the chart).',
    },
    (v) => {
      consecutive = v;
      recompute();
    },
  );
  alertCommon.appendChild(consecutiveCtl.row);

  // Fraction alert rule (issue #101): an anomaly-window (in grid points; 'off'
  // below 2) + a min share of flagged points within it. OR-ed with the
  // consecutive rule, exactly like the pipeline — good for diffuse incidents
  // where anomalies are frequent but never strictly consecutive.
  const anomalyWindowCtl = rangeControl(
    'Alert: anomaly window (points)',
    {
      min: 0,
      max: Math.max(96, anomalyWindowPoints),
      step: 1,
      value: anomalyWindowPoints,
      fmt: (v) =>
        v >= 2 ? `${v} · ${fmtDur(v * payload.interval_seconds * 1000)}` : 'off',
      hint: 'Fraction rule (OR-ed with the consecutive rule): also fire when at least the share ' +
        'below of the trailing window is anomalous AND the latest point is anomalous. Set to ' +
        'off (< 2) for the classic consecutive-only alert.',
    },
    (v) => {
      anomalyWindowPoints = v;
      refreshShareVisibility();
      recompute();
    },
  );
  alertCommon.appendChild(anomalyWindowCtl.row);

  const minAnomalyShareCtl = rangeControl(
    'Alert: min share in window',
    {
      min: 0.05,
      max: 1,
      step: 0.05,
      value: minAnomalyShare,
      fmt: (v) => `${Math.round(v * 100)}%`,
      hint: 'Fraction rule: the share of the anomaly window that must be flagged for the alert ' +
        'to fire. Missing points count against the share (an outage never makes it easier).',
    },
    (v) => {
      minAnomalyShare = v;
      recompute();
    },
  );
  alertCommon.appendChild(minAnomalyShareCtl.row);
  const refreshShareVisibility = (): void => {
    minAnomalyShareCtl.row.style.display = anomalyWindowPoints >= 2 ? '' : 'none';
  };
  refreshShareVisibility();

  // y = 0 reference line.
  const zeroRow = el('div', 'dtk-ctl');
  const zeroLab = el('label', 'dtk-check');
  const zeroBox = el('input');
  zeroBox.type = 'checkbox';
  zeroBox.onchange = (): void => {
    chart.setZeroLine(zeroBox.checked);
  };
  zeroLab.title =
    'Draw a horizontal line at y = 0 and include zero in the scale — for real-valued metrics ' +
    'best read relative to zero.';
  zeroLab.appendChild(zeroBox);
  zeroLab.appendChild(document.createTextNode(' Show y = 0 line'));
  zeroRow.appendChild(zeroLab);
  alertCommon.appendChild(zeroRow);

  // Marked-incidents list (label edit + focus + delete). Shares the SAME `incidents`
  // array the chart edits in Label mode.
  const incidentsWrap = el('div', 'dtk-ctl dtk-incidents');
  incidentsWrap.appendChild(
    ctlLabel(
      'Marked incidents',
      'The real incidents you marked (in Label mode). Edit a label, focus to zoom the chart to ' +
        'it, or remove it. Save the set below to incidents/<metric>/ — the same store dtk autotune reads.',
    ),
  );
  const incidentsList = el('div', 'dtk-inc-list');
  incidentsWrap.appendChild(incidentsList);
  labelGroup.appendChild(incidentsWrap);

  function focusIncident(iv: Incident): void {
    const pad = Math.max((iv.end - iv.start) * 0.5, payload.interval_seconds * 1000 * 5);
    chart.setViewWindow(iv.start - pad, iv.end + pad);
  }
  function deleteIncident(iv: Incident): void {
    const k = incidents.indexOf(iv);
    if (k >= 0) incidents.splice(k, 1);
    // Retract a confirmed-valid verdict this incident overlapped, so it doesn't
    // resurface as a "confirmed alert" row — the chart ✕ and this list ✕ stay in sync.
    const retracted = retractConfirmationFor(iv);
    chart.setIncidents(incidents);
    if (retracted) repaintAlerts(); // recolours markers + recomputes metrics + refreshes list
    else {
      refreshIncidentList();
      renderMetrics();
    }
  }
  // Un-confirm a validated-alert incident: clear its verdict (the green marker
  // reverts to an un-reviewed alert), then repaint everything — this is the inverse
  // of confirming the alert in Review mode, exposed here so the list is the single
  // place to add/remove every kind of incident.
  function unconfirmAlert(iv: Incident): void {
    setReview(iv.start, iv.end, null);
    chart.setIncidents(incidents);
    repaintAlerts(); // re-colours markers + recomputes metrics + refreshes this list
  }
  function refreshIncidentList(): void {
    incidentsList.innerHTML = '';
    // One list, two provenances: hand-marked incidents (editable label/delete) and
    // confirmed-valid alerts (a read-only "✓ alert" badge; ✕ un-confirms). Deduped:
    // a validated span already covered by a hand-marked incident shows once, as the
    // editable manual row. Sorted together so the list reads chronologically.
    type Row = { iv: Incident; kind: 'manual' | 'alert' };
    const rows: Row[] = [
      ...incidents.map((iv) => ({ iv, kind: 'manual' as const })),
      ...validatedExtra().map((iv) => ({ iv, kind: 'alert' as const })),
    ].sort((a, b) => a.iv.start - b.iv.start);
    if (!rows.length) {
      incidentsList.appendChild(
        el('div', 'dtk-inc-empty', 'None yet — switch to Label mode and drag across the chart, or confirm alerts in Review mode.'),
      );
      return;
    }
    for (const { iv, kind } of rows) {
      const row = el('div', 'dtk-inc-row' + (kind === 'alert' ? ' dtk-inc-fromalert' : ''));
      row.appendChild(el('span', 'dtk-inc-span', `${fmtTs(iv.start)} → ${fmtTs(iv.end)}`));
      row.appendChild(el('span', 'dtk-inc-dur', fmtDur(Math.max(0, iv.end - iv.start))));
      if (kind === 'alert') {
        // Confirmed-from-alert: a static badge (the verdict, not a free label) +
        // an ✕ that clears the verdict instead of editing a hand-marked span.
        const badge = el('span', 'dtk-inc-badge', '✓ confirmed alert');
        badge.title = 'A fired alert you confirmed valid (in Review mode). It counts as a real ' +
          'incident — remove it here to un-confirm the alert.';
        row.appendChild(badge);
      } else {
        const lbl = el('input', 'dtk-inc-label');
        lbl.type = 'text';
        lbl.value = iv.label || '';
        lbl.placeholder = 'label (optional)';
        lbl.oninput = (): void => {
          iv.label = lbl.value;
        };
        row.appendChild(lbl);
      }
      const focus = el('button', 'dtk-inc-btn', 'focus');
      focus.type = 'button';
      focus.onclick = (): void => focusIncident(iv);
      row.appendChild(focus);
      const del = el('button', 'dtk-inc-btn dtk-inc-del', '✕');
      del.type = 'button';
      del.title = kind === 'alert' ? 'un-confirm this alert' : 'remove this incident';
      del.onclick = (): void => (kind === 'alert' ? unconfirmAlert(iv) : deleteIncident(iv));
      row.appendChild(del);
      incidentsList.appendChild(row);
    }
  }

  // Show only the controls relevant to the selected detector — a 3-way split:
  // band rows (threshold/window/stabilization) for every history-based detector
  // (windowed AND autoreg), windowed-only rows (weights/detrend/smoothing/
  // seasonality) hidden for autoreg (v1 has none — the detector rejects
  // seasonality), lags for autoreg only, bounds for manual_bounds only.
  // Direction + consecutive + the anomaly-window pair (alert-layer) always show.
  const bandRows = [thresholdCtl.row, windowCtl.row, stabilizationCtl.row];
  const windowedOnlyRows = [weightsCtl.row, detrendCtl.row, smoothingCtl.row];
  if (seasonalityRow) windowedOnlyRows.push(seasonalityRow);
  function refreshVisibility(): void {
    const t = detectorCtl.get() as DetectorType;
    const manual = t === 'manual_bounds';
    const autoreg = t === 'autoreg';
    for (const row of bandRows) row.style.display = manual ? 'none' : '';
    for (const row of windowedOnlyRows) row.style.display = manual || autoreg ? 'none' : '';
    lagsCtl.row.style.display = autoreg ? '' : 'none';
    lowerBoundCtl.row.style.display = manual ? '' : 'none';
    upperBoundCtl.row.style.display = manual ? '' : 'none';
    // half-life only when windowed AND exponential weighting.
    halfLifeRow.style.display =
      !manual && !autoreg && weightsCtl.get() === 'exponential' ? '' : 'none';
  }
  refreshVisibility();

  // Set every detector control from a camelCase seed (a metric detector, a
  // previously-edited detector, or an autotune winner) WITHOUT marking anything
  // dirty — .set() never fires onChange, and the caller drives one recompute after.
  // Updates the closed-over `seed` so readParams()'s passthrough knobs
  // (minSamples/inputType/smoothing*/minSamplesPerGroup) follow the active detector.
  function reseedControls(s: DetectorSeed): void {
    seed = s;
    detectorCtl.set(s.type);
    thresholdCtl.set(s.threshold);
    // A re-seed may carry a window/half-life beyond the slider's explore reach; raise
    // the max first so .set() can't silently clamp (which would shrink what Apply writes).
    const wMax = Math.max(windowMax, s.windowSize);
    windowCtl.setMax(wMax);
    halfLifeCtl.setMax(wMax);
    windowCtl.set(s.windowSize);
    weightsCtl.set(s.windowWeights);
    if (s.windowWeights === 'exponential' && s.halfLife != null) halfLifeCtl.set(s.halfLife);
    detrendCtl.set(s.detrend);
    stabilizationCtl.set(s.stabilization ?? 'none');
    smoothingCtl.set(s.smoothing);
    setSeasonalityGroups(s.seasonalityComponents || []);
    if (s.lowerBound != null) lowerBoundCtl.set(s.lowerBound);
    if (s.upperBound != null) upperBoundCtl.set(s.upperBound);
    if (s.lags != null || s.type === 'autoreg') {
      lagsCtl.set(Math.max(1, Math.round(s.lags ?? 5)));
    }
    refreshVisibility();
  }

  // Switch which of a multi-detector metric's detectors the cockpit is tuning.
  // FLUSH the outgoing detector's live control state into editedParams FIRST — a
  // just-released slider only *schedules* a debounced recompute, and reseeding the
  // controls below (plus recompute()'s own clearTimeout) would cancel that pending
  // capture, silently losing an edit made <130ms before the switch. Then load the
  // target (its in-session edits if any, else its original seed) and recompute.
  function switchDetector(idx: number): void {
    if (idx === activeIndex) return;
    const entry = detectorEntries.find((d) => d.index === idx);
    if (!entry || !entry.tunable || !entry.seed) return;
    if (activeIndex != null) editedParams.set(activeIndex, readParams());
    activeIndex = idx;
    reseedControls(editedParams.get(idx) ?? entry.seed);
    recompute();
  }

  // ---- stat bar + effective config + apply ----------------------------------
  const statBar = el('div', 'dtk-tune-stat');
  stageFoot.appendChild(statBar);

  // The effective-config readout is a vertical hog, so it's **collapsed by default**
  // (a one-line clickable header) to give the scrolling knob column more room; click
  // the header to expand it. configEcho stays updated even while hidden, so it shows
  // the current config the moment it's opened.
  const cfgWrap = el('div', 'dtk-tune-cfg');
  const cfgToggle = el('button', 'dtk-tune-cfg-k');
  cfgToggle.type = 'button';
  cfgToggle.title = 'Show or hide the exact config that will be written on Apply.';
  const configEcho = el('code', 'dtk-tune-cfg-v');
  let cfgOpen = false;
  const setCfgOpen = (open: boolean): void => {
    cfgOpen = open;
    configEcho.style.display = open ? '' : 'none';
    cfgToggle.textContent = `${open ? '▾' : '▸'} // effective config`;
  };
  cfgToggle.onclick = (): void => setCfgOpen(!cfgOpen);
  cfgWrap.appendChild(cfgToggle);
  cfgWrap.appendChild(configEcho);
  setCfgOpen(false);
  railFoot.appendChild(cfgWrap);

  if (payload.save_url) {
    const applyWrap = el('div', 'dtk-tune-apply');
    const btn = el('button', 'dtk-apply-btn', 'Apply to metric');
    btn.type = 'button';
    btn.title =
      'Write this detector config back into the metric YAML (the previous version is archived ' +
      'under metrics/.history/). Trimming the sample does not change what is written.';
    const msg = el('span', 'dtk-apply-msg');
    btn.onclick = (): void => {
      const activeParams = readParams();
      // Capture the on-screen detector's live params so it's written with its current
      // state (also covers the initial detector when it IS the active one).
      if (activeIndex != null) editedParams.set(activeIndex, activeParams);
      // Write back the detector the cockpit opened on (always) PLUS any slot the user
      // actually EDITED (dirty) — never a slot merely switched to and left untouched.
      // The server preserves every other detector verbatim, so a manual_bounds floor /
      // prophet alongside the tuned detector survives (the fix for the silent drop
      // that killed min_detectors≥2), and a lower-only floor you only glanced at in
      // the picker keeps its single bound.
      const out: Array<{ index: number | null; type: string; params: Record<string, unknown> }> =
        [];
      if (initialIndex != null) {
        for (const i of new Set<number>([initialIndex, ...dirty])) {
          const p = editedParams.get(i);
          if (p) out.push({ index: i, type: p.type, params: applyParams(p) });
        }
      } else {
        // No existing tunable slot (e.g. a prophet-only metric): append the fresh one.
        out.push({ index: null, type: activeParams.type, params: applyParams(activeParams) });
      }
      btn.disabled = true;
      msg.className = 'dtk-apply-msg info';
      msg.textContent = 'Applying…';
      fetch(payload.save_url as string, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          detectors: out,
          consecutive_anomalies: consecutive,
          // Fraction rule: exact-seconds duration (lossless points round-trip)
          // + share, or nulls to remove the pair from the alerting block.
          anomaly_window: shareWindowPoints()
            ? `${(shareWindowPoints() as number) * payload.interval_seconds}s`
            : null,
          min_anomaly_share: shareValue(),
        }),
      })
        .then((r) =>
          r.ok
            ? r.json()
            : r.text().then((t) => {
                throw new Error(t || `HTTP ${r.status}`);
              }),
        )
        .then((res: { saved?: string; updated?: string[]; preserved?: string[] }) => {
          msg.className = 'dtk-apply-msg ok';
          const kept =
            res.preserved && res.preserved.length ? ` Kept: ${res.preserved.join(', ')}.` : '';
          msg.textContent = `Applied → ${res.saved ?? 'metric'} (previous archived).${kept} You can close this tab.`;
        })
        .catch((e: Error) => {
          btn.disabled = false;
          msg.className = 'dtk-apply-msg err';
          msg.textContent = `Apply failed: ${e.message}`;
        });
    };
    applyWrap.appendChild(btn);
    applyWrap.appendChild(msg);
    railFoot.appendChild(applyWrap);
  } else {
    railFoot.appendChild(
      el(
        'div',
        'dtk-tune-note',
        'Static preview — sliders recompute live, but there is no write-back. ' +
          'Run `dtk tune` (without --no-serve) to apply a config.',
      ),
    );
  }

  // ---- save labels (incidents) ----------------------------------------------
  // Build the canonical labels YAML and either POST it to the localhost server
  // (writes incidents/<metric>/<stamp>.yml — the store dtk autotune reads) or, for
  // a static preview, download it for the user to drop in themselves.
  const yamlStr = (s: string): string => '"' + s.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
  const fmtUtc = (ms: number): string => new Date(ms).toISOString().slice(0, 19).replace('T', ' ');
  const buildLabelsYaml = (): string => {
    const lines = [`metric: ${payload.metric}`, 'timezone: UTC'];
    // Hand-marked incidents PLUS a derived incident for each confirmed (valid) alert
    // not already covered by one (groundTruth() = incidents ∪ overlap-deduped
    // validatedExtra), so confirming alerts feeds the next supervised `dtk autotune`
    // too. The seen-set below guards exact-span repeats.
    const seen = new Set<string>();
    const sorted = groundTruth()
      .sort((a, b) => a.start - b.start)
      .filter((iv) => {
        const k = `${Math.round(iv.start)}:${Math.round(iv.end)}`;
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      });
    if (!sorted.length) {
      lines.push('incidents: []');
    } else {
      lines.push('incidents:');
      for (const iv of sorted) {
        const lbl = iv.label ? `, label: ${yamlStr(iv.label)}` : '';
        lines.push(`  - {start: "${fmtUtc(iv.start)}", end: "${fmtUtc(iv.end)}"${lbl}}`);
      }
    }
    // Persist the painted threshold-capture window so the regime scope is auditable
    // and restored on reopen. Pure metadata — autotune ignores it.
    const cap = chart.getCaptureWindow();
    if (cap) {
      lines.push('capture_windows:');
      lines.push(`  - {start: "${fmtUtc(cap.start)}", end: "${fmtUtc(cap.end)}"}`);
    }
    // Per-alert verdicts as metadata so the green/slate markers re-seed on reopen
    // (re-bound by streak-span overlap). Autotune ignores this block.
    if (reviews.length) {
      lines.push('alert_reviews:');
      for (const r of [...reviews].sort((a, b) => a.start - b.start)) {
        lines.push(`  - {start: "${fmtUtc(r.start)}", end: "${fmtUtc(r.end)}", verdict: ${r.verdict}}`);
      }
    }
    return lines.join('\n') + '\n';
  };

  const labelsWrap = el('div', 'dtk-tune-apply');
  const setNameInput = el('input', 'dtk-setname');
  setNameInput.type = 'text';
  setNameInput.placeholder = 'name this set (optional)';
  const saveLabelsBtn = el(
    'button',
    'dtk-apply-btn dtk-labels-btn',
    payload.labels_save_url ? 'Save incidents' : 'Download incidents',
  );
  saveLabelsBtn.type = 'button';
  saveLabelsBtn.title =
    'Write the marked incidents to incidents/<metric>/ (versioned) so they also feed the next ' +
    '`dtk autotune`. Saving labels does not end tuning — keep adjusting and apply the detector when ready.';
  const labelsMsg = el('span', 'dtk-apply-msg');
  saveLabelsBtn.onclick = (): void => {
    const yaml = buildLabelsYaml();
    if (!payload.labels_save_url) {
      const blob = new Blob([yaml], { type: 'text/yaml' });
      const a = el('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${payload.metric}.yml`;
      a.click();
      URL.revokeObjectURL(a.href);
      labelsMsg.className = 'dtk-apply-msg ok';
      labelsMsg.textContent = `Downloaded — drop it into incidents/${payload.metric}/`;
      return;
    }
    labelsMsg.className = 'dtk-apply-msg info';
    labelsMsg.textContent = 'Saving…';
    fetch(payload.labels_save_url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: setNameInput.value, yaml }),
    })
      .then((r) =>
        r.ok
          ? r.json()
          : r.text().then((t) => {
              throw new Error(t || `HTTP ${r.status}`);
            }),
      )
      .then((res: { saved?: string }) => {
        labelsMsg.className = 'dtk-apply-msg ok';
        labelsMsg.textContent = `Saved → ${res.saved ?? 'incidents'} (keep tuning, or Apply the detector)`;
      })
      .catch((e: Error) => {
        labelsMsg.className = 'dtk-apply-msg err';
        labelsMsg.textContent = `Save failed: ${e.message}`;
      });
  };
  labelsWrap.appendChild(setNameInput);
  labelsWrap.appendChild(saveLabelsBtn);
  labelsWrap.appendChild(labelsMsg);
  labelGroup.appendChild(labelsWrap);

  // ---- autotune panel (Autotune mode) ---------------------------------------
  // Server-side autotune: POST the current ground truth (the same labels YAML as
  // Save incidents) plus the window currently shown (the 'Points shown' trim) to
  // the engine, which searches over exactly that window — the same series the
  // cockpit displays and scores — and returns the winning detector. We re-seed
  // every knob from it, recompute the
  // live band, and render the decision log — then the user reviews and Applies (in
  // Tune/Autotune mode). Re-seeding mirrors the initial render() seeding exactly,
  // via the same camelCase shape the server builds with seed_detector_params.
  function applyAutotuneResult(res: AutotuneResult): void {
    // Re-seed the ACTIVE detector's knobs from the winner (shared with the picker's
    // detector-switch). Autotune tunes the detector currently on screen; the metric's
    // other detectors are untouched and stay preserved on Apply. Marks the active
    // detector dirty so the searched config is written back.
    reseedControls(res.detector);
    markActiveDirty();
    if (res.consecutive_anomalies != null) {
      consecutive = res.consecutive_anomalies;
      consecutiveCtl.set(consecutive);
    }
    // Fraction rule from the sweep: re-seed the pair, or switch it off when the
    // legacy consecutive-only rule won (null ⇒ off).
    if (res.anomaly_window_points != null && res.min_anomaly_share != null) {
      anomalyWindowPoints = res.anomaly_window_points;
      minAnomalyShare = res.min_anomaly_share;
      anomalyWindowCtl.setMax(Math.max(96, anomalyWindowPoints));
      anomalyWindowCtl.set(anomalyWindowPoints);
      minAnomalyShareCtl.set(minAnomalyShare);
    } else {
      anomalyWindowPoints = 0;
      anomalyWindowCtl.set(0);
    }
    refreshShareVisibility();
    recompute();
  }

  autotuneGroup.appendChild(
    el(
      'div',
      'dtk-tune-note',
      'Run the full autotune engine server-side over the window shown (the ‘Points shown’ ' +
        'trim — the same series you see and score here), using the incidents you’ve marked ' +
        '(and confirmed alerts) as ground truth. It re-seeds the knobs with the winning ' +
        'detector — review the band, then Apply (here or in Tune). Nothing is written until ' +
        'you Apply; the next `dtk run` is the source of truth.',
    ),
  );
  if (payload.autotune_url) {
    const atWrap = el('div', 'dtk-tune-apply');
    const atBtn = el('button', 'dtk-apply-btn', 'Run autotune');
    atBtn.type = 'button';
    atBtn.title =
      'Search for the best detector over the window shown (the ‘Points shown’ trim). Uses ' +
      'your marked incidents as ground truth when present (supervised), else an unsupervised ' +
      'objective. Can take a few seconds on a long window.';
    const atMsg = el('span', 'dtk-apply-msg');
    atWrap.appendChild(atBtn);
    atWrap.appendChild(atMsg);
    autotuneGroup.appendChild(atWrap);

    const atResult = el('div', 'dtk-at-result');
    atResult.style.display = 'none';
    autotuneGroup.appendChild(atResult);

    const renderAutotuneResult = (res: AutotuneResult): void => {
      atResult.innerHTML = '';
      atResult.style.display = '';
      const head = el('div', 'dtk-at-head');
      head.appendChild(el('span', 'dtk-at-winner', res.winner));
      head.appendChild(
        el(
          'span',
          'dtk-at-score',
          `${res.scoring_metric} ${Number.isFinite(res.score) ? res.score.toFixed(3) : '—'} · ${res.mode}`,
        ),
      );
      atResult.appendChild(head);
      atResult.appendChild(
        el(
          'div',
          'dtk-at-meta',
          `${res.n_candidates} candidate${res.n_candidates === 1 ? '' : 's'} · ${res.n_points} pts` +
            (res.consecutive_anomalies != null ? ` · consecutive ${res.consecutive_anomalies}` : '') +
            (res.anomaly_window_points != null && res.min_anomaly_share != null
              ? ` · window ${res.anomaly_window_points}p × ${res.min_anomaly_share}`
              : '') +
            (res.seasonality && res.seasonality.length
              ? ` · seasonality ${JSON.stringify(res.seasonality)}`
              : ' · no seasonality'),
        ),
      );
      // Decision log — collapsed by default (it can be long), one line per stage.
      const logToggle = el('button', 'dtk-tune-cfg-k');
      logToggle.type = 'button';
      const logBody = el('div', 'dtk-at-log');
      let logOpen = false;
      const setLogOpen = (o: boolean): void => {
        logOpen = o;
        logBody.style.display = o ? '' : 'none';
        logToggle.textContent = `${o ? '▾' : '▸'} decision log (${res.decision_log.length})`;
      };
      logToggle.onclick = (): void => setLogOpen(!logOpen);
      for (const e of res.decision_log) {
        const line = el('div', 'dtk-at-logline');
        line.appendChild(el('span', 'dtk-at-stage', e.stage));
        line.appendChild(el('span', 'dtk-at-msg', e.message));
        logBody.appendChild(line);
      }
      setLogOpen(false);
      atResult.appendChild(logToggle);
      atResult.appendChild(logBody);
    };

    atBtn.onclick = (): void => {
      atBtn.disabled = true;
      atMsg.className = 'dtk-apply-msg info';
      atMsg.textContent = 'Autotuning over the shown window… this can take a moment.';
      fetch(payload.autotune_url as string, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          // The current ground truth, so the search is supervised by what's marked.
          yaml: buildLabelsYaml(),
          // Tune on exactly the window shown (the 'Points shown' trim re-slices
          // `series`), so the engine optimizes the same series the cockpit displays
          // and scores — not the full history. Omitted → server uses full history.
          window: series.timestamps.length
            ? {
                start: series.timestamps[0],
                end: series.timestamps[series.timestamps.length - 1],
              }
            : null,
        }),
      })
        .then((r) =>
          r.ok
            ? r.json()
            : r.text().then((t) => {
                throw new Error(t || `HTTP ${r.status}`);
              }),
        )
        .then((res: AutotuneResult) => {
          atBtn.disabled = false;
          applyAutotuneResult(res);
          renderAutotuneResult(res);
          const sup =
            res.mode === 'supervised'
              ? ' — supervised by your incidents'
              : ' — unsupervised (mark incidents for a supervised tune)';
          atMsg.className = 'dtk-apply-msg ok';
          atMsg.textContent = `Tuned${sup}. Knobs updated; review the band, then Apply.`;
        })
        .catch((e: Error) => {
          atBtn.disabled = false;
          atMsg.className = 'dtk-apply-msg err';
          atMsg.textContent = `Autotune failed: ${e.message}`;
        });
    };
  } else {
    autotuneGroup.appendChild(
      el(
        'div',
        'dtk-tune-note',
        'Autotune needs the live server — run `dtk tune` without --no-serve.',
      ),
    );
  }

  // ---- first paint + resize -------------------------------------------------
  setUiMode('tune');
  refreshIncidentList();
  runRecompute();
  renderMetrics();
  // Re-fit the chart whenever its box changes — window resize, font reflow, AND the
  // rail collapsing/expanding (which widens/narrows the windshield without a window
  // resize). ResizeObserver catches all three; fall back to window resize if absent.
  let rafResize = 0;
  const refit = (): void => {
    if (rafResize) cancelAnimationFrame(rafResize);
    rafResize = requestAnimationFrame(() => chart.resize());
  };
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(refit).observe(chartWrap);
  } else {
    window.addEventListener('resize', refit);
  }
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

function fmtNum(v: number): string {
  if (!Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a !== 0 && (a < 0.01 || a >= 1e6)) return v.toExponential(2);
  return Number(v.toFixed(a < 1 ? 4 : 2)).toString();
}

function fmtTs(ms: number): string {
  return new Date(ms).toISOString().slice(0, 16).replace('T', ' ');
}

function fmtDur(ms: number): string {
  const m = Math.round(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  const hh = h % 24;
  return hh ? `${d}d ${hh}h` : `${d}d`;
}

function fmtInterval(seconds: number): string {
  if (seconds % 86400 === 0) return `${seconds / 86400}d`;
  if (seconds % 3600 === 0) return `${seconds / 3600}h`;
  if (seconds % 60 === 0) return `${seconds / 60}min`;
  return `${seconds}s`;
}

// ---------------------------------------------------------------------------
// Styles (brand tokens; injected once)
// ---------------------------------------------------------------------------

let styled = false;
function injectStyle(): void {
  if (styled) return;
  styled = true;
  const css = `
.dtk-tune{--c:#d15b36;--c7:#b4471f;--ink:#1b1916;--muted:#6e675b;--faint:#9a9384;
  --paper:#f5f1e8;--surface:#fbf9f3;--border:#e6e0d4;--green:#2e9e73;--anom:#d63232;
  --mono:'JetBrains Mono',ui-monospace,Menlo,monospace;
  --sans:'Schibsted Grotesk',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;}
.dtk-tune-root{max-width:1680px;margin:0 auto;padding:12px 16px;font-family:var(--sans);color:var(--ink);
  height:100dvh;display:flex;flex-direction:column;gap:10px;overflow:hidden;}
.dtk-tune-header{flex:0 0 auto;}
.dtk-tune-titlerow{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;}
.dtk-tune-title{font-size:19px;margin:0;font-weight:700;}
.dtk-tune-badge{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.06em;
  color:#fff;background:var(--c);border-radius:999px;padding:3px 9px;}
.dtk-tune-sub{color:var(--muted);font-size:12px;margin-top:2px;font-family:var(--mono);}
.dtk-tune-desc{color:var(--muted);font-size:12px;margin-top:3px;white-space:pre-wrap;max-height:2.6em;overflow:auto;}
/* cockpit: chart-windshield (stage) + always-visible mode-aware control rail */
.dtk-tune-cockpit{display:flex;gap:12px;flex:1;min-height:0;}
.dtk-tune-stage{position:relative;display:flex;flex-direction:column;gap:8px;flex:1;min-width:0;min-height:0;}
.dtk-tune-hud{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;flex:0 0 auto;}
.dtk-tune-stagefoot{flex:0 0 auto;display:flex;flex-direction:column;gap:6px;}
.dtk-tune-rail{flex:0 0 340px;display:flex;flex-direction:column;min-height:0;background:var(--surface);
  border:1px solid var(--border);border-radius:12px;overflow:hidden;}
.dtk-tune-railhead{flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;gap:8px;
  padding:9px 12px;border-bottom:1px solid var(--border);}
.dtk-rail-title{font-family:var(--mono);font-size:11px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.06em;flex:1 1 auto;}
.dtk-tune-railfoot{flex:0 0 auto;display:flex;flex-direction:column;gap:8px;padding:11px 12px;
  border-top:1px solid var(--border);background:var(--paper);}
.dtk-rail-open{position:absolute;top:50%;right:6px;transform:translateY(-50%);z-index:6;
  border:1px solid var(--border);background:var(--surface);color:var(--ink);border-radius:8px;
  padding:13px 7px;font-size:15px;cursor:pointer;box-shadow:0 1px 6px rgba(27,25,22,.14);}
.dtk-rail-open:hover{border-color:var(--c);color:var(--c7);}
.dtk-dock-toggle{flex:0 0 auto;border:1px solid var(--border);background:var(--surface);color:var(--muted);
  border-radius:7px;padding:4px 10px;font-family:var(--sans);font-size:13px;font-weight:700;cursor:pointer;line-height:1;}
.dtk-dock-toggle:hover{border-color:var(--c);color:var(--c7);}
.dtk-tune-controls{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:14px;padding:14px;}
.dtk-rail-group{display:flex;flex-direction:column;gap:14px;}
.dtk-ctl{display:flex;flex-direction:column;gap:6px;}
.dtk-ctl-head{display:flex;justify-content:space-between;align-items:baseline;}
.dtk-ctl-label{font-size:12px;font-weight:600;color:var(--ink);}
.dtk-ctl-val{font-family:var(--mono);font-size:12px;color:var(--c7);}
.dtk-seg{display:flex;gap:4px;background:var(--paper);border:1px solid var(--border);border-radius:8px;padding:3px;}
.dtk-seg.dtk-wrap{flex-wrap:wrap;}
.dtk-seg-btn{flex:1 1 auto;border:0;background:transparent;color:var(--muted);font-family:var(--sans);
  font-size:12px;padding:5px 8px;border-radius:6px;cursor:pointer;white-space:nowrap;}
.dtk-seg-btn:hover{color:var(--ink);}
.dtk-seg-btn.on{background:var(--c);color:#fff;font-weight:600;}
.dtk-range{width:100%;accent-color:var(--c);cursor:pointer;}
.dtk-check{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);margin-top:2px;cursor:pointer;}
.dtk-tune-chart{position:relative;width:100%;flex:1;min-height:220px;background:var(--surface);
  border:1px solid var(--border);border-radius:12px;overflow:hidden;}
.dtk-tune-chart canvas{width:100%;height:100%;display:block;}
.dtk-tune-readout{font-family:var(--mono);font-size:12px;color:var(--muted);min-height:18px;}
.dtk-tune-stat{font-family:var(--mono);font-size:12px;color:var(--ink);}
.dtk-tune-warn{font-family:var(--mono);font-size:12px;line-height:1.5;color:var(--c7);
  background:rgba(240,173,78,0.13);border:1px solid rgba(240,173,78,0.5);border-radius:8px;padding:8px 11px;}
.dtk-tune-cfg{background:var(--ink);color:#c9c2b4;border-radius:8px;padding:8px 11px;font-family:var(--mono);
  font-size:12px;overflow-x:auto;}
.dtk-tune-cfg-k{display:flex;width:100%;border:0;background:transparent;color:var(--faint);
  font-family:var(--mono);font-size:11.5px;cursor:pointer;padding:0;text-align:left;}
.dtk-tune-cfg-k:hover{color:#e6e0d4;}
.dtk-tune-cfg-v{display:block;color:#e6e0d4;white-space:pre-wrap;word-break:break-word;margin-top:6px;}
.dtk-tune-apply{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
.dtk-apply-btn{background:var(--c);color:#fff;border:0;border-radius:8px;padding:10px 18px;font-family:var(--sans);
  font-size:14px;font-weight:600;cursor:pointer;}
.dtk-apply-btn:hover{background:var(--c7);}
.dtk-apply-btn:disabled{opacity:.55;cursor:default;}
.dtk-apply-msg{font-size:13px;}
.dtk-apply-msg.ok{color:var(--green);}
.dtk-apply-msg.err{color:var(--anom);}
.dtk-apply-msg.info{color:var(--muted);}
.dtk-tune-note{font-size:13px;color:var(--muted);background:var(--surface);border:1px dashed var(--border);
  border-radius:8px;padding:10px 12px;}
.dtk-ctl-info{color:var(--faint);font-size:10px;cursor:help;vertical-align:super;}
.dtk-tune-trim{display:flex;flex-direction:column;gap:6px;background:var(--surface);
  border:1px solid var(--border);border-radius:10px;padding:9px 12px;}
.dtk-tune-trim-head{display:flex;justify-content:space-between;align-items:baseline;}
.dtk-tune-trim-val{font-family:var(--mono);font-size:12px;color:var(--c7);}
.dtk-tune-spin{position:absolute;top:10px;right:12px;display:none;align-items:center;gap:7px;
  background:rgba(27,25,22,0.78);color:#e6e0d4;border:1px solid #332f29;border-radius:999px;
  padding:4px 11px 4px 8px;font-family:var(--mono);font-size:11px;pointer-events:none;}
.dtk-tune-spin.on{display:inline-flex;}
.dtk-spin-ring{width:12px;height:12px;border-radius:50%;border:2px solid rgba(245,241,232,0.25);
  border-top-color:var(--c);animation:dtk-spin .7s linear infinite;}
@keyframes dtk-spin{to{transform:rotate(360deg);}}
.dtk-tune-legend{flex:0 0 auto;display:flex;align-items:center;flex-wrap:wrap;gap:8px 16px;font-size:12px;
  color:var(--muted);padding:6px 12px;background:var(--surface);border:1px solid var(--border);border-radius:9px;}
.dtk-leg-item{display:inline-flex;align-items:center;gap:6px;cursor:help;}
.dtk-leg-sw{display:inline-block;flex:0 0 auto;}
.dtk-leg-sw.line{width:16px;height:3px;background:var(--c);border-radius:2px;}
.dtk-leg-sw.band{width:16px;height:11px;background:rgba(209,91,54,0.18);
  border:1px solid rgba(209,91,54,0.5);border-radius:2px;}
.dtk-leg-sw.center{width:16px;height:2px;
  background:repeating-linear-gradient(90deg,var(--faint) 0 4px,transparent 4px 7px);}
.dtk-leg-sw.dot{width:9px;height:9px;border-radius:50%;background:var(--anom);}
.dtk-leg-sw.alert{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;
  border-top:7px solid var(--anom);}
.dtk-leg-sw.alert-ok{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;
  border-top:7px solid var(--green);}
.dtk-leg-sw.alert-no{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;
  border-top:7px solid #5a7a8c;}
.dtk-leg-txt{white-space:nowrap;}
.dtk-season-row{display:flex;align-items:center;justify-content:space-between;gap:8px;}
.dtk-season-col{font-family:var(--mono);font-size:11.5px;color:var(--muted);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.dtk-season-seg{flex:0 0 auto;padding:2px;}
.dtk-season-seg .dtk-seg-btn{flex:0 0 auto;padding:3px 7px;font-family:var(--mono);font-size:11px;}
.dtk-tune-metrics{display:flex;flex-wrap:wrap;gap:8px;margin:0;flex:0 1 auto;}
.dtk-m-chip{display:inline-flex;align-items:center;gap:7px;padding:7px 13px;background:var(--surface);
  border:1px solid var(--border);border-radius:10px;font-size:13px;}
.dtk-m-dot{width:9px;height:9px;border-radius:50%;flex:0 0 auto;}
.dtk-m-v{font-family:var(--mono);font-weight:700;font-size:15px;color:var(--ink);}
.dtk-m-l{color:var(--faint);font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.05em;}
.dtk-m-sub{color:var(--muted);font-family:var(--mono);font-size:11.5px;}
.dtk-m-chip.over{border-color:var(--anom);box-shadow:inset 0 0 0 1px rgba(214,50,50,.5);}
.dtk-m-chip.over .dtk-m-sub{color:var(--anom);font-weight:600;}
.dtk-tune-modes{display:inline-flex;gap:4px;background:var(--ink);border-radius:9px;padding:4px;margin:0;flex:0 0 auto;}
.dtk-mode-btn{border:0;background:transparent;color:#c9c2b4;font-family:var(--sans);font-size:13px;font-weight:600;
  padding:7px 16px;border-radius:6px;cursor:pointer;transition:background .12s,color .12s;}
.dtk-mode-btn:hover{color:#fff;}
.dtk-mode-btn.on{background:var(--c);color:#fff;}
.dtk-tune-reviewbar{align-items:center;}
.dtk-tune-reviewbar .dtk-apply-btn{background:var(--green);}
.dtk-tune-reviewbar .dtk-apply-btn:hover{background:#27815d;}
.dtk-at-result{display:flex;flex-direction:column;gap:7px;background:var(--surface);
  border:1px solid var(--border);border-radius:10px;padding:11px 13px;}
.dtk-at-head{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px;}
.dtk-at-winner{font-family:var(--mono);font-size:12.5px;font-weight:700;color:var(--ink);}
.dtk-at-score{font-family:var(--mono);font-size:11.5px;color:var(--c7);}
.dtk-at-meta{font-family:var(--mono);font-size:11px;color:var(--muted);word-break:break-word;}
.dtk-at-log{display:flex;flex-direction:column;gap:5px;max-height:240px;overflow:auto;margin-top:4px;}
.dtk-at-logline{display:flex;gap:8px;align-items:baseline;}
.dtk-at-stage{flex:0 0 auto;font-family:var(--mono);font-size:9.5px;text-transform:uppercase;
  letter-spacing:.05em;color:#fff;background:var(--c);border-radius:4px;padding:1px 6px;}
.dtk-at-msg{font-family:var(--mono);font-size:11px;color:var(--ink);}
.dtk-th{display:flex;flex-direction:column;gap:8px;margin:2px 0 6px;}
.dtk-th-toggles{display:flex;gap:8px;flex-wrap:wrap;}
.dtk-th-toggle{align-self:flex-start;border:1px solid var(--border);background:var(--surface);
  color:var(--muted);border-radius:8px;padding:6px 12px;font-family:var(--sans);font-size:12.5px;cursor:pointer;}
.dtk-th-toggle:hover{border-color:var(--c);color:var(--c7);}
.dtk-th-toggle.on{background:var(--c);border-color:var(--c);color:#fff;}
.dtk-th-bar{display:flex;flex-wrap:wrap;align-items:flex-end;gap:10px 14px;padding:11px 13px;
  background:var(--surface);border:1px solid var(--border);border-radius:10px;}
.dtk-th-grp{display:flex;flex-direction:column;gap:3px;}
.dtk-th-lbl{font-family:var(--mono);font-size:10.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.05em;}
.dtk-th-num,.dtk-th-sel{background:var(--paper);color:var(--ink);border:1px solid var(--border);
  border-radius:6px;padding:5px 8px;font-family:var(--mono);font-size:12px;}
.dtk-th-num{width:96px;}
.dtk-th-num:focus,.dtk-th-sel:focus{outline:none;border-color:var(--c);}
.dtk-th-scope{font-family:var(--mono);font-size:11px;color:var(--muted);align-self:center;flex:1 1 160px;}
.dtk-th-add{padding:7px 14px;}
.dtk-th-add:disabled{opacity:.5;cursor:default;}
.dtk-incidents{gap:8px;}
.dtk-inc-list{display:flex;flex-direction:column;gap:6px;max-height:240px;overflow:auto;}
.dtk-inc-empty{font-size:12px;color:var(--faint);font-style:italic;}
.dtk-inc-row{display:flex;align-items:center;gap:6px;flex-wrap:wrap;background:var(--paper);
  border:1px solid var(--border);border-radius:7px;padding:6px 8px;}
.dtk-inc-span{font-family:var(--mono);font-size:10.5px;color:var(--ink);}
.dtk-inc-dur{font-family:var(--mono);font-size:10.5px;color:var(--muted);}
.dtk-inc-label{flex:1 1 90px;min-width:70px;background:var(--surface);color:var(--ink);
  border:1px solid var(--border);border-radius:5px;padding:4px 7px;font-family:var(--sans);font-size:11.5px;}
.dtk-inc-label:focus{outline:none;border-color:var(--c);}
.dtk-inc-btn{border:1px solid var(--border);background:var(--surface);color:var(--muted);border-radius:6px;
  padding:3px 8px;font-size:11px;cursor:pointer;font-family:var(--sans);}
.dtk-inc-btn:hover{border-color:var(--c);color:var(--c7);}
.dtk-inc-del{color:var(--anom);}
.dtk-inc-fromalert{border-color:rgba(46,158,115,.5);background:rgba(46,158,115,.08);}
.dtk-inc-badge{flex:1 1 90px;min-width:70px;font-family:var(--mono);font-size:10.5px;color:var(--green);
  display:inline-flex;align-items:center;font-weight:600;}
.dtk-setname{background:var(--surface);color:var(--ink);border:1px solid var(--border);border-radius:8px;
  padding:9px 11px;font-family:var(--sans);font-size:13px;min-width:180px;}
.dtk-setname::placeholder{color:var(--faint);}
.dtk-setname:focus{outline:none;border-color:var(--c);}
.dtk-labels-btn{background:var(--surface);color:var(--ink);border:1px solid var(--border);}
.dtk-labels-btn:hover{background:var(--paper);border-color:var(--c);color:var(--c7);}
/* Narrow viewports: drop the cockpit to a scrolling stack (chart over rail). */
@media (max-width:900px){
  .dtk-tune-root{height:auto;overflow:visible;}
  .dtk-tune-cockpit{flex-direction:column;}
  .dtk-tune-rail{flex:0 0 auto;width:100%;}
  .dtk-tune-controls{overflow:visible;}
  .dtk-tune-chart{flex:0 0 auto;height:54vh;min-height:320px;}
  .dtk-rail-open{display:none!important;}
}
`;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);
}

// Expose the global the inlined HTML bootstrap calls (mirrors __DTK_REPORT__).
(window as unknown as { __DTK_TUNE__: { render: typeof render } }).__DTK_TUNE__ = { render };

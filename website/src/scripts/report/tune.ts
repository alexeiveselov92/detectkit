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
  Detrend,
  DetectorParams,
  DetectorType,
  Incident,
  LassoInfo,
  ScoredPoint,
  Series,
  Smoothing,
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
  consecutive_anomalies: number;
  /** alert-layer direction the view filter seeds to ('any' = both). */
  direction?: AlertDirection;
  /** localhost POST endpoint for Apply; null = static read-only preview. */
  save_url: string | null;
  /** seeded incident spans ({start,end,label} naive-UTC strings) from incidents/<metric>/. */
  incidents?: Array<{ start: string; end: string; label?: string }>;
  /** seeded threshold-capture window(s) ({start,end} naive-UTC strings) — regime scope. */
  capture_windows?: Array<{ start: string; end: string }>;
  /** localhost POST endpoint for Save labels; null = download instead (no server). */
  labels_save_url?: string | null;
}

// Per-type interval-width default (mirrors the detector classes / the demo).
// Partial: manual_bounds has no threshold / per-group default.
const THRESHOLD_DEFAULT: Partial<Record<DetectorType, number>> = { mad: 3.0, zscore: 3.0, iqr: 1.5 };
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
): { row: HTMLElement; get: () => number; setMax: (m: number) => void } {
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
  input.oninput = (): void => {
    const v = Number(input.value);
    out.textContent = fmt(v);
    onChange(v);
  };
  row.appendChild(input);
  return {
    row,
    get: () => Number(input.value),
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
  const out: Record<string, unknown> = {
    threshold: p.threshold,
    window_size: p.windowSize,
  };
  if (p.windowWeights !== 'none') {
    out.window_weights = p.windowWeights;
    if (p.windowWeights === 'exponential' && p.halfLife != null) out.half_life = p.halfLife;
  }
  if (p.detrend !== 'none') out.detrend = p.detrend;
  if (p.smoothing !== 'none') out.smoothing = p.smoothing;
  if (p.inputType !== 'values') out.input_type = p.inputType;
  if (p.seasonalityComponents && p.seasonalityComponents.length) {
    out.seasonality_components = p.seasonalityComponents;
    out.min_samples_per_group = p.minSamplesPerGroup;
  }
  return out;
}

function configText(p: DetectorParams, consecutive: number): string {
  const ap = applyParams(p);
  const parts = [`type: ${p.type}`];
  for (const [k, v] of Object.entries(ap)) {
    parts.push(`${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`);
  }
  if (p.direction && p.direction !== 'any') parts.push(`direction=${p.direction}`);
  parts.push(`consecutive_anomalies=${consecutive}`);
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

  // ---- mutable parameter state, seeded from the metric's current config -----
  const seed = payload.detector;
  let consecutive = payload.consecutive_anomalies;

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
    seasonalityComponents: buildSeasonality(),
    minSamplesPerGroup:
      MIN_SAMPLES_PER_GROUP_DEFAULT[detectorCtl.get() as DetectorType] ?? seed.minSamplesPerGroup,
    consecutiveAnomalies: consecutive,
    direction: directionCtl.get() as AlertDirection,
    // Read from the bound sliders regardless of type; the windowed detectors
    // ignore these, the manual_bounds port reads them.
    lowerBound: lowerBoundCtl.get(),
    upperBound: upperBoundCtl.get(),
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

  // ---- alert-quality metrics bar (top, prominent) --------------------------
  // Two operator-facing numbers, recomputed live: how many real incidents the
  // current config CATCHES (recall) and what share of fired alerts are FALSE
  // (FDR / type-I control). Filled by renderMetrics() once it's defined.
  const metricsBar = el('div', 'dtk-tune-metrics');
  root.appendChild(metricsBar);

  // ---- layout: controls | main ---------------------------------------------
  const grid = el('div', 'dtk-tune-grid');
  const controls = el('div', 'dtk-tune-controls');
  const main = el('div', 'dtk-tune-main');
  grid.appendChild(controls);
  grid.appendChild(main);
  root.appendChild(grid);

  // ---- trim slider (above the chart) ---------------------------------------
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
  main.appendChild(trimWrap);

  // chart
  const chartWrap = el('div', 'dtk-tune-chart');
  const canvas = el('canvas');
  chartWrap.appendChild(canvas);
  // recompute spinner overlay (top-right of the chart)
  const spinner = el('div', 'dtk-tune-spin');
  spinner.appendChild(el('span', 'dtk-spin-ring'));
  spinner.appendChild(el('span', 'dtk-spin-txt', 'computing…'));
  chartWrap.appendChild(spinner);
  main.appendChild(chartWrap);

  // legend
  const legend = el('div', 'dtk-tune-legend');
  const legItem = (sw: string, text: string, hint: string): void => {
    const item = el('span', 'dtk-leg-item');
    item.title = hint;
    item.appendChild(el('span', `dtk-leg-sw ${sw}`));
    item.appendChild(el('span', 'dtk-leg-txt', text));
    legend.appendChild(item);
  };
  legItem('line', 'metric', 'The metric value over time.');
  legItem('band', 'expected range', "The detector's confidence band — values inside it read as normal.");
  legItem('center', 'band center', 'The expected value at the middle of the band.');
  legItem('dot', 'anomaly', 'A point the detector flagged as anomalous (outside the band).');
  legItem('alert', 'alert', 'Where an alert fired — enough consecutive anomalies to meet the rule.');
  main.appendChild(legend);

  const readout = el('div', 'dtk-tune-readout');
  main.appendChild(readout);

  // Surfaces when the window is too small to fill the chosen seasonality, so the
  // band silently uses global (un-conditioned) statistics. Mirrors the Python
  // detector's runtime warning — without it a wide band reads like a bug.
  const seasonWarn = el('div', 'dtk-tune-warn');
  seasonWarn.style.display = 'none';
  main.appendChild(seasonWarn);
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

  // ---- labeler chart (synced beneath the detector chart) -------------------
  // Same series, same x-zoom/pan + y-scale; here the user MARKS real incidents
  // (drag to create, edges to resize, ✕/Delete to remove). The detector chart
  // overlays the same spans read-only, so alerts vs incidents read together.
  const labHead = el('div', 'dtk-tune-labhead');
  labHead.appendChild(
    ctlLabel(
      'Real incidents',
      'Drag on this chart to mark each real incident span — drag its edges to adjust, drag the ' +
        'middle to move, click its ✕ (or select + Delete) to remove. Pan via the strip below, ' +
        'scroll to zoom (both charts move together). The metrics above update as you tune.',
    ),
  );
  labHead.appendChild(
    el('span', 'dtk-tune-labhint', 'drag to mark · edges adjust · ✕/Delete remove · strip pans'),
  );
  main.appendChild(labHead);
  const labChartWrap = el('div', 'dtk-tune-chart dtk-tune-labchart');
  const labCanvas = el('canvas');
  labChartWrap.appendChild(labCanvas);
  main.appendChild(labChartWrap);

  // ---- live alert-quality metrics ------------------------------------------
  interface Quality {
    realIncidents: number;
    caught: number;
    recall: number;
    totalAlerts: number;
    correctAlerts: number;
    falseAlerts: number;
    fdr: number;
  }
  const computeQuality = (spans: Array<[number, number]>, allIvs: Incident[]): Quality => {
    const tol = (payload.interval_seconds * 1000) / 2; // ±½ interval grid tolerance
    // Only score incidents that overlap the active (possibly trimmed) series — an
    // incident outside the loaded window can never be caught, so counting it would
    // wrongly drag recall down. The chart still LISTS every marked incident.
    const ts = series.timestamps;
    const lo = (ts.length ? ts[0] : 0) - tol;
    const hi = (ts.length ? ts[ts.length - 1] : 0) + tol;
    const ivs = allIvs.filter((iv) => iv.end >= lo && iv.start <= hi);
    // An alert is "for" an incident when its anomaly STREAK overlaps the span (not
    // just the fire point, which sits consecutive-1 intervals into the streak and
    // would miss a narrow incident — the recall-undercount bug).
    const overlaps = (sp: [number, number], iv: Incident): boolean =>
      sp[1] >= iv.start - tol && sp[0] <= iv.end + tol;
    let correct = 0;
    for (const sp of spans) if (ivs.some((iv) => overlaps(sp, iv))) correct++;
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
    };
  };
  const pctOrDash = (v: number): string => (Number.isFinite(v) ? `${Math.round(v * 100)}%` : '—');
  const metricChip = (value: string, label: string, sub: string, color: string): string =>
    `<span class="dtk-m-chip"><span class="dtk-m-dot" style="background:${color}"></span>` +
    `<span class="dtk-m-v">${value}</span><span class="dtk-m-l">${label}</span>` +
    (sub ? `<span class="dtk-m-sub">${sub}</span>` : '') +
    `</span>`;
  function renderMetrics(): void {
    const q = computeQuality(lastFireSpans, incidents);
    // Without any marked incidents there is no ground truth, so catch-rate and
    // false-alert rate are undefined (not "100% false") — prompt to mark some.
    const haveTruth = q.realIncidents > 0;
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
    metricsBar.innerHTML =
      metricChip(String(q.realIncidents), 'real incidents', '', 'var(--c)') +
      metricChip(
        haveTruth ? `${q.caught}/${q.realIncidents}` : '—',
        'caught',
        haveTruth ? `recall ${pctOrDash(q.recall)}` : 'mark incidents',
        'var(--green)',
      ) +
      metricChip(String(q.totalAlerts), 'alerts', '', 'var(--c)') +
      metricChip(haveTruth ? String(q.falseAlerts) : '—', 'false alerts', falseSub, 'var(--anom)');
  }

  // Forward declaration so the detector chart's onViewChange can sync the labeler.
  let labelerChart: ChartHandle;

  const chart: ChartHandle = createChart(canvas, {
    navigable: true,
    // The labeler chart beneath provides the shared navigator strip; this one
    // keeps wheel-zoom + drag-pan but hides its own strip so the two align.
    showNavigator: false,
    // Fit the y-axis to the data, not the band — so turning the Threshold slider
    // visibly widens/narrows the corridor relative to the metric instead of the
    // axis rescaling in lockstep and making the change look like a no-op.
    yFit: 'data',
    onViewChange: (a, b): void => labelerChart.setViewWindow(a, b),
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
  });

  // The synced labeler: raw series + editable incident spans (no band/dots).
  const LABELER_PARAMS: DetectorParams = {
    type: 'mad',
    threshold: 3,
    windowSize: 100,
    minSamples: 30,
    inputType: 'values',
    smoothing: 'none',
    smoothingAlpha: 0.3,
    smoothingWindow: 10,
    windowWeights: 'none',
    halfLife: null,
    detrend: 'none',
    seasonalityComponents: null,
    minSamplesPerGroup: 10,
    consecutiveAnomalies: 1,
  };
  // Filled once the capture toolbars are built (the chart pushes preview state here
  // on every hover / window paint / knob change / lasso draw).
  let updateThresholdUI: (info: ThresholdInfo) => void = () => {};
  let updateLassoUI: (info: LassoInfo) => void = () => {};
  labelerChart = createChart(labCanvas, {
    navigable: true,
    labeling: true,
    yFit: 'data',
    onViewChange: (a, b): void => chart.setViewWindow(a, b),
    onIncidentsChange: (): void => {
      // The chart mutates `incidents` in place (shared ref); reflect it.
      refreshIncidentList();
      renderMetrics();
      chart.setIncidents(incidents); // live read-only shading on the detector chart
    },
    onThresholdChange: (info): void => updateThresholdUI(info),
    onLassoChange: (info): void => updateLassoUI(info),
  });
  labelerChart.setIncidents(incidents);
  if (seedCaptureWin) labelerChart.setCaptureWindow(seedCaptureWin);
  // The labeler mirrors the detector's anomaly dots (so the lasso has a cloud to
  // grab) — fed the latest scored array once it matches the active series length
  // (after a trim, the next recompute refills it a frame later). It draws the raw
  // line + dots + alert ticks, never the band (that's the detector chart's job).
  const renderLabeler = (): void => {
    const sc = lastScored.length === series.timestamps.length ? lastScored : [];
    const params = lastParams ?? LABELER_PARAMS;
    labelerChart.render({ series, scored: sc, params, alerts: lastAlerts, incidents });
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
  main.insertBefore(thWrap, labChartWrap);

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
    labelerChart.setThresholdMode(on);
    if (on && lassoActive) setLassoActive(false); // mutually exclusive tools
  };
  // Lasso mode: commits incidents on mouseup via onIncidentsChange, so the bar is
  // just a live readout + Done. The chart enforces threshold/lasso exclusivity too.
  const setLassoActive = (on: boolean): void => {
    lassoActive = on;
    lassoToggle.classList.toggle('on', on);
    lassoBar.style.display = on ? 'flex' : 'none';
    labelerChart.setLassoMode(on);
    if (on && thActive) setThActive(false);
  };
  thToggle.onclick = (): void => setThActive(!thActive);
  thDone.onclick = (): void => setThActive(false);
  lassoToggle.onclick = (): void => setLassoActive(!lassoActive);
  lassoDone.onclick = (): void => setLassoActive(false);
  thDirSel.onchange = (): void =>
    labelerChart.setThresholdDirection(thDirSel.value as 'above' | 'below');
  thValInput.oninput = (): void => {
    const s = thValInput.value.trim();
    thTyping = true;
    labelerChart.setThresholdValue(s !== '' && !isNaN(Number(s)) ? Number(s) : null);
    thTyping = false;
  };
  thGapInput.oninput = (): void => labelerChart.setThresholdGap(Number(thGapInput.value) || 0);
  thWinReset.onclick = (): void => labelerChart.clearCaptureWindow();
  thAdd.onclick = (): void => {
    labelerChart.applyThreshold(); // commits spans → incidents (fires onIncidentsChange)
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
  const worker = new Worker(
    URL.createObjectURL(new Blob([__DTK_WORKER_SRC__], { type: 'text/javascript' })),
  );
  worker.postMessage({ type: 'series', series });
  let reqId = 0;
  let lastParams: DetectorParams | null = null;
  worker.onmessage = (e: MessageEvent): void => {
    const res = e.data as WorkerResult;
    if (res.type !== 'result' || res.id !== reqId || !lastParams) return; // ignore stale
    spinner.classList.remove('on');
    const params = lastParams;
    const fireTs = res.fires.map((i) => series.timestamps[i]);
    const alerts: ChartAlert[] = fireTs.map((t) => ({ t, kind: 'anomaly' }));
    chart.render({ series, scored: res.scored, params, alerts, incidents });
    lastScored = res.scored;
    lastFireTs = fireTs;
    lastFireSpans = res.fireSpans;
    lastAlerts = alerts;
    renderLabeler(); // refresh the labeler's mirrored anomaly dots + alert ticks
    renderMetrics();
    statBar.textContent =
      `${res.flagged} flagged · ${res.fires.length} alert${res.fires.length === 1 ? '' : 's'} · ` +
      `warm-up ${res.eff} pts`;
    updateSeasonWarn(params);
    configEcho.textContent = configText(params, consecutive);
  };
  worker.onerror = (): void => {
    spinner.classList.remove('on');
    statBar.textContent = 'recompute failed — see the browser console';
  };
  const runRecompute = (): void => {
    lastParams = readParams();
    reqId += 1;
    spinner.classList.add('on');
    worker.postMessage({ type: 'run', id: reqId, params: lastParams });
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
    renderLabeler(); // keep the labeler chart on the same active series
    recompute();
  }
  let trimDebounce = 0;
  trimInput.oninput = (): void => {
    const count = Number(trimInput.value);
    setTrimEcho(count);
    if (trimDebounce) window.clearTimeout(trimDebounce);
    trimDebounce = window.setTimeout(() => setActivePoints(count), 200);
  };
  let debounce = 0;
  const recompute = (): void => {
    if (debounce) window.clearTimeout(debounce);
    debounce = window.setTimeout(runRecompute, 130);
  };

  // ---- controls -------------------------------------------------------------
  const detectorCtl = segControl(
    'Detector',
    [
      { label: 'MAD', value: 'mad' },
      { label: 'Z-Score', value: 'zscore' },
      { label: 'IQR', value: 'iqr' },
      { label: 'Manual', value: 'manual_bounds' },
    ],
    seed.type,
    (v) => {
      // reset threshold to the new type's default for a sane starting point
      thresholdCtl_setDefault(THRESHOLD_DEFAULT[v as DetectorType] ?? 3.0);
      refreshVisibility();
      recompute();
    },
    'The statistic for the band: MAD (robust median, default), Z-Score (mean/std) or IQR ' +
      '(quartiles) — all windowed — or Manual (fixed lower/upper thresholds, no window/history).',
  );
  controls.appendChild(detectorCtl.row);

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
    recompute,
  );
  controls.appendChild(lowerBoundCtl.row);

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
    recompute,
  );
  controls.appendChild(upperBoundCtl.row);

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
    recompute,
  );
  controls.appendChild(thresholdCtl.row);
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
    recompute,
  );
  controls.appendChild(windowCtl.row);

  const weightsCtl = segControl(
    'Recency weighting',
    [
      { label: 'none', value: 'none' },
      { label: 'exponential', value: 'exponential' },
      { label: 'linear', value: 'linear' },
    ],
    seed.windowWeights,
    () => {
      refreshVisibility();
      recompute();
    },
    'Weight recent points in the window more heavily: none (flat), exponential (half-life ' +
      'decay) or linear. Helps the baseline track a drifting level.',
  );
  controls.appendChild(weightsCtl.row);

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
    recompute,
  );
  const halfLifeRow = halfLifeCtl.row;
  halfLifeRow.style.display = seed.windowWeights === 'exponential' ? '' : 'none';
  controls.appendChild(halfLifeRow);

  const detrendCtl = segControl(
    'Detrend',
    [
      { label: 'none', value: 'none' },
      { label: 'linear', value: 'linear' },
    ],
    seed.detrend,
    recompute,
    'Remove a robust linear trend from each window before computing the band, so a steadily ' +
      'rising/falling metric is not flagged for the trend itself.',
  );
  controls.appendChild(detrendCtl.row);

  const smoothingCtl = segControl(
    'Smoothing',
    [
      { label: 'none', value: 'none' },
      { label: 'EMA', value: 'ema' },
      { label: 'SMA', value: 'sma' },
    ],
    seed.smoothing,
    recompute,
    'Smooth the series before detection (EMA or SMA) so single-point jitter does not flag. ' +
      'The detector judges the smoothed line; the raw values show as a faint ghost.',
  );
  controls.appendChild(smoothingCtl.row);

  // seasonality (only when the metric has seasonality columns).
  // Each column is assigned a group: Off, or G1/G2/G3… Columns sharing a group
  // are conjoined into ONE seasonal key (e.g. dow×hour); separate groups apply
  // independent corrections — the full string[][] grouping the detector supports.
  let seasonalityRow: HTMLElement | null = null;
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
    const groupCount = Math.min(cols.length, 6);
    const opts: SegSpec[] = [{ label: '—', value: '0' }];
    for (let gi = 1; gi <= groupCount; gi++) opts.push({ label: `G${gi}`, value: String(gi) });
    cols.forEach((col) => {
      const crow = el('div', 'dtk-season-row');
      crow.appendChild(el('span', 'dtk-season-col', col));
      const seg = el('div', 'dtk-seg dtk-season-seg');
      const buttons: HTMLButtonElement[] = [];
      const cur = (): number => colGroup.get(col) ?? 0;
      const paint = (): void =>
        buttons.forEach((b) => b.classList.toggle('on', Number(b.dataset.v) === cur()));
      opts.forEach((opt) => {
        const b = el('button', 'dtk-seg-btn', opt.label);
        b.type = 'button';
        b.dataset.v = opt.value;
        b.title = opt.value === '0' ? `ignore ${col}` : `put ${col} in group ${opt.value}`;
        b.onclick = (): void => {
          colGroup.set(col, Number(opt.value));
          paint();
          recompute();
        };
        buttons.push(b);
        seg.appendChild(b);
      });
      paint();
      crow.appendChild(seg);
      row.appendChild(crow);
    });
    controls.appendChild(row);
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
  controls.appendChild(directionCtl.row);

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
  controls.appendChild(consecutiveCtl.row);

  // y = 0 reference line — applies to BOTH synced charts at once.
  const zeroRow = el('div', 'dtk-ctl');
  const zeroLab = el('label', 'dtk-check');
  const zeroBox = el('input');
  zeroBox.type = 'checkbox';
  zeroBox.onchange = (): void => {
    chart.setZeroLine(zeroBox.checked);
    labelerChart.setZeroLine(zeroBox.checked);
  };
  zeroLab.title =
    'Draw a horizontal line at y = 0 and include zero in the scale — for real-valued metrics ' +
    'best read relative to zero.';
  zeroLab.appendChild(zeroBox);
  zeroLab.appendChild(document.createTextNode(' Show y = 0 line'));
  zeroRow.appendChild(zeroLab);
  controls.appendChild(zeroRow);

  // Marked-incidents list (label edit + focus + delete; marking happens on the
  // lower chart). Shares the SAME `incidents` array the labeler chart edits.
  const incidentsWrap = el('div', 'dtk-ctl dtk-incidents');
  incidentsWrap.appendChild(
    ctlLabel(
      'Marked incidents',
      'The real incidents marked on the lower chart. Edit a label, focus to zoom both charts to ' +
        'it, or remove it. Save the set below to incidents/<metric>/ — the same store dtk autotune reads.',
    ),
  );
  const incidentsList = el('div', 'dtk-inc-list');
  incidentsWrap.appendChild(incidentsList);
  controls.appendChild(incidentsWrap);

  function focusIncident(iv: Incident): void {
    const pad = Math.max((iv.end - iv.start) * 0.5, payload.interval_seconds * 1000 * 5);
    chart.setViewWindow(iv.start - pad, iv.end + pad);
    labelerChart.setViewWindow(iv.start - pad, iv.end + pad);
  }
  function deleteIncident(iv: Incident): void {
    const k = incidents.indexOf(iv);
    if (k >= 0) incidents.splice(k, 1);
    labelerChart.setIncidents(incidents);
    chart.setIncidents(incidents);
    refreshIncidentList();
    renderMetrics();
  }
  function refreshIncidentList(): void {
    incidentsList.innerHTML = '';
    const sorted = [...incidents].sort((a, b) => a.start - b.start);
    if (!sorted.length) {
      incidentsList.appendChild(
        el('div', 'dtk-inc-empty', 'None yet — drag across the lower chart to mark one.'),
      );
      return;
    }
    for (const iv of sorted) {
      const row = el('div', 'dtk-inc-row');
      row.appendChild(el('span', 'dtk-inc-span', `${fmtTs(iv.start)} → ${fmtTs(iv.end)}`));
      row.appendChild(el('span', 'dtk-inc-dur', fmtDur(Math.max(0, iv.end - iv.start))));
      const lbl = el('input', 'dtk-inc-label');
      lbl.type = 'text';
      lbl.value = iv.label || '';
      lbl.placeholder = 'label (optional)';
      lbl.oninput = (): void => {
        iv.label = lbl.value;
      };
      row.appendChild(lbl);
      const focus = el('button', 'dtk-inc-btn', 'focus');
      focus.type = 'button';
      focus.onclick = (): void => focusIncident(iv);
      row.appendChild(focus);
      const del = el('button', 'dtk-inc-btn dtk-inc-del', '✕');
      del.type = 'button';
      del.title = 'remove this incident';
      del.onclick = (): void => deleteIncident(iv);
      row.appendChild(del);
      incidentsList.appendChild(row);
    }
  }

  // Show only the controls relevant to the selected detector: the windowed knobs
  // for MAD/Z-Score/IQR, or the bound sliders for manual_bounds. Direction +
  // consecutive (alert-layer) are always shown.
  const windowedRows = [
    thresholdCtl.row,
    windowCtl.row,
    weightsCtl.row,
    detrendCtl.row,
    smoothingCtl.row,
  ];
  if (seasonalityRow) windowedRows.push(seasonalityRow);
  function refreshVisibility(): void {
    const manual = (detectorCtl.get() as DetectorType) === 'manual_bounds';
    for (const row of windowedRows) row.style.display = manual ? 'none' : '';
    lowerBoundCtl.row.style.display = manual ? '' : 'none';
    upperBoundCtl.row.style.display = manual ? '' : 'none';
    // half-life only when windowed AND exponential weighting.
    halfLifeRow.style.display = !manual && weightsCtl.get() === 'exponential' ? '' : 'none';
  }
  refreshVisibility();

  // ---- stat bar + effective config + apply ----------------------------------
  const statBar = el('div', 'dtk-tune-stat');
  main.appendChild(statBar);

  const cfgWrap = el('div', 'dtk-tune-cfg');
  cfgWrap.appendChild(el('span', 'dtk-tune-cfg-k', '// effective config'));
  const configEcho = el('code', 'dtk-tune-cfg-v');
  cfgWrap.appendChild(configEcho);
  main.appendChild(cfgWrap);

  if (payload.save_url) {
    const applyWrap = el('div', 'dtk-tune-apply');
    const btn = el('button', 'dtk-apply-btn', 'Apply to metric');
    btn.type = 'button';
    btn.title =
      'Write this detector config back into the metric YAML (the previous version is archived ' +
      'under metrics/.history/). Trimming the sample does not change what is written.';
    const msg = el('span', 'dtk-apply-msg');
    btn.onclick = (): void => {
      const params = readParams();
      btn.disabled = true;
      msg.className = 'dtk-apply-msg info';
      msg.textContent = 'Applying…';
      fetch(payload.save_url as string, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          detector: { type: params.type, params: applyParams(params) },
          consecutive_anomalies: consecutive,
        }),
      })
        .then((r) =>
          r.ok
            ? r.json()
            : r.text().then((t) => {
                throw new Error(t || `HTTP ${r.status}`);
              }),
        )
        .then((res: { saved?: string; archived?: string }) => {
          msg.className = 'dtk-apply-msg ok';
          msg.textContent = `Applied → ${res.saved ?? 'metric'} (previous archived). You can close this tab.`;
        })
        .catch((e: Error) => {
          btn.disabled = false;
          msg.className = 'dtk-apply-msg err';
          msg.textContent = `Apply failed: ${e.message}`;
        });
    };
    applyWrap.appendChild(btn);
    applyWrap.appendChild(msg);
    main.appendChild(applyWrap);
  } else {
    main.appendChild(
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
    const sorted = [...incidents].sort((a, b) => a.start - b.start);
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
    const cap = labelerChart.getCaptureWindow();
    if (cap) {
      lines.push('capture_windows:');
      lines.push(`  - {start: "${fmtUtc(cap.start)}", end: "${fmtUtc(cap.end)}"}`);
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
  main.appendChild(labelsWrap);

  // ---- first paint + resize -------------------------------------------------
  renderLabeler();
  refreshIncidentList();
  runRecompute();
  renderMetrics();
  let rafResize = 0;
  window.addEventListener('resize', () => {
    if (rafResize) cancelAnimationFrame(rafResize);
    rafResize = requestAnimationFrame(() => {
      chart.resize();
      labelerChart.resize();
    });
  });
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
.dtk-tune-root{max-width:1200px;margin:0 auto;padding:24px 20px 56px;font-family:var(--sans);color:var(--ink);}
.dtk-tune-titlerow{display:flex;align-items:center;gap:12px;}
.dtk-tune-title{font-size:24px;margin:0;font-weight:700;}
.dtk-tune-badge{font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.06em;
  color:#fff;background:var(--c);border-radius:999px;padding:3px 10px;}
.dtk-tune-sub{color:var(--muted);font-size:13px;margin-top:4px;font-family:var(--mono);}
.dtk-tune-desc{color:var(--muted);font-size:13px;margin-top:8px;white-space:pre-wrap;}
.dtk-tune-grid{display:grid;grid-template-columns:280px 1fr;gap:24px;margin-top:20px;align-items:start;}
@media(max-width:820px){.dtk-tune-grid{grid-template-columns:1fr;}}
.dtk-tune-controls{display:flex;flex-direction:column;gap:16px;background:var(--surface);
  border:1px solid var(--border);border-radius:12px;padding:16px;}
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
.dtk-tune-main{display:flex;flex-direction:column;gap:10px;min-width:0;}
.dtk-tune-chart{position:relative;width:100%;height:470px;background:var(--surface);
  border:1px solid var(--border);border-radius:12px;overflow:hidden;}
.dtk-tune-chart canvas{width:100%;height:100%;display:block;}
.dtk-tune-readout{font-family:var(--mono);font-size:12px;color:var(--muted);min-height:18px;}
.dtk-tune-stat{font-family:var(--mono);font-size:12px;color:var(--ink);}
.dtk-tune-warn{font-family:var(--mono);font-size:12px;line-height:1.5;color:var(--c7);
  background:rgba(240,173,78,0.13);border:1px solid rgba(240,173,78,0.5);border-radius:8px;padding:8px 11px;}
.dtk-tune-cfg{background:var(--ink);color:#c9c2b4;border-radius:8px;padding:10px 12px;font-family:var(--mono);
  font-size:12px;overflow-x:auto;}
.dtk-tune-cfg-k{color:var(--faint);display:block;margin-bottom:4px;}
.dtk-tune-cfg-v{color:#e6e0d4;white-space:pre-wrap;word-break:break-word;}
.dtk-tune-apply{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:6px;}
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
.dtk-tune-legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--muted);padding:2px 2px 0;}
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
.dtk-leg-txt{white-space:nowrap;}
.dtk-season-row{display:flex;align-items:center;justify-content:space-between;gap:8px;}
.dtk-season-col{font-family:var(--mono);font-size:11.5px;color:var(--muted);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.dtk-season-seg{flex:0 0 auto;padding:2px;}
.dtk-season-seg .dtk-seg-btn{flex:0 0 auto;padding:3px 7px;font-family:var(--mono);font-size:11px;}
.dtk-tune-metrics{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0 2px;}
.dtk-m-chip{display:inline-flex;align-items:center;gap:7px;padding:7px 13px;background:var(--surface);
  border:1px solid var(--border);border-radius:10px;font-size:13px;}
.dtk-m-dot{width:9px;height:9px;border-radius:50%;flex:0 0 auto;}
.dtk-m-v{font-family:var(--mono);font-weight:700;font-size:15px;color:var(--ink);}
.dtk-m-l{color:var(--faint);font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.05em;}
.dtk-m-sub{color:var(--muted);font-family:var(--mono);font-size:11.5px;}
.dtk-tune-labhead{display:flex;align-items:baseline;justify-content:space-between;gap:10px;
  margin-top:4px;flex-wrap:wrap;}
.dtk-tune-labhint{font-family:var(--mono);font-size:11px;color:var(--faint);}
.dtk-tune-labchart{height:240px;}
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
.dtk-setname{background:var(--surface);color:var(--ink);border:1px solid var(--border);border-radius:8px;
  padding:9px 11px;font-family:var(--sans);font-size:13px;min-width:180px;}
.dtk-setname::placeholder{color:var(--faint);}
.dtk-setname:focus{outline:none;border-color:var(--c);}
.dtk-labels-btn{background:var(--surface);color:var(--ink);border:1px solid var(--border);}
.dtk-labels-btn:hover{background:var(--paper);border-color:var(--c);color:var(--c7);}
`;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);
}

// Expose the global the inlined HTML bootstrap calls (mirrors __DTK_REPORT__).
(window as unknown as { __DTK_TUNE__: { render: typeof render } }).__DTK_TUNE__ = { render };

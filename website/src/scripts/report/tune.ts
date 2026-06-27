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
  /** seeded per-alert review verdicts (span + 'valid'/'false') from the saved file. */
  alert_reviews?: Array<{ start: string; end: string; verdict: string }>;
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
  // Validated streak spans within the active window — virtual incidents for scoring.
  const validatedSpans = (): Incident[] =>
    lastFireSpans
      .filter(([s, e]) => reviewFor(s, e) === 'valid')
      .map(([s, e]) => ({ start: s, end: e, label: 'alert ✓' }));
  // Build the alert markers with their review-verdict color (red / green / slate).
  const buildAlerts = (): ChartAlert[] =>
    lastFireTs.map((t, i) => {
      const sp = lastFireSpans[i] ?? [t, t];
      const v = reviewFor(sp[0], sp[1]);
      return { t, kind: v === 'valid' ? 'anomaly-validated' : v === 'false' ? 'anomaly-false' : 'anomaly' };
    });

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
  // Stage footer (hover readout + stat line + season warning + legend) — created
  // now, filled below; attached right under the chart.
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
  // Per-mode control groups — only one is shown at a time (driven by setUiMode).
  const tuneGroup = el('div', 'dtk-rail-group');
  const reviewGroup = el('div', 'dtk-rail-group');
  const labelGroup = el('div', 'dtk-rail-group');
  reviewGroup.style.display = 'none';
  labelGroup.style.display = 'none';
  controls.append(tuneGroup, reviewGroup, labelGroup);
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

  // ---- trim slider (top of the Tune panel) ---------------------------------
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
  tuneGroup.appendChild(trimWrap);

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

  // ---- mode switch (Tune / Review / Label) ----------------------------------
  // One chart, three jobs: the mode picks which layers lead and which interactions
  // are armed. 'tune' steers the band, 'review' confirms the fired alerts, 'label'
  // marks incidents. setUiMode (defined once the tool bars exist) drives the chart
  // + reveals the matching tools.
  const modeRow = el('div', 'dtk-tune-modes');
  const modeBtns: Partial<Record<ChartMode, HTMLButtonElement>> = {};
  const MODES: Array<{ v: ChartMode; label: string; hint: string }> = [
    { v: 'tune', label: 'Tune', hint: 'Steer the band — the confidence corridor leads; incidents recede to read-only context. Hover a point for its window.' },
    { v: 'review', label: 'Review alerts', hint: 'Confirm the fired alerts — click a marker to cycle un-reviewed → valid (green) → false (slate). The band ghosts so the alerts lead.' },
    { v: 'label', label: 'Label incidents', hint: 'Mark real incidents — drag a span, lasso the anomaly cloud, or threshold-capture. The band hides so incidents lead.' },
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
  legItem('alert', 'alert', 'A fired alert, not yet reviewed — enough consecutive anomalies to meet the rule.');
  legItem('alert-ok', 'valid alert', 'An alert you confirmed is real (click a marker in Review mode). Counts toward recall.');
  legItem('alert-no', 'false alarm', 'An alert you marked a false positive. Stays in the false-alert rate.');
  stageFoot.appendChild(legend);

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
  const computeQuality = (spans: Array<[number, number]>, manualIvs: Incident[]): Quality => {
    const tol = spanTol(); // ±½ interval grid tolerance
    // Only score incidents that overlap the active (possibly trimmed) series — an
    // incident outside the loaded window can never be caught, so counting it would
    // wrongly drag recall down. The chart still LISTS every marked incident. The
    // ground-truth set is the marked incidents PLUS the validated-alert spans (a
    // confirmed alert is the user asserting "a real incident happened here").
    const ts = series.timestamps;
    const lo = (ts.length ? ts[0] : 0) - tol;
    const hi = (ts.length ? ts[ts.length - 1] : 0) + tol;
    const ivs = [...manualIvs, ...validatedSpans()].filter((iv) => iv.end >= lo && iv.start <= hi);
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
    // Review progress: how many fired alerts you've confirmed/dismissed, and how
    // many you confirmed valid (the green markers).
    const reviewSub =
      q.totalAlerts === 0
        ? 'no alerts'
        : `${q.validated} valid${q.totalAlerts > q.reviewed ? ` · ${q.totalAlerts - q.reviewed} left` : ' · all reviewed'}`;
    metricsBar.innerHTML =
      metricChip(String(q.realIncidents), 'real incidents', '', 'var(--c)') +
      metricChip(
        haveTruth ? `${q.caught}/${q.realIncidents}` : '—',
        'caught',
        haveTruth ? `recall ${pctOrDash(q.recall)}` : 'mark or confirm',
        'var(--green)',
      ) +
      metricChip(String(q.totalAlerts), 'alerts', '', 'var(--c)') +
      metricChip(haveTruth ? String(q.falseAlerts) : '—', 'false alerts', falseSub, 'var(--anom)') +
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
    onIncidentsChange: (): void => {
      // The chart mutates `incidents` in place (shared ref); reflect it.
      refreshIncidentList();
      renderMetrics();
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
  const RAIL_TITLES: Record<ChartMode, string> = {
    tune: 'Tune · controls',
    review: 'Review · verdicts',
    label: 'Label · incidents',
  };
  function setUiMode(md: ChartMode): void {
    chart.setMode(md);
    (Object.keys(modeBtns) as ChartMode[]).forEach((v) =>
      modeBtns[v]?.classList.toggle('on', v === md),
    );
    if (md !== 'label') {
      setThActive(false);
      setLassoActive(false);
    }
    // Swap the rail to the current mode's panel (and rename its header): detector
    // knobs + effective config + Apply in Tune, the verdict actions in Review, the
    // capture tools + incident list + Save in Label — never all the controls at once.
    tuneGroup.style.display = md === 'tune' ? '' : 'none';
    reviewGroup.style.display = md === 'review' ? '' : 'none';
    labelGroup.style.display = md === 'label' ? '' : 'none';
    railFoot.style.display = md === 'tune' ? '' : 'none';
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
    recompute,
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
    recompute,
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
    recompute,
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
    recompute,
  );
  tuneGroup.appendChild(windowCtl.row);

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
    recompute,
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
    recompute,
    'Remove a robust linear trend from each window before computing the band, so a steadily ' +
      'rising/falling metric is not flagged for the trend itself.',
  );
  tuneGroup.appendChild(detrendCtl.row);

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
  tuneGroup.appendChild(smoothingCtl.row);

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
    tuneGroup.appendChild(row);
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
  tuneGroup.appendChild(directionCtl.row);

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
  tuneGroup.appendChild(consecutiveCtl.row);

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
  tuneGroup.appendChild(zeroRow);

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
    chart.setIncidents(incidents);
    refreshIncidentList();
    renderMetrics();
  }
  function refreshIncidentList(): void {
    incidentsList.innerHTML = '';
    const sorted = [...incidents].sort((a, b) => a.start - b.start);
    if (!sorted.length) {
      incidentsList.appendChild(
        el('div', 'dtk-inc-empty', 'None yet — switch to Label mode and drag across the chart, or confirm alerts in Review mode.'),
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
  stageFoot.appendChild(statBar);

  const cfgWrap = el('div', 'dtk-tune-cfg');
  cfgWrap.appendChild(el('span', 'dtk-tune-cfg-k', '// effective config'));
  const configEcho = el('code', 'dtk-tune-cfg-v');
  cfgWrap.appendChild(configEcho);
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
    // Manual incidents PLUS a derived incident for each confirmed (valid) alert, so
    // confirming alerts feeds the next supervised `dtk autotune` too. De-dup by span.
    const validIvs: Incident[] = reviews
      .filter((r) => r.verdict === 'valid')
      .map((r) => ({ start: r.start, end: r.end, label: 'alert (confirmed)' }));
    const seen = new Set<string>();
    const sorted = [...incidents, ...validIvs]
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
.dtk-tune-controls{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;padding:14px;}
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
.dtk-tune-cfg{background:var(--ink);color:#c9c2b4;border-radius:8px;padding:10px 12px;font-family:var(--mono);
  font-size:12px;overflow-x:auto;}
.dtk-tune-cfg-k{color:var(--faint);display:block;margin-bottom:4px;}
.dtk-tune-cfg-v{color:#e6e0d4;white-space:pre-wrap;word-break:break-word;}
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
.dtk-tune-modes{display:inline-flex;gap:4px;background:var(--ink);border-radius:9px;padding:4px;margin:0;flex:0 0 auto;}
.dtk-mode-btn{border:0;background:transparent;color:#c9c2b4;font-family:var(--sans);font-size:13px;font-weight:600;
  padding:7px 16px;border-radius:6px;cursor:pointer;transition:background .12s,color .12s;}
.dtk-mode-btn:hover{color:#fff;}
.dtk-mode-btn.on{background:var(--c);color:#fff;}
.dtk-tune-reviewbar{align-items:center;}
.dtk-tune-reviewbar .dtk-apply-btn{background:var(--green);}
.dtk-tune-reviewbar .dtk-apply-btn:hover{background:#27815d;}
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

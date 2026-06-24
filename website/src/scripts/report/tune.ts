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
  ChartAlert,
  ChartHandle,
  Detrend,
  DetectorParams,
  DetectorType,
  ScoredPoint,
  Series,
  Smoothing,
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
  eff: number;
  flagged: number;
}

// ---------------------------------------------------------------------------
// Payload contract — kept in lockstep with detectkit/tuning/payload.py
// ---------------------------------------------------------------------------

/** The detector seed (camelCase DetectorParams minus the alert-only knob). */
type DetectorSeed = Omit<DetectorParams, 'consecutiveAnomalies'>;

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
  /** localhost POST endpoint for Apply; null = static read-only preview. */
  save_url: string | null;
}

// Per-type interval-width default (mirrors the detector classes / the demo).
const THRESHOLD_DEFAULT: Record<DetectorType, number> = { mad: 3.0, zscore: 3.0, iqr: 1.5 };
const MIN_SAMPLES_PER_GROUP_DEFAULT: Record<DetectorType, number> = { mad: 10, zscore: 3, iqr: 4 };

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
  // ---- mutable parameter state, seeded from the metric's current config -----
  const seed = payload.detector;
  let consecutive = payload.consecutive_anomalies;
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

  const chart: ChartHandle = createChart(canvas, {
    navigable: true,
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
    const alerts: ChartAlert[] = res.fires.map((i) => ({
      t: series.timestamps[i],
      kind: 'anomaly',
    }));
    chart.render({ series, scored: res.scored, params, alerts });
    statBar.textContent =
      `${res.flagged} flagged · ${res.fires.length} alert${res.fires.length === 1 ? '' : 's'} · ` +
      `warm-up ${res.eff} pts`;
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
    ],
    seed.type,
    (v) => {
      // reset threshold to the new type's default for a sane starting point
      thresholdCtl_setDefault(THRESHOLD_DEFAULT[v as DetectorType] ?? 3.0);
      recompute();
    },
    'The statistic used for the center/spread of the band: MAD (robust median, ' +
      'default), Z-Score (mean/std) or IQR (quartiles). All share the same windowing.',
  );
  controls.appendChild(detectorCtl.row);

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

  // Cap the window at half the shown points so there's always a scored region.
  const windowMax = Math.max(50, Math.min(2000, Math.floor(n / 2)));
  const windowCtl = rangeControl(
    'Window size (points)',
    {
      min: 10,
      max: windowMax,
      step: 5,
      value: Math.min(seed.windowSize, windowMax),
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
    (v) => {
      halfLifeRow.style.display = v === 'exponential' ? '' : 'none';
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
  if (payload.seasonality_columns.length) {
    const cols = payload.seasonality_columns;
    const row = el('div', 'dtk-ctl');
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

  // ---- first paint + resize -------------------------------------------------
  runRecompute();
  let rafResize = 0;
  window.addEventListener('resize', () => {
    if (rafResize) cancelAnimationFrame(rafResize);
    rafResize = requestAnimationFrame(() => chart.resize());
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
`;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);
}

// Expose the global the inlined HTML bootstrap calls (mirrors __DTK_REPORT__).
(window as unknown as { __DTK_TUNE__: { render: typeof render } }).__DTK_TUNE__ = { render };

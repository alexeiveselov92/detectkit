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
import { effectiveStartIndex, runDetector } from '../demo/detector';
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

/** A segmented button group. Returns the row element + a getter/setter. */
function segControl(
  label: string,
  options: SegSpec[],
  initial: string,
  onChange: (v: string) => void,
): { row: HTMLElement; get: () => string; set: (v: string) => void } {
  const row = el('div', 'dtk-ctl');
  row.appendChild(el('label', 'dtk-ctl-label', label));
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
  opts: { min: number; max: number; step: number; value: number; fmt?: (v: number) => string },
  onChange: (v: number) => void,
): { row: HTMLElement; get: () => number; setMax: (m: number) => void } {
  const row = el('div', 'dtk-ctl');
  const head = el('div', 'dtk-ctl-head');
  const lab = el('label', 'dtk-ctl-label', label);
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
// Alert-fire timeline (mirrors main.ts computeScorecard's alert-run logic)
// ---------------------------------------------------------------------------

/** One fire index per maximal run of grid-adjacent flagged points reaching `consecutive`. */
function alertFireIndexes(scored: ScoredPoint[], intervalMs: number, consecutive: number): number[] {
  const fires: number[] = [];
  let runLen = 0;
  for (let i = 0; i < scored.length; i++) {
    const flagged = scored[i].scored && scored[i].isAnomaly;
    if (!flagged) {
      runLen = 0;
      continue;
    }
    const prevFlagged = i > 0 && scored[i - 1].scored && scored[i - 1].isAnomaly;
    const adjacent = i > 0 && scored[i].timestamp - scored[i - 1].timestamp === intervalMs;
    runLen = prevFlagged && adjacent ? runLen + 1 : 1;
    if (runLen === consecutive) fires.push(i);
  }
  return fires;
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
  const series: Series = {
    timestamps: payload.points.map((p) => p.t),
    values: payload.points.map((p) => (p.v == null ? NaN : p.v)),
    intervalSeconds: payload.interval_seconds,
    truthAnomaly: new Array(n).fill(false),
    seasonalityData: payload.seasonality_columns.length ? payload.seasonality : undefined,
    seasonalityColumns: payload.seasonality_columns.length
      ? payload.seasonality_columns
      : undefined,
  };
  const intervalMs = payload.interval_seconds * 1000;

  // ---- mutable parameter state, seeded from the metric's current config -----
  const seed = payload.detector;
  let consecutive = payload.consecutive_anomalies;
  // seasonality: selected columns + whether to conjoin them into one group
  const seedGroups = seed.seasonalityComponents ?? [];
  const selectedCols = new Set<string>(seedGroups.flat());
  let conjoin = seedGroups.length === 1 && seedGroups[0].length > 1;

  const buildSeasonality = (): string[][] | null => {
    const cols = payload.seasonality_columns.filter((c) => selectedCols.has(c));
    if (!cols.length) return null;
    return conjoin ? [cols] : cols.map((c) => [c]);
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

  // chart
  const chartWrap = el('div', 'dtk-tune-chart');
  const canvas = el('canvas');
  chartWrap.appendChild(canvas);
  main.appendChild(chartWrap);
  const readout = el('div', 'dtk-tune-readout');
  main.appendChild(readout);

  const chart: ChartHandle = createChart(canvas, {
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

  // ---- recompute (rAF-throttled) --------------------------------------------
  let queued = false;
  const recompute = (): void => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      const params = readParams();
      const scored = runDetector(series, params);
      const fires = alertFireIndexes(scored, intervalMs, params.consecutiveAnomalies);
      const alerts: ChartAlert[] = fires.map((i) => ({ t: series.timestamps[i], kind: 'anomaly' }));
      chart.render({ series, scored, params, alerts });
      const eff = effectiveStartIndex(series, params);
      const flagged = scored.filter((s) => s.scored && s.isAnomaly).length;
      statBar.textContent =
        `${flagged} flagged · ${fires.length} alert${fires.length === 1 ? '' : 's'} · ` +
        `warm-up ${eff} pts`;
      configEcho.textContent = configText(params, consecutive);
    });
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
  );
  controls.appendChild(detectorCtl.row);

  const thresholdCtl = rangeControl(
    'Threshold (σ-equivalent)',
    { min: 0.5, max: 10, step: 0.1, value: seed.threshold, fmt: (v) => v.toFixed(1) },
    recompute,
  );
  controls.appendChild(thresholdCtl.row);
  const thresholdInput = thresholdCtl.row.querySelector<HTMLInputElement>('input');
  const thresholdOut = thresholdCtl.row.querySelector<HTMLElement>('.dtk-ctl-val');
  const thresholdCtl_setDefault = (v: number): void => {
    if (thresholdInput) thresholdInput.value = String(v);
    if (thresholdOut) thresholdOut.textContent = v.toFixed(1);
  };

  const windowMax = Math.max(50, Math.min(2000, n));
  const windowCtl = rangeControl(
    'Window size (points)',
    {
      min: 10,
      max: windowMax,
      step: 5,
      value: Math.min(seed.windowSize, windowMax),
      fmt: (v) => String(v),
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
  );
  controls.appendChild(weightsCtl.row);

  const halfLifeCtl = rangeControl(
    'Half-life (points)',
    {
      min: 1,
      max: windowMax,
      step: 1,
      value: seed.halfLife ?? Math.max(5, Math.round(seed.windowSize / 20)),
      fmt: (v) => String(v),
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
  );
  controls.appendChild(smoothingCtl.row);

  // seasonality (only when the metric has seasonality columns)
  if (payload.seasonality_columns.length) {
    const row = el('div', 'dtk-ctl');
    row.appendChild(el('label', 'dtk-ctl-label', 'Seasonality conditioning'));
    const chips = el('div', 'dtk-seg dtk-wrap');
    payload.seasonality_columns.forEach((col) => {
      const b = el('button', 'dtk-seg-btn', col);
      b.type = 'button';
      b.classList.toggle('on', selectedCols.has(col));
      b.onclick = (): void => {
        if (selectedCols.has(col)) selectedCols.delete(col);
        else selectedCols.add(col);
        b.classList.toggle('on', selectedCols.has(col));
        recompute();
      };
      chips.appendChild(b);
    });
    row.appendChild(chips);
    const conjoinLab = el('label', 'dtk-check');
    const cb = el('input');
    cb.type = 'checkbox';
    cb.checked = conjoin;
    cb.onchange = (): void => {
      conjoin = cb.checked;
      recompute();
    };
    conjoinLab.appendChild(cb);
    conjoinLab.appendChild(el('span', undefined, 'conjoin selected into one group'));
    row.appendChild(conjoinLab);
    controls.appendChild(row);
  }

  const consecutiveCtl = rangeControl(
    'Alert: consecutive anomalies',
    { min: 1, max: 10, step: 1, value: consecutive, fmt: (v) => String(v) },
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
  recompute();
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
.dtk-tune-chart{position:relative;width:100%;height:420px;background:var(--surface);
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
`;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);
}

// Expose the global the inlined HTML bootstrap calls (mirrors __DTK_REPORT__).
(window as unknown as { __DTK_TUNE__: { render: typeof render } }).__DTK_TUNE__ = { render };

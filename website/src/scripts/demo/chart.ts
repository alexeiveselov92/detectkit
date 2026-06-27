// Dependency-free HTML5 Canvas 2D renderer for the interactive demo.
//
// Paints, back to front: the value gridlines, the confidence corridor (filled
// band between lower/upper over contiguous scored runs), the band center line,
// the metric line (min/max decimated, one envelope column per pixel), the
// flagged anomaly markers, and — on hover — the trailing WINDOW used to score
// the point under the cursor. The window overlay is the pedagogical centrepiece:
// it shades exactly the history [i-windowSize .. i-1] that predicts point i.
//
// The whole series is always fitted to the canvas width (no zoom/pan). Canvas
// primitives (DPR-aware fit, px/py coordinate helpers, decimated drawSeries) are
// ported from detectkit/autotune/html_labeler.py and now live in core/canvas.ts,
// shared with the library report renderer.

import {
  type Margins,
  drawAlertMarkers,
  drawSeriesDecimated,
  drawWarmupOverlay,
  fit as fitCanvas,
  fmtTick,
  fmtVal,
  rgba,
  token,
} from '../core/canvas';
import { effectiveStartIndex } from './detector';
import type {
  ChartAlert,
  ChartData,
  ChartHandle,
  ChartOptions,
  HoverInfo,
  Incident,
  LassoInfo,
  ScoredPoint,
  Series,
} from './types';

const MARGINS: Margins = { l: 52, r: 14, t: 14, b: 26 };

// Navigator strip geometry (CSS px), used only in navigable mode.
const NAV_H = 46;
const NAV_GAP = 10;
const NAV_LABEL_H = 13;

const isFinite = Number.isFinite;

// Adaptive, UTC-aligned "nice" time ticks (mirrors the labeler's niceTimeTicks):
// round calendar boundaries (hour/day/month/year) rather than even splits, so a
// point's real time reads off the grid. Returns the ticks + the chosen step (ms).
const MS_S = 1000;
const MS_MIN = 60 * MS_S;
const MS_H = 60 * MS_MIN;
const MS_D = 24 * MS_H;
const TICK_STEPS = [
  MS_S, 2 * MS_S, 5 * MS_S, 10 * MS_S, 15 * MS_S, 30 * MS_S,
  MS_MIN, 2 * MS_MIN, 5 * MS_MIN, 10 * MS_MIN, 15 * MS_MIN, 30 * MS_MIN,
  MS_H, 2 * MS_H, 3 * MS_H, 6 * MS_H, 12 * MS_H,
  MS_D, 2 * MS_D, 3 * MS_D, 5 * MS_D, 7 * MS_D, 14 * MS_D,
];

function niceTimeTicks(lo: number, hi: number, target: number): { ticks: number[]; step: number } {
  const span = Math.max(hi - lo, 1);
  // Escalate to calendar months/years once even the coarsest sub-monthly step
  // (14d, the last TICK_STEPS entry) would exceed the target count — i.e. span >
  // target*14d. The old threshold (target*28d) left a gap [target*14d, target*28d]
  // (~3-6 months at target 7) where no sub-monthly step satisfied the target and
  // the loop fell through to a 14d step, packing ~13 labels in and overlapping.
  if (span > target * 14 * MS_D) {
    const mSteps = [1, 2, 3, 6, 12, 24, 36, 60, 120, 240];
    let stepM = mSteps[mSteps.length - 1];
    for (const m of mSteps) {
      if (span / (m * 30.44 * MS_D) <= target) {
        stepM = m;
        break;
      }
    }
    const d = new Date(lo);
    let y = d.getUTCFullYear();
    let mo = d.getUTCMonth();
    if (stepM >= 12) {
      const ys = stepM / 12;
      y = Math.floor(y / ys) * ys;
      mo = 0;
    } else {
      mo = Math.floor(mo / stepM) * stepM;
    }
    const ticks: number[] = [];
    let t = Date.UTC(y, mo, 1);
    while (t <= hi) {
      if (t >= lo) ticks.push(t);
      mo += stepM;
      y += Math.floor(mo / 12);
      mo %= 12;
      t = Date.UTC(y, mo, 1);
    }
    return { ticks, step: stepM * 30 * MS_D };
  }
  let step = TICK_STEPS[TICK_STEPS.length - 1];
  for (const s of TICK_STEPS) {
    if (span / s <= target) {
      step = s;
      break;
    }
  }
  let first: number;
  if (step % MS_D === 0) {
    const d = new Date(lo);
    first = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
    const k = step / MS_D;
    const dayNo = Math.round(first / MS_D);
    first += ((k - (dayNo % k)) % k) * MS_D;
  } else {
    first = Math.ceil(lo / step) * step;
  }
  const ticks: number[] = [];
  for (let t = first; t <= hi; t += step) if (t >= lo) ticks.push(t);
  return { ticks, step };
}

function fmtAxis(ts: number, step: number): string {
  const s = new Date(ts).toISOString();
  if (step >= 320 * MS_D) return s.slice(0, 4);
  if (step >= 26 * MS_D) return s.slice(0, 7);
  if (step >= MS_D) return s.slice(5, 10);
  if (step >= MS_H) return s.slice(5, 16).replace('T', ' ');
  return s.slice(5, 19).replace('T', ' ');
}

export function createChart(canvas: HTMLCanvasElement, opts: ChartOptions = {}): ChartHandle {
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('chart: 2D context unavailable');
  const g = ctx; // non-null alias

  const navigable = !!opts.navigable;
  // The navigator/minimap strip: on by default with `navigable`, suppressible so
  // a chart keeps wheel-zoom + drag-pan but yields the strip to a synced sibling.
  const hasNav = navigable && opts.showNavigator !== false;
  // 'data' fits the y-axis to the metric values only (band may clip past the
  // edges); 'band' (default) also folds in the confidence band so it's fully
  // visible. See ChartOptions.yFit.
  const yFitData = opts.yFit === 'data';
  // Incident-labeling mode: plot-drag marks/edits incident spans (pan via the
  // strip). Off → incidents (if any) are read-only shaded context.
  const labeling = !!opts.labeling;

  let dpr = 1;
  let data: ChartData | null = null;
  let hoverIndex = -1;
  let raf = 0;
  // y = 0 reference line + 0-relative scaling (toggled via setZeroLine).
  let showZero = !!opts.showZeroLine;
  // Incident spans drawn as bands. On a labeling chart this is the owned, mutable
  // source of truth; on a read-only chart it is replaced from render data.
  let incidents: Incident[] = [];
  // Labeling interaction state.
  let selIncident: Incident | null = null;
  let hoverDelIdx = -1;
  let incidentDrag:
    | { mode: 'new'; a: number; b: number; moved: boolean }
    | { mode: 'edge'; iv: Incident; edge: 'a' | 'b'; moved: boolean }
    | { mode: 'move'; iv: Incident; grab: number; a0: number; b0: number; moved: boolean }
    | null = null;
  // Suppresses onViewChange re-emit during a programmatic setViewWindow (sync).
  let suppressViewEmit = false;

  // Threshold-capture state (labeling mode only): paint a horizontal line and grab
  // every contiguous run of points on the chosen side of it in one shot. All off
  // unless the tool is toggled on, so a non-labeling chart is untouched.
  let thMode = false;
  let thDir: 'above' | 'below' = 'above';
  let thGap = 0; // bridge gaps up to this many non-matching points
  let thLockedVal: number | null = null; // a typed/clicked line value (wins over hover)
  let thHoverVal: number | null = null; // live cursor value
  // capWin: committed painted window; thDown/thDragWin track an in-progress press/paint.
  let capWin: { a: number; b: number } | null = null;
  let thDown: { x: number; ts: number } | null = null;
  let thDragWin: { a: number; b: number } | null = null;

  // Lasso-capture state (labeling mode only): draw a freeform loop around a cloud
  // of anomalies (or raw points where no detector runs) and turn each grid-adjacent
  // run — bridging gaps up to `consecutiveAnomalies` — into one proper incident
  // span. `lassoPath` holds the in-progress loop in device px. Off until toggled.
  let lassoMode = false;
  let lassoPath: Array<{ x: number; y: number }> | null = null;

  // Domain, recomputed per render.
  let tmin = 0;
  let tmax = 1;
  let vmin = 0;
  let vmax = 1;

  // Navigable view window over [tmin, tmax]; identifies the active series so a
  // data swap (e.g. the trim slider) resets the view to full. Inert otherwise.
  let viewMin = 0;
  let viewMax = 1;
  let seriesKey = '';

  // ---- DPR-aware sizing (shared core/canvas.fit) ----------------------------
  function fit(): void {
    dpr = fitCanvas(canvas);
  }

  // Reserve a navigator strip at the bottom when shown; the main plot shrinks by
  // exactly that much so nothing else moves.
  const navTotal = (): number => (hasNav ? (NAV_GAP + NAV_H) * dpr : 0);
  const plotW = (): number => canvas.width - (MARGINS.l + MARGINS.r) * dpr;
  const plotH = (): number => canvas.height - (MARGINS.t + MARGINS.b) * dpr - navTotal();
  // X domain = the visible window when navigable, else the whole series.
  const xLo = (): number => (navigable ? viewMin : tmin);
  const xHi = (): number => (navigable ? viewMax : tmax);
  const tspan = (): number => xHi() - xLo() || 1;
  const fullSpan = (): number => tmax - tmin || 1;
  const px = (ts: number): number => MARGINS.l * dpr + ((ts - xLo()) / tspan()) * plotW();
  const py = (v: number): number =>
    canvas.height - MARGINS.b * dpr - navTotal() - ((v - vmin) / (vmax - vmin || 1)) * plotH();

  // Navigator-strip geometry (device px). The strip spans the FULL series.
  const navTop = (): number => canvas.height - NAV_H * dpr;
  const navPlotH = (): number => (NAV_H - NAV_LABEL_H) * dpr;
  const navW = (): number => canvas.width - (MARGINS.l + MARGINS.r) * dpr;
  const navPx = (ts: number): number =>
    MARGINS.l * dpr + ((ts - tmin) / fullSpan()) * navW();
  const navVy = (v: number): number =>
    navTop() + navPlotH() - ((v - vmin) / (vmax - vmin || 1)) * navPlotH();

  // Which ticks may show a TEXT label without colliding: keep the first, then
  // keep each only if its x clears the previous kept label by the label width +
  // a gutter. Gridlines/ticks still draw for every entry; only text is thinned.
  // A robust backstop for any width/zoom/format (measures with the current font,
  // so set g.font before calling). Same per-step format ⇒ uniform label width.
  const labelMask = (ticks: number[], xOf: (t: number) => number, step: number): boolean[] => {
    const show = new Array<boolean>(ticks.length).fill(false);
    if (ticks.length === 0) return show;
    const minGap = g.measureText(fmtAxis(ticks[0], step)).width + 16 * dpr;
    let lastX = -Infinity;
    for (let i = 0; i < ticks.length; i++) {
      const xx = xOf(ticks[i]);
      if (xx - lastX >= minGap) {
        show[i] = true;
        lastX = xx;
      }
    }
    return show;
  };

  const clampNum = (x: number, a: number, b: number): number => Math.max(a, Math.min(b, x));
  const minSpan = (): number => {
    const s = data?.series;
    const n = s ? s.timestamps.length : 0;
    const step = n > 1 ? fullSpan() / (n - 1) : 1000;
    return Math.max(step * 8, 1000);
  };
  // Set the visible window, clamped so it never leaves [tmin, tmax].
  function setView(a: number, b: number): void {
    let s = b - a;
    const ms = minSpan();
    if (s < ms) {
      const m = (a + b) / 2;
      a = m - ms / 2;
      b = m + ms / 2;
      s = ms;
    }
    if (s >= fullSpan()) {
      a = tmin;
      b = tmax;
    }
    if (a < tmin) {
      b += tmin - a;
      a = tmin;
    }
    if (b > tmax) {
      a -= b - tmax;
      b = tmax;
    }
    viewMin = clampNum(a, tmin, tmax);
    viewMax = clampNum(b, tmin, tmax);
    if (!suppressViewEmit) opts.onViewChange?.(viewMin, viewMax);
    // The default capture window is the current view, so its run count tracks pan/zoom.
    if (thMode) emitThreshold();
    schedule();
  }
  // Set the visible window from a synced sibling WITHOUT re-emitting onViewChange
  // (so A→B→A never loops). No-op when not navigable.
  function setViewWindow(a: number, b: number): void {
    if (!navigable) return;
    suppressViewEmit = true;
    setView(a, b);
    suppressViewEmit = false;
  }
  // Timestamp at a device-px X within the main plot.
  const tsAtDevX = (devX: number): number => {
    const frac = (devX - MARGINS.l * dpr) / (plotW() || 1);
    return xLo() + clampNum(frac, 0, 1) * tspan();
  };
  // Timestamp at a device-px X within the navigator strip.
  const navTsAtDevX = (devX: number): number => {
    const frac = (devX - MARGINS.l * dpr) / (navW() || 1);
    return tmin + clampNum(frac, 0, 1) * fullSpan();
  };
  // Value at a device-px Y within the main plot (inverse of py) — reads the
  // threshold line off the cursor.
  const vAtDevY = (devY: number): number => {
    const bottom = canvas.height - MARGINS.b * dpr - navTotal();
    const frac = clampNum((bottom - devY) / (plotH() || 1), 0, 1);
    return vmin + frac * (vmax - vmin);
  };

  // Inverse of px: nearest series index for a device-px X coordinate.
  function nearestIndex(devX: number): number {
    const s = data?.series;
    if (!s || s.timestamps.length === 0) return -1;
    const frac = (devX - MARGINS.l * dpr) / (plotW() || 1);
    const ts = xLo() + frac * tspan();
    // binary search on the strictly-increasing grid
    const ta = s.timestamps;
    let lo = 0;
    let hi = ta.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (ta[mid] < ts) lo = mid + 1;
      else hi = mid;
    }
    if (lo > 0 && ts - ta[lo - 1] < ta[lo] - ts) lo -= 1;
    return lo;
  }

  // ---- domain ---------------------------------------------------------------
  function computeDomain(series: Series, scored: ScoredPoint[]): void {
    const ts = series.timestamps;
    tmin = ts[0];
    tmax = ts[ts.length - 1];
    if (navigable) {
      // Reset the view to full whenever the active series changes (first render
      // or a trim/data swap); otherwise preserve the user's zoom across the
      // per-knob recomputes, re-clamping it into the (possibly new) range.
      const key = `${ts.length}:${tmin}:${tmax}`;
      if (key !== seriesKey) {
        seriesKey = key;
        viewMin = tmin;
        viewMax = tmax;
      } else {
        viewMin = clampNum(viewMin, tmin, tmax);
        viewMax = clampNum(Math.max(viewMax, viewMin + minSpan()), tmin, tmax);
      }
    }
    let lo = Infinity;
    let hi = -Infinity;
    for (const v of series.values) {
      if (isFinite(v)) {
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    }
    // Fold the band into the vertical extent only in 'band' mode. In 'data' mode
    // the axis tracks the values alone, so widening the threshold visibly grows
    // the band toward (and past) the plot edges instead of the axis growing with
    // it. The band fill is clipped to the plot rect, so this never overdraws.
    if (!yFitData) {
      for (const p of scored) {
        if (p.scored) {
          if (isFinite(p.lower) && p.lower < lo) lo = p.lower;
          if (isFinite(p.upper) && p.upper > hi) hi = p.upper;
        }
      }
    }
    if (!isFinite(lo) || !isFinite(hi)) {
      lo = 0;
      hi = 1;
    }
    // Fold 0 into the extent so the metric reads relative to zero (the y=0 line is
    // then always in view, not clipped off an all-positive / all-negative series).
    if (showZero) {
      if (lo > 0) lo = 0;
      if (hi < 0) hi = 0;
    }
    if (hi <= lo) {
      hi = lo + 1;
    }
    const pad = (hi - lo) * 0.06;
    vmin = lo - pad;
    vmax = hi + pad;
  }

  // ---- min/max-decimated series line (shared core/canvas.drawSeriesDecimated)
  // lo/hi follow the visible window (the whole series unless navigable + zoomed).
  function drawSeries(values: number[], color: string, lw: number): void {
    const ts = data!.series.timestamps;
    drawSeriesDecimated(g, ts, values, xLo(), xHi(), MARGINS.l * dpr, plotW(), px, py, color, lw, dpr);
  }

  // Contiguous runs of scored points with finite band bounds (warm-up / NaN-band
  // gaps break a run), so the corridor polygon never bridges un-scored regions.
  // Only points at/after `from` (the effective-zone start) are eligible, so the
  // degraded lead-in never gets a corridor.
  function scoredRuns(scored: ScoredPoint[], from: number): Array<[number, number]> {
    const runs: Array<[number, number]> = [];
    let start = -1;
    for (let i = Math.max(0, from); i < scored.length; i++) {
      const p = scored[i];
      const ok = p.scored && isFinite(p.lower) && isFinite(p.upper);
      if (ok) {
        if (start === -1) start = i;
      } else if (start !== -1) {
        runs.push([start, i - 1]);
        start = -1;
      }
    }
    if (start !== -1) runs.push([start, scored.length - 1]);
    return runs;
  }

  // ---- frame ----------------------------------------------------------------
  function paint(): void {
    raf = 0;
    if (!data || canvas.width === 0 || canvas.height === 0) return;
    const { series, scored, params, alerts } = data;
    if (series.timestamps.length === 0) {
      g.fillStyle = token('--term-bg');
      g.fillRect(0, 0, canvas.width, canvas.height);
      return;
    }

    const clay = token('--clay');
    const anomaly = token('--st-anomaly');
    const faint = token('--faint');
    const muted = token('--muted');

    // 1. background + gridlines + axis labels
    g.fillStyle = token('--term-bg');
    g.fillRect(0, 0, canvas.width, canvas.height);
    g.font = `${11 * dpr}px ui-monospace, 'JetBrains Mono', monospace`;
    g.textBaseline = 'middle';
    for (let i = 0; i <= 4; i++) {
      const v = vmin + ((vmax - vmin) * i) / 4;
      const yy = py(v);
      g.strokeStyle = rgba(faint, 0.1);
      g.lineWidth = 1 * dpr;
      g.beginPath();
      g.moveTo(MARGINS.l * dpr, yy);
      g.lineTo(canvas.width - MARGINS.r * dpr, yy);
      g.stroke();
      g.fillStyle = muted;
      g.textAlign = 'right';
      g.fillText(fmtVal(v), (MARGINS.l - 8) * dpr, yy);
    }
    // y = 0 reference line (distinct from the faint gridlines) when in view.
    if (showZero && vmin <= 0 && vmax >= 0) {
      const y0 = py(0);
      g.strokeStyle = rgba(muted, 0.6);
      g.lineWidth = 1.25 * dpr;
      g.beginPath();
      g.moveTo(MARGINS.l * dpr, y0);
      g.lineTo(canvas.width - MARGINS.r * dpr, y0);
      g.stroke();
      g.fillStyle = muted;
      g.textAlign = 'right';
      g.fillText('0', (MARGINS.l - 8) * dpr, y0);
    }
    g.textBaseline = 'top';
    const mainBot = canvas.height - MARGINS.b * dpr - navTotal();
    if (navigable) {
      // Adaptive vertical time gridlines + round-boundary labels over the view.
      const xtk = niceTimeTicks(xLo(), xHi(), 7);
      const showLabel = labelMask(xtk.ticks, px, xtk.step);
      for (let ti = 0; ti < xtk.ticks.length; ti++) {
        const ts = xtk.ticks[ti];
        const xx = px(ts);
        g.strokeStyle = rgba(faint, 0.1);
        g.lineWidth = 1 * dpr;
        g.beginPath();
        g.moveTo(xx, MARGINS.t * dpr);
        g.lineTo(xx, mainBot);
        g.stroke();
        if (!showLabel[ti]) continue;
        g.fillStyle = muted;
        g.textAlign =
          xx < (MARGINS.l + 24) * dpr ? 'left' : xx > canvas.width - (MARGINS.r + 24) * dpr ? 'right' : 'center';
        g.fillText(fmtAxis(ts, xtk.step), xx, mainBot + 7 * dpr);
      }
    } else {
      const spanMs = tspan();
      for (let i = 0; i <= 5; i++) {
        const ts = tmin + (spanMs * i) / 5;
        const xx = px(ts);
        g.fillStyle = muted;
        g.textAlign = i === 0 ? 'left' : i === 5 ? 'right' : 'center';
        g.fillText(fmtTick(ts, spanMs), xx, mainBot + 7 * dpr);
      }
    }

    // clip to the plot rect for everything data-related
    g.save();
    g.beginPath();
    g.rect(MARGINS.l * dpr, MARGINS.t * dpr, plotW(), plotH());
    g.clip();

    // 0. incident span bands (under the band/line) — read-only context on a
    // detector chart, interactive on a labeling chart. Threshold-capture preview
    // bands sit just beneath them.
    drawThresholdPreview();
    drawIncidents();

    // Effective-zone start: the first index where the detector runs at full
    // power. Everything before it (the degraded warm-up lead-in) gets no band,
    // no center line and no anomaly dots — only the dimming overlay + the
    // context metric line. effTs is the divider timestamp (undefined if the
    // whole series is in the effective zone).
    const n = scored.length;
    const eff = Math.min(effectiveStartIndex(series, params), n);
    const effTs = eff < n ? series.timestamps[eff] : undefined;
    // A labeling chart is a labeler, not a detector view: it shows the raw line +
    // anomaly dots (so you can lasso the cloud) but NOT the band/center/warm-up,
    // which belong to the synced detector chart above it. Zeroing the runs makes
    // the corridor/center loops no-ops.
    const runs = labeling ? [] : scoredRuns(scored, eff);

    // 2. confidence corridor — one filled polygon per contiguous scored run
    g.fillStyle = rgba(clay, 0.13);
    for (const [a, b] of runs) {
      g.beginPath();
      g.moveTo(px(scored[a].timestamp), py(scored[a].upper));
      for (let i = a + 1; i <= b; i++) g.lineTo(px(scored[i].timestamp), py(scored[i].upper));
      for (let i = b; i >= a; i--) g.lineTo(px(scored[i].timestamp), py(scored[i].lower));
      g.closePath();
      g.fill();
    }
    // faint top/bottom edges
    g.strokeStyle = rgba(clay, 0.4);
    g.lineWidth = 1 * dpr;
    for (const [a, b] of runs) {
      for (const bound of ['upper', 'lower'] as const) {
        g.beginPath();
        for (let i = a; i <= b; i++) {
          const X = px(scored[i].timestamp);
          const Y = py(scored[i][bound]);
          if (i === a) g.moveTo(X, Y);
          else g.lineTo(X, Y);
        }
        g.stroke();
      }
    }

    // 3. center line — thin dashed faint
    g.strokeStyle = rgba(faint, 0.55);
    g.lineWidth = 1 * dpr;
    g.setLineDash([3 * dpr, 3 * dpr]);
    for (const [a, b] of runs) {
      g.beginPath();
      for (let i = a; i <= b; i++) {
        const c = scored[i].center;
        if (!isFinite(c)) continue;
        const X = px(scored[i].timestamp);
        const Y = py(c);
        if (i === a) g.moveTo(X, Y);
        else g.lineTo(X, Y);
      }
      g.stroke();
    }
    g.setLineDash([]);

    // 4. metric line(s).
    // With smoothing on, the detector judges the PROCESSED (smoothed) series, so
    // draw that as the active clay line and the raw values as a faint ghost
    // behind it (so a viewer sees both what the metric did and what the band
    // sees). With no smoothing the processed value equals the raw value, so a
    // single clay line is all that's needed.
    if (params.smoothing !== 'none' && !labeling) {
      drawSeries(series.values, rgba(clay, 0.28), 1.25);
      const processed = scored.map((p) => p.processedValue);
      drawSeries(processed, clay, 1.6);
    } else {
      // Labeler always shows the raw series (the dots sit on the real values).
      drawSeries(series.values, clay, 1.5);
    }

    // 5. anomaly markers (flagged dots) + missed-truth rings — effective zone only
    for (let i = eff; i < n; i++) {
      const p = scored[i];
      if (!p.scored || !isFinite(p.value)) continue;
      const X = px(p.timestamp);
      const Y = py(p.value);
      if (p.isAnomaly) {
        g.fillStyle = rgba(anomaly, 0.18);
        g.beginPath();
        g.arc(X, Y, 6 * dpr, 0, Math.PI * 2);
        g.fill();
        g.fillStyle = anomaly;
        g.beginPath();
        g.arc(X, Y, 3 * dpr, 0, Math.PI * 2);
        g.fill();
      } else if (series.truthAnomaly[i]) {
        // subtle hollow ring: an injected anomaly the detector missed
        g.strokeStyle = rgba(muted, 0.7);
        g.lineWidth = 1.25 * dpr;
        g.beginPath();
        g.arc(X, Y, 3.5 * dpr, 0, Math.PI * 2);
        g.stroke();
      }
    }

    // 6. warm-up overlay: dim the lead-in + label where detection reaches full
    // power. Drawn before the hover overlay so the window box stays crisp on top.
    if (effTs !== undefined && !labeling) {
      drawWarmupOverlay(g, canvas, MARGINS, dpr, px, effTs, 'detection at full power →');
    }

    // 7. window overlay (hover) — works across the whole series for context
    if (hoverIndex >= 0 && hoverIndex < scored.length) {
      drawWindowOverlay(hoverIndex, params.windowSize, scored, series, faint);
    }

    // 8. alert markers — one per fired incident, along the top axis
    if (alerts && alerts.length) {
      drawAlertMarkers(g, canvas, MARGINS, dpr, px, alerts, (k) =>
        k === 'anomaly'
          ? token('--st-anomaly')
          : k === 'recovery'
            ? token('--st-recovery')
            : token('--st-nodata'),
      );
    }

    // 9. threshold-capture line + capture-window dimming, on top of the series.
    drawThresholdOverlay();
    // 9b. lasso loop + the anomalies it currently encloses.
    drawLasso(scored, eff, n);

    g.restore();

    // 10. navigator strip — the whole series in miniature with the current view
    // window, alert ticks and a time axis, so a zoomed-in view never loses the
    // big picture.
    if (hasNav) drawNavigator(series, alerts, clay, faint, muted);
  }

  // The bottom navigator/minimap: full-series mini line + faint time gridlines,
  // the dimmed out-of-view region, the draggable view window, red alert ticks
  // (so every firing is locatable at a glance) and absolute-time labels.
  function drawNavigator(
    series: Series,
    alerts: ChartAlert[] | undefined,
    clay: string,
    faint: string,
    muted: string,
  ): void {
    const top = navTop();
    const bot = top + navPlotH();
    const left = MARGINS.l * dpr;
    const right = canvas.width - MARGINS.r * dpr;
    const otk = niceTimeTicks(tmin, tmax, 5);

    g.save();
    g.beginPath();
    g.rect(left, top, navW(), navPlotH());
    g.clip();
    // faint vertical time gridlines behind the mini series
    g.strokeStyle = rgba(faint, 0.1);
    g.lineWidth = 1 * dpr;
    for (const ts of otk.ticks) {
      const xx = navPx(ts);
      g.beginPath();
      g.moveTo(xx, top);
      g.lineTo(xx, bot);
      g.stroke();
    }
    drawSeriesDecimated(
      g,
      series.timestamps,
      series.values,
      tmin,
      tmax,
      left,
      navW(),
      navPx,
      navVy,
      rgba(clay, 0.7),
      1.1,
      dpr,
    );
    g.restore();

    // dim the out-of-view region
    const vx0 = navPx(viewMin);
    const vx1 = navPx(viewMax);
    g.fillStyle = 'rgba(27,25,22,0.55)';
    g.fillRect(left, top, vx0 - left, navPlotH());
    g.fillRect(vx1, top, right - vx1, navPlotH());

    // incident spans (faint bands) so labeled incidents are locatable at a glance
    if (incidents.length) {
      const anomalyCol = token('--st-anomaly');
      g.fillStyle = rgba(anomalyCol, 0.28);
      for (const iv of incidents) {
        const x0 = navPx(iv.start);
        const w = Math.max(navPx(iv.end) - x0, 2 * dpr);
        g.fillRect(x0, top, w, navPlotH());
      }
    }

    // alert ticks (full strength on top of the dim) — every firing, locatable
    if (alerts && alerts.length) {
      const anomalyCol = token('--st-anomaly');
      g.fillStyle = rgba(anomalyCol, 0.85);
      for (const a of alerts) {
        const xx = navPx(a.t);
        g.fillRect(xx - 1 * dpr, top, 2 * dpr, navPlotH());
      }
    }

    // view window frame + grab handles
    g.fillStyle = 'rgba(245,241,232,0.06)';
    g.fillRect(vx0, top, vx1 - vx0, navPlotH());
    g.strokeStyle = clay;
    g.lineWidth = 1.5 * dpr;
    g.strokeRect(vx0, top + 1, vx1 - vx0, navPlotH() - 2);
    g.fillStyle = clay;
    const hy = top + navPlotH() / 2 - 8 * dpr;
    g.fillRect(vx0 - 2 * dpr, hy, 4 * dpr, 16 * dpr);
    g.fillRect(vx1 - 2 * dpr, hy, 4 * dpr, 16 * dpr);

    // absolute-time labels under the strip
    g.font = `${10 * dpr}px ui-monospace, monospace`;
    g.textBaseline = 'top';
    g.fillStyle = muted;
    const showNavLabel = labelMask(otk.ticks, navPx, otk.step);
    for (let ti = 0; ti < otk.ticks.length; ti++) {
      const ts = otk.ticks[ti];
      const xx = navPx(ts);
      g.strokeStyle = rgba(faint, 0.25);
      g.lineWidth = 1 * dpr;
      g.beginPath();
      g.moveTo(xx, bot);
      g.lineTo(xx, bot + 3 * dpr);
      g.stroke();
      if (!showNavLabel[ti]) continue;
      g.textAlign =
        xx < (MARGINS.l + 26) * dpr ? 'left' : xx > canvas.width - (MARGINS.r + 26) * dpr ? 'right' : 'center';
      g.fillText(fmtAxis(ts, otk.step), xx, bot + 5 * dpr);
    }
  }

  // The trailing-window overlay: shade [i-windowSize .. i-1], mark point i, and
  // emphasise its band handles — the history that predicts the hovered point.
  function drawWindowOverlay(
    i: number,
    windowSize: number,
    scored: ScoredPoint[],
    series: Series,
    faint: string,
  ): void {
    const ts = series.timestamps;
    const wStart = Math.max(0, i - windowSize);
    const wEnd = i - 1;
    const top = MARGINS.t * dpr;
    const h = plotH();

    if (wEnd >= wStart) {
      // grid points are point-samples; pad the shaded rect half an interval each
      // side so the edge points sit inside it.
      const halfStep =
        ((series.intervalSeconds * 1000) / tspan()) * plotW() * 0.5;
      const x0 = px(ts[wStart]) - halfStep;
      const x1 = px(ts[wEnd]) + halfStep;
      g.fillStyle = 'rgba(255,255,255,0.05)';
      g.fillRect(x0, top, x1 - x0, h);
      g.strokeStyle = rgba(faint, 0.5);
      g.lineWidth = 1 * dpr;
      g.beginPath();
      g.moveTo(x0, top);
      g.lineTo(x0, top + h);
      g.moveTo(x1, top);
      g.lineTo(x1, top + h);
      g.stroke();
    }

    // vertical marker at the hovered point
    const xi = px(ts[i]);
    g.strokeStyle = rgba(faint, 0.85);
    g.lineWidth = 1 * dpr;
    g.setLineDash([2 * dpr, 2 * dpr]);
    g.beginPath();
    g.moveTo(xi, top);
    g.lineTo(xi, top + h);
    g.stroke();
    g.setLineDash([]);

    const p = scored[i];

    // band handles at lower[i]/upper[i]
    if (p.scored && isFinite(p.lower) && isFinite(p.upper)) {
      const cap = 5 * dpr;
      g.strokeStyle = rgba(token('--clay'), 0.85);
      g.lineWidth = 1.5 * dpr;
      for (const bound of [p.lower, p.upper]) {
        const Y = py(bound);
        g.beginPath();
        g.moveTo(xi - cap, Y);
        g.lineTo(xi + cap, Y);
        g.stroke();
      }
    }

    // crosshair dot on the metric line
    if (isFinite(p.value)) {
      const Y = py(p.value);
      g.fillStyle = token('--term-bg');
      g.beginPath();
      g.arc(xi, Y, 4 * dpr, 0, Math.PI * 2);
      g.fill();
      g.strokeStyle = p.isAnomaly ? token('--st-anomaly') : token('--clay');
      g.lineWidth = 2 * dpr;
      g.beginPath();
      g.arc(xi, Y, 4 * dpr, 0, Math.PI * 2);
      g.stroke();
    }
  }

  // ---- incident bands -------------------------------------------------------
  // A rounded-rect path (for the ✕ delete handle), ported from html_labeler.
  function roundRect(x: number, y: number, w: number, h: number, r: number): void {
    g.beginPath();
    g.moveTo(x + r, y);
    g.arcTo(x + w, y, x + w, y + h, r);
    g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r);
    g.arcTo(x, y, x + w, y, r);
    g.closePath();
  }

  // The ✕ delete handle at a band's top-right (device px); `hot` brightens it.
  function drawDelHandle(x1: number, hot: boolean): void {
    const anomaly = token('--st-anomaly');
    const s = 14 * dpr;
    const m = 3 * dpr;
    const bx = x1 - s - m;
    const by = MARGINS.t * dpr + m;
    g.fillStyle = hot ? rgba(anomaly, 0.95) : 'rgba(27,25,22,0.82)';
    g.strokeStyle = rgba(anomaly, 0.9);
    g.lineWidth = 1 * dpr;
    roundRect(bx, by, s, s, 3 * dpr);
    g.fill();
    g.stroke();
    g.strokeStyle = hot ? '#fff' : anomaly;
    g.lineWidth = 1.5 * dpr;
    const p = 4 * dpr;
    g.beginPath();
    g.moveTo(bx + p, by + p);
    g.lineTo(bx + s - p, by + s - p);
    g.moveTo(bx + s - p, by + p);
    g.lineTo(bx + p, by + s - p);
    g.stroke();
  }

  // ---- threshold capture ----------------------------------------------------
  // The effective line value: a locked (typed/clicked) value wins, else the live
  // cursor value.
  const thEff = (): number | null => (thLockedVal != null ? thLockedVal : thHoverVal);
  // The active capture window [lo, hi] in ms: a live/committed painted window, else
  // the current view — so the threshold only grabs the period you're looking at.
  const thCapRange = (): [number, number] => {
    const w = thDragWin || capWin;
    if (w) return [Math.min(w.a, w.b), Math.max(w.a, w.b)];
    return [xLo(), xHi()];
  };
  // Contiguous runs (in ms) of points on the chosen side of the line within the
  // capture window, bridging up to `thGap` non-matching points. Ported from the
  // autotune html_labeler threshold capture.
  function thRuns(): Array<[number, number]> {
    const runs: Array<[number, number]> = [];
    const val = thEff();
    if (val == null || !data) return runs;
    const ts = data.series.timestamps;
    const vs = data.series.values;
    const [lo, hi] = thCapRange();
    let s = -1;
    let e = -1;
    let gap = 0;
    for (let i = 0; i < ts.length; i++) {
      if (ts[i] < lo || ts[i] > hi) continue;
      const v = vs[i];
      const hit = isFinite(v) && (thDir === 'above' ? v > val : v < val);
      if (hit) {
        if (s === -1) s = ts[i];
        e = ts[i];
        gap = 0;
      } else if (s !== -1) {
        gap++;
        if (gap > thGap) {
          runs.push([s, e]);
          s = -1;
          gap = 0;
        }
      }
    }
    if (s !== -1) runs.push([s, e]);
    return runs;
  }
  // Push the current preview state (run count, value, window) to the UI.
  function emitThreshold(): void {
    if (!opts.onThresholdChange) return;
    const [lo, hi] = thCapRange();
    const w = thDragWin || capWin;
    opts.onThresholdChange({
      value: thEff(),
      locked: thLockedVal != null,
      runs: thRuns().length,
      window: w ? { start: Math.min(w.a, w.b), end: Math.max(w.a, w.b) } : null,
      committed: capWin != null,
      windowMs: hi - lo,
    });
  }
  // Add a captured [a, b] span (ms), merging it into any overlapping incidents (a
  // single span can bridge several) into one band keeping the first's label.
  function addCaptured(a: number, b: number): void {
    let host: Incident | null = null;
    for (let i = incidents.length - 1; i >= 0; i--) {
      const iv = incidents[i];
      if (a <= iv.end && b >= iv.start) {
        if (host === null) {
          iv.start = Math.min(iv.start, a);
          iv.end = Math.max(iv.end, b);
          host = iv;
        } else {
          host.start = Math.min(host.start, iv.start);
          host.end = Math.max(host.end, iv.end);
          if (selIncident === iv) selIncident = host;
          incidents.splice(i, 1);
        }
      }
    }
    if (host === null) incidents.push({ start: a, end: b, label: '' });
  }
  // Amber preview bands for the spans the current threshold would capture (drawn
  // under the committed incident bands). No-op unless threshold mode is active.
  function drawThresholdPreview(): void {
    if (!thMode) return;
    const val = thEff();
    if (val == null) return;
    const top = MARGINS.t * dpr;
    const h = plotH();
    const nodata = token('--st-nodata');
    for (const [a, b] of thRuns()) {
      const x0 = px(a);
      const w = Math.max(px(b) - x0, 2 * dpr);
      g.fillStyle = rgba(nodata, 0.22);
      g.fillRect(x0, top, w, h);
      g.strokeStyle = rgba(nodata, 0.6);
      g.lineWidth = 1 * dpr;
      g.strokeRect(x0, top, w, h);
    }
  }
  // The threshold line + capture-window dimming, drawn on top of the series so the
  // line reads over the data. No-op unless threshold mode is active.
  function drawThresholdOverlay(): void {
    if (!thMode) return;
    const top = MARGINS.t * dpr;
    const bottomFull = canvas.height - MARGINS.b * dpr - navTotal();
    const left = MARGINS.l * dpr;
    const right = canvas.width - MARGINS.r * dpr;
    const nodata = token('--st-nodata');
    const [lo, hi] = thCapRange();
    const narrow = !!(thDragWin || capWin);
    const xlo = clampNum(px(lo), left, right);
    const xhi = clampNum(px(hi), left, right);
    if (narrow) {
      // dim everything outside the painted capture window
      g.fillStyle = rgba(token('--ink'), 0.5);
      g.fillRect(left, top, Math.max(0, xlo - left), plotH());
      g.fillRect(xhi, top, Math.max(0, right - xhi), plotH());
      g.strokeStyle = rgba(nodata, 0.7);
      g.lineWidth = 1 * dpr;
      g.setLineDash([3 * dpr, 3 * dpr]);
      g.beginPath();
      g.moveTo(xlo, top);
      g.lineTo(xlo, bottomFull);
      g.moveTo(xhi, top);
      g.lineTo(xhi, bottomFull);
      g.stroke();
      g.setLineDash([]);
    }
    const val = thEff();
    if (val != null && val >= vmin && val <= vmax) {
      const yy = py(val);
      g.strokeStyle = nodata;
      g.lineWidth = 1.5 * dpr;
      g.setLineDash([6 * dpr, 4 * dpr]);
      g.beginPath();
      g.moveTo(xlo, yy);
      g.lineTo(xhi, yy);
      g.stroke();
      g.setLineDash([]);
    }
  }

  // ---- lasso capture --------------------------------------------------------
  // Grid step in ms (1s fallback before any data).
  const intervalMs = (): number => (data ? data.series.intervalSeconds * 1000 : 1000);

  // Ray-casting point-in-polygon over a device-px loop.
  function inPolygon(x: number, y: number, poly: Array<{ x: number; y: number }>): boolean {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const xi = poly[i].x;
      const yi = poly[i].y;
      const xj = poly[j].x;
      const yj = poly[j].y;
      const hit = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi || 1e-9) + xi;
      if (hit) inside = !inside;
    }
    return inside;
  }

  // The anomaly indices currently enclosed by the lasso loop (effective zone only).
  function lassoCaptured(scored: ScoredPoint[], eff: number, n: number): number[] {
    const out: number[] = [];
    if (!lassoPath || lassoPath.length < 3) return out;
    for (let i = Math.max(0, eff); i < n; i++) {
      const p = scored[i];
      if (!p.scored || !p.isAnomaly || !isFinite(p.value)) continue;
      if (inPolygon(px(p.timestamp), py(p.value), lassoPath)) out.push(i);
    }
    return out;
  }

  // Collapse captured anomaly indices into incident spans: a new span starts only
  // when the gap to the previous capture exceeds `consecutiveAnomalies` intervals
  // (so the calm middle of a real incident doesn't fragment it). Each span is
  // padded half an interval each side, so a lone anomaly becomes one full-interval
  // incident (never a zero-width point the alert can land just outside of).
  function lassoSpans(scored: ScoredPoint[], captured: number[]): Array<[number, number]> {
    if (!captured.length) return [];
    const step = intervalMs();
    const bridge = Math.max(1, data?.params.consecutiveAnomalies ?? 1);
    const maxGap = (bridge + 1) * step; // bridge up to `bridge` missing points
    const half = step / 2;
    const spans: Array<[number, number]> = [];
    let runStart = captured[0];
    let prev = captured[0];
    for (let k = 1; k < captured.length; k++) {
      const idx = captured[k];
      if (scored[idx].timestamp - scored[prev].timestamp > maxGap) {
        spans.push([scored[runStart].timestamp - half, scored[prev].timestamp + half]);
        runStart = idx;
      }
      prev = idx;
    }
    spans.push([scored[runStart].timestamp - half, scored[prev].timestamp + half]);
    return spans;
  }

  // Push the live lasso state (capture counts) to the UI.
  function emitLasso(scored: ScoredPoint[], eff: number, n: number): void {
    if (!opts.onLassoChange) return;
    const captured = lassoMode && lassoPath ? lassoCaptured(scored, eff, n) : [];
    opts.onLassoChange({
      active: !!lassoPath,
      anomalies: captured.length,
      incidents: lassoSpans(scored, captured).length,
    });
  }

  // Commit the loop: build incident spans from the enclosed anomalies, merge them
  // into the incident set (addCaptured bridges overlaps) and emit.
  function commitLasso(): void {
    if (!data || !lassoPath) return;
    const { scored } = data;
    const n = scored.length;
    const eff = Math.min(effectiveStartIndex(data.series, data.params), n);
    const spans = lassoSpans(scored, lassoCaptured(scored, eff, n));
    for (const [a, b] of spans) addCaptured(a, b);
    if (spans.length) emitIncidents();
  }

  // The lasso loop (dashed accent outline + faint fill) and a brightened ring on
  // every anomaly it currently encloses. No-op unless a loop is being drawn.
  function drawLasso(scored: ScoredPoint[], eff: number, n: number): void {
    if (!lassoMode || !lassoPath || lassoPath.length < 2) return;
    const clay = token('--clay');
    const anomaly = token('--st-anomaly');
    g.beginPath();
    g.moveTo(lassoPath[0].x, lassoPath[0].y);
    for (let i = 1; i < lassoPath.length; i++) g.lineTo(lassoPath[i].x, lassoPath[i].y);
    g.closePath();
    g.fillStyle = rgba(clay, 0.08);
    g.fill();
    g.strokeStyle = rgba(clay, 0.9);
    g.lineWidth = 1.5 * dpr;
    g.setLineDash([5 * dpr, 4 * dpr]);
    g.stroke();
    g.setLineDash([]);
    for (const i of lassoCaptured(scored, eff, n)) {
      const X = px(scored[i].timestamp);
      const Y = py(scored[i].value);
      g.strokeStyle = anomaly;
      g.lineWidth = 2 * dpr;
      g.beginPath();
      g.arc(X, Y, 7 * dpr, 0, Math.PI * 2);
      g.stroke();
    }
  }

  // Shaded incident bands. Read-only on a detector chart (just fill + faint
  // edges); on a labeling chart they gain edge handles, a selection highlight, a
  // ✕ delete handle and a live drag preview.
  function drawIncidents(): void {
    const top = MARGINS.t * dpr;
    const h = plotH();
    const anomaly = token('--st-anomaly');
    const left = MARGINS.l * dpr;
    const right = canvas.width - MARGINS.r * dpr;
    for (let idx = 0; idx < incidents.length; idx++) {
      const iv = incidents[idx];
      const x0 = px(iv.start);
      const x1 = px(iv.end);
      if (x1 < left - 1 || x0 > right + 1) continue;
      const w = Math.max(x1 - x0, 2 * dpr);
      const isSel = labeling && iv === selIncident;
      g.fillStyle = rgba(anomaly, isSel ? 0.3 : 0.16);
      g.fillRect(x0, top, w, h);
      g.strokeStyle = rgba(anomaly, isSel ? 0.95 : 0.5);
      g.lineWidth = (isSel ? 2 : 1) * dpr;
      g.strokeRect(x0, top, w, h);
      if (labeling) {
        g.fillStyle = rgba(anomaly, 0.95);
        g.fillRect(x0 - 1.5 * dpr, top, 3 * dpr, h);
        g.fillRect(x1 - 1.5 * dpr, top, 3 * dpr, h);
        if (x1 - x0 >= 22 * dpr || isSel) drawDelHandle(x1, isSel || idx === hoverDelIdx);
      }
    }
    if (labeling && incidentDrag && incidentDrag.mode === 'new') {
      const x0 = px(incidentDrag.a);
      const x1 = px(incidentDrag.b);
      g.fillStyle = rgba(token('--st-nodata'), 0.28);
      g.fillRect(Math.min(x0, x1), top, Math.abs(x1 - x0), h);
    }
  }

  // Emit the LIVE array (not a copy) so the caller and chart share one source of
  // truth — list-edited labels and drag-edited spans never diverge.
  function emitIncidents(): void {
    opts.onIncidentsChange?.(incidents);
  }

  function removeIncident(iv: Incident): void {
    const k = incidents.indexOf(iv);
    if (k < 0) return;
    incidents.splice(k, 1);
    if (selIncident === iv) selIncident = null;
    hoverDelIdx = -1;
    emitIncidents();
    schedule();
  }

  // Hit-test incidents in device px: ✕ handle first, then edges, then body.
  function hitIncident(devX: number, devY: number): { i: number; edge: 'del' | 'a' | 'b' | 'move' } | null {
    const top = MARGINS.t * dpr;
    const EDGE = 6 * dpr;
    for (let i = 0; i < incidents.length; i++) {
      const x1 = px(incidents[i].end);
      if (x1 - px(incidents[i].start) >= 22 * dpr || incidents[i] === selIncident) {
        const s = 14 * dpr;
        const m = 3 * dpr;
        const hx0 = x1 - s - m;
        const hy0 = top + m;
        if (devX >= hx0 && devX <= hx0 + s && devY >= hy0 && devY <= hy0 + s) return { i, edge: 'del' };
      }
    }
    for (let i = 0; i < incidents.length; i++) {
      const xa = px(incidents[i].start);
      const xb = px(incidents[i].end);
      if (Math.abs(devX - xa) <= EDGE) return { i, edge: 'a' };
      if (Math.abs(devX - xb) <= EDGE) return { i, edge: 'b' };
    }
    for (let i = 0; i < incidents.length; i++) {
      const xa = px(incidents[i].start);
      const xb = px(incidents[i].end);
      if (devX > xa + EDGE && devX < xb - EDGE) return { i, edge: 'move' };
    }
    return null;
  }

  // Smallest editable span (a few grid steps) so an edge/move never collapses.
  const incidentMinStep = (): number => {
    const s = data?.series;
    const n = s ? s.timestamps.length : 0;
    return n > 1 ? Math.max(fullSpan() / (n - 1), 1) : 1000;
  };

  function schedule(): void {
    if (raf === 0) raf = requestAnimationFrame(paint);
  }

  // Compute the effective zone + emit live lasso capture counts from current data.
  function emitLassoNow(): void {
    if (!data) return;
    const n = data.scored.length;
    const eff = Math.min(effectiveStartIndex(data.series, data.params), n);
    emitLasso(data.scored, eff, n);
  }

  // ---- interaction ----------------------------------------------------------
  function emitHover(): void {
    if (!opts.onHover || !data) return;
    if (hoverIndex < 0) {
      opts.onHover(null);
      return;
    }
    const p = data.scored[hoverIndex] ?? null;
    const info: HoverInfo = {
      index: hoverIndex,
      point: p,
      windowStart: Math.max(0, hoverIndex - data.params.windowSize),
      windowEnd: hoverIndex - 1,
    };
    opts.onHover(info);
  }

  // ---- navigation drag state (navigable mode only) --------------------------
  let pan: { x: number; vMin: number; vMax: number } | null = null;
  let navDrag: { type: 'move' | 'l' | 'r'; grab: number; vMin: number; vMax: number } | null = null;

  const devOf = (ev: MouseEvent): { x: number; y: number } => {
    const r = canvas.getBoundingClientRect();
    return { x: (ev.clientX - r.left) * dpr, y: (ev.clientY - r.top) * dpr };
  };
  const inNav = (devY: number): boolean => hasNav && devY >= navTop();
  const navHit = (devX: number): 'l' | 'r' | 'move' | 'out' => {
    const xl = navPx(viewMin);
    const xr = navPx(viewMax);
    const H = 8 * dpr;
    if (Math.abs(devX - xl) <= H) return 'l';
    if (Math.abs(devX - xr) <= H) return 'r';
    if (devX > xl && devX < xr) return 'move';
    return 'out';
  };

  function onMove(ev: MouseEvent): void {
    if (!data) return;
    const { x: devX, y: devY } = devOf(ev);
    if (pan || navDrag || incidentDrag) return; // active drag is handled on window
    if (inNav(devY)) {
      // over the navigator strip: no hover; hint the grab/resize affordance
      if (hoverIndex !== -1) {
        hoverIndex = -1;
        emitHover();
        schedule();
      }
      const hit = navHit(devX);
      canvas.style.cursor = hit === 'l' || hit === 'r' ? 'ew-resize' : hit === 'move' ? 'grab' : 'pointer';
      return;
    }
    if (labeling && lassoMode) {
      // lasso capture: the freeform loop is drawn on the window-level drag handler;
      // here just keep the crosshair and suppress point hover.
      if (hoverIndex !== -1) {
        hoverIndex = -1;
        emitHover();
      }
      canvas.style.cursor = 'crosshair';
      return;
    }
    if (labeling && thMode) {
      // threshold capture: the cursor's Y sets the candidate line (unless pinned).
      // While a press is active (thDown), the drag is a window paint handled in
      // onWinMove — don't also move the line here.
      if (hoverIndex !== -1) {
        hoverIndex = -1;
        emitHover();
      }
      if (thLockedVal == null && !thDown) {
        thHoverVal = vAtDevY(devY);
        emitThreshold();
        schedule();
      }
      canvas.style.cursor = 'crosshair';
      return;
    }
    if (labeling) {
      // over the plot in labeling mode: hint create/move/resize/delete; no point hover.
      if (hoverIndex !== -1) {
        hoverIndex = -1;
        emitHover();
      }
      const hit = hitIncident(devX, devY);
      const nextDel = hit && hit.edge === 'del' ? hit.i : -1;
      if (nextDel !== hoverDelIdx) {
        hoverDelIdx = nextDel;
        schedule();
      }
      canvas.style.cursor = hit
        ? hit.edge === 'del'
          ? 'pointer'
          : hit.edge === 'move'
            ? 'grab'
            : 'ew-resize'
        : 'crosshair';
      return;
    }
    if (navigable) canvas.style.cursor = 'grab';
    const idx = nearestIndex(devX);
    if (idx !== hoverIndex) {
      hoverIndex = idx;
      emitHover();
      schedule();
    }
  }

  function onLeave(): void {
    if (hoverIndex !== -1) {
      hoverIndex = -1;
      emitHover();
      schedule();
    }
  }

  function onDown(ev: MouseEvent): void {
    if (!navigable || !data) return;
    const { x: devX, y: devY } = devOf(ev);
    if (hasNav && devY >= navTop()) {
      const hit = navHit(devX);
      if (hit === 'l') navDrag = { type: 'l', grab: 0, vMin: viewMin, vMax: viewMax };
      else if (hit === 'r') navDrag = { type: 'r', grab: 0, vMin: viewMin, vMax: viewMax };
      else if (hit === 'move')
        navDrag = { type: 'move', grab: navTsAtDevX(devX), vMin: viewMin, vMax: viewMax };
      else {
        const t = navTsAtDevX(devX);
        const s = tspan();
        setView(t - s / 2, t + s / 2);
        navDrag = { type: 'move', grab: t, vMin: viewMin, vMax: viewMax };
      }
      canvas.style.cursor = 'grabbing';
      ev.preventDefault();
      return;
    }
    // plot area (everything above the navigator strip / bottom margin)
    if (devY > MARGINS.t * dpr && devY < canvas.height - MARGINS.b * dpr - navTotal()) {
      if (labeling && lassoMode) {
        // start a freeform loop; points accumulate on the window-level drag.
        lassoPath = [{ x: devX, y: devY }];
        emitLassoNow();
        canvas.style.cursor = 'crosshair';
        schedule();
        ev.preventDefault();
        return;
      }
      if (labeling && thMode) {
        // a press either sets the line (a click) or paints a capture window (a
        // horizontal drag) — resolved on mouseup by how far it moved.
        thDown = { x: devX, ts: tsAtDevX(devX) };
        if (thLockedVal == null) thHoverVal = vAtDevY(devY);
        emitThreshold();
        schedule();
        ev.preventDefault();
        return;
      }
      if (labeling) {
        const t = tsAtDevX(devX);
        const hit = hitIncident(devX, devY);
        if (hit && hit.edge === 'del') {
          removeIncident(incidents[hit.i]);
          ev.preventDefault();
          return;
        }
        if (hit && hit.edge === 'move') {
          const iv = incidents[hit.i];
          selIncident = iv;
          incidentDrag = { mode: 'move', iv, grab: t, a0: iv.start, b0: iv.end, moved: false };
        } else if (hit) {
          const iv = incidents[hit.i];
          selIncident = iv;
          incidentDrag = { mode: 'edge', iv, edge: hit.edge, moved: false };
        } else {
          selIncident = null;
          incidentDrag = { mode: 'new', a: t, b: t, moved: false };
        }
        canvas.style.cursor = 'crosshair';
        schedule();
        ev.preventDefault();
        return;
      }
      pan = { x: devX, vMin: viewMin, vMax: viewMax };
      canvas.style.cursor = 'grabbing';
      ev.preventDefault();
    }
  }

  function onWinMove(ev: MouseEvent): void {
    if (!data) return;
    const { x: devX, y: devY } = devOf(ev);
    if (lassoMode && lassoPath) {
      lassoPath.push({ x: devX, y: devY });
      emitLassoNow();
      schedule();
      return;
    }
    if (thMode && thDown) {
      // a far-enough horizontal move paints a capture window; otherwise keep
      // tracking the cursor's Y as the candidate line value.
      if (Math.abs(devX - thDown.x) > 6 * dpr) {
        thDragWin = { a: thDown.ts, b: tsAtDevX(devX) };
      } else {
        thDragWin = null;
        if (thLockedVal == null) thHoverVal = vAtDevY(devY);
      }
      emitThreshold();
      schedule();
      return;
    }
    if (incidentDrag) {
      const t = tsAtDevX(devX);
      if (incidentDrag.mode === 'new') {
        incidentDrag.b = t;
        if (Math.abs(px(incidentDrag.b) - px(incidentDrag.a)) > 4 * dpr) incidentDrag.moved = true;
      } else if (incidentDrag.mode === 'edge') {
        const iv = incidentDrag.iv;
        const ms = incidentMinStep();
        if (incidentDrag.edge === 'a') iv.start = clampNum(Math.min(t, iv.end - ms), tmin, tmax);
        else iv.end = clampNum(Math.max(t, iv.start + ms), tmin, tmax);
        incidentDrag.moved = true;
      } else {
        const iv = incidentDrag.iv;
        let na = incidentDrag.a0 + (t - incidentDrag.grab);
        let nb = incidentDrag.b0 + (t - incidentDrag.grab);
        if (na < tmin) {
          nb += tmin - na;
          na = tmin;
        }
        if (nb > tmax) {
          na -= nb - tmax;
          nb = tmax;
        }
        iv.start = clampNum(na, tmin, tmax);
        iv.end = clampNum(nb, tmin, tmax);
        incidentDrag.moved = true;
      }
      schedule();
      return;
    }
    if (pan) {
      const d = ((devX - pan.x) * (pan.vMax - pan.vMin)) / (plotW() || 1);
      setView(pan.vMin - d, pan.vMax - d);
    } else if (navDrag) {
      const t = navTsAtDevX(devX);
      if (navDrag.type === 'l') setView(Math.min(t, viewMax - minSpan()), viewMax);
      else if (navDrag.type === 'r') setView(viewMin, Math.max(t, viewMin + minSpan()));
      else setView(navDrag.vMin + (t - navDrag.grab), navDrag.vMax + (t - navDrag.grab));
    }
  }

  function onUp(ev: MouseEvent): void {
    if (lassoMode && lassoPath) {
      commitLasso();
      lassoPath = null;
      emitLassoNow();
      schedule();
      return;
    }
    if (thMode && thDown) {
      const { x: devX, y: devY } = devOf(ev);
      if (Math.abs(devX - thDown.x) > 6 * dpr) {
        // a drag → commit the painted capture window
        const a = thDown.ts;
        const b = tsAtDevX(devX);
        capWin = { a: Math.min(a, b), b: Math.max(a, b) };
      } else {
        // a click → pin the line value at the cursor's Y
        thLockedVal = vAtDevY(devY);
      }
      thDown = null;
      thDragWin = null;
      emitThreshold();
      schedule();
      return;
    }
    if (incidentDrag) {
      const drag = incidentDrag;
      if (drag.mode === 'new') {
        if (drag.moved) {
          const a = clampNum(Math.min(drag.a, drag.b), tmin, tmax);
          const b = clampNum(Math.max(drag.a, drag.b), tmin, tmax);
          const iv: Incident = { start: a, end: b, label: '' };
          incidents.push(iv);
          selIncident = iv;
        } else {
          selIncident = null; // a plain click on empty space clears the selection
        }
      } else if (drag.iv.start > drag.iv.end) {
        const t = drag.iv.start;
        drag.iv.start = drag.iv.end;
        drag.iv.end = t;
      }
      incidentDrag = null;
      canvas.style.cursor = 'crosshair';
      if (drag.moved) emitIncidents();
      schedule();
      return;
    }
    if (pan || navDrag) {
      pan = null;
      navDrag = null;
      canvas.style.cursor = 'grab';
    }
  }

  function onKey(ev: KeyboardEvent): void {
    const t = ev.target as HTMLElement | null;
    const typing = !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
    // In lasso mode the selection is inert; Escape abandons an in-progress loop.
    if (lassoMode) {
      if (ev.key === 'Escape' && lassoPath) {
        lassoPath = null;
        emitLassoNow();
        schedule();
      }
      return;
    }
    // In threshold mode the selection is inert — don't let Delete remove a band.
    if (thMode || typing || !selIncident) return;
    if (ev.key === 'Delete' || ev.key === 'Backspace') {
      ev.preventDefault();
      removeIncident(selIncident);
    } else if (ev.key === 'Escape') {
      selIncident = null;
      schedule();
    }
  }

  function onWheel(ev: WheelEvent): void {
    if (!navigable || !data) return;
    // Don't let a zoom distort the device-px loop mid-draw.
    if (lassoMode && lassoPath) {
      ev.preventDefault();
      return;
    }
    ev.preventDefault();
    const { x: devX, y: devY } = devOf(ev);
    const s = clampNum(tspan() * Math.pow(1.0015, ev.deltaY), minSpan(), fullSpan());
    if (devY >= navTop()) {
      // over the navigator: center the new span on the cursor
      const t = navTsAtDevX(devX);
      setView(t - s / 2, t + s / 2);
    } else {
      // over the plot: keep the point under the cursor fixed (zoom to cursor)
      const t = tsAtDevX(devX);
      const f = (t - viewMin) / (tspan() || 1);
      setView(t - f * s, t - f * s + s);
    }
  }

  function onDbl(): void {
    if (navigable) setView(tmin, tmax);
  }

  canvas.addEventListener('mousemove', onMove);
  canvas.addEventListener('mouseleave', onLeave);
  if (navigable) {
    canvas.addEventListener('mousedown', onDown);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('dblclick', onDbl);
    window.addEventListener('mousemove', onWinMove);
    window.addEventListener('mouseup', onUp);
  }
  if (labeling) {
    window.addEventListener('keydown', onKey);
    canvas.style.cursor = 'crosshair';
  }

  // ---- public handle --------------------------------------------------------
  function render(next: ChartData): void {
    data = next;
    // A read-only chart takes incidents from render data; a labeling chart owns
    // them (seed/replace via setIncidents), so don't clobber in-progress edits.
    if (!labeling && next.incidents) incidents = next.incidents;
    computeDomain(next.series, next.scored);
    if (hoverIndex >= next.series.timestamps.length) hoverIndex = -1;
    schedule();
  }

  function setZeroLine(on: boolean): void {
    if (showZero === on) return;
    showZero = on;
    if (data) computeDomain(data.series, data.scored);
    schedule();
  }

  // Adopt the array by reference (shared source of truth — see emitIncidents) and
  // drop any stale selection into it.
  function setIncidents(list: Incident[]): void {
    incidents = list;
    selIncident = null;
    hoverDelIdx = -1;
    schedule();
  }

  // ---- threshold-capture public API (labeling charts only) ------------------
  function setThresholdMode(on: boolean): void {
    if (!labeling) return;
    thMode = on;
    if (!on) {
      thHoverVal = null;
      thDown = null;
      thDragWin = null;
    } else {
      selIncident = null;
      // mutually exclusive with the lasso tool.
      lassoMode = false;
      lassoPath = null;
      emitLassoNow();
    }
    canvas.style.cursor = 'crosshair';
    emitThreshold();
    schedule();
  }
  // Toggle the freeform lasso tool (mutually exclusive with threshold capture).
  function setLassoMode(on: boolean): void {
    if (!labeling) return;
    lassoMode = on;
    if (on) {
      thMode = false;
      thDown = null;
      thDragWin = null;
      thHoverVal = null;
      selIncident = null;
      emitThreshold();
    } else {
      lassoPath = null;
    }
    canvas.style.cursor = 'crosshair';
    emitLassoNow();
    schedule();
  }
  function setThresholdDirection(dir: 'above' | 'below'): void {
    thDir = dir;
    emitThreshold();
    schedule();
  }
  function setThresholdGap(gap: number): void {
    thGap = Math.max(0, Math.floor(gap) || 0);
    emitThreshold();
    schedule();
  }
  function setThresholdValue(value: number | null): void {
    thLockedVal = value != null && isFinite(value) ? value : null;
    emitThreshold();
    schedule();
  }
  function applyThreshold(): number {
    const runs = thRuns();
    // Pad each captured run half an interval each side so a single matching point
    // becomes a full-interval-wide incident (not a zero-width point the fired
    // alert lands just outside of) — the recall-undercount fix on the capture side.
    const half = intervalMs() / 2;
    for (const [a, b] of runs) addCaptured(a - half, b + half);
    if (runs.length) emitIncidents();
    emitThreshold();
    schedule();
    return runs.length;
  }
  function clearCaptureWindow(): void {
    capWin = null;
    thDragWin = null;
    emitThreshold();
    schedule();
  }
  function getCaptureWindow(): { start: number; end: number } | null {
    if (!capWin) return null;
    return { start: Math.min(capWin.a, capWin.b), end: Math.max(capWin.a, capWin.b) };
  }
  function setCaptureWindow(win: { start: number; end: number } | null): void {
    capWin = win ? { a: win.start, b: win.end } : null;
    emitThreshold();
    schedule();
  }

  function resize(): void {
    fit();
    if (data) {
      computeDomain(data.series, data.scored);
      schedule();
    }
  }

  function destroy(): void {
    canvas.removeEventListener('mousemove', onMove);
    canvas.removeEventListener('mouseleave', onLeave);
    if (navigable) {
      canvas.removeEventListener('mousedown', onDown);
      canvas.removeEventListener('wheel', onWheel);
      canvas.removeEventListener('dblclick', onDbl);
      window.removeEventListener('mousemove', onWinMove);
      window.removeEventListener('mouseup', onUp);
    }
    if (labeling) window.removeEventListener('keydown', onKey);
    if (raf !== 0) cancelAnimationFrame(raf);
    raf = 0;
    data = null;
  }

  fit();
  return {
    render,
    resize,
    setZeroLine,
    setViewWindow,
    setIncidents,
    setThresholdMode,
    setThresholdDirection,
    setThresholdGap,
    setThresholdValue,
    applyThreshold,
    setLassoMode,
    clearCaptureWindow,
    getCaptureWindow,
    setCaptureWindow,
    destroy,
  };
}

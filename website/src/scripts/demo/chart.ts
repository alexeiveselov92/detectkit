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

  let dpr = 1;
  let data: ChartData | null = null;
  let hoverIndex = -1;
  let raf = 0;

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

  // Reserve a navigator strip at the bottom in navigable mode; the main plot
  // shrinks by exactly that much so nothing else moves.
  const navTotal = (): number => (navigable ? (NAV_GAP + NAV_H) * dpr : 0);
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
    schedule();
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
    for (const p of scored) {
      if (p.scored) {
        if (isFinite(p.lower) && p.lower < lo) lo = p.lower;
        if (isFinite(p.upper) && p.upper > hi) hi = p.upper;
      }
    }
    if (!isFinite(lo) || !isFinite(hi)) {
      lo = 0;
      hi = 1;
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

    // Effective-zone start: the first index where the detector runs at full
    // power. Everything before it (the degraded warm-up lead-in) gets no band,
    // no center line and no anomaly dots — only the dimming overlay + the
    // context metric line. effTs is the divider timestamp (undefined if the
    // whole series is in the effective zone).
    const n = scored.length;
    const eff = Math.min(effectiveStartIndex(series, params), n);
    const effTs = eff < n ? series.timestamps[eff] : undefined;
    const runs = scoredRuns(scored, eff);

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
    if (params.smoothing !== 'none') {
      drawSeries(series.values, rgba(clay, 0.28), 1.25);
      const processed = scored.map((p) => p.processedValue);
      drawSeries(processed, clay, 1.6);
    } else {
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
    if (effTs !== undefined) {
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

    g.restore();

    // 9. navigator strip (navigable mode) — the whole series in miniature with
    // the current view window, alert ticks and a time axis, so a zoomed-in view
    // never loses the big picture.
    if (navigable) drawNavigator(series, alerts, clay, faint, muted);
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

  function schedule(): void {
    if (raf === 0) raf = requestAnimationFrame(paint);
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
  const inNav = (devY: number): boolean => navigable && devY >= navTop();
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
    if (pan || navDrag) return; // active drag is handled on window
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
    if (devY >= navTop()) {
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
    } else if (devY > MARGINS.t * dpr && devY < navTop() - NAV_GAP * dpr) {
      pan = { x: devX, vMin: viewMin, vMax: viewMax };
      canvas.style.cursor = 'grabbing';
      ev.preventDefault();
    }
  }

  function onWinMove(ev: MouseEvent): void {
    if (!data) return;
    const { x: devX } = devOf(ev);
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

  function onUp(): void {
    if (pan || navDrag) {
      pan = null;
      navDrag = null;
      canvas.style.cursor = 'grab';
    }
  }

  function onWheel(ev: WheelEvent): void {
    if (!navigable || !data) return;
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

  // ---- public handle --------------------------------------------------------
  function render(next: ChartData): void {
    data = next;
    computeDomain(next.series, next.scored);
    if (hoverIndex >= next.series.timestamps.length) hoverIndex = -1;
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
    if (raf !== 0) cancelAnimationFrame(raf);
    raf = 0;
    data = null;
  }

  fit();
  return { render, resize, destroy };
}

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
  drawSeriesDecimated,
  fit as fitCanvas,
  fmtTick,
  fmtVal,
  rgba,
  token,
} from '../core/canvas';
import type { ChartData, ChartHandle, ChartOptions, HoverInfo, ScoredPoint, Series } from './types';

const MARGINS: Margins = { l: 52, r: 14, t: 14, b: 26 };

const isFinite = Number.isFinite;

export function createChart(canvas: HTMLCanvasElement, opts: ChartOptions = {}): ChartHandle {
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('chart: 2D context unavailable');
  const g = ctx; // non-null alias

  let dpr = 1;
  let data: ChartData | null = null;
  let hoverIndex = -1;
  let raf = 0;

  // Domain, recomputed per render.
  let tmin = 0;
  let tmax = 1;
  let vmin = 0;
  let vmax = 1;

  // ---- DPR-aware sizing (shared core/canvas.fit) ----------------------------
  function fit(): void {
    dpr = fitCanvas(canvas);
  }

  const plotW = (): number => canvas.width - (MARGINS.l + MARGINS.r) * dpr;
  const plotH = (): number => canvas.height - (MARGINS.t + MARGINS.b) * dpr;
  const tspan = (): number => tmax - tmin || 1;
  const px = (ts: number): number => MARGINS.l * dpr + ((ts - tmin) / tspan()) * plotW();
  const py = (v: number): number =>
    canvas.height - MARGINS.b * dpr - ((v - vmin) / (vmax - vmin || 1)) * plotH();

  // Inverse of px: nearest series index for a device-px X coordinate.
  function nearestIndex(devX: number): number {
    const s = data?.series;
    if (!s || s.timestamps.length === 0) return -1;
    const frac = (devX - MARGINS.l * dpr) / (plotW() || 1);
    const ts = tmin + frac * tspan();
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
  // The whole series is always in view (no zoom/pan), so lo/hi span the domain.
  function drawSeries(values: number[], color: string, lw: number): void {
    const ts = data!.series.timestamps;
    drawSeriesDecimated(g, ts, values, tmin, tmax, MARGINS.l * dpr, plotW(), px, py, color, lw, dpr);
  }

  // Contiguous runs of scored points with finite band bounds (warm-up / NaN-band
  // gaps break a run), so the corridor polygon never bridges un-scored regions.
  function scoredRuns(scored: ScoredPoint[]): Array<[number, number]> {
    const runs: Array<[number, number]> = [];
    let start = -1;
    for (let i = 0; i < scored.length; i++) {
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
    const { series, scored, params } = data;
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
    const spanMs = tspan();
    for (let i = 0; i <= 5; i++) {
      const ts = tmin + (spanMs * i) / 5;
      const xx = px(ts);
      g.fillStyle = muted;
      g.textAlign = i === 0 ? 'left' : i === 5 ? 'right' : 'center';
      g.fillText(fmtTick(ts, spanMs), xx, (canvas.height - MARGINS.b + 7) * dpr);
    }

    // clip to the plot rect for everything data-related
    g.save();
    g.beginPath();
    g.rect(MARGINS.l * dpr, MARGINS.t * dpr, plotW(), plotH());
    g.clip();

    const runs = scoredRuns(scored);

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

    // 4. metric line
    drawSeries(series.values, clay, 1.5);

    // 5. anomaly markers (flagged dots) + missed-truth rings
    for (let i = 0; i < scored.length; i++) {
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

    // 6. window overlay (hover)
    if (hoverIndex >= 0 && hoverIndex < scored.length) {
      drawWindowOverlay(hoverIndex, params.windowSize, scored, series, faint);
    }

    g.restore();
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

  function onMove(ev: MouseEvent): void {
    if (!data) return;
    const rect = canvas.getBoundingClientRect();
    const devX = (ev.clientX - rect.left) * dpr;
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

  canvas.addEventListener('mousemove', onMove);
  canvas.addEventListener('mouseleave', onLeave);

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
    if (raf !== 0) cancelAnimationFrame(raf);
    raf = 0;
    data = null;
  }

  fit();
  return { render, resize, destroy };
}

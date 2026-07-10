// Framework-free HTML5 Canvas 2D primitives, shared by the landing demo chart
// (src/scripts/demo/chart.ts) and the library report renderer
// (src/scripts/report/report.ts).
//
// These are extracted verbatim (behaviour-identical) from the demo chart logic:
// a brand-token reader, hex → rgb(a) parsing, DPR-aware canvas fitting, a scales
// factory (px/py over a domain + margins), a min/max-decimated series line (NaN
// breaks the pen), a translucent confidence band over contiguous scored runs,
// anomaly dots, gridlines + axis ticks, and value/timestamp formatters.
//
// Nothing here is detectkit-specific or report-specific; both renderers compose
// these into their own frames.

export interface Margins {
  l: number;
  r: number;
  t: number;
  b: number;
}

// ----------------------------------------------------------------------------
// Brand tokens
// ----------------------------------------------------------------------------

// Brand token fallbacks (hex). The report is rendered inside a Python-generated
// standalone HTML where :root may not define these vars, so the fallbacks must
// stand on their own. In the site demo the live :root values win.
export const TOKEN_FALLBACKS: Record<string, string> = {
  '--term-bg': '#211e1a',
  '--clay': '#d15b36',
  '--st-anomaly': '#d63232',
  '--st-recovery': '#36a64f',
  '--st-nodata': '#f0ad4e',
  '--st-error': '#5a7a8c',
  '--faint': '#9a9384',
  '--muted': '#6e675b',
  '--border': '#332f29',
  '--term-border': '#332f29',
};

/** Read a brand CSS custom property off :root, falling back to a known hex. */
export function token(name: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || TOKEN_FALLBACKS[name] || '#888';
}

// Parse "#rgb" / "#rrggbb" into [r,g,b] for translucent fills.
export function rgb(hex: string): [number, number, number] {
  let h = hex.replace('#', '').trim();
  if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
  const n = parseInt(h, 16);
  if (h.length !== 6 || Number.isNaN(n)) return [209, 91, 54]; // clay
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function rgba(hex: string, a: number): string {
  const [r, g, b] = rgb(hex);
  return `rgba(${r},${g},${b},${a})`;
}

// ----------------------------------------------------------------------------
// Sizing
// ----------------------------------------------------------------------------

/**
 * DPR-aware backing-store fit. Sizes the canvas' pixel buffer to its CSS box ×
 * devicePixelRatio. Returns the dpr used so the caller can scale line widths /
 * fonts.
 */
export function fit(canvas: HTMLCanvasElement): number {
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  const w = canvas.clientWidth || canvas.offsetWidth || 0;
  const h = canvas.clientHeight || canvas.offsetHeight || 0;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  return dpr;
}

// ----------------------------------------------------------------------------
// Scales
// ----------------------------------------------------------------------------

export interface Domain {
  tmin: number;
  tmax: number;
  vmin: number;
  vmax: number;
}

export interface Scales {
  /** time-axis → device-px X */
  px(ts: number): number;
  /** value-axis → device-px Y */
  py(v: number): number;
  /** inverse of px: device-px X → timestamp */
  tAt(devX: number): number;
  /** inverse of py: device-px Y → value */
  vAt(devY: number): number;
  /** device-px width of the plot rect */
  plotW(): number;
  /** device-px height of the plot rect */
  plotH(): number;
  /** time-axis span (tmax - tmin, floored at 1) */
  tspan(): number;
}

/**
 * Build the px/py mapping for a domain + margins on a canvas at a given dpr.
 * Identical math to the demo chart: device-px space, origin top-left, y
 * inverted.
 */
export function makeScales(
  canvas: HTMLCanvasElement,
  m: Margins,
  dom: Domain,
  dpr: number,
): Scales {
  const plotW = (): number => canvas.width - (m.l + m.r) * dpr;
  const plotH = (): number => canvas.height - (m.t + m.b) * dpr;
  const tspan = (): number => dom.tmax - dom.tmin || 1;
  const vspan = (): number => dom.vmax - dom.vmin || 1;
  const px = (ts: number): number => m.l * dpr + ((ts - dom.tmin) / tspan()) * plotW();
  const py = (v: number): number => canvas.height - m.b * dpr - ((v - dom.vmin) / vspan()) * plotH();
  const tAt = (devX: number): number => dom.tmin + ((devX - m.l * dpr) / (plotW() || 1)) * tspan();
  const vAt = (devY: number): number =>
    dom.vmin + ((canvas.height - m.b * dpr - devY) / (plotH() || 1)) * vspan();
  return { px, py, tAt, vAt, plotW, plotH, tspan };
}

// ----------------------------------------------------------------------------
// Series line (min/max decimation)
// ----------------------------------------------------------------------------

const isFiniteNum = Number.isFinite;

/**
 * Draw a value series as a min/max-decimated envelope (one column per device
 * pixel) so a 100k-point series stays fast and spikes stay visible. When few
 * points are visible (zoomed in) it falls back to a direct polyline. A
 * non-finite value (NaN gap) breaks the pen, exactly like the demo chart's
 * series renderer.
 *
 * `lo`/`hi` bound the time range that should be drawn (the current view); points
 * outside it are skipped. `left`/`width` are device-px geometry of the plot rect.
 */
export function drawSeriesDecimated(
  g: CanvasRenderingContext2D,
  timestamps: ArrayLike<number>,
  values: ArrayLike<number>,
  lo: number,
  hi: number,
  left: number,
  width: number,
  px: (ts: number) => number,
  py: (v: number) => number,
  color: string,
  lw: number,
  dpr: number,
): void {
  const n = timestamps.length;
  const cols = Math.max(1, Math.round(width));
  const sp = hi - lo || 1;

  let vis = 0;
  for (let i = 0; i < n; i++) {
    const v = values[i];
    if (!isFiniteNum(v) || timestamps[i] < lo || timestamps[i] > hi) continue;
    vis++;
  }

  g.strokeStyle = color;
  g.lineWidth = lw * dpr;
  g.lineJoin = 'round';
  g.beginPath();

  if (vis <= cols) {
    // Direct polyline; NaN / out-of-range breaks the pen.
    let pen = false;
    for (let i = 0; i < n; i++) {
      const v = values[i];
      const ts = timestamps[i];
      if (!isFiniteNum(v) || ts < lo || ts > hi) {
        pen = false;
        continue;
      }
      const X = px(ts);
      const Y = py(v);
      if (!pen) {
        g.moveTo(X, Y);
        pen = true;
      } else {
        g.lineTo(X, Y);
      }
    }
  } else {
    // One envelope column per pixel: track per-column min/max, draw high→low.
    const cmin = new Array<number | null>(cols).fill(null);
    const cmax = new Array<number | null>(cols).fill(null);
    for (let i = 0; i < n; i++) {
      const v = values[i];
      const ts = timestamps[i];
      if (!isFiniteNum(v) || ts < lo || ts > hi) continue;
      let col = Math.floor(((ts - lo) / sp) * (cols - 1));
      col = col < 0 ? 0 : col > cols - 1 ? cols - 1 : col;
      if (cmin[col] === null || v < (cmin[col] as number)) cmin[col] = v;
      if (cmax[col] === null || v > (cmax[col] as number)) cmax[col] = v;
    }
    let pen = false;
    for (let col = 0; col < cols; col++) {
      if (cmax[col] === null) {
        pen = false;
        continue;
      }
      const X = left + col;
      const yh = py(cmax[col] as number);
      const yl = py(cmin[col] as number);
      if (!pen) {
        g.moveTo(X, yh);
        pen = true;
      } else {
        g.lineTo(X, yh);
      }
      g.lineTo(X, yl);
    }
  }
  g.stroke();
}

// ----------------------------------------------------------------------------
// Confidence band
// ----------------------------------------------------------------------------

/** One scored point of a band: timestamp + lower/upper bound (null = un-scored). */
export interface BandPoint {
  t: number;
  lo: number | null;
  hi: number | null;
}

/**
 * Contiguous runs of points with finite band bounds, as [start, end] inclusive
 * index pairs. A warm-up / NaN-band gap breaks a run so the corridor polygon
 * never bridges an un-scored region.
 */
export function scoredRuns(pts: ArrayLike<BandPoint>): Array<[number, number]> {
  const runs: Array<[number, number]> = [];
  let start = -1;
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i];
    const ok = p.lo !== null && p.hi !== null && isFiniteNum(p.lo) && isFiniteNum(p.hi);
    if (ok) {
      if (start === -1) start = i;
    } else if (start !== -1) {
      runs.push([start, i - 1]);
      start = -1;
    }
  }
  if (start !== -1) runs.push([start, pts.length - 1]);
  return runs;
}

/**
 * Fill a translucent corridor between lower/upper over each contiguous scored
 * run, then stroke faint top/bottom edges. `hexColor` is the band's accent; the
 * fill uses `fillAlpha` and the edges `edgeAlpha`.
 */
export function fillBand(
  g: CanvasRenderingContext2D,
  pts: ArrayLike<BandPoint>,
  runs: Array<[number, number]>,
  px: (ts: number) => number,
  py: (v: number) => number,
  hexColor: string,
  fillAlpha: number,
  edgeAlpha: number,
  dpr: number,
): void {
  g.fillStyle = rgba(hexColor, fillAlpha);
  for (const [a, b] of runs) {
    g.beginPath();
    g.moveTo(px(pts[a].t), py(pts[a].hi as number));
    for (let i = a + 1; i <= b; i++) g.lineTo(px(pts[i].t), py(pts[i].hi as number));
    for (let i = b; i >= a; i--) g.lineTo(px(pts[i].t), py(pts[i].lo as number));
    g.closePath();
    g.fill();
  }
  g.strokeStyle = rgba(hexColor, edgeAlpha);
  g.lineWidth = 1 * dpr;
  for (const [a, b] of runs) {
    for (const bound of ['hi', 'lo'] as const) {
      g.beginPath();
      for (let i = a; i <= b; i++) {
        const X = px(pts[i].t);
        const Y = py(pts[i][bound] as number);
        if (i === a) g.moveTo(X, Y);
        else g.lineTo(X, Y);
      }
      g.stroke();
    }
  }
}

// ----------------------------------------------------------------------------
// Anomaly dots
// ----------------------------------------------------------------------------

/** One flagged point to mark: device-independent (ts, value). */
export interface AnomalyMark {
  t: number;
  v: number;
}

/**
 * Draw flagged-anomaly markers: a translucent halo + a solid core dot at each
 * (t, v), skipping non-finite values and points outside [lo, hi].
 */
export function drawAnomalyDots(
  g: CanvasRenderingContext2D,
  marks: ArrayLike<AnomalyMark>,
  lo: number,
  hi: number,
  px: (ts: number) => number,
  py: (v: number) => number,
  hexColor: string,
  dpr: number,
): void {
  for (let i = 0; i < marks.length; i++) {
    const m = marks[i];
    if (!isFiniteNum(m.v) || m.t < lo || m.t > hi) continue;
    const X = px(m.t);
    const Y = py(m.v);
    g.fillStyle = rgba(hexColor, 0.18);
    g.beginPath();
    g.arc(X, Y, 6 * dpr, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = hexColor;
    g.beginPath();
    g.arc(X, Y, 3 * dpr, 0, Math.PI * 2);
    g.fill();
  }
}

// ----------------------------------------------------------------------------
// Gridlines + axis ticks
// ----------------------------------------------------------------------------

/**
 * Paint horizontal value gridlines + right-aligned value labels in the left
 * gutter, and bottom-axis time ticks across the view. `tickLo`/`tickHi` bound
 * the visible time range so labels track zoom/pan.
 */
export function drawGridAndAxes(
  g: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  m: Margins,
  dom: Domain,
  px: (ts: number) => number,
  py: (v: number) => number,
  tickLo: number,
  tickHi: number,
  faintHex: string,
  mutedHex: string,
  dpr: number,
): void {
  g.font = `${11 * dpr}px ui-monospace, 'JetBrains Mono', monospace`;
  g.textBaseline = 'middle';
  for (let i = 0; i <= 4; i++) {
    const v = dom.vmin + ((dom.vmax - dom.vmin) * i) / 4;
    const yy = py(v);
    g.strokeStyle = rgba(faintHex, 0.1);
    g.lineWidth = 1 * dpr;
    g.beginPath();
    g.moveTo(m.l * dpr, yy);
    g.lineTo(canvas.width - m.r * dpr, yy);
    g.stroke();
    g.fillStyle = mutedHex;
    g.textAlign = 'right';
    g.fillText(fmtVal(v), (m.l - 8) * dpr, yy);
  }
  g.textBaseline = 'top';
  const span = tickHi - tickLo || 1;
  for (let i = 0; i <= 5; i++) {
    const ts = tickLo + (span * i) / 5;
    const xx = px(ts);
    g.fillStyle = mutedHex;
    g.textAlign = i === 0 ? 'left' : i === 5 ? 'right' : 'center';
    g.fillText(fmtTick(ts, span), xx, (canvas.height - m.b + 7) * dpr);
  }
}

// ----------------------------------------------------------------------------
// Formatters
// ----------------------------------------------------------------------------

/** Compact value formatter: more decimals as the magnitude shrinks. */
export function fmtVal(v: number): string {
  const a = Math.abs(v);
  return a >= 1000 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : a >= 1 ? v.toFixed(2) : v.toFixed(3);
}

/** Axis-tick timestamp: "MM-DD HH:MM" when the span is short, else "MM-DD". */
export function fmtTick(ts: number, spanMs: number): string {
  const s = new Date(ts).toISOString();
  return spanMs < 2 * 86400000 ? s.slice(5, 16).replace('T', ' ') : s.slice(5, 10);
}

/** Full timestamp "YYYY-MM-DD HH:MM:SS" (UTC). */
export function fmtTs(ts: number): string {
  return new Date(ts).toISOString().slice(0, 19).replace('T', ' ');
}

/** Human duration from milliseconds: "45m", "2h 30m", "3d 4h". */
export function fmtDur(ms: number): string {
  const mtot = Math.round(ms / 60000);
  if (mtot < 60) return mtot + 'm';
  const h = Math.floor(mtot / 60);
  const mm = mtot % 60;
  if (h < 24) return h + 'h' + (mm ? ' ' + mm + 'm' : '');
  const d = Math.floor(h / 24);
  const hh = h % 24;
  return d + 'd' + (hh ? ' ' + hh + 'h' : '');
}

// ----------------------------------------------------------------------------
// Warm-up overlay + alert markers (shared by the playground and the report)
// ----------------------------------------------------------------------------

export interface PlotRect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/** Device-px bounds of the plot area for a canvas + margins. */
export function plotRect(canvas: HTMLCanvasElement, m: Margins, dpr: number): PlotRect {
  return {
    left: m.l * dpr,
    top: m.t * dpr,
    right: canvas.width - m.r * dpr,
    bottom: canvas.height - m.b * dpr,
  };
}

/**
 * Dim the warm-up region (timestamps before `dividerTs`) so it never reads as
 * real detection, then draw a dashed divider + a small label marking where the
 * detector reaches full power. Bands / anomalies should be drawn only at/after
 * the divider; the metric line still spans the whole series for context.
 */
export function drawWarmupOverlay(
  g: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  m: Margins,
  dpr: number,
  px: (ts: number) => number,
  dividerTs: number,
  label: string,
): void {
  const r = plotRect(canvas, m, dpr);
  const xDiv = Math.max(r.left, Math.min(px(dividerTs), r.right));
  if (xDiv <= r.left + 0.5) return; // nothing meaningful to dim
  // Dim fill over the warm-up span.
  g.save();
  g.fillStyle = 'rgba(17,15,13,0.42)';
  g.fillRect(r.left, r.top, xDiv - r.left, r.bottom - r.top);
  // Dashed divider.
  g.strokeStyle = rgba(token('--faint'), 0.7);
  g.lineWidth = 1 * dpr;
  g.setLineDash([4 * dpr, 4 * dpr]);
  g.beginPath();
  g.moveTo(xDiv, r.top);
  g.lineTo(xDiv, r.bottom);
  g.stroke();
  g.setLineDash([]);
  // Label, just right of the divider near the top.
  g.fillStyle = rgba(token('--faint'), 0.95);
  g.font = `${10 * dpr}px ui-monospace, monospace`;
  g.textAlign = 'left';
  g.textBaseline = 'top';
  g.fillText(label, xDiv + 6 * dpr, r.top + 5 * dpr);
  g.restore();
}

/**
 * The `dividerTs`-less sibling of drawWarmupOverlay for the "everything shown
 * is warm-up" state (effective start ≥ series length): dim the WHOLE plot and
 * center the explanation, since a divider label would land off-canvas (the
 * divider x is clamped to the plot's right edge and the label sits right of it).
 * Without this the chart is silently bare — no band, no dots, no explanation.
 */
export function drawFullWarmupOverlay(
  g: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  m: Margins,
  dpr: number,
  label: string,
): void {
  const r = plotRect(canvas, m, dpr);
  if (r.right <= r.left || r.bottom <= r.top) return;
  g.save();
  g.fillStyle = 'rgba(17,15,13,0.42)';
  g.fillRect(r.left, r.top, r.right - r.left, r.bottom - r.top);
  g.fillStyle = rgba(token('--faint'), 0.95);
  g.font = `${10 * dpr}px ui-monospace, monospace`;
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillText(label, (r.left + r.right) / 2, r.top + (r.bottom - r.top) * 0.3, r.right - r.left - 12 * dpr);
  g.restore();
}

export interface AlertMark {
  t: number;
  kind: string;
}

/**
 * Draw a vertical tick + a down-pointing triangle at the top of the plot for
 * each alert, colored by kind via `colorOf`. Used to surface ALL alert firings
 * (not just the first) on both the playground and the report chart.
 */
export function drawAlertMarkers(
  g: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  m: Margins,
  dpr: number,
  px: (ts: number) => number,
  alerts: ArrayLike<AlertMark>,
  colorOf: (kind: string) => string,
): void {
  const r = plotRect(canvas, m, dpr);
  const tri = 5 * dpr;
  g.save();
  for (let i = 0; i < alerts.length; i++) {
    const a = alerts[i];
    const x = px(a.t);
    if (x < r.left - 1 || x > r.right + 1) continue;
    const col = colorOf(a.kind);
    // faint full-height tick
    g.strokeStyle = rgba(col, 0.45);
    g.lineWidth = 1 * dpr;
    g.beginPath();
    g.moveTo(x, r.top);
    g.lineTo(x, r.bottom);
    g.stroke();
    // solid triangle at the top
    g.fillStyle = col;
    g.beginPath();
    g.moveTo(x - tri, r.top);
    g.lineTo(x + tri, r.top);
    g.lineTo(x, r.top + tri * 1.4);
    g.closePath();
    g.fill();
  }
  g.restore();
}

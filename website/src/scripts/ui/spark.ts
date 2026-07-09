// Hand-rolled sparkline painter for the metrics table's spark cell (~140×30).
//
// Deliberately not the full report/demo chart core: a sparkline has no axes,
// no zoom, no hover — just a decimated polyline plus anomaly dots. Reuses only
// the token/rgba helpers from core/canvas.ts, not `fit()` — a table can hold
// hundreds of these, and `fit()` sizes from the canvas' *laid-out* CSS box,
// which requires the element to already be attached (forces a synchronous
// reflow per call, and reads 0 before attachment). The sparkline's box is a
// fixed constant instead, so the backing store is sized directly from the
// devicePixelRatio with no DOM read — paint before or after attaching, either
// works.

import { rgba, token } from '../core/canvas';

export interface SparkPoint {
  t: number;
  v: number | null;
}

export const SPARK_W = 140;
export const SPARK_H = 30;

/**
 * Paint a sparkline into `canvas` from `points` (ascending by time) plus a set
 * of anomalous timestamps `anomTimes`. Sizes the canvas' own CSS box + backing
 * store to the fixed 140×30 spark dimensions (devicePixelRatio-aware) — no
 * dependency on the canvas already being attached/laid out. No-ops (clears
 * only) when `points` is empty — the caller renders a "no data yet" label
 * instead in that case. When every point is null (buckets exist but carry no
 * value), draws a flat faint baseline so the cell still reads as "we have a
 * series, just no value here" rather than truly empty.
 */
export function paintSpark(canvas: HTMLCanvasElement, points: SparkPoint[], anomTimes: number[]): void {
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  canvas.style.width = `${SPARK_W}px`;
  canvas.style.height = `${SPARK_H}px`;
  canvas.width = Math.round(SPARK_W * dpr);
  canvas.height = Math.round(SPARK_H * dpr);
  const g = canvas.getContext('2d');
  if (!g) return;
  g.clearRect(0, 0, canvas.width, canvas.height);
  if (points.length === 0) return;

  const pad = 3 * dpr;
  const w = canvas.width;
  const h = canvas.height;
  const tmin = points[0].t;
  const tmax = points[points.length - 1].t;
  const tspan = tmax - tmin || 1;
  const px = (t: number): number => pad + ((t - tmin) / tspan) * Math.max(1, w - 2 * pad);

  let lo = Infinity;
  let hi = -Infinity;
  for (const p of points) {
    if (p.v !== null && Number.isFinite(p.v)) {
      if (p.v < lo) lo = p.v;
      if (p.v > hi) hi = p.v;
    }
  }
  const allNull = !Number.isFinite(lo) || !Number.isFinite(hi);
  if (allNull) {
    lo = 0;
    hi = 1;
  }
  if (hi <= lo) hi = lo + 1;
  const py = (v: number): number => h - pad - ((v - lo) / (hi - lo)) * Math.max(1, h - 2 * pad);

  if (allNull) {
    // Flat baseline: a series exists (buckets), just carries no values here.
    const y = h / 2;
    g.strokeStyle = rgba(token('--faint'), 0.5);
    g.lineWidth = 1 * dpr;
    g.setLineDash([2 * dpr, 2 * dpr]);
    g.beginPath();
    g.moveTo(pad, y);
    g.lineTo(w - pad, y);
    g.stroke();
    g.setLineDash([]);
    return;
  }

  g.strokeStyle = token('--term-text');
  g.lineWidth = 1 * dpr;
  g.lineJoin = 'round';
  g.beginPath();
  let pen = false;
  for (const p of points) {
    if (p.v === null || !Number.isFinite(p.v)) {
      pen = false;
      continue;
    }
    const X = px(p.t);
    const Y = py(p.v);
    if (!pen) {
      g.moveTo(X, Y);
      pen = true;
    } else {
      g.lineTo(X, Y);
    }
  }
  g.stroke();

  if (anomTimes.length === 0) return;

  // Value at t: linear interpolation between the bracketing non-null points
  // (nearest neighbour at the edges) — spark_anoms timestamps need not line up
  // exactly with a bucket boundary.
  const known: Array<[number, number]> = [];
  for (const p of points) if (p.v !== null && Number.isFinite(p.v)) known.push([p.t, p.v]);
  const valueAt = (t: number): number | null => {
    if (known.length === 0) return null;
    if (t <= known[0][0]) return known[0][1];
    if (t >= known[known.length - 1][0]) return known[known.length - 1][1];
    for (let i = 1; i < known.length; i++) {
      const [t1, v1] = known[i];
      if (t <= t1) {
        const [t0, v0] = known[i - 1];
        const frac = t1 === t0 ? 0 : (t - t0) / (t1 - t0);
        return v0 + (v1 - v0) * frac;
      }
    }
    return known[known.length - 1][1];
  };

  g.fillStyle = token('--st-anomaly');
  for (const t of anomTimes) {
    if (t < tmin || t > tmax) continue;
    const v = valueAt(t);
    if (v === null) continue;
    g.beginPath();
    g.arc(px(t), py(v), 2 * dpr, 0, Math.PI * 2);
    g.fill();
  }
}

// tune.worker.ts — runs the detector off the UI thread for `dtk tune`.
//
// The interactive tuner recomputes the detector on every knob change, which is
// O(points x window) and re-runs from scratch. Doing that on the main thread
// freezes the UI on large metrics. This worker holds the (large) series once and,
// on each `run` message, computes the scored series + would-fire alerts + warm-up
// boundary and posts them back — so the page stays responsive no matter how many
// points or how big the window. It runs the SAME parity-checked detector port as
// the landing playground (../demo/detector), so results are identical to the
// Python detectors; nothing about the algorithm changes here.
//
// Bundled to a string and embedded into tune.js (see gen-tune-bundle.mjs), then
// instantiated from a Blob URL so the report stays a single self-contained file.

import { effectiveStartIndex, runDetector } from '../demo/detector';
import type { DetectorParams, ScoredPoint, Series } from '../demo/types';

// Minimal worker-global typing (avoids pulling in the DOM/webworker lib).
declare const self: {
  onmessage: ((e: { data: unknown }) => void) | null;
  postMessage: (message: unknown) => void;
};

interface RunMsg {
  type: 'run';
  id: number;
  params: DetectorParams;
}
interface SeriesMsg {
  type: 'series';
  series: Series;
}

/** A firing alert: the fire index + the ms-span of the anomaly streak that fired. */
interface FireRun {
  /** index where the run reaches `consecutive` (the marker / fire point). */
  fire: number;
  /** streak start/end timestamps (ms) — the WHOLE grid-adjacent flagged run. */
  startTs: number;
  endTs: number;
}

let series: Series | null = null;

/**
 * Alert-layer direction filter (view only, never touches the band math): when a
 * direction is chosen, anomalies of the other direction stop counting as flags —
 * for the dots, the alert runs and the flagged tally alike. Mutates the freshly
 * scored array in place ('up' keeps 'above', 'down' keeps 'below').
 */
function applyDirection(scored: ScoredPoint[], direction: DetectorParams['direction']): void {
  if (!direction || direction === 'any') return;
  const want = direction === 'up' ? 'above' : 'below';
  for (const s of scored) {
    if (s.isAnomaly && s.direction !== want) s.isAnomaly = false;
  }
}

/**
 * One FireRun per maximal run of grid-adjacent flagged points that reaches
 * `consecutive`. We return the WHOLE run's span (not just the fire point) so the
 * cockpit can score recall/FDR by overlap with the marked incident spans — an
 * alert fires `consecutive-1` intervals into the streak, so matching the fire
 * point alone against a narrow incident misses (the recall-undercount bug).
 */
function alertFireRuns(scored: ScoredPoint[], intervalMs: number, consecutive: number): FireRun[] {
  const runs: FireRun[] = [];
  const n = scored.length;
  let i = 0;
  while (i < n) {
    if (!(scored[i].scored && scored[i].isAnomaly)) {
      i++;
      continue;
    }
    // Extend the run while the next point is flagged AND exactly one interval on.
    let j = i;
    while (
      j + 1 < n &&
      scored[j + 1].scored &&
      scored[j + 1].isAnomaly &&
      scored[j + 1].timestamp - scored[j].timestamp === intervalMs
    ) {
      j++;
    }
    if (j - i + 1 >= consecutive) {
      runs.push({ fire: i + consecutive - 1, startTs: scored[i].timestamp, endTs: scored[j].timestamp });
    }
    i = j + 1;
  }
  return runs;
}

self.onmessage = (e: { data: unknown }): void => {
  const msg = e.data as RunMsg | SeriesMsg;
  if (msg.type === 'series') {
    series = msg.series;
    return;
  }
  if (msg.type === 'run' && series) {
    const params = msg.params;
    const scored = runDetector(series, params);
    applyDirection(scored, params.direction);
    const intervalMs = series.intervalSeconds * 1000;
    const runs = alertFireRuns(scored, intervalMs, params.consecutiveAnomalies);
    const fires = runs.map((r) => r.fire);
    const fireSpans = runs.map((r) => [r.startTs, r.endTs] as [number, number]);
    const eff = effectiveStartIndex(series, params);
    let flagged = 0;
    for (const s of scored) if (s.scored && s.isAnomaly) flagged++;
    self.postMessage({ type: 'result', id: msg.id, scored, fires, fireSpans, eff, flagged });
  }
};

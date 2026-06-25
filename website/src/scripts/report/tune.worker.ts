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
    const fires = alertFireIndexes(scored, intervalMs, params.consecutiveAnomalies);
    const eff = effectiveStartIndex(series, params);
    let flagged = 0;
    for (const s of scored) if (s.scored && s.isAnomaly) flagged++;
    self.postMessage({ type: 'result', id: msg.id, scored, fires, eff, flagged });
  }
};

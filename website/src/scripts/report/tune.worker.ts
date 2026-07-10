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
  /**
   * Fraction alert rule (issue #101), OR-ed with the consecutive rule exactly
   * like the pipeline. Top-level fields, NOT DetectorParams: they change which
   * alerts fire, never the band, so they must not join the detector-param
   * identity. Both-or-neither (mirrors the AlertConfig validator).
   */
  anomalyWindowPoints?: number | null;
  minAnomalyShare?: number | null;
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

/**
 * Share-rule fires (port of the pipeline's `_decision._share_fire` semantics
 * onto the cockpit's gap-filled grid): a point fires when it is itself flagged
 * (a stale window never fires) AND the flagged share over the trailing
 * `windowPoints` grid slots (current inclusive) reaches `share`. Slots before
 * the series start / NaN gaps count in the denominator only. Fires within one
 * window of each other collapse into a single episode (one marker), whose span
 * runs from the onset (oldest flagged slot the firing window sees) to the last
 * firing point — so recall/FDR overlap matching covers the whole diffuse
 * incident, not just the fire instant.
 */
function shareFireRuns(
  scored: ScoredPoint[],
  windowPoints: number,
  share: number
): FireRun[] {
  const n = scored.length;
  const flags: boolean[] = new Array(n);
  for (let t = 0; t < n; t++) flags[t] = scored[t].scored && scored[t].isAnomaly;
  const need = share * windowPoints;

  const runs: FireRun[] = [];
  let cur: FireRun | null = null;
  let lastFire = -Infinity;
  let count = 0;
  for (let t = 0; t < n; t++) {
    if (flags[t]) count++;
    if (t - windowPoints >= 0 && flags[t - windowPoints]) count--;
    if (!flags[t] || count < need) continue;
    if (cur && t - lastFire <= windowPoints) {
      cur.endTs = scored[t].timestamp; // same elevated episode — extend
    } else {
      if (cur) runs.push(cur);
      let onset = t;
      for (let k = Math.max(0, t - windowPoints + 1); k <= t; k++) {
        if (flags[k]) {
          onset = k;
          break;
        }
      }
      cur = { fire: t, startTs: scored[onset].timestamp, endTs: scored[t].timestamp };
    }
    lastFire = t;
  }
  if (cur) runs.push(cur);
  return runs;
}

/**
 * OR-merge the two rules' fires, dedup by fire point (a point fires once no
 * matter which rule tripped — mirrors the pipeline replay's per-timestamp
 * dedup); the consecutive rule's run wins the tie for the span.
 */
function mergeFireRuns(consecutive: FireRun[], share: FireRun[]): FireRun[] {
  const seen = new Set(consecutive.map((r) => r.fire));
  const merged = consecutive.slice();
  for (const r of share) if (!seen.has(r.fire)) merged.push(r);
  merged.sort((a, b) => a.fire - b.fire);
  return merged;
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
    let runs = alertFireRuns(scored, intervalMs, params.consecutiveAnomalies);
    const wp = msg.anomalyWindowPoints ?? null;
    const shareReq = msg.minAnomalyShare ?? null;
    if (wp !== null && shareReq !== null && wp >= 2 && shareReq > 0) {
      runs = mergeFireRuns(runs, shareFireRuns(scored, wp, shareReq));
    }
    const fires = runs.map((r) => r.fire);
    const fireSpans = runs.map((r) => [r.startTs, r.endTs] as [number, number]);
    const eff = effectiveStartIndex(series, params);
    let flagged = 0;
    for (const s of scored) if (s.scored && s.isAnomaly) flagged++;
    self.postMessage({ type: 'result', id: msg.id, scored, fires, fireSpans, eff, flagged });
  }
};

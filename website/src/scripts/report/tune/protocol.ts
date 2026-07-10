// protocol.ts — the tune.ts ⇄ tune.worker.ts message contract (single source of
// truth for both sides of the Blob-instantiated worker).

import type { DetectorParams, ScoredPoint, Series } from '../../demo/types';

/** Shape of the message the worker posts back after a `run`. */
export interface WorkerResult {
  type: 'result';
  id: number;
  scored: ScoredPoint[];
  fires: number[];
  /** per-fire [startTs, endTs] of the whole grid-adjacent anomaly streak (ms). */
  fireSpans: Array<[number, number]>;
  eff: number;
  /**
   * UNCLAMPED warm-up requirement (eff is clamped to the shown length): when
   * the whole view is warm-up, only this still says how many points the page
   * must show for a band to appear.
   */
  need: number;
  flagged: number;
}

export interface RunMsg {
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
export interface SeriesMsg {
  type: 'series';
  series: Series;
}

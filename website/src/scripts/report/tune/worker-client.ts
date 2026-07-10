// worker-client.ts — owns the detector Web Worker for the tune cockpit: the
// Blob URL, spawn/terminate lifecycle, request ids, the in-flight kill switch
// and the slider-drag debounce. The composition root supplies the params/share
// getters and receives results through callbacks; all UI state stays out there.

import type { DetectorParams, Series } from '../../demo/types';
import type { WorkerResult } from './protocol';

export interface TuneWorkerClient {
  /** Store + post a (re)sliced series; the stored series re-posts on respawn. */
  postSeries(series: Series): void;
  /** Debounced recompute (130 ms) — a slider drag fires once when it settles. */
  recompute(): void;
  /** Immediate dispatch (first paint; programmatic re-seeds go through recompute). */
  runNow(): void;
}

export function createTuneWorkerClient(opts: {
  /** the bundled worker source (__DTK_WORKER_SRC__). */
  src: string;
  /** the initial (possibly trimmed) series; re-posted on every respawn. */
  series: Series;
  getParams: () => DetectorParams;
  getShare: () => { windowPoints: number | null; share: number | null };
  /** fires when a run is dispatched (spinner on, dirty-params bookkeeping). */
  onDispatch: (params: DetectorParams) => void;
  onResult: (res: WorkerResult, params: DetectorParams) => void;
  onError: () => void;
}): TuneWorkerClient {
  // ---- detector worker + debounced recompute --------------------------------
  // runDetector is O(points x window) and re-runs from scratch on every change;
  // running it in a Worker keeps the UI responsive no matter the size. Post the
  // (large) series once, then only params per recompute. Stale results (an older
  // id) are dropped so only the latest knob state paints. Debounce so a slider
  // DRAG fires one recompute when it settles, not one per frame.
  // One blob URL, reused across (re)spawns — no per-spawn leak.
  const workerUrl = URL.createObjectURL(new Blob([opts.src], { type: 'text/javascript' }));
  let series = opts.series;
  let worker: Worker;
  let reqId = 0;
  let inFlight = false;
  let lastParams: DetectorParams | null = null;
  let debounce = 0;

  const onWorkerMessage = (e: MessageEvent): void => {
    const res = e.data as WorkerResult;
    // Only the CURRENT request clears the in-flight flag. A stale message (an old
    // worker's result that slipped through before terminate, or an out-of-order id)
    // must NOT clear it — the live compute is still running, and clearing it here
    // would let the next knob-change queue behind that compute instead of killing it.
    if (res.type !== 'result' || res.id !== reqId || !lastParams) return; // ignore stale
    inFlight = false;
    opts.onResult(res, lastParams);
  };
  const onWorkerError = (): void => {
    inFlight = false;
    opts.onError();
  };
  function spawnWorker(): void {
    worker = new Worker(workerUrl);
    worker.onmessage = onWorkerMessage;
    worker.onerror = onWorkerError;
    worker.postMessage({ type: 'series', series });
  }
  spawnWorker();

  const runNow = (): void => {
    lastParams = opts.getParams();
    opts.onDispatch(lastParams);
    reqId += 1;
    // Kill an in-flight compute instead of queuing behind it: the worker is
    // single-threaded and would otherwise run the now-stale config to completion
    // (O(points × window) — seconds on a large window) before starting this one.
    // Terminate + respawn re-posts the (bounded) series, which is cheap by comparison.
    if (inFlight) {
      worker.terminate();
      spawnWorker();
    }
    inFlight = true;
    const share = opts.getShare();
    worker.postMessage({
      type: 'run',
      id: reqId,
      params: lastParams,
      // Fraction alert rule — top-level (never DetectorParams: it changes which
      // alerts fire, not the band). null when off ⇒ legacy consecutive-only.
      anomalyWindowPoints: share.windowPoints,
      minAnomalyShare: share.share,
    });
  };

  const recompute = (): void => {
    if (debounce) window.clearTimeout(debounce);
    debounce = window.setTimeout(runNow, 130);
  };

  const postSeries = (s: Series): void => {
    series = s;
    worker.postMessage({ type: 'series', series });
  };

  return { postSeries, recompute, runNow };
}

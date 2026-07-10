// Faithful TypeScript port of detectkit's windowed statistical detectors
// (MAD / Z-Score / IQR). Source of truth:
//   detectkit/detectors/statistical/_windowed.py, mad.py, zscore.py, iqr.py
//   detectkit/detectors/base.py            (smoothing + input_type)
//   detectkit/detectors/seasonality.py     (group masks)
//   detectkit/utils/stats.py               (weighted percentile/median/mad/mean/std)
//
// The port reproduces the Python output within 1e-6. It operates purely on the
// in-memory Series and is deterministic. Like the Python pipeline it runs:
//   STEP 0  preprocessing (smoothing FIRST, then input_type) -> processed values
//   per point i, left -> right:
//     1. processed NaN          -> missing_data (skip)
//     2. trailing window slice  (current point EXCLUDED), NaN-filtered
//     3. insufficient valid pts -> insufficient_data (skip)
//     4. ages on the time grid  (1 = previous point, L = oldest in slice)
//     5. recency weights        (none / exponential / linear)
//     6. optional linear detrend (split-median slope projection)
//     7. global statistics
//     8. seasonality-group multipliers
//     9. confidence interval
//    10. anomaly flag / direction / severity (on the PROCESSED value)
//    11. band center (median / mean / midhinge) from the adjusted stats
//    12. optional stabilization write-back (flagged point clamped to its
//        violated bound for subsequent windows)

import type {
  AnomalyDirection,
  DetectorParams,
  ScoredPoint,
  ScoreReason,
  Series,
  WindowedType,
} from './types';

// Normal-consistency constant: sigma ~= 1.4826 * MAD for Gaussian data, so the
// MAD threshold is expressed in the same sigma units as Z-Score.
const MAD_SCALE = 1.4826;

/** Per-type minimum-valid-samples floor (max'd against params.minSamples). */
const MIN_SAMPLES_FLOOR: Record<WindowedType, number> = {
  mad: 1,
  zscore: 2,
  iqr: 4,
};

// ----------------------------------------------------------------------------
// Weighted statistics (port of detectkit/utils/stats.py).
//
// Weights only need to be positive; every function normalizes internally. With
// uniform weights the percentile uses the midpoint (Hazen) convention so the
// weighted median reproduces numpy's median exactly for odd and even sizes.
// Callers must filter NaN out of `data` first.
// ----------------------------------------------------------------------------

/** Sum of an array. */
function sum(xs: number[]): number {
  let s = 0;
  for (const x of xs) s += x;
  return s;
}

/**
 * Stable argsort ascending (matches numpy's kind="stable"). Ties keep their
 * original relative order, which the weighted-percentile reorder depends on.
 */
function stableArgsort(data: number[]): number[] {
  const idx = data.map((_, i) => i);
  idx.sort((a, b) => {
    if (data[a] < data[b]) return -1;
    if (data[a] > data[b]) return 1;
    return a - b; // stable tie-break
  });
  return idx;
}

/**
 * Linear interpolation matching numpy.interp: evaluate `target` over the
 * monotonically non-decreasing breakpoints `xp` with values `fp`, clamping to
 * the first/last value outside [xp[0], xp[-1]].
 */
function npInterp(target: number, xp: number[], fp: number[]): number {
  const n = xp.length;
  if (n === 0) return NaN;
  if (target <= xp[0]) return fp[0];
  if (target >= xp[n - 1]) return fp[n - 1];
  // Find the segment [xp[k-1], xp[k]] that brackets target. xp is sorted, so a
  // linear scan reproduces numpy's behavior (incl. its handling of equal xp:
  // it picks the first bracket where target < xp[k], same as below).
  for (let k = 1; k < n; k++) {
    if (target <= xp[k]) {
      const x0 = xp[k - 1];
      const x1 = xp[k];
      const y0 = fp[k - 1];
      const y1 = fp[k];
      if (x1 === x0) return y0; // degenerate segment -> left value
      const t = (target - x0) / (x1 - x0);
      return y0 + t * (y1 - y0);
    }
  }
  return fp[n - 1];
}

/**
 * Weighted percentile (midpoint / Hazen convention). Each sorted point i sits
 * at cumulative position (cumsum(w)[i] - w[i]/2) / sum(w); the requested
 * percentile is linearly interpolated between neighboring positions. Division
 * by the total happens once at the end so uniform integer weights produce
 * exact positions (matching the Python implementation).
 */
export function weightedPercentile(data: number[], weights: number[], percentile: number): number {
  const order = stableArgsort(data);
  const sortedData = order.map((i) => data[i]);
  const sortedWeights = order.map((i) => weights[i]);

  const total = sum(sortedWeights);
  // Cumulative positions: (cumsum - 0.5*w) / total.
  const positions: number[] = new Array(sortedWeights.length);
  let cum = 0;
  for (let i = 0; i < sortedWeights.length; i++) {
    cum += sortedWeights[i];
    positions[i] = (cum - 0.5 * sortedWeights[i]) / total;
  }

  const target = percentile / 100.0;
  return npInterp(target, positions, sortedData);
}

/** Weighted median (50th percentile, midpoint convention). */
export function weightedMedian(data: number[], weights: number[]): number {
  return weightedPercentile(data, weights, 50.0);
}

/** Weighted Median Absolute Deviation; `center` defaults to the weighted median. */
export function weightedMad(data: number[], weights: number[], center?: number): number {
  const c = center === undefined ? weightedMedian(data, weights) : center;
  const deviations = data.map((v) => Math.abs(v - c));
  return weightedMedian(deviations, weights);
}

/** Weighted mean. */
export function weightedMean(data: number[], weights: number[]): number {
  const total = sum(weights);
  let acc = 0;
  for (let i = 0; i < data.length; i++) acc += data[i] * (weights[i] / total);
  return acc;
}

/**
 * Weighted standard deviation. `center` defaults to the weighted mean; with
 * ddof=1 the reliability correction 1/(1 - sum(w^2)) is applied unless the
 * effective sample size is too small (correction <= 1e-12), in which case the
 * population estimate is kept.
 */
export function weightedStd(
  data: number[],
  weights: number[],
  center?: number,
  ddof: 0 | 1 = 0
): number {
  const total = sum(weights);
  const w = weights.map((x) => x / total);
  const c = center === undefined ? sum(data.map((v, i) => v * w[i])) : center;

  let variance = 0;
  for (let i = 0; i < data.length; i++) variance += w[i] * (data[i] - c) ** 2;

  if (ddof === 1) {
    const correction = 1.0 - sum(w.map((x) => x * x));
    if (correction > 1e-12) variance /= correction;
    // else: effective n <= 1, keep the population estimate
  }
  return Math.sqrt(variance);
}

// ----------------------------------------------------------------------------
// STEP 0 — preprocessing (smoothing first, then input_type).
// ----------------------------------------------------------------------------

/** Identity / EMA / SMA smoothing over the original values (same length out). */
function applySmoothing(values: number[], params: DetectorParams): number[] {
  if (params.smoothing === 'none') return values.slice();
  if (params.smoothing === 'ema') return computeEma(values, params.smoothingAlpha);
  return computeSma(values, params.smoothingWindow);
}

/**
 * Exponential Moving Average. Leading NaNs stay NaN (the EMA starts at the
 * first valid point); later NaNs carry the previous EMA forward.
 *   ema[first] = values[first]
 *   ema[t]     = alpha*values[t] + (1-alpha)*ema[t-1]   (else carry forward)
 */
function computeEma(values: number[], alpha: number): number[] {
  const n = values.length;
  const ema = new Array<number>(n).fill(NaN);
  if (n === 0) return ema;

  let first = -1;
  for (let i = 0; i < n; i++) {
    if (!Number.isNaN(values[i])) {
      first = i;
      break;
    }
  }
  if (first === -1) return ema; // all NaN

  ema[first] = values[first];
  for (let i = first + 1; i < n; i++) {
    if (Number.isNaN(values[i])) ema[i] = ema[i - 1];
    else ema[i] = alpha * values[i] + (1 - alpha) * ema[i - 1];
  }
  return ema;
}

/**
 * NaN-aware Simple Moving Average: the trailing mean over the inclusive range
 * [max(0, i-window+1) .. i], ignoring NaNs. An all-NaN window yields NaN. The
 * first window-1 points average over what's available.
 */
function computeSma(values: number[], window: number): number[] {
  const n = values.length;
  const sma = new Array<number>(n).fill(NaN);
  for (let i = 0; i < n; i++) {
    const start = Math.max(0, i - window + 1);
    let s = 0;
    let count = 0;
    for (let j = start; j <= i; j++) {
      if (!Number.isNaN(values[j])) {
        s += values[j];
        count += 1;
      }
    }
    sma[i] = count > 0 ? s / count : NaN;
  }
  return sma;
}

/**
 * input_type transform on the (smoothed) series x. The first element of any
 * change series is NaN (no previous point):
 *   values           -> x
 *   changes          -> (x[t] - x[t-1]) / x[t-1]
 *   absolute_changes -> x[t] - x[t-1]
 *   log_changes      -> log(x[t]+1) - log(x[t-1]+1)
 */
function preprocessInput(values: number[], params: DetectorParams): number[] {
  const n = values.length;
  if (params.inputType === 'values') return values.slice();

  const out = new Array<number>(n).fill(NaN);
  for (let t = 1; t < n; t++) {
    const prev = values[t - 1];
    const cur = values[t];
    if (params.inputType === 'changes') {
      out[t] = (cur - prev) / prev; // matches numpy (Inf/NaN on prev==0)
    } else if (params.inputType === 'absolute_changes') {
      out[t] = cur - prev;
    } else {
      // log_changes: +1 to handle zeros, matching the Python helper.
      out[t] = Math.log(cur + 1) - Math.log(prev + 1);
    }
  }
  return out;
}

// ----------------------------------------------------------------------------
// Recency weighting.
// ----------------------------------------------------------------------------

/**
 * Resolve the exponential half-life to a number of grid points.
 *   number  -> taken as points directly
 *   null    -> adaptive: max(windowSize/20, effectiveMinSamples/2, 1)
 * (The Python default uses the raw min_samples; the demo passes the effective,
 * floored value, matching the spec.)
 */
function resolveHalfLife(params: DetectorParams, effectiveMinSamples: number): number {
  if (params.halfLife !== null) return params.halfLife;
  return Math.max(params.windowSize / 20.0, effectiveMinSamples / 2.0, 1.0);
}

/**
 * Precompute the weight-by-age lookup table (index = age - 1) over ages
 * 1..windowSize. Returns null for uniform weighting.
 *   exponential -> w(a) = 0.5 ^ min(a/halfLife, 1000)  (capped so it never
 *                  underflows to exact 0)
 *   linear      -> w(a) = (windowSize + 1 - a) / windowSize
 */
function buildWeightLut(params: DetectorParams, effectiveMinSamples: number): number[] | null {
  if (params.windowWeights === 'none') return null;

  const windowSize = params.windowSize;
  const lut = new Array<number>(windowSize);

  if (params.windowWeights === 'exponential') {
    const halfLife = resolveHalfLife(params, effectiveMinSamples);
    for (let a = 1; a <= windowSize; a++) {
      const exponent = Math.min(a / halfLife, 1000.0);
      lut[a - 1] = Math.pow(0.5, exponent);
    }
    return lut;
  }

  // linear: newest age 1 gets weight windowSize, oldest gets 1.
  for (let a = 1; a <= windowSize; a++) {
    lut[a - 1] = (windowSize + 1 - a) / windowSize;
  }
  return lut;
}

/** Weight for each age (1-based), via the LUT; uniform 1.0 when LUT is null. */
function weightsFor(ages: number[], lut: number[] | null): number[] {
  if (lut === null) return ages.map(() => 1.0);
  return ages.map((a) => lut[a - 1]);
}

// ----------------------------------------------------------------------------
// Detrending (robust split-median slope).
// ----------------------------------------------------------------------------

/** Index of the maximum of a non-empty array. */
function maxOf(xs: number[]): number {
  let m = xs[0];
  for (const x of xs) if (x > m) m = x;
  return m;
}

/** Index of the minimum of a non-empty array. */
function minOf(xs: number[]): number {
  let m = xs[0];
  for (const x of xs) if (x < m) m = x;
  return m;
}

/**
 * Robust per-point slope via split-median: the window is split at its median
 * age and the slope is taken between the weighted medians of the two halves.
 * Returns 0 when the window is too small or a half is under-filled.
 *
 * values ~ c - slope*age, so projecting to the current point (age 0) is
 * values + slope*age (done by the caller).
 */
export function estimateSlope(values: number[], ages: number[], weights: number[]): number {
  if (values.length < 4) return 0.0;

  const mid = (maxOf(ages) + minOf(ages)) / 2.0;
  const oldMask = ages.map((a) => a > mid);
  const newMask = oldMask.map((b) => !b);

  let oldCount = 0;
  let newCount = 0;
  for (let i = 0; i < ages.length; i++) {
    if (oldMask[i]) oldCount++;
    else newCount++;
  }
  if (oldCount < 2 || newCount < 2) return 0.0;

  const pick = (mask: boolean[], src: number[]): number[] =>
    src.filter((_, i) => mask[i]);

  const valsNew = pick(newMask, values);
  const valsOld = pick(oldMask, values);
  const agesNew = pick(newMask, ages);
  const agesOld = pick(oldMask, ages);
  const wNew = pick(newMask, weights);
  const wOld = pick(oldMask, weights);

  const medNew = weightedMedian(valsNew, wNew);
  const medOld = weightedMedian(valsOld, wOld);
  const ageNew = weightedMedian(agesNew, wNew);
  const ageOld = weightedMedian(agesOld, wOld);

  if (ageOld === ageNew) return 0.0;
  return (medNew - medOld) / (ageOld - ageNew);
}

// ----------------------------------------------------------------------------
// Per-detector statistics + interval + severity (the three hooks).
// ----------------------------------------------------------------------------

type Stats = Record<string, number>;

/** Ordered (name, kind) stat spec per detector; "spread" guards with >0. */
const STATS: Record<WindowedType, ReadonlyArray<readonly [string, 'center' | 'spread']>> = {
  mad: [
    ['median', 'center'],
    ['mad', 'spread'],
  ],
  zscore: [
    ['mean', 'center'],
    ['std', 'spread'],
  ],
  iqr: [
    ['q1', 'center'],
    ['q3', 'center'],
    ['iqr', 'spread'],
  ],
};

/** Compute the named statistics for a detector type over a weighted window. */
function computeStats(type: WindowedType, values: number[], weights: number[]): Stats {
  if (type === 'mad') {
    const median = weightedMedian(values, weights);
    return { median, mad: weightedMad(values, weights, median) };
  }
  if (type === 'zscore') {
    const mean = weightedMean(values, weights);
    return { mean, std: weightedStd(values, weights, mean, 1) };
  }
  const q1 = weightedPercentile(values, weights, 25);
  const q3 = weightedPercentile(values, weights, 75);
  return { q1, q3, iqr: q3 - q1 };
}

/** Build the (lower, upper) confidence interval from the adjusted statistics. */
function buildInterval(type: WindowedType, stats: Stats, threshold: number): [number, number] {
  if (type === 'mad') {
    if (stats.mad === 0) return [stats.median - 1e-10, stats.median + 1e-10];
    const margin = threshold * MAD_SCALE * stats.mad;
    return [stats.median - margin, stats.median + margin];
  }
  if (type === 'zscore') {
    if (stats.std === 0) return [stats.mean - 1e-10, stats.mean + 1e-10];
    return [stats.mean - threshold * stats.std, stats.mean + threshold * stats.std];
  }
  if (stats.iqr === 0) return [stats.q1 - 1e-10, stats.q3 + 1e-10];
  return [stats.q1 - threshold * stats.iqr, stats.q3 + threshold * stats.iqr];
}

/** Severity (spread units beyond the breached bound). Inf when spread <= 0. */
function severity(type: WindowedType, stats: Stats, distance: number): number {
  if (type === 'mad') {
    const sigmaEst = MAD_SCALE * stats.mad;
    return sigmaEst > 0 ? distance / sigmaEst : Infinity;
  }
  if (type === 'zscore') {
    return stats.std > 0 ? distance / stats.std : Infinity;
  }
  return stats.iqr > 0 ? distance / stats.iqr : Infinity;
}

/** Band center for the ScoredPoint, from the adjusted statistics. */
function bandCenter(type: WindowedType, stats: Stats): number {
  if (type === 'mad') return stats.median;
  if (type === 'zscore') return stats.mean;
  return (stats.q1 + stats.q3) / 2.0; // midhinge
}

// ----------------------------------------------------------------------------
// Detection pipeline.
// ----------------------------------------------------------------------------

/** Build a non-scored ScoredPoint (missing_data / insufficient_data). */
function unscored(
  index: number,
  timestamp: number,
  value: number,
  processedValue: number,
  reason: ScoreReason
): ScoredPoint {
  return {
    index,
    timestamp,
    value,
    processedValue,
    scored: false,
    isAnomaly: false,
    lower: NaN,
    upper: NaN,
    center: NaN,
    direction: null,
    severity: 0,
    reason,
  };
}

/**
 * Stateless manual-bounds scoring (port of ManualBoundsDetector). No window, no
 * statistics — each PROCESSED value is compared against the user's lower/upper
 * thresholds. NO smoothing (the Python detector applies only input_type). A
 * `null` bound leaves that side open. The band fields carry the bounds verbatim
 * so the chart draws a flat corridor; severity is the distance beyond the bound,
 * normalized by the bound range when both are set (else absolute).
 */
function runManualBounds(series: Series, params: DetectorParams): ScoredPoint[] {
  const { timestamps, values } = series;
  const n = timestamps.length;
  const processed = preprocessInput(values, params); // input_type only, no smoothing
  const lower = params.lowerBound ?? null;
  const upper = params.upperBound ?? null;

  const results: ScoredPoint[] = [];
  for (let i = 0; i < n; i++) {
    const value = values[i];
    const pv = processed[i];
    const ts = timestamps[i];

    if (Number.isNaN(pv)) {
      results.push(unscored(i, ts, value, pv, 'missing_data'));
      continue;
    }

    let isAnomaly = false;
    let direction: AnomalyDirection = null;
    let distance = 0;
    if (lower !== null && pv < lower) {
      isAnomaly = true;
      direction = 'below';
      distance = lower - pv;
    }
    if (upper !== null && pv > upper) {
      isAnomaly = true;
      direction = 'above';
      distance = pv - upper;
    }

    let sev = 0;
    if (isAnomaly) {
      if (lower !== null && upper !== null) {
        const range = upper - lower;
        sev = range > 0 ? distance / range : Infinity;
      } else {
        sev = distance; // one-sided: absolute distance (matches Python)
      }
    }

    const lo = lower ?? -Infinity;
    const up = upper ?? Infinity;
    const center =
      lower !== null && upper !== null ? (lower + upper) / 2 : (lower ?? upper ?? NaN);

    results.push({
      index: i,
      timestamp: ts,
      value,
      processedValue: pv,
      scored: true,
      isAnomaly,
      lower: lo,
      upper: up,
      center,
      direction,
      severity: sev,
      reason: 'ok',
    });
  }
  return results;
}

/**
 * Score every point of `series` under `params`. Pure and deterministic;
 * reproduces the Python detectors within 1e-6.
 */
export function runDetector(series: Series, params: DetectorParams): ScoredPoint[] {
  if (params.type === 'manual_bounds') return runManualBounds(series, params);

  const type = params.type as WindowedType;
  const effectiveMinSamples = Math.max(params.minSamples, MIN_SAMPLES_FLOOR[type]);
  const statSpec = STATS[type];

  const { timestamps, values } = series;
  const n = timestamps.length;

  // STEP 0: preprocessing — smoothing FIRST, then input_type.
  const smoothed = applySmoothing(values, params);
  const processed = preprocessInput(smoothed, params);

  // Stabilization (opt-in): statistics windows read from a working copy where
  // every previously-flagged point is clamped to the confidence bound it
  // violated, so an ongoing incident cannot inflate the band and mask itself.
  // The scored value stays the raw processed observation.
  const stabilize = params.stabilization === 'clamp';
  const work = stabilize ? processed.slice() : processed;

  // Seasonality is active only with both components and per-point keys.
  const seasonalityActive =
    params.seasonalityComponents !== null &&
    params.seasonalityComponents.length > 0 &&
    Array.isArray(series.seasonalityData) &&
    series.seasonalityData.length > 0;
  const seasonalityData = series.seasonalityData;

  const weightLut = buildWeightLut(params, effectiveMinSamples);

  const results: ScoredPoint[] = [];

  for (let i = 0; i < n; i++) {
    const currentVal = values[i];
    const currentProcessed = processed[i];
    const currentTs = timestamps[i];

    // STEP 1: NaN processed value -> missing_data.
    if (Number.isNaN(currentProcessed)) {
      results.push(unscored(i, currentTs, currentVal, currentProcessed, 'missing_data'));
      continue;
    }

    // STEP 2: trailing window slice, current point EXCLUDED. Sliced from the
    // (possibly stabilized) working copy — both the global stats and the
    // seasonality-group values below consume this slice.
    const windowStart = Math.max(0, i - params.windowSize);
    const sliceLen = i - windowStart; // L
    const slice = work.slice(windowStart, i);
    const validMask: boolean[] = slice.map((v) => !Number.isNaN(v));
    const windowValid: number[] = [];
    for (let k = 0; k < slice.length; k++) if (validMask[k]) windowValid.push(slice[k]);

    // STEP 3: too few valid points -> insufficient_data.
    if (windowValid.length < effectiveMinSamples) {
      results.push(unscored(i, currentTs, currentVal, currentProcessed, 'insufficient_data'));
      continue;
    }

    // STEP 4: ages over the FULL slice [L, L-1, ..., 1]; slice pos 0 = oldest.
    const ages: number[] = new Array(sliceLen);
    for (let k = 0; k < sliceLen; k++) ages[k] = sliceLen - k;
    const validAges: number[] = [];
    for (let k = 0; k < sliceLen; k++) if (validMask[k]) validAges.push(ages[k]);

    // STEP 5: recency weights for the valid window points.
    const weights = weightsFor(validAges, weightLut);

    // STEP 6: optional linear detrend — project window points to the current
    // point along the robust slope (only when the slope is non-zero).
    let slope = 0.0;
    if (params.detrend === 'linear') {
      slope = estimateSlope(windowValid, validAges, weights);
    }
    const windowForStats =
      slope !== 0.0 ? windowValid.map((v, k) => v + slope * validAges[k]) : windowValid;

    // STEP 7: global statistics; adjusted starts as a copy.
    const globalStats = computeStats(type, windowForStats, weights);
    const adjustedStats: Stats = { ...globalStats };

    // STEP 8: seasonality-group multipliers (cumulative across groupings).
    if (seasonalityActive && seasonalityData) {
      const currentRow = seasonalityData[i];
      for (const group of params.seasonalityComponents!) {
        // season_mask over slice positions: every column must match point i.
        const seasonMask: boolean[] = new Array(sliceLen).fill(true);
        for (let k = 0; k < sliceLen; k++) {
          const row = seasonalityData[windowStart + k];
          let match = true;
          for (const col of group) {
            if (!row || row[col] !== currentRow?.[col]) {
              match = false;
              break;
            }
          }
          seasonMask[k] = match;
        }

        // combined = valid_mask AND season_mask; group values (pre-detrend).
        const groupValues: number[] = [];
        const groupAges: number[] = [];
        for (let k = 0; k < sliceLen; k++) {
          if (validMask[k] && seasonMask[k]) {
            groupValues.push(slice[k]);
            groupAges.push(ages[k]);
          }
        }

        // Under-filled group -> fallback (all multipliers 1, no change).
        if (groupValues.length < params.minSamplesPerGroup) continue;

        const groupWeights = weightsFor(groupAges, weightLut);
        const projected =
          slope !== 0.0 ? groupValues.map((v, k) => v + slope * groupAges[k]) : groupValues;
        const groupStats = computeStats(type, projected, groupWeights);

        for (const [name, kind] of statSpec) {
          const globalVal = globalStats[name];
          const ok = kind === 'spread' ? globalVal > 0 : globalVal !== 0;
          const multiplier = ok ? groupStats[name] / globalVal : 1.0;
          adjustedStats[name] *= multiplier;
        }
      }
    }

    // STEP 9: confidence interval (swap if multipliers inverted it).
    let [lower, upper] = buildInterval(type, adjustedStats, params.threshold);
    if (lower > upper) [lower, upper] = [upper, lower];

    // STEP 10: anomaly check on the PROCESSED value.
    const isAnomaly = currentProcessed < lower || currentProcessed > upper;
    let direction: AnomalyDirection = null;
    let sev = 0;
    if (isAnomaly) {
      let distance: number;
      if (currentProcessed < lower) {
        direction = 'below';
        distance = lower - currentProcessed;
      } else {
        direction = 'above';
        distance = currentProcessed - upper;
      }
      sev = severity(type, adjustedStats, distance);
    }

    // Stabilization write-back: later windows see this point clamped to the
    // bound it violated, not the anomalous observation.
    if (stabilize && isAnomaly) {
      work[i] = currentProcessed < lower ? lower : upper;
    }

    // STEP 11: band center from the adjusted statistics.
    const center = bandCenter(type, adjustedStats);

    results.push({
      index: i,
      timestamp: currentTs,
      value: currentVal,
      processedValue: currentProcessed,
      scored: true,
      isAnomaly,
      lower,
      upper,
      center,
      direction,
      severity: sev,
      reason: 'ok',
    });
  }

  return results;
}

/**
 * Distinct seasonal-key cardinality for a grouping set — the binding grouping
 * (most distinct keys) drives how much history is needed before per-group stats
 * can engage. Each grouping is a conjunction of columns; we take the max over
 * groupings.
 */
function seasonalityCardinality(series: Series, groups: string[][]): number {
  const data = series.seasonalityData;
  if (!data || data.length === 0) return 0;
  let card = 0;
  for (const group of groups) {
    const seen = new Set<string>();
    for (const row of data) {
      seen.add(group.map((c) => String(row?.[c] ?? '')).join('|'));
    }
    card = Math.max(card, seen.size);
  }
  return card;
}

/**
 * First index where the detector runs at "full power" for these params — past
 * every warm-up: the min-samples floor, smoothing / input_type, and (when
 * seasonality grouping is active AND the trailing window can actually hold
 * `minSamplesPerGroup` points of every key) the per-group fill. Before this
 * index the band is a degraded lead-in (global fallback / partial window) that
 * should not read as real detection. Returns a clamped index in [0, n].
 */
export function effectiveStartIndex(series: Series, params: DetectorParams): number {
  const n = series.timestamps.length;
  // manual_bounds is stateless: no warm-up except the first change point being
  // undefined when input_type transforms to changes.
  if (params.type === 'manual_bounds') {
    return Math.min(params.inputType !== 'values' ? 1 : 0, n);
  }
  let warm = Math.max(params.minSamples, MIN_SAMPLES_FLOOR[params.type as WindowedType]);
  if (params.smoothing === 'sma') warm = Math.max(warm, params.smoothingWindow - 1);
  if (params.smoothing === 'ema') warm = Math.max(warm, Math.ceil(5 / params.smoothingAlpha));
  if (params.inputType !== 'values') warm = Math.max(warm, 1);

  const seasonalityActive =
    params.seasonalityComponents !== null &&
    params.seasonalityComponents.length > 0 &&
    Array.isArray(series.seasonalityData) &&
    series.seasonalityData.length > 0;
  if (seasonalityActive) {
    const card = seasonalityCardinality(series, params.seasonalityComponents as string[][]);
    if (card > 0) {
      const groupWarm = params.minSamplesPerGroup * card;
      // Groups only ever engage if the window can hold enough same-key points;
      // otherwise the detector stays in global fallback the whole way and there
      // is no degraded-then-sharp transition to hide.
      if (params.windowSize >= groupWarm) warm = Math.max(warm, groupWarm);
    }
  }
  return Math.min(warm, n);
}

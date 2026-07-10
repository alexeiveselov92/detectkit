// Deterministic synthetic time-series generator for the interactive landing demo.
//
// A visitor "dials in a metric that looks like theirs" — a seasonality shape, a
// noise level, a trend and an injected anomaly — and we fabricate a metric on a
// complete time grid plus a ground-truth anomaly mask the detector demo scores
// against. Everything here is pure and deterministic: the same `SynthOptions`
// (including `opts.seed`) produce byte-identical output. No `Math.random`, no
// `Date.now` — a seeded PRNG and a fixed anchor epoch keep it reproducible.

import type { Series, SeasonalityRow, SynthOptions } from './types';

// ----------------------------------------------------------------------------
// Constants
// ----------------------------------------------------------------------------

/** Fixed anchor: the series ends at this epoch so output never depends on the clock. */
const ANCHOR_EPOCH_MS = Date.UTC(2024, 0, 1);
const SECONDS_PER_DAY = 86_400;
const SECONDS_PER_WEEK = 7 * SECONDS_PER_DAY;

/** Baseline level all presets ride on (a latency-/throughput-like magnitude). */
const BASE_LEVEL = 100;

/** Gaussian sigma as a fraction of the signal amplitude, per noise level. */
const NOISE_SIGMA_RATIO: Record<SynthOptions['noise'], number> = {
  low: 0.03,
  medium: 0.08,
  high: 0.18,
};

/** Linear trend ramp across the whole span, as a fraction of the base level. */
const TREND_FRACTION = 0.35;

// ----------------------------------------------------------------------------
// Seeded PRNG (mulberry32) + gaussian noise (Box-Muller)
// ----------------------------------------------------------------------------

/** mulberry32: a tiny, fast, well-distributed 32-bit seeded PRNG → [0, 1). */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296;
  };
}

/** Standard-normal sample (mean 0, sigma 1) via Box-Muller on a uniform source. */
function gaussian(rand: () => number): number {
  // Guard against log(0): u1 is drawn in (0, 1].
  const u1 = 1 - rand();
  const u2 = rand();
  return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

// ----------------------------------------------------------------------------
// Calendar helpers (derive hour-of-day / day-of-week from an epoch)
// ----------------------------------------------------------------------------

/** UTC hour-of-day [0, 23] for a ms epoch. */
function hourOfDay(ms: number): number {
  return Math.floor((ms / 1000 / 3600) % 24 + 24) % 24;
}

/** UTC day-of-week [0, 6], 0 = Sunday (matches JS getUTCDay). */
function dayOfWeek(ms: number): number {
  return new Date(ms).getUTCDay();
}

/** True for Saturday/Sunday. */
function isWeekend(dow: number): boolean {
  return dow === 0 || dow === 6;
}

// ----------------------------------------------------------------------------
// Seasonal shape (deterministic, parameterised by epoch only)
// ----------------------------------------------------------------------------

/**
 * Seasonal component (added on top of `BASE_LEVEL`) plus the local signal
 * amplitude that noise / anomaly magnitude are scaled against. Returning the
 * amplitude alongside the value keeps both calibrated to the same shape.
 */
interface SeasonalSample {
  /** seasonal offset to add to the base level. */
  value: number;
  /** characteristic swing of the shape — the unit noise and anomalies scale to. */
  amplitude: number;
}

function seasonalSample(preset: SynthOptions['seasonality'], ms: number, rand: () => number): SeasonalSample {
  const hour = hourOfDay(ms);
  const dow = dayOfWeek(ms);
  // Continuous phase within the day/week for smooth sinusoids.
  const dayPhase = (2 * Math.PI * (ms / 1000)) / SECONDS_PER_DAY;
  const weekPhase = (2 * Math.PI * (ms / 1000)) / SECONDS_PER_WEEK;

  switch (preset) {
    case 'flat':
      // No cycle: the only swing is the noise envelope itself.
      return { value: 0, amplitude: BASE_LEVEL };

    case 'daily': {
      // One cycle per day; trough near local "night", peak mid-cycle.
      const amp = 0.4 * BASE_LEVEL;
      return { value: amp * Math.sin(dayPhase), amplitude: amp };
    }

    case 'weekly': {
      // Slow single cycle across the week.
      const amp = 0.4 * BASE_LEVEL;
      return { value: amp * Math.sin(weekPhase), amplitude: amp };
    }

    case 'daily_weekly': {
      // Daily sinusoid whose amplitude is modulated by a weekly envelope so
      // weekends ride lower (envelope in [0.4, 1.0]).
      const envelope = 0.7 + 0.3 * Math.cos(weekPhase); // peaks midweek, dips at the week edge
      const amp = 0.4 * BASE_LEVEL * envelope;
      return { value: amp * Math.sin(dayPhase), amplitude: amp };
    }

    case 'business_hours': {
      // High plateau on weekday daytime, low at night and on weekends. A raised
      // cosine bump centred on 13:30 gives a smooth (not square) working day.
      const swing = 0.6 * BASE_LEVEL;
      let level = -0.5 * swing; // off-hours floor
      if (!isWeekend(dow)) {
        // Smooth bump over ~09:00–18:00 (centre 13.5, half-width 4.5h).
        const t = (hour - 13.5) / 4.5;
        const bump = Math.exp(-0.5 * t * t); // gaussian-ish plateau in [0, 1]
        level = -0.5 * swing + swing * bump;
      }
      return { value: level, amplitude: swing };
    }

    case 'spiky_counts': {
      // Low count-like baseline with frequent small positive bursts. The bursts
      // are part of the *normal* signal here (not anomalies); amplitude reflects
      // the typical burst height so noise/anomalies stay calibrated.
      const baselineRate = 4; // expected baseline count
      // Poisson-ish burst: a geometric-tailed positive integer fired ~30% of points.
      let burst = 0;
      if (rand() < 0.3) {
        // Sum of a few exponential-ish draws → small skewed positive integer.
        burst = Math.round(2 + 4 * (-Math.log(1 - rand())));
      }
      // Centre the component on the base level so the composed value sits low-ish.
      const amp = 6;
      return { value: baselineRate + burst - BASE_LEVEL + amp, amplitude: amp };
    }

    case 'pulse': {
      // A fast, free-running ~7-hour cycle that deliberately does NOT align with
      // the calendar: gcd(7h, 24h) = 1h, so each hour-of-day key sees every phase
      // and hour/dow conditioning can't capture the pattern (the per-key band
      // spans the whole wave) — but a short AR forecast extrapolates it easily.
      // The autoreg showcase rhythm.
      const pulsePhase = (2 * Math.PI * (ms / 1000)) / (7 * 3600);
      const amp = 0.45 * BASE_LEVEL;
      return { value: amp * Math.sin(pulsePhase), amplitude: amp };
    }

    default: {
      // Exhaustiveness guard — unreachable for the union above.
      const _never: never = preset;
      return _never;
    }
  }
}

// ----------------------------------------------------------------------------
// Trend
// ----------------------------------------------------------------------------

/** Gentle linear ramp from 0 at the first point to ±TREND_FRACTION·level at the last. */
function trendComponent(kind: SynthOptions['trend'], i: number, points: number): number {
  if (kind === 'none' || points <= 1) return 0;
  const frac = i / (points - 1); // 0 → 1 across the span
  const span = TREND_FRACTION * BASE_LEVEL;
  return kind === 'up' ? span * frac : -span * frac;
}

// ----------------------------------------------------------------------------
// Anomaly injection
// ----------------------------------------------------------------------------

/** Where the injected anomaly starts: in the later part so there is history before it. */
function anomalyStartIndex(points: number): number {
  return Math.min(points - 1, Math.max(0, Math.floor(points * 0.78)));
}

/** Points per dominant seasonal cycle (~7h for pulse, week for weekly, else day). */
function dominantPeriodPoints(opts: SynthOptions): number {
  const cycleSeconds =
    opts.seasonality === 'pulse'
      ? 7 * 3600
      : opts.seasonality === 'weekly'
        ? SECONDS_PER_WEEK
        : SECONDS_PER_DAY;
  return Math.max(1, Math.round(cycleSeconds / opts.intervalSeconds));
}

/**
 * Inject the anomaly in place and flag the affected points as ground truth.
 *
 * `anomalyMagnitude` (0..1) is scaled into multiples of the LOCAL noise sigma so
 * a low slider reads borderline (~3σ) and a high slider is unmistakable (~14σ).
 * For step/drift the deviation is also expressed relative to the local sigma so
 * the shift is detectable regardless of the chosen noise level.
 */
function injectAnomaly(
  opts: SynthOptions,
  values: number[],
  truth: boolean[],
  sigma: number,
  amplitudes: number[],
  rand: () => number,
): void {
  const m = Math.min(1, Math.max(0, opts.anomalyMagnitude));
  const start = anomalyStartIndex(opts.points);
  // Point-deviation in value units: 3σ (borderline) → 14σ (obvious), local sigma.
  const pointDev = (3 + 11 * m) * sigma;
  // Sustained shifts read against the slower-moving amplitude as well as sigma.
  const ampDev = (0.4 + 1.6 * m) * (amplitudes[start] || BASE_LEVEL);
  const sustainedDev = Math.max(pointDev, ampDev);

  switch (opts.anomaly) {
    case 'spike': {
      values[start] += pointDev;
      truth[start] = true;
      break;
    }
    case 'dip': {
      values[start] -= pointDev;
      truth[start] = true;
      break;
    }
    case 'cluster': {
      // 3–5 nearby points pushed up; the count scales gently with magnitude.
      const count = 3 + Math.round(2 * m);
      for (let k = 0; k < count && start + k < opts.points; k++) {
        values[start + k] += pointDev * (0.7 + 0.3 * (1 - k / count));
        truth[start + k] = true;
      }
      break;
    }
    case 'step': {
      // Sustained level shift from `start` to the end; mark the leading run as
      // truth so recall is meaningful without flooding the mask.
      const markRun = 12;
      for (let k = start; k < opts.points; k++) {
        values[k] += sustainedDev;
        if (k - start < markRun) truth[k] = true;
      }
      break;
    }
    case 'drift': {
      // Gradual ramp away from normal over a span; the ramped span is truth.
      const span = Math.min(15, opts.points - start);
      for (let k = 0; k < span; k++) {
        const frac = (k + 1) / span; // 0 → 1 across the ramp
        values[start + k] += sustainedDev * frac;
        truth[start + k] = true;
      }
      // The series stays shifted after the ramp (not flagged — it is the new normal).
      for (let k = start + span; k < opts.points; k++) {
        values[k] += sustainedDev;
      }
      break;
    }
    case 'pattern_break': {
      // The value FREEZES at its current reading mid-rhythm (a stuck sensor, a dead
      // upstream, a cache serving one stale answer): every frozen point stays inside
      // the normal envelope, so level-modeling detectors see nothing — only the
      // SHAPE is wrong. This is the autoreg showcase. For the fast free-running
      // pulse the freeze spans about a FULL cycle (the wave is short, so a whole
      // stalled cycle is what reads as "stuck"); calendar rhythms freeze about a
      // quarter cycle. The size slider stretches it 0.5x-1.5x either way.
      const period = dominantPeriodPoints(opts);
      const base = opts.seasonality === 'pulse' ? period : period / 4;
      const span = Math.max(3, Math.min(40, Math.round(base * (0.5 + m))));
      const hold = start > 0 ? values[start - 1] : values[start];
      const jitter = 0.15 * sigma; // a hair of noise so the freeze reads as data, not a gap
      for (let k = 0; k < span && start + k < opts.points; k++) {
        values[start + k] = hold + gaussian(rand) * jitter;
        truth[start + k] = true;
      }
      break;
    }
    default: {
      const _never: never = opts.anomaly;
      void _never;
    }
  }
}

// ----------------------------------------------------------------------------
// Public API
// ----------------------------------------------------------------------------

/** Build a synthetic series + ground-truth anomaly mask from the options. */
export function generateSeries(opts: SynthOptions): Series {
  const { points, intervalSeconds, seasonality } = opts;
  const rand = mulberry32(opts.seed);

  const timestamps = new Array<number>(points);
  const values = new Array<number>(points);
  const truthAnomaly = new Array<boolean>(points).fill(false);
  const amplitudes = new Array<number>(points);
  const seasonalityData = new Array<SeasonalityRow>(points);

  // Grid ends at the fixed anchor; point i sits (points-1-i) intervals before it.
  const stepMs = intervalSeconds * 1000;
  const firstMs = ANCHOR_EPOCH_MS - (points - 1) * stepMs;

  // Compose the clean signal first so we can size noise against the local amplitude.
  for (let i = 0; i < points; i++) {
    const ms = firstMs + i * stepMs;
    timestamps[i] = ms;

    const { value: seasonal, amplitude } = seasonalSample(seasonality, ms, rand);
    amplitudes[i] = amplitude;

    const trend = trendComponent(opts.trend, i, points);
    const signal = BASE_LEVEL + seasonal + trend;

    // Noise sigma scales with the local amplitude so the SNR reads consistently.
    const sigma = NOISE_SIGMA_RATIO[opts.noise] * amplitude;
    let v = signal + gaussian(rand) * sigma;

    // Count-like presets stay non-negative integers.
    if (seasonality === 'spiky_counts') {
      v = Math.max(0, Math.round(v));
    } else {
      // Keep latency/throughput values sensibly positive.
      v = Math.max(0, v);
    }
    values[i] = v;

    seasonalityData[i] = {
      hour_of_day: hourOfDay(ms),
      day_of_week: dayOfWeek(ms),
    };
  }

  // Inject the anomaly using a representative sigma (median local amplitude).
  const refAmplitude = amplitudes[anomalyStartIndex(points)] || BASE_LEVEL;
  const refSigma = NOISE_SIGMA_RATIO[opts.noise] * refAmplitude;
  injectAnomaly(opts, values, truthAnomaly, refSigma, amplitudes, rand);

  // Re-clamp anomaly-affected points to honour the per-preset value invariants.
  if (seasonality === 'spiky_counts') {
    for (let i = 0; i < points; i++) values[i] = Math.max(0, Math.round(values[i]));
  } else {
    for (let i = 0; i < points; i++) values[i] = Math.max(0, values[i]);
  }

  return {
    timestamps,
    values,
    intervalSeconds,
    truthAnomaly,
    seasonalityData,
    seasonalityColumns: ['hour_of_day', 'day_of_week'],
  };
}

// Shared contract for the interactive "playground" landing demo.
//
// The demo runs entirely client-side: synth.ts fabricates a metric, detector.ts
// re-implements detectkit's windowed statistical detectors (MAD / Z-Score / IQR)
// faithfully in TS, and chart.ts paints the series, the confidence corridor, the
// flagged points and the trailing window used to score the hovered point. main.ts
// wires the controls and the scorecard. Each module imports ONLY from this file,
// so the three implementations can evolve independently behind these types.

// ----------------------------------------------------------------------------
// Series
// ----------------------------------------------------------------------------

/** Per-point seasonal key, one map per timestamp (column name -> integer code). */
export type SeasonalityRow = Record<string, number>;

/** A metric on a complete, evenly-spaced time grid (gaps are NaN values). */
export interface Series {
  /** ms epoch, strictly increasing, spaced by `intervalSeconds * 1000`. */
  timestamps: number[];
  /** metric value; NaN marks a gap-filled missing point. */
  values: number[];
  /** grid step in seconds (e.g. 600 = 10min, 3600 = 1h, 86400 = 1d). */
  intervalSeconds: number;
  /** ground truth: true where an anomaly was injected (drives the scorecard). */
  truthAnomaly: boolean[];
  /** optional per-point seasonal keys, present when the synth emits them. */
  seasonalityData?: SeasonalityRow[];
  /** seasonal column names available in `seasonalityData` (e.g. ["hour_of_day"]). */
  seasonalityColumns?: string[];
}

// ----------------------------------------------------------------------------
// Synthetic data generation (synth.ts)
// ----------------------------------------------------------------------------

export type SeasonalityPreset =
  | 'flat' // no cycle, just a level + noise
  | 'daily' // one cycle per day
  | 'weekly' // one slow cycle per week
  | 'daily_weekly' // daily cycle modulated by a weekly envelope
  | 'business_hours' // high on weekday daytime, low nights/weekends
  | 'spiky_counts'; // low baseline with frequent positive bursts (count-like)

export type NoiseLevel = 'low' | 'medium' | 'high';
export type TrendKind = 'none' | 'up' | 'down';

export type AnomalyKind =
  | 'spike' // one sharp positive outlier
  | 'dip' // one sharp negative outlier
  | 'step' // sustained level shift from a point onward
  | 'drift' // gradual ramp away from normal over a span
  | 'cluster'; // a short burst of several outliers

export interface SynthOptions {
  seasonality: SeasonalityPreset;
  noise: NoiseLevel;
  trend: TrendKind;
  /** grid step in seconds. */
  intervalSeconds: number;
  /** total number of points on the grid. */
  points: number;
  anomaly: AnomalyKind;
  /** 0..1 slider; synth scales it into a sensible magnitude per anomaly kind. */
  anomalyMagnitude: number;
  /** deterministic PRNG seed (same seed + opts => identical series). */
  seed: number;
}

/** Build a synthetic series + ground-truth anomaly mask from the options. */
export type GenerateSeries = (opts: SynthOptions) => Series;

// ----------------------------------------------------------------------------
// Detector (detector.ts) — faithful port of WindowedStatDetector
// ----------------------------------------------------------------------------

export type DetectorType = 'mad' | 'zscore' | 'iqr' | 'manual_bounds';
/** The windowed statistical detectors (everything except stateless manual_bounds). */
export type WindowedType = 'mad' | 'zscore' | 'iqr';
/** Alert-layer direction filter: which anomaly direction counts ('any' = both). */
export type AlertDirection = 'any' | 'up' | 'down';
export type InputType = 'values' | 'changes' | 'absolute_changes' | 'log_changes';
export type Smoothing = 'none' | 'ema' | 'sma';
export type WindowWeights = 'none' | 'exponential' | 'linear';
export type Detrend = 'none' | 'linear';

export interface DetectorParams {
  type: DetectorType;
  /** interval width in spread units (MAD/Z default 3.0, IQR default 1.5). */
  threshold: number;
  /** trailing window length in points (current point excluded). */
  windowSize: number;
  /** minimum valid points in a window required to score (floored per type). */
  minSamples: number;
  inputType: InputType;
  smoothing: Smoothing;
  /** EMA factor in (0,1], default 0.3. */
  smoothingAlpha: number;
  /** SMA window length, default 10. */
  smoothingWindow: number;
  windowWeights: WindowWeights;
  /** exponential half-life in POINTS; null = adaptive default (see spec). */
  halfLife: number | null;
  detrend: Detrend;
  /**
   * Seasonality groupings, each a conjunction of column names, e.g.
   * [["hour_of_day"]] or [["hour_of_day","day_of_week"]]. null = off.
   */
  seasonalityComponents: string[][] | null;
  /** per-group fallback threshold; below this a group reverts to global stats. */
  minSamplesPerGroup: number;
  /**
   * Alert-layer knob (NOT a band parameter): how many grid-adjacent flagged
   * points must form a run before an alert "fires". Used only by the scorecard
   * / alert-timeline overlay, never by the per-point band math.
   */
  consecutiveAnomalies: number;
  /**
   * manual_bounds only — the user threshold the value is compared against
   * (null = that side is open). Ignored by the windowed detectors.
   */
  lowerBound?: number | null;
  upperBound?: number | null;
  /**
   * Alert-layer knob (NOT a band parameter): which anomaly direction is counted
   * as a flag for the alert timeline / dots ('any' = both). Omitted = 'any'.
   * The per-point band math is unaffected.
   */
  direction?: AlertDirection;
}

export type AnomalyDirection = 'above' | 'below' | null;
export type ScoreReason = 'ok' | 'missing_data' | 'insufficient_data';

/** One scored grid point. lower/upper/center are NaN when `scored` is false. */
export interface ScoredPoint {
  index: number;
  timestamp: number;
  /** original (display) value, may be NaN for a gap. */
  value: number;
  /** value after smoothing + input_type transform; NaN when un-scorable. */
  processedValue: number;
  /** false for missing_data / insufficient_data points (no band drawn). */
  scored: boolean;
  isAnomaly: boolean;
  lower: number;
  upper: number;
  /** band center (median / mean / midhinge) — used by the window overlay. */
  center: number;
  direction: AnomalyDirection;
  /** spread-units beyond the breached bound (0 when not anomalous). */
  severity: number;
  reason: ScoreReason;
}

/**
 * Score every point of `series` under `params`. Pure and deterministic. Must
 * reproduce the Python detectors within 1e-6 on the golden-parity vectors.
 */
export type RunDetector = (series: Series, params: DetectorParams) => ScoredPoint[];

// ----------------------------------------------------------------------------
// Scorecard (computed in main.ts from the ScoredPoint[] + ground truth)
// ----------------------------------------------------------------------------

export interface Scorecard {
  /** injected anomalies that were flagged (point-wise, within a small tolerance window). */
  caught: number;
  /** injected anomalies that were missed. */
  missed: number;
  /** flags on non-injected points. */
  falsePositives: number;
  injectedTotal: number;
  flaggedTotal: number;
  scoredTotal: number;
  /** flaggedTotal / scoredTotal. */
  flagRate: number;
  precision: number;
  recall: number;
  f1: number;
  mcc: number;
  /** true when some run of grid-adjacent flags reaches consecutiveAnomalies. */
  alertWouldFire: boolean;
  /** index of the first point where an alert would fire (-1 if none). */
  alertFireIndex: number;
  /**
   * One index per qualifying incident: the point where a maximal run of
   * grid-adjacent flags REACHES consecutiveAnomalies (an alert fires there).
   * `alertFireIndex` is the first of these.
   */
  alertFireIndexes: number[];
}

// ----------------------------------------------------------------------------
// Chart (chart.ts)
// ----------------------------------------------------------------------------

export interface HoverInfo {
  /** index of the point under the cursor, or -1. */
  index: number;
  point: ScoredPoint | null;
  /** inclusive grid range [start, end] of the trailing window for `index`. */
  windowStart: number;
  windowEnd: number;
}

/** A fired alert to surface on the chart timeline: ms-epoch + kind. */
export interface ChartAlert {
  /** ms-epoch timestamp where the alert fired. */
  t: number;
  /** 'anomaly' | 'recovery' | 'nodata' — picks the marker color. */
  kind: string;
}

export interface ChartData {
  series: Series;
  scored: ScoredPoint[];
  params: DetectorParams;
  /** all fired alerts, drawn as colored markers along the top axis. */
  alerts?: ChartAlert[];
}

export interface ChartOptions {
  /** notified as the cursor moves so main.ts can update a textual readout. */
  onHover?: (info: HoverInfo | null) => void;
  /**
   * Opt-in time navigation (used by `dtk tune`, not the fixed-window landing
   * demo): mouse-wheel zoom, drag-to-pan, double-click reset and a bottom
   * navigator/minimap strip with the current-view window + alert ticks. When
   * false/absent the whole series is fitted to the canvas width as before.
   */
  navigable?: boolean;
}

export interface ChartHandle {
  /** repaint with fresh data (called on every control change). */
  render(data: ChartData): void;
  /** re-fit the backing store to the element size (call on resize). */
  resize(): void;
  destroy(): void;
}

/** Construct a chart bound to a <canvas>. */
export type CreateChart = (canvas: HTMLCanvasElement, opts?: ChartOptions) => ChartHandle;

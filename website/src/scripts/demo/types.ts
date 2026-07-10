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
  | 'spiky_counts' // low baseline with frequent positive bursts (count-like)
  | 'pulse'; // free-running ~7h cycle, NOT calendar-aligned (the autoreg showcase)

export type NoiseLevel = 'low' | 'medium' | 'high';
export type TrendKind = 'none' | 'up' | 'down';

export type AnomalyKind =
  | 'spike' // one sharp positive outlier
  | 'dip' // one sharp negative outlier
  | 'step' // sustained level shift from a point onward
  | 'drift' // gradual ramp away from normal over a span
  | 'cluster' // a short burst of several outliers
  | 'pattern_break'; // the value freezes mid-rhythm — normal in level, wrong in shape

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

export type DetectorType = 'mad' | 'zscore' | 'iqr' | 'manual_bounds' | 'autoreg';
/** The windowed statistical detectors (not stateless manual_bounds, not the
 * prediction-based autoreg — both have their own runDetector branches). */
export type WindowedType = 'mad' | 'zscore' | 'iqr';
/** Alert-layer direction filter: which anomaly direction counts ('any' = both). */
export type AlertDirection = 'any' | 'up' | 'down';
export type InputType = 'values' | 'changes' | 'absolute_changes' | 'log_changes';
export type Smoothing = 'none' | 'ema' | 'sma';
export type WindowWeights = 'none' | 'exponential' | 'linear';
export type Detrend = 'none' | 'linear';
export type Stabilization = 'none' | 'clamp';

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
   * Anomaly-robust baseline (winsorizing): flagged points enter subsequent
   * trailing windows clamped to the confidence bound they violated, so a long
   * incident cannot inflate the band and mask itself. Omitted = 'none'.
   */
  stabilization?: Stabilization;
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
   * autoreg only — AR order: how many immediately-preceding values predict the
   * current one. Ignored by the other detectors. Omitted = 5.
   */
  lags?: number;
  /**
   * Alert-layer knob (NOT a band parameter): which anomaly direction is counted
   * as a flag for the alert timeline / dots ('any' = both). Omitted = 'any'.
   * The per-point band math is unaffected.
   */
  direction?: AlertDirection;
}

export type AnomalyDirection = 'above' | 'below' | null;
/** `missing_lags` is autoreg-only: a NaN gap inside the lag view (strict v1
 * policy — never impute across a gap). Rendered like insufficient_data. */
export type ScoreReason = 'ok' | 'missing_data' | 'insufficient_data' | 'missing_lags';

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
  /**
   * Picks the marker color:
   * - 'anomaly'           — fired, not yet reviewed (red)
   * - 'anomaly-validated' — the user confirmed it's a real alert (green)
   * - 'anomaly-false'     — the user marked it a false alarm (slate, recedes)
   * - 'recovery' | 'nodata' — pipeline event markers
   */
  kind: string;
}

/**
 * Which working mode the chart is in (labeling charts only — see ChartOptions.mode).
 * The mode drives which visual LAYERS are full / dimmed / hidden and which
 * interactions are armed, so one chart serves tuning, alert-review and labeling
 * without two stacked canvases:
 * - 'tune'   — steer the band: band full, incidents dim/read-only, hover window on.
 * - 'review' — confirm the fired alerts: band ghosted, alert markers are the subject
 *              (click one to cycle its verdict), incidents dim/read-only.
 * - 'label'  — mark incidents: band hidden, incidents full + editable, capture tools armed.
 */
export type ChartMode = 'tune' | 'review' | 'label';

/** Per-alert review verdict (keyed on the fire timestamp in the cockpit). */
export type AlertVerdict = 'unreviewed' | 'valid' | 'false';

/**
 * A labeled real-world incident span (ms-epoch). Drawn as a shaded band on the
 * chart; on a `labeling` chart it can be created/moved/resized/deleted, and the
 * `dtk tune` cockpit overlays the same spans (read-only) on the detector chart to
 * compute the live catch-rate / false-alert metrics. A point incident is a
 * degenerate span with `start === end`.
 */
export interface Incident {
  start: number;
  end: number;
  label?: string;
}

/**
 * Live state of the threshold-capture tool (labeling charts only): a horizontal
 * line that grabs every contiguous run of points on one side of it. Pushed to the
 * UI via `ChartOptions.onThresholdChange` so it can render the run count, the line
 * value and the active capture scope.
 */
export interface ThresholdInfo {
  /** the effective line value (a pinned value wins, else the live cursor), or null. */
  value: number | null;
  /** true when the value is pinned (typed or clicked), false while it follows the cursor. */
  locked: boolean;
  /** how many spans would be captured right now. */
  runs: number;
  /** the painted capture window (ms), live during a drag, or null when capturing the view. */
  window: { start: number; end: number } | null;
  /** true once a capture window is COMMITTED (mouseup), false while merely drag-painting. */
  committed: boolean;
  /** duration (ms) of the active capture region (painted window or current view). */
  windowMs: number;
}

/**
 * Live state of the lasso-capture tool (labeling charts only): draw a freeform
 * loop around a cloud of detector anomalies (or raw points where no detector
 * runs) and turn each grid-adjacent run — bridging small gaps — into one proper
 * incident SPAN. Pushed to the UI via `ChartOptions.onLassoChange` so a toolbar
 * can show the live capture count. See `ChartHandle.setLassoMode`.
 */
export interface LassoInfo {
  /** true while a loop is being drawn. */
  active: boolean;
  /** anomalies currently enclosed by the in-progress loop. */
  anomalies: number;
  /** incidents the current loop would create (grid-adjacent runs, gaps bridged). */
  incidents: number;
}

export interface ChartData {
  series: Series;
  scored: ScoredPoint[];
  params: DetectorParams;
  /** all fired alerts, drawn as colored markers along the top axis. */
  alerts?: ChartAlert[];
  /**
   * Labeled incident spans drawn as shaded bands. On a non-`labeling` chart they
   * are read-only context (e.g. the tune detector chart); a `labeling` chart owns
   * its own incidents (seed/replace via `ChartHandle.setIncidents`).
   */
  incidents?: Incident[];
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
  /**
   * Vertical autoscale source. 'band' (default) fits the y-axis to the union of
   * the data and the confidence band, so the whole band is always visible — right
   * for the read-only report. 'data' fits to the data values only (the band may
   * extend past the plot edges, clipped); used by `dtk tune` so that turning the
   * threshold visibly widens/narrows the band relative to the data instead of the
   * axis rescaling in lockstep and hiding the change.
   */
  yFit?: 'band' | 'data';
  /**
   * Draw a horizontal reference line at y = 0 and fold 0 into the y-domain, so a
   * real-valued metric can be read RELATIVE TO ZERO. Off by default (the landing
   * playground / report are unaffected); toggle live via `setZeroLine`.
   */
  showZeroLine?: boolean;
  /**
   * Incident-labeling mode: drag on the plot to mark an incident span, drag its
   * edges to resize / its middle to move, click its ✕ (or select + Delete) to
   * remove it. Pan/zoom stays available via the navigator strip + wheel. Used by
   * the `dtk tune` cockpit's single chart; off by default.
   */
  labeling?: boolean;
  /**
   * Working mode for a labeling chart (see ChartMode). Default 'tune'. Drives the
   * per-layer full/dim/hidden states + which interactions are armed, so the cockpit
   * runs tuning / alert-review / labeling on ONE chart. Ignored on non-labeling
   * charts (the landing demo), which always render in the 'tune' layer set — i.e.
   * exactly as before. Switch live via `setMode`.
   */
  mode?: ChartMode;
  /**
   * Called when the user cycles a fired alert's review verdict (clicking its marker
   * in 'review'/'label' mode). `fireTs` is the alert's fire timestamp; `verdict` is
   * the NEXT state. The cockpit stores it and re-renders with the alert's `kind`
   * updated. Labeling charts only.
   */
  onAlertReviewChange?: (fireTs: number, verdict: AlertVerdict) => void;
  /**
   * Called whenever the user edits incidents in `labeling` mode. `incidents` is the
   * live array (shared ref). `removed` is the incident that was just DELETED (✕ handle
   * or Delete key) — present only for deletions, so the cockpit can retract a
   * confirmed-alert verdict that span overlapped rather than let it resurface.
   */
  onIncidentsChange?: (incidents: Incident[], removed?: Incident) => void;
  /**
   * Called whenever the threshold-capture preview changes (line value, run count
   * or painted window) in `labeling` mode. Used by the `dtk tune` cockpit to drive
   * the "Add N spans" button + scope readout. See `ChartHandle.setThresholdMode`.
   */
  onThresholdChange?: (info: ThresholdInfo) => void;
  /**
   * Called as a lasso loop is drawn / committed in `labeling` mode (see
   * `ChartHandle.setLassoMode`). Drives the toolbar's live "N anomalies → M
   * incidents" readout.
   */
  onLassoChange?: (info: LassoInfo) => void;
  /**
   * Called whenever the visible window changes (zoom / pan / reset). Used to keep
   * two charts in sync — the listener typically calls the other chart's
   * `setViewWindow`. Only fires for user-driven view changes, not programmatic
   * `setViewWindow` (which suppresses re-emit to avoid feedback loops).
   */
  onViewChange?: (viewMin: number, viewMax: number) => void;
  /**
   * Show the bottom navigator/minimap strip. Defaults to true when `navigable`.
   * Set false to keep wheel-zoom + drag-pan but hide the strip (e.g. the tune
   * cockpit's detector chart, whose strip is provided by the synced labeler chart
   * beneath it).
   */
  showNavigator?: boolean;
}

export interface ChartHandle {
  /** repaint with fresh data (called on every control change). */
  render(data: ChartData): void;
  /** re-fit the backing store to the element size (call on resize). */
  resize(): void;
  /** Switch the working mode (labeling charts only): 'tune' | 'review' | 'label'. */
  setMode(mode: ChartMode): void;
  /** Toggle the y = 0 reference line + 0-relative scaling (see ChartOptions.showZeroLine). */
  setZeroLine(on: boolean): void;
  /** Set the visible window programmatically WITHOUT re-emitting onViewChange (for sync). */
  setViewWindow(a: number, b: number): void;
  /** Replace the incident spans (seed/reset). Clears any selection. */
  setIncidents(incidents: Incident[]): void;
  /**
   * Threshold-capture (labeling charts only): grab every contiguous run of points
   * on one side of a horizontal line in one click. `setThresholdMode` toggles the
   * tool; while on, a plot click sets the line value, a horizontal plot drag paints
   * a capture window, and `applyThreshold` commits the previewed spans as incidents.
   */
  setThresholdMode(on: boolean): void;
  /** Capture points 'above' or 'below' the line. */
  setThresholdDirection(dir: 'above' | 'below'): void;
  /** Bridge gaps up to this many non-matching points when forming contiguous spans. */
  setThresholdGap(gap: number): void;
  /** Pin the line to a value (null → follow the cursor / last click). */
  setThresholdValue(value: number | null): void;
  /** Commit the previewed spans into incidents; returns how many were added. */
  applyThreshold(): number;
  /**
   * Lasso-capture (labeling charts only): draw a freeform loop around a cloud of
   * detector anomalies (the dots, when `ChartData.scored` carries them) — or raw
   * points where no detector runs — and turn each grid-adjacent run (bridging
   * gaps up to `consecutiveAnomalies`) into one proper incident span. Toggles the
   * tool; while on, a plot drag draws the loop and mouseup commits.
   */
  setLassoMode(on: boolean): void;
  /** Clear the painted capture window (back to capturing the current view). */
  clearCaptureWindow(): void;
  /** The painted capture window for persistence, or null. */
  getCaptureWindow(): { start: number; end: number } | null;
  /** Restore a painted capture window (seed from a saved labels file). */
  setCaptureWindow(win: { start: number; end: number } | null): void;
  destroy(): void;
}

/** Construct a chart bound to a <canvas>. */
export type CreateChart = (canvas: HTMLCanvasElement, opts?: ChartOptions) => ChartHandle;

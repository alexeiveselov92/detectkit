import type { DetectorParams } from '../../demo/types';

// ---------------------------------------------------------------------------
// Effective-config readout + the snake_case apply body
// ---------------------------------------------------------------------------

/** Build the snake_case params written to YAML (omitting defaults/none). */
export function applyParams(p: DetectorParams): Record<string, unknown> {
  if (p.type === 'manual_bounds') {
    // Stateless thresholds — no window/threshold/weights/etc. Both bounds are
    // always emitted by the tuner (the controls keep lower < upper).
    const mb: Record<string, unknown> = {};
    if (p.lowerBound != null) mb.lower_bound = p.lowerBound;
    if (p.upperBound != null) mb.upper_bound = p.upperBound;
    if (p.inputType !== 'values') mb.input_type = p.inputType;
    return mb;
  }
  if (p.type === 'autoreg') {
    // Prediction-based AR(p): its own param set — lags/threshold/window +
    // min_samples (emitted explicitly, clamped valid: the Python constructor
    // requires lags+2 <= min_samples <= window_size) + stabilization, which
    // is DEFAULT-ON for autoreg, so turning it off must be written as null.
    // Never seasonality/weights/detrend/smoothing (v1 has none; the detector
    // rejects truthy seasonality_components).
    const lags = Math.max(1, Math.round(p.lags ?? 5));
    const ar: Record<string, unknown> = {
      lags,
      threshold: p.threshold,
      window_size: p.windowSize,
      min_samples: Math.min(Math.max(p.minSamples, lags + 2), p.windowSize),
    };
    if (p.stabilization !== 'clamp') ar.stabilization = null;
    if (p.inputType !== 'values') ar.input_type = p.inputType;
    return ar;
  }
  const out: Record<string, unknown> = {
    threshold: p.threshold,
    window_size: p.windowSize,
  };
  if (p.windowWeights !== 'none') {
    out.window_weights = p.windowWeights;
    if (p.windowWeights === 'exponential' && p.halfLife != null) out.half_life = p.halfLife;
  }
  if (p.detrend !== 'none') out.detrend = p.detrend;
  if (p.stabilization && p.stabilization !== 'none') out.stabilization = p.stabilization;
  if (p.smoothing !== 'none') out.smoothing = p.smoothing;
  if (p.inputType !== 'values') out.input_type = p.inputType;
  if (p.seasonalityComponents && p.seasonalityComponents.length) {
    out.seasonality_components = p.seasonalityComponents;
    out.min_samples_per_group = p.minSamplesPerGroup;
  }
  return out;
}

export function configText(
  p: DetectorParams,
  consecutive: number,
  windowPoints?: number | null,
  share?: number | null,
): string {
  const ap = applyParams(p);
  const parts = [`type: ${p.type}`];
  for (const [k, v] of Object.entries(ap)) {
    parts.push(`${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`);
  }
  if (p.direction && p.direction !== 'any') parts.push(`direction=${p.direction}`);
  parts.push(`consecutive_anomalies=${consecutive}`);
  if (windowPoints != null && share != null) {
    parts.push(`anomaly_window=${windowPoints}p`);
    parts.push(`min_anomaly_share=${share}`);
  }
  return parts.join('  ·  ');
}

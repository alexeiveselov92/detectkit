# Autoreg Detector (Autoregressive)

The Autoreg detector is detectkit's first **dynamics** detector: instead of
comparing a value against a level statistic (median, mean, quartiles), it
fits a short autoregressive model on recent history and flags values that
break the metric's usual short-range dynamics — even when that value sits
comfortably inside the metric's normal historical range.

## Overview

Where MAD/Z-Score/IQR ask "is this value far from the recent center?", Autoreg
asks "is this value far from what the last few points would have predicted?".
That makes it a good fit for:

- **Fast-moving, non-seasonal metrics** — queue depths, request rates,
  in-flight counts — where the *trajectory* matters more than a static band.
- **Shape anomalies** — a sudden direction change, an oscillation that stops,
  a value that jumps against the recent trend — that a level-based detector
  can miss if the jump lands inside the historical value range.
- **A complement to a level detector** — pairing Autoreg with MAD/Z-Score/IQR
  via `min_detectors` catches both "unusual level" and "unusual dynamics" in
  one alert rule.

It is **not** a drop-in replacement for MAD/Z-Score/IQR: it has no
seasonality support, no smoothing, no recency weighting, and no detrending
(see [Limitations](#v1-limitations) below), and an AR model naturally follows
a slow drift rather than flagging it (see the
[Advanced](#advanced-an-ar-model-follows-slow-drift) note).

## Algorithm

At each point `t`, the detector:

1. Takes the `lags` immediately preceding (processed) values as features:
   `y_{t-1}, ..., y_{t-lags}`.
2. Fits an AR(`lags`) model — an intercept plus one coefficient per lag — by
   ordinary least squares over the trailing `window_size` window (current
   point excluded), using every window row whose target and lag features are
   all finite (gaps are dropped, never imputed).
3. Predicts `ŷ_t` from the current lag vector and computes the fit's residual
   standard deviation `σ_r` over the window.
4. Builds the band `[ŷ_t − threshold·σ_r, ŷ_t + threshold·σ_r]` and flags `t`
   when the actual value falls outside it.

This is a genuine prediction model, not a statistic over a set of values: two
metrics with an identical value distribution but different short-range
dynamics get different bands.

## Parameters

### Algorithm Parameters

#### `lags` (int, default: 5)
AR order — how many immediately-preceding values feed the prediction.

- Must be at least 1 and strictly less than `window_size`.
- **Higher** `lags` lets the model capture longer-range dynamics (e.g. a
  short cyclical pattern) but needs proportionally more history to fit
  reliably.
- **Lower** `lags` (e.g. 1-2) is closer to a pure "does this jump match the
  recent trend" check.

```yaml
detectors:
  - type: autoreg
    params:
      lags: 3
```

#### `window_size` (int, default: 200)
Trailing history (current point excluded) used to refit the AR model at
every point.

- Must be at least `lags + 2` (an AR(`lags`) model has `lags + 1` unknowns —
  the intercept plus one coefficient per lag — so at least one more row than
  that is needed to fit at all).
- Larger windows give a more stable fit but adapt more slowly if the
  underlying dynamics genuinely change.

```yaml
detectors:
  - type: autoreg
    params:
      window_size: 500
```

#### `threshold` (float, default: 3.0)
Band half-width in residual-sigma units: `ŷ_t ± threshold · σ_r`.

- **Higher** = less sensitive, fewer anomalies.
- **Lower** = more sensitive, more anomalies.
- Comparable in spirit to MAD/Z-Score's `threshold`, but expressed in
  *prediction-residual* sigma, not raw-value sigma — the two are not
  numerically interchangeable.

```yaml
detectors:
  - type: autoreg
    params:
      threshold: 4.0  # less sensitive
```

#### `min_samples` (int, default: 30)
Minimum number of valid (gap-free) fit rows required in the window before
scoring a point; points before this are marked `insufficient_data`.

- Must be at least `lags + 2` and at most `window_size`.

```yaml
detectors:
  - type: autoreg
    params:
      min_samples: 50
```

#### `input_type` (str, default: `"values"`)
One of `values`, `changes`, `absolute_changes`, `log_changes` — the same
preprocessing transform shared with the other detectors. See
[Shared Detector Parameters → Input preprocessing](shared-parameters.md#input-preprocessing).

#### `stabilization` (str or None, default: `"clamp"`)
Unlike the windowed detectors (where `stabilization` defaults to `None`),
Autoreg ships with **`clamp` on by default** — it is the detector's key
novation and the reason it exists.

Once a point is flagged anomalous, later fit windows see it clamped to the
confidence bound it violated (`lower` or `upper`), not the raw observed
value. This keeps a sustained incident from being fit directly into the AR
coefficients and residual scale.

> **Advanced — why clamp to the bound, not the prediction.** It would seem
> simpler to substitute the model's own prediction `ŷ_t` for a flagged point.
> Don't: that feeds a **zero-residual** row into every later fit that uses it
> as a lag feature or target, which collapses `σ_r` and then cascades into
> false flags on ordinary noise once the band has shrunk to near nothing —
> the exact center-substitution failure measured and rejected for the
> windowed detectors' own `stabilization: clamp` (see
> [Shared Detector Parameters → Stabilization](shared-parameters.md#stabilization)).
> Clamping to the *violated bound* instead keeps a `threshold · σ_r` residual
> in play, so the model keeps flagging a sustained incident instead of
> adapting to it.

Set `stabilization: null` to disable (the pre-v0.52 windowed-detector
default) — useful mainly for A/B-comparing behavior, since `clamp` is
strictly the intended production setting for this detector.

```yaml
detectors:
  - type: autoreg
    params:
      stabilization: null  # disable (not recommended)
```

**Numerical notes** (v0.53.0, `ALGORITHM_VERSION` 2): each fit window is
centered and scaled before the normal equations are solved, and the clamp
substitution above is capped to the observed window range — both close out
edge-case numerical instability without changing behavior on typical series.
The version bump means Autoreg's `detector_id` changes and detections
recompute on the next run.

### Execution Parameters

`start_time` and `batch_size` control how detection runs without affecting
results (they are not part of the detector ID). See
[Shared Detector Parameters → Execution Parameters](shared-parameters.md#execution-parameters).

### Detector Identity

Every algorithm parameter above (`lags`, `window_size`, `threshold`,
`min_samples`, `input_type`, `stabilization`) is hashed into the
`detector_id`, so changing any of them recomputes detections under a new id
rather than silently mixing regimes. See
[Shared Detector Parameters → Detector Identity and Recomputation](shared-parameters.md#detector-identity-and-recomputation).

## Configuration Example

```yaml
name: queue_depth
interval: 1min
query: "SELECT timestamp, depth FROM queue_metrics"

detectors:
  - type: autoreg
    params:
      lags: 3
      window_size: 300
      threshold: 3.5
      min_samples: 40

alerting:
  enabled: true
  consecutive_anomalies: 2
```

### Paired with a level detector

```yaml
detectors:
  # Catches an unusual level (too high/low vs history)
  - type: mad
    params:
      threshold: 3.0
      window_size: 4320

  # Catches unusual dynamics (a level-consistent but trend-breaking jump)
  - type: autoreg
    params:
      lags: 3
      window_size: 300

alerting:
  enabled: true
  min_detectors: 1     # either one firing is enough
  direction: "any"
```

## Detection Metadata

```python
{
    "fit_points": 187,               # Valid rows used to fit the AR model
    "sigma_r": 0.842,                # Residual standard deviation of the fit
    "prediction": 41.203,            # The model's ŷ_t for this point
    "stabilized_in_window": 4,       # Only when stabilization="clamp" substituted points
    # Only for anomalies:
    "direction": "above",            # "above" or "below"
    "distance": 3.91,                # Absolute distance beyond the violated bound
    "severity": 4.64,                # distance / sigma_r
}
```

`reason` appears instead, with no band, when a point isn't scored:
`missing_data` (the point itself is NaN), `missing_lags` (fewer than `lags`
prior points, or a gap inside the lag window — v1 never imputes across a
gap), or `insufficient_data` (fewer than `min_samples` valid fit rows in the
window).

## V1 Limitations

Autoreg v1 is deliberately minimal:

- **No seasonality.** `seasonality_components` is rejected at construction
  (`ValueError`) — a lag model already captures local dynamics, and a
  per-seasonality-group multiplier doesn't compose meaningfully with
  autoregressive coefficients. Use a windowed detector (`mad`/`zscore`/`iqr`)
  for a metric whose *level* varies by hour/day-of-week/etc.
- **No smoothing, no recency weighting, no detrending.** The AR residual
  model already adapts to the local level and short-range dynamics on its
  own; these knobs may be reconsidered in a later version.
- **Strict NaN policy.** A gap inside the lag window or at the fit target
  drops that row entirely (`missing_lags` for the scored point itself) —
  never imputed, unlike some AR implementations that interpolate through
  small gaps.

## Advanced: an AR model follows slow drift

A windowed level detector holds a *slow* trend inside its confidence band
(the median/mean shifts with it) unless you turn on `detrend: linear`. An AR
model's own dynamics do something similar for a **gradual** drift: if the
metric moves smoothly step to step, the AR coefficients learn that
persistence and the model predicts the drift forward, so a slow trend
generally does *not* get flagged. This is by design — Autoreg targets
*dynamics breaks* (a jump, a reversal, a dynamics change), not "this metric
has drifted far from where it started". If you also need a hard guarantee on
absolute level (e.g. "alert once revenue drifts more than 20% from its
30-day baseline regardless of how smoothly it got there"), pair Autoreg with
a windowed detector (optionally with `detrend: linear` if the *rate* of drift
itself should not be flagged) rather than relying on Autoreg alone.

## Advanced: per-point refit cost

Like the windowed detectors, Autoreg refits at **every point** in a Python
loop — there is no incremental/online AR update in v1. The per-point cost is
the design-matrix assembly (`O(window_size · lags)`, vectorized with numpy
sliding-window views) plus solving an `(lags + 1) × (lags + 1)` linear
system, which is cheap for typical `lags` (single digits) but means a large
historical backfill costs roughly `O(points × window_size × lags)`. Pick
`window_size`/`lags` with backfill size in mind, exactly as documented for
MAD/Z-Score/IQR.

## Comparison with Other Detectors

| Feature | Autoreg | MAD | Z-Score | IQR |
|---------|---------|-----|---------|-----|
| Models | Short-range dynamics (prediction residual) | Level (median/MAD) | Level (mean/std) | Level (quartiles) |
| Seasonality support | No (v1) | Yes | Yes | Yes |
| Robust to outliers | Via stabilization (default on) | Very | No | Very |
| Detects "right level, wrong dynamics" | Yes | No | No | No |
| `dtk autotune` support | Yes | Yes | Yes | Yes |

## See Also

- [MAD Detector](mad.md) - Robust level-based detection with seasonality
- [Shared Detector Parameters](shared-parameters.md) - `input_type`, stabilization, detector identity
- [Detectors Guide](../../guides/detectors.md) - Choosing the right detector
- [Configuration Guide](../../guides/configuration.md) - Complete config reference

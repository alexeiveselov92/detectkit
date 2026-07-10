# Shared Detector Parameters

MAD, Z-Score and IQR share one windowed implementation, so every parameter
below behaves identically across the three. Manual Bounds supports only
`input_type` (it has no window, so smoothing, weighting and detrending do not
apply). [Autoreg](autoreg.md) is a separate, non-windowed (dynamics) model: it
supports `input_type` and `stabilization` — defaulting to `clamp` there,
unlike the windowed detectors' default of `None` — but not smoothing, recency
weighting, detrending or seasonality; see its own page for the full parameter
set.

This page is the **single reference** for those shared parameters. Detector-specific
parameters (each detector's `threshold` default, `min_samples` minimums,
`min_samples_per_group` defaults, recommended `window_size`) live on the individual
[MAD](mad.md) / [Z-Score](zscore.md) / [IQR](iqr.md) /
[Manual Bounds](manual_bounds.md) / [Autoreg](autoreg.md) pages.

The full shared parameter set:

```yaml
detectors:
  - type: mad                  # same params for zscore and iqr
    params:
      threshold: 3.0           # detector-specific default (mad 3.0, zscore 3.0, iqr 1.5)
      window_size: 100         # trailing window in points (current point excluded)
      min_samples: 30          # min valid points in window before detection starts
      seasonality_components: null   # e.g. ["hour"] or [["hour", "day_of_week"]]
      min_samples_per_group: 10      # mad 10, zscore 3, iqr 4 (iqr floor: 4)
      input_type: values       # values | changes | absolute_changes | log_changes
      smoothing: null          # null | ema | sma
      smoothing_alpha: 0.3     # EMA factor, 0 < alpha <= 1
      smoothing_window: 10     # SMA window in points
      window_weights: null     # null (uniform) | exponential | linear
      half_life: null          # exponential half-life: int points or "3d"/"12h"; default max(window_size/20, min_samples/2)
      weight_decay: null       # DEPRECATED alias for half_life
      detrend: null            # null | linear
      stabilization: null      # null | clamp
```

All parameters are validated when the detector is constructed at the start
of the `detect` step — a typo like `input_type: "diff"` fails fast on the
first run with a clear error instead of being silently ignored. (Validation
happens per run, not when the YAML config is loaded.)

## Input Preprocessing

Transform input values before detection to detect on changes rather than
absolute values.

### Available Transformations

**`input_type: "values"`** (default) — use values as-is.

**`input_type: "absolute_changes"`** — detect on differences between
consecutive points, `v[t] - v[t-1]`:
```yaml
detectors:
  - type: mad
    params:
      input_type: "absolute_changes"
      threshold: 3.0
```

```
Original values:        [100, 102, 105, 150, 152]
After absolute_changes: [NaN, 2,   3,   45,  2]
                                       ↑ Anomaly detected (spike in change)
```

**`input_type: "changes"`** — detect on relative changes,
`(v[t] - v[t-1]) / v[t-1]`:
```yaml
detectors:
  - type: mad
    params:
      input_type: "changes"
      threshold: 3.0
```

```
Original values: [100, 102, 105, 200, 202]
After changes:   [NaN, 0.02, 0.029, 0.90, 0.01]
                                    ↑ Anomaly detected (90% jump)
```

**`input_type: "log_changes"`** — detect on log-scaled changes,
`log(v[t] + 1) - log(v[t-1] + 1)` (a log1p-style difference). Good for
exponential growth: for large values it behaves like a symmetric version of
`changes` (a +100% jump and the −50% drop back have roughly equal
magnitude), though the `+1` shift makes it only approximately symmetric for
percentage moves, especially at small values. Tolerates zeros — values just
need to be greater than −1.

### When to Use Each Type

**Use `"values"`** (default):
- Absolute values matter (CPU %, memory usage, latency)
- Thresholds are meaningful (>500ms is bad regardless of trend)
- Baseline is stable

**Use `"absolute_changes"`**:
- Changes matter more than absolute values
- Sudden jumps/drops are anomalies
- Examples: error counts increasing rapidly, queue depth changes

**Use `"changes"` or `"log_changes"`**:
- Relative changes matter (revenue, traffic, conversions)
- Different baselines (10 vs 10,000 — both can have a 50% spike)
- Growth rates, ratios, percentages

The first point has no previous value, so change transformations mark it as
NaN; the detection context automatically includes one extra point to
compensate.

## Value Smoothing

Reduce noise with a moving average before detection. Smoothing is applied
first, then the `input_type` transformation.

**Simple moving average (SMA):**
```yaml
detectors:
  - type: mad
    params:
      smoothing: "sma"
      smoothing_window: 5   # 5-point moving average
      threshold: 3.0
```

**Exponential moving average (EMA):**
```yaml
detectors:
  - type: mad
    params:
      smoothing: "ema"
      smoothing_alpha: 0.3  # higher = less smoothing
      threshold: 3.0
```

**When to use:**
- Noisy metrics with high-frequency fluctuations
- Single-point spikes that aren't real issues
- Reduce false positives from measurement errors

**Typical SMA values:**
- `smoothing_window: 3` — light smoothing
- `smoothing_window: 5` — standard smoothing
- `smoothing_window: 7-10` — heavy smoothing

**Trade-off**: reduces noise but also reduces sensitivity to short-lived
anomalies.

## Window Weighting

By default every point in the window contributes equally. With
`window_weights` recent points contribute more, so the confidence interval
adapts faster to a shifting baseline.

```yaml
detectors:
  - type: mad
    params:
      window_size: 8640
      window_weights: exponential
      half_life: "3d"     # weight halves every 3 days of data
```

**Methods:**
- `window_weights: exponential` — `w(age) = 0.5^(age / half_life)`.
  `half_life` is the age at which a point's weight halves: an integer means
  points, a duration string (`"3d"`, `"12h"`) is converted using the metric's
  data grid step. Default when unset: `max(window_size / 20, min_samples / 2)`
  — the `window/20` adaptation horizon (≈ `"3d"` on the large trending windows
  it is tuned for), floored at `min_samples / 2` so on small/default windows
  the effective weighted sample size never drops below the raw `min_samples`
  gate.
- `window_weights: linear` — weight decreases linearly with age:
  `w(age) = (window_size + 1 - age) / window_size`.

**Weights are time-aware**: a point's weight depends on its age on the time
grid (age 1 = the previous point), not on its position among valid points.
Data gaps therefore don't compress the decay, and seasonality groups share
the same recency horizon as the global statistics.

`min_samples` always counts raw valid points, regardless of weighting.

**Deprecated**: `weight_decay` (a per-point multiplier in (0, 1)) is a legacy
alias for `half_life` — decay `d` is equivalent to
`half_life = ln(0.5)/ln(d)` points (e.g. 0.95 ≈ 13.5 points). It is mutually
exclusive with `half_life`; prefer `half_life`.

## Detrending

`detrend: linear` estimates a robust linear trend over the window
(split-median slope, outlier-resistant) and projects every window point to the
current point along that trend before computing statistics. A gradual drift
therefore no longer pulls the metric out of its own confidence interval,
while sharp deviations from the trend are still caught.

```yaml
detectors:
  - type: mad
    params:
      window_size: 8640
      detrend: linear
```

## Stabilization

`stabilization: clamp` prevents a sustained incident from poisoning its own
baseline. Without it, once an incident starts, its anomalous points enter the
trailing window like any other point — inflating the spread and dragging the
center toward the incident — so the confidence interval widens and the
detector stops flagging the incident's own tail (it becomes "the new
normal"). With `stabilization: clamp`, once a point is flagged anomalous,
subsequent windows see it **clamped** to the confidence bound it violated (a
winsorized value) instead of its observed value. Only the statistics windows
read the substituted history — the scored/persisted value and the anomaly
flag are unchanged. Seasonality-group statistics read the same substituted
history.

```yaml
detectors:
  - type: mad
    params:
      window_size: 100
      stabilization: clamp
```

**Why clamp, not substitute the band center**: replacing an anomalous point
with the center feeds a zero-deviation point back into the spread statistics,
which collapses the band after a long incident and cascades into false
flags once the incident ends (measured: 34-44 false flags after the incident
for MAD/IQR with center-substitution, vs 0 with clamping). Clamping bounds an
anomaly's influence at exactly the threshold without destroying the spread
estimate.

**When to use it**: metrics with occasional sustained incidents (an
elevated error rate that persists for tens of points, a stuck-high latency
plateau). Z-Score (mean/std) benefits the most — on a synthetic 30-point
incident inside a 100-point window it flags only ~10/30 points without
stabilization and 30/30 with it. MAD/IQR are median/quartile-based and
already resist short incidents, but a long incident still bends them (IQR:
25/30 → 30/30 with clamping). It composes with `detrend`, `window_weights` /
`half_life`, `smoothing`, `input_type` and seasonality groups — it matters
most alongside recency weighting, since that weighting gives an ongoing
incident's points *more* influence on the window. On a clean series with no
sustained incidents, the effect is near-neutral.

Enabling it adds one extra `window_size` of warm-up history to
`get_context_size()`, so incremental batches reproduce the same substitution
history a continuous run would have seen. The [`dtk tune`](../../guides/tuning.md)
cockpit's visible band start honors this extra warm-up too (for both the
windowed detectors and Autoreg), so with `clamp` enabled the band starts one
window later than it would without it.

## Handling Metrics with Trends

A metric with a gradual trend (e.g. slowly declining sessions) drifts out of
a uniform-window confidence interval — the window median lags behind the
current level, and every point starts to look "below the interval". The
result is alert spam on perfectly expected behavior.

Two shared parameters address this directly: `window_weights` (the interval
follows the recent level) and `detrend` (the in-window trend is removed
before statistics).

**Recommended recipe for trending metrics:**

```yaml
seasonality_columns:
  - hour                       # built-in hour-of-day feature

detectors:
  - type: mad
    params:
      window_size: 8640        # 60 days of 10-min points
      min_samples: 1000
      seasonality_components: ["hour"]
      window_weights: exponential
      half_life: "3d"          # adapt to the new normal over ~3 days
      detrend: linear          # optional: also remove in-window trend
```

**Measured effect** (simulation: 60-day window, 10-min interval, daily
seasonality, −15% gradual decline over 30 days, hour-of-day grouping,
threshold 3; false "below" alerts out of 4320 points):

| Configuration | False alerts |
|---------------|--------------|
| Uniform window (unscaled MAD) | 1557 |
| Uniform window (scaled MAD) | 238 |
| `window_weights: exponential` + `half_life: "3d"` | 26 (≈ noise floor) |
| `detrend: linear` | 54 |
| Both combined | 19 |

A sharp −40% incident was caught on 18/18 anomalous points in **all**
configurations — recency weighting and detrending suppress trend-induced
false positives without losing real incidents.

**Trade-off**: a shorter `half_life` adapts faster but also "accepts" a real
sustained degradation as the new normal sooner — alerts still fire during
roughly the first `half_life` of an incident. Avoid very short half-lives
(the legacy `weight_decay: 0.95` default ≈ 13.5 points, ~2 hours at 10-min
intervals, chased real incidents within hours while barely helping the
trend — that's why it was redesigned).

## Combining Features

All features can be combined:

```yaml
name: api_error_rate_changes
description: API error rate with change detection and smoothing
interval: "5min"

query: |
  SELECT
    timestamp,
    error_count / total_requests * 100 AS value
  FROM api_metrics
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  ORDER BY timestamp

detectors:
  - type: mad
    params:
      # Detect on relative changes (not absolute error rate)
      input_type: "changes"

      # Smooth out noise from low-traffic periods
      smoothing: "sma"
      smoothing_window: 3

      # Weight recent data more (baseline shifts over time)
      window_weights: exponential
      half_life: "12h"

      # Standard MAD parameters
      threshold: 3.5
      window_size: 288  # 24 hours

alerting:
  enabled: true
  channels:
    - slack_oncall
  consecutive_anomalies: 2
  alert_cooldown: "15min"
  cooldown_reset_on_recovery: true
```

**This configuration:**
1. Converts error rate to relative changes (10% → 15% is a 50% increase)
2. Applies 3-point smoothing to reduce noise
3. Halves a point's weight every 12 hours (adapts to new baselines faster)
4. Uses MAD detector with 3.5 threshold
5. Alerts only after 2 consecutive anomalies
6. Prevents spam with 15-minute cooldown

## Feature Compatibility

| Feature | MAD | Z-Score | IQR | Manual Bounds | Autoreg |
|---------|-----|---------|-----|---------------|---------|
| `input_type` | Yes | Yes | Yes | Yes | Yes |
| `smoothing` / `smoothing_alpha` / `smoothing_window` | Yes | Yes | Yes | No (N/A) | No (v1) |
| `window_weights` / `half_life` | Yes | Yes | Yes | No (N/A) | No (v1) |
| `detrend` | Yes | Yes | Yes | No (N/A) | No (v1) |
| `stabilization` | Yes | Yes | Yes | No (N/A) | Yes (default `clamp`, unlike the windowed detectors) |
| `seasonality_components` | Yes | Yes | Yes | No (N/A) | No — rejected at construction (v1) |

**Note**: Manual Bounds uses fixed thresholds with no historical window, so
window-based features don't apply. Autoreg fits its own lag-based (AR) model
instead of a windowed level statistic, so the windowed-only features are
unsupported in v1 rather than N/A — see
[Autoreg → V1 Limitations](autoreg.md#v1-limitations) for why.

## Execution Parameters

Execution parameters control how detection runs; they don't affect results
and are **not** part of the detector ID hash.

### `start_time` (string, optional)
Start detecting anomalies from this timestamp. Data before is used only for building history.

If omitted, detection starts from the metric's `loading_start_time` (and, failing
that, its earliest stored datapoint) — so the **first run detects across all
loaded history**. Set `start_time` only when you want detection to begin later
than the loaded data.

**Format**: `"YYYY-MM-DD HH:MM:SS"`

**Example:**
```yaml
detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 8640
      start_time: "2024-03-01 00:00:00"  # Start detection after 2 months
```

### `batch_size` (int, optional)
Number of points to process per batch. Useful for large datasets.

**Example:**
```yaml
detectors:
  - type: mad
    params:
      batch_size: 2160  # Process 15 days at a time (10-min intervals)
```

## Detector Identity and Recomputation

Every parameter that affects detection results (threshold, window_size,
min_samples, seasonality_components, min_samples_per_group, input_type,
smoothing settings, window_weights, half_life/weight_decay, detrend,
stabilization) is
hashed into the `detector_id` — only non-default values participate.

Changing any of these parameters produces a new `detector_id`, and detections
for that detector are recomputed from scratch on the next run. Old rows
remain in `_dtk_detections` under the previous id; use
`dtk run --full-refresh` to purge them.

Execution parameters (`start_time`, `batch_size`) don't affect results and
are not hashed.

## Debugging Preprocessed Detections

Detection metadata records what the detector "saw":

```python
{
  "preprocessing": {            # present when smoothing or non-default input_type is used
    "input_type": "changes",
    "smoothing": "sma",
    "smoothed_value": 2.4       # only when smoothing is enabled
  },
  "global_median": 2.5,         # statistics on preprocessed values
  "adjusted_median": 2.3,       # after seasonality multipliers
  "ess": 41.2,                  # effective sample size (Kish) — when weighting is on
  "trend_slope_per_point": -0.0021,  # when detrend is on
  ...
}
```

- `ess` — the Kish effective sample size of the weighted window. With heavy
  weighting it can be much smaller than the raw point count; if it gets very
  low, the statistics are dominated by a handful of recent points.
- `trend_slope_per_point` — the estimated robust trend slope per grid point
  used by `detrend: linear`.

## See also

- [Detectors guide](../../guides/detectors.md) — choosing a detector and tuning recipes.
- [MAD](mad.md) / [Z-Score](zscore.md) / [IQR](iqr.md) / [Manual Bounds](manual_bounds.md) / [Autoreg](autoreg.md) — detector-specific parameters and metadata.
- [Internal Tables](../internal-tables.md) — where `detection_metadata` is stored.

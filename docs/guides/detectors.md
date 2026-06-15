# Detectors Guide

This guide helps you choose and configure the right detector for your metrics.

## Overview

detectkit provides several detector types for anomaly detection:

| Detector | Best For | Robustness | Seasonality | Speed |
|----------|----------|------------|-------------|-------|
| [MAD](../reference/detectors/mad.md) | General-purpose, seasonal data | ✅ High | ✅ Yes | Fast |
| [Z-Score](../reference/detectors/zscore.md) | Normal distributions, clean data | ❌ Low | ✅ Yes | Very Fast |
| [IQR](../reference/detectors/iqr.md) | Skewed distributions, outliers | ✅ High | ✅ Yes | Fast |
| [Manual Bounds](../reference/detectors/manual_bounds.md) | Known thresholds, SLAs | N/A | ❌ No | Fastest |

## Decision Tree

### 1. Do you know the acceptable bounds?

**YES** → Use [Manual Bounds](#manual-bounds-detector)

Examples:
- CPU usage should be ≤ 90%
- Response time SLA < 1000ms
- Error rate should be 0

**NO** → Continue to question 2

### 2. Does your metric have seasonal patterns?

**YES** → Use [MAD with Seasonality](#mad-detector-with-seasonality)

Examples:
- Website traffic (hourly/daily patterns)
- Sales (day-of-week patterns)
- Gaming metrics (event-based patterns)

**NO** → Continue to question 3

### 3. Is your data normally distributed?

**Test**: Create a histogram. Does it look like a bell curve?

**YES** → Use [Z-Score](#z-score-detector)

**NO** → Continue to question 4

### 4. Does your data have outliers or heavy tails?

**YES** → Use [MAD](#mad-detector-basic) or [IQR](#iqr-detector)

**UNSURE** → Use [MAD](#mad-detector-basic) (safe default)

## Detector Details

### MAD Detector (Basic)

**Use when**:
- General-purpose anomaly detection
- Data with outliers
- Skewed or non-normal distributions
- Good default choice

**Advantages**:
- Robust to outliers
- No distribution assumptions
- Fast computation
- Excellent seasonality support

**Configuration**:
```yaml
detectors:
  - type: mad
    params:
      threshold: 3.0        # In sigma-equivalents (MAD scaled by 1.4826)
      window_size: 100      # Historical window size
      min_samples: 30       # Warm-up period
```

**Threshold is in σ-equivalents**: MAD is multiplied by the normal-consistency
constant 1.4826, so `threshold: 3.0` corresponds to 3-sigma on Gaussian noise
(~0.27% false positives), exactly like Z-Score.

**Tuning threshold**:
- `threshold: 2.0` - More sensitive (more anomalies)
- `threshold: 3.0` - Balanced (recommended)
- `threshold: 5.0` - Less sensitive (fewer anomalies)

[Full MAD Reference →](../reference/detectors/mad.md)

### MAD Detector (with Seasonality)

**Use when**:
- Metric has time-based patterns
- Different behavior at different times (hour/day/week)
- Need adaptive confidence intervals

**Examples**:
- Website traffic (higher during business hours)
- API calls (spikes during events)
- Gaming metrics (tournament schedules)

**Configuration**:
```yaml
# Extract seasonality features from timestamps (built-in names:
# hour, day_of_week, day_of_month, month, is_weekend, is_holiday)
seasonality_columns:
  - hour
  - day_of_week

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 2016      # 2 weeks of hourly data
      min_samples: 500

      # Apply seasonality grouping
      seasonality_components:
        - "hour"             # Different intervals per hour
        # OR combine multiple:
        # - ["hour", "day_of_week"]  # Different per hour+day combo
```

**Seasonality components**:
- **Single**: `["hour"]` - One group per hour (24 groups)
- **Multiple separate**: `["hour", "day_of_week"]` - Two separate adjustments
- **Combined**: `[["hour", "day_of_week"]]` - One group per hour+day combo (168 groups)

Component names must match the metric's seasonality feature names: the
built-in `seasonality_columns` names shown above, or custom column names
(e.g. `hour_of_day`) — the latter only when your query returns them and
they are declared in `query_columns.seasonality`.

**Window size recommendations**:
- Hourly data: 672-2016 (1-3 weeks)
- 10-minute data: 4320-8640 (30-60 days)
- Daily data: 60-90 (2-3 months)

Rule: `window_size` should contain multiple full cycles of your seasonality.

[Full MAD Reference →](../reference/detectors/mad.md)

### Z-Score Detector

**Use when**:
- Data is normally distributed (bell curve)
- No significant outliers in historical data
- Need high sensitivity on clean data

**Advantages**:
- Very fast computation
- High sensitivity on normal data
- Well-understood (3-sigma rule)

**Disadvantages**:
- Sensitive to outliers (can produce false positives)
- Assumes normal distribution

**Configuration**:
```yaml
detectors:
  - type: zscore
    params:
      threshold: 3.0        # 3 standard deviations
      window_size: 100
      min_samples: 30
```

**Threshold interpretation**:
- `threshold: 1.0` → 68.3% confidence (very sensitive)
- `threshold: 2.0` → 95.4% confidence (sensitive)
- `threshold: 3.0` → 99.7% confidence (balanced)
- `threshold: 4.0` → 99.99% confidence (conservative)

**When to avoid**:
- Skewed distributions (use MAD or IQR)
- Data with outliers (use MAD or IQR)

[Full Z-Score Reference →](../reference/detectors/zscore.md)

### IQR Detector

**Use when**:
- Data is heavily skewed
- Percentile-based metrics (P95, P99)
- Need quartile-based detection
- Want box plot visualization

**Advantages**:
- Robust to outliers
- Works with any distribution
- Natural for percentile metrics
- Creates asymmetric bounds (good for skewed data)

**Disadvantages**:
- Less sensitive than MAD
- Slightly slower than Z-Score

**Configuration**:
```yaml
detectors:
  - type: iqr
    params:
      threshold: 1.5        # Tukey's fences (standard)
      window_size: 100
      min_samples: 30
```

**Threshold values**:
- `threshold: 1.0` - More sensitive
- `threshold: 1.5` - Standard outliers (Tukey's fences)
- `threshold: 3.0` - Extreme outliers only

**Comparison with MAD**:
- IQR uses Q1/Q3 (25%/75% percentiles)
- MAD uses median (50% percentile)
- Both are robust, MAD slightly more sensitive

[Full IQR Reference →](../reference/detectors/iqr.md)

### Manual Bounds Detector

**Use when**:
- You know acceptable thresholds
- SLA/compliance monitoring
- Physical/logical constraints
- Binary "too high/low" alerts

**Advantages**:
- Instant detection (no warm-up)
- Simple and transparent
- Predictable behavior
- Fastest detector

**Disadvantages**:
- Requires domain knowledge
- No adaptation to data patterns
- Can't handle seasonality

**Configuration**:
```yaml
# Upper bound only
detectors:
  - type: manual_bounds
    params:
      upper_bound: 90.0    # Alert when value > 90

# Lower bound only
detectors:
  - type: manual_bounds
    params:
      lower_bound: 0.8     # Alert when value < 0.8

# Both bounds (range check)
detectors:
  - type: manual_bounds
    params:
      lower_bound: 0.0
      upper_bound: 100.0
```

**Use cases**:
- SLA monitoring (response time < 1000ms)
- Resource limits (memory < 8GB)
- Error rates (errors should be 0)
- Percentages (0-100% range)

[Full Manual Bounds Reference →](../reference/detectors/manual_bounds.md)

## Multiple Detectors

You can configure multiple detectors per metric. Use cases:

### Hard Limit + Statistical Detection

```yaml
detectors:
  # Hard limit: never exceed 95%
  - type: manual_bounds
    params:
      upper_bound: 95.0

  # Soft limit: detect unusual patterns
  - type: mad
    params:
      threshold: 3.0
      window_size: 1440
```

### Conservative + Aggressive Detection

```yaml
detectors:
  # Conservative: fewer false positives
  - type: mad
    params:
      threshold: 5.0
      window_size: 2880

  # Aggressive: catch subtle anomalies
  - type: zscore
    params:
      threshold: 2.5
      window_size: 1440
```

### Alert Filtering

Control when alerts trigger with multiple detectors:

```yaml
detectors:
  - type: mad
    params:
      threshold: 3.0
  - type: zscore
    params:
      threshold: 3.0

alerting:
  enabled: true
  min_detectors: 2   # Both must agree to trigger alert
  direction: "same"  # Both must agree on ONE direction (up or down)
```

With `direction: "same"`, at least `min_detectors` detectors must agree on a
single direction at the latest point — one detector firing "up" and another
firing "down" is disagreement, not consensus. Other policies: `"up"` / `"down"`
(only that direction counts) and `"any"` (every anomaly counts regardless of
direction). See the [Alerting Guide](alerting.md) for the full contract.

## Common Patterns

### Pattern 1: High-Traffic Website

```yaml
name: website_visitors
interval: 10min

seasonality_columns:
  - hour
  - day_of_week

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 4320    # 30 days
      min_samples: 1000
      seasonality_components:
        - ["hour", "day_of_week"]
```

**Why**: Traffic varies by hour and day of week. Seasonality ensures different thresholds for peak vs off-peak times.

### Pattern 2: System Metrics (CPU/Memory)

```yaml
name: cpu_usage
interval: 30s

detectors:
  # Hard limit
  - type: manual_bounds
    params:
      upper_bound: 90.0

  # Statistical
  - type: zscore
    params:
      threshold: 3.0
      window_size: 2880  # 1 day
```

**Why**: System metrics are often normally distributed. Combine hard limit with statistical detection.

### Pattern 3: Error Rates

```yaml
name: api_errors
interval: 1min

detectors:
  # Zero tolerance
  - type: manual_bounds
    params:
      upper_bound: 0

  # Allow small spikes but catch sustained increases
  - type: mad
    params:
      threshold: 3.0
      window_size: 1440
```

**Why**: Errors should be rare. Manual bounds catches any error, MAD catches unusual patterns.

### Pattern 4: Business Metrics (Revenue, Conversions)

```yaml
name: daily_revenue
interval: 1day

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 90     # 3 months
      min_samples: 30
```

**Why**: Business metrics often have trends and outliers. MAD is robust to both.

### Pattern 5: Latency Percentiles

```yaml
name: api_p99_latency
interval: 1min

detectors:
  # SLA limit
  - type: manual_bounds
    params:
      upper_bound: 1000  # 1 second max

  # Detect degradation
  - type: iqr
    params:
      threshold: 1.5
      window_size: 1440
```

**Why**: Percentile metrics are skewed. IQR handles skewness better than Z-Score.

## Tuning Tips

> **After retuning a live metric:** a detector's identity is a hash of its
> parameters, so detections written under the old parameters stay in
> `_dtk_detections` as orphaned rows once you change a param (or remove the
> detector). Run [`dtk clean --select <metric>`](../reference/cli.md#dtk-clean)
> to prune them (preview first, then `--execute`). To *recompute* detections
> for the new parameters over history instead, use
> `dtk run --select <metric> --steps detect --full-refresh`.

### Window Size

**Too small** (< 50 points):
- ❌ Unstable confidence intervals
- ❌ Sensitive to recent outliers
- ✅ Responsive to changes

**Too large** (> window with 10+ cycles):
- ❌ Slow to adapt to changes
- ✅ Very stable intervals

**Recommended**:
- Non-seasonal: 100-500 points
- Seasonal: 2-4 complete cycles

### Threshold

**Start with defaults**:
- MAD: 3.0
- Z-Score: 3.0
- IQR: 1.5

**Tune based on results**:
- Too many false positives → Increase threshold
- Missing real anomalies → Decrease threshold

### Min Samples

**Too small** (< 30):
- ❌ Unreliable statistics
- ✅ Faster detection startup

**Too large** (> 50% of window_size):
- ❌ Long warm-up period
- ✅ Very reliable statistics

**Recommended**: 10-30% of `window_size`

## Performance Comparison

Approximate speeds (including I/O):

| Detector | Points/Second | Notes |
|----------|---------------|-------|
| Manual Bounds | ~3,000 | Fastest (simple comparison) |
| Z-Score | ~1,800 | Fast (mean/std) |
| MAD (no seasonality) | ~1,500 | Fast (median/MAD) |
| MAD (with seasonality) | ~1,450 | Minimal seasonality penalty |
| IQR | ~1,400 | Percentile calculation |

All detectors are fast enough for production use. Choose based on accuracy needs, not performance.

## Troubleshooting

### All points marked as "insufficient_data"

**Cause**: Not enough historical data before `min_samples` threshold.

**Solution**:
1. Lower `min_samples` parameter
2. Increase `loading_start_time` to load more history
3. Wait for more data to accumulate

### Too many false positives

**Causes**:
- Threshold too low
- No seasonality on seasonal data
- Wrong detector for data distribution

**Solutions**:
- Increase `threshold` parameter
- Add `seasonality_components` (works with MAD, Z-Score and IQR)
- For trending metrics: add `window_weights: exponential` and/or `detrend: linear`
  (see [Handling Metrics with Trends](#handling-metrics-with-trends))
- Try different detector (e.g., MAD instead of Z-Score)
- Increase `consecutive_anomalies` in alerting config

### Missing real anomalies

**Causes**:
- Threshold too high
- Window too large (includes outliers)
- Wrong detector

**Solutions**:
- Decrease `threshold` parameter
- Decrease `window_size`
- Try more sensitive detector (Z-Score instead of MAD)

### Confidence intervals don't vary with seasonality

**Cause**: Seasonality not configured correctly.

**Checklist**:
1. ✅ Seasonality features exist — either built-in `seasonality_columns`
   (allowed names: `hour`, `day_of_week`, `day_of_month`, `month`,
   `is_weekend`, `is_holiday`) or custom columns returned by the query and
   declared in `query_columns.seasonality`
2. ✅ `seasonality_components` uses exactly those feature names
3. ✅ Enough data per group (`min_samples_per_group`)

**Example (built-in extraction)**:
```yaml
# Extract features from timestamps
seasonality_columns:
  - hour             # Feature is named "hour" — must match below

# Use in detector
detectors:
  - type: mad
    params:
      seasonality_components:
        - "hour"     # Must match above
```

Custom feature names (e.g. `hour_of_day`) only work when your query returns
such a column and it is declared in `query_columns.seasonality` — they are
not valid in the built-in `seasonality_columns` list.

## Advanced Detector Features

MAD, Z-Score and IQR share one windowed implementation, so every parameter
below behaves identically across the three. Manual Bounds supports only
`input_type` (it has no window, so smoothing, weighting and detrending do not
apply).

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
      half_life: null          # exponential half-life: int points or "3d"/"12h"; default window_size/20
      weight_decay: null       # DEPRECATED alias for half_life
      detrend: null            # null | linear
```

All parameters are validated when the detector is constructed at the start
of the `detect` step — a typo like `input_type: "diff"` fails fast on the
first run with a clear error instead of being silently ignored. (Validation
happens per run, not when the YAML config is loaded.)

### Input Preprocessing

Transform input values before detection to detect on changes rather than
absolute values.

#### Available Transformations

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

#### When to Use Each Type

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

### Value Smoothing

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

### Window Weighting

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
  data grid step. Default when unset: `window_size / 20`.
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

### Detrending

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

### Handling Metrics with Trends

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
| Uniform window (pre-0.7.0 unscaled MAD) | 1557 |
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

### Combining Features

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
    - pagerduty_oncall
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

### Feature Compatibility

| Feature | MAD | Z-Score | IQR | Manual Bounds |
|---------|-----|---------|-----|---------------|
| `input_type` | ✅ | ✅ | ✅ | ✅ |
| `smoothing` / `smoothing_alpha` / `smoothing_window` | ✅ | ✅ | ✅ | ❌ (N/A) |
| `window_weights` / `half_life` | ✅ | ✅ | ✅ | ❌ (N/A) |
| `detrend` | ✅ | ✅ | ✅ | ❌ (N/A) |
| `seasonality_components` | ✅ | ✅ | ✅ | ❌ (N/A) |

**Note**: Manual Bounds uses fixed thresholds with no historical window, so
window-based features don't apply.

### Detector Identity and Recomputation

Every parameter that affects detection results (threshold, window_size,
min_samples, seasonality_components, min_samples_per_group, input_type,
smoothing settings, window_weights, half_life/weight_decay, detrend) is
hashed into the `detector_id` — only non-default values participate.

Changing any of these parameters produces a new `detector_id`, and detections
for that detector are recomputed from scratch on the next run. Old rows
remain in `_dtk_detections` under the previous id; use
`dtk run --full-refresh` to purge them.

Execution parameters (`start_time`, `batch_size`) don't affect results and
are not hashed.

### Debugging Preprocessed Detections

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

## See Also

- [MAD Detector Reference](../reference/detectors/mad.md)
- [Z-Score Detector Reference](../reference/detectors/zscore.md)
- [IQR Detector Reference](../reference/detectors/iqr.md)
- [Manual Bounds Detector Reference](../reference/detectors/manual_bounds.md)
- [Configuration Guide](configuration.md)
- [Alerting Guide](alerting.md)

# Detectors

This guide helps you choose and configure the right detector for your metrics.

## Overview

detectkit provides several detector types for anomaly detection:

| Detector | Best For | Robustness | Seasonality | Speed |
|----------|----------|------------|-------------|-------|
| [MAD](../reference/detectors/mad.md) | General-purpose, seasonal data | High | Yes | Fast |
| [Z-Score](../reference/detectors/zscore.md) | Normal distributions, clean data | Low | Yes | Very Fast |
| [IQR](../reference/detectors/iqr.md) | Skewed distributions, outliers | High | Yes | Fast |
| [Manual Bounds](../reference/detectors/manual_bounds.md) | Known thresholds, SLAs | N/A | No | Fastest |
| [Autoreg](../reference/detectors/autoreg.md) | Fast-moving, non-seasonal metrics; dynamics breaks | Via stabilization | No (v1) | Fast |

> **Don't want to choose by hand?** `dtk autotune` can pick the detector type,
> hyperparameters and seasonality grouping for you from the metric's data (and
> labeled incidents, if you have them), then write a ready-to-run, annotated
> config. See [Auto-tuning a Detector](autotuning.md).

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

### 3. Do anomalies look like broken *dynamics* rather than an unusual *level*?

Some metrics move fast and have no stable "normal level", so a value can sit
well inside the usual range yet still be wrong given the last few points — a
sudden jump, a reversal, a step a level detector would wave through.

Examples:
- Queue depth / backlog
- Request rate, in-flight count
- Any fast-moving, non-seasonal series where *shape* matters more than *level*

**YES** → Use [Autoreg](#autoreg-detector). It predicts each point from a short
autoregressive fit on recent history and flags large residuals, catching shape
breaks the level-based detectors miss. Pair it with a level detector
(`mad`/`zscore`/`iqr`) via `min_detectors` for both level *and* shape coverage.

**NO** → Continue to question 4

### 4. Is your data normally distributed?

**Test**: Create a histogram. Does it look like a bell curve?

**YES** → Use [Z-Score](#z-score-detector)

**NO** → Continue to question 5

### 5. Does your data have outliers or heavy tails?

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

> `seasonality_columns:` is a top-level metric key (a sibling of `detectors:`),
> not a detector param. It extracts the features; `seasonality_components`
> inside a detector's `params:` then groups on them.

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

### Autoreg Detector

MAD/Z-Score/IQR ask "is this value far from the recent center?"; Autoreg asks
"is this value far from what the last few points would have predicted?" — it
fits a short autoregressive model on recent history instead of a level
statistic, so it can catch a value that sits well inside the metric's normal
range but breaks its usual short-range dynamics (a sudden jump, a reversal).

**Use when**:
- Fast-moving, non-seasonal metrics (queue depth, request rate, in-flight count)
- You want to catch "unusual dynamics", not just "unusual level"
- Pairing with a level detector (`mad`/`zscore`/`iqr`) via `min_detectors` for
  full coverage

**Disadvantages**:
- No seasonality support in v1 (rejected at construction)
- No smoothing, recency weighting or detrending

`dtk autotune` sweeps threshold, lags, stabilization and window size for
Autoreg (its own axis set — no weighting/detrend/seasonality), and it's
tunable in the `dtk tune` cockpit too.

**Configuration**:
```yaml
detectors:
  - type: autoreg
    params:
      lags: 3            # AR order (predictors = last 3 values)
      window_size: 300   # trailing history used to refit at each point
      threshold: 3.5      # residual-sigma band half-width
```

[Full Autoreg Reference →](../reference/detectors/autoreg.md)

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
- Con: Unstable confidence intervals
- Con: Sensitive to recent outliers
- Pro: Responsive to changes

**Too large** (> window with 10+ cycles):
- Con: Slow to adapt to changes
- Pro: Very stable intervals

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
- Con: Unreliable statistics
- Pro: Faster detection startup

**Too large** (> 50% of window_size):
- Con: Long warm-up period
- Pro: Very reliable statistics

**Recommended**: 10-30% of `window_size`

**Per-detector floors** (a value below the floor raises `ValueError`):
- Z-Score: `min_samples` >= 2
- IQR: `min_samples` >= 4, `min_samples_per_group` >= 4 (quartiles need 4 points)

## Performance Comparison

Approximate speeds (including I/O):

| Detector | Points/Second | Notes |
|----------|---------------|-------|
| Manual Bounds | ~3,000 | Fastest (simple comparison) |
| Z-Score | ~1,800 | Fast (mean/std) |
| MAD (no seasonality) | ~1,500 | Fast (median/MAD) |
| MAD (with seasonality) | ~1,450 | Minimal seasonality penalty |
| IQR | ~1,400 | Percentile calculation |

These rates describe incremental runs — the normal path, where each run scores
only the handful of new points and stays cheap. Detection runs a per-point loop,
so a large historical backfill costs roughly O(points × window_size) and can be
slow (recomputing every point against a long window). Pick a detector for
accuracy; size backfills with the per-point loop in mind, not the steady-state
rate.

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
1. Seasonality features exist — either built-in `seasonality_columns`
   (allowed names: `hour`, `day_of_week`, `day_of_month`, `month`,
   `is_weekend`, `is_holiday`) or custom columns returned by the query and
   declared in `query_columns.seasonality`
2. `seasonality_components` uses exactly those feature names
3. **The window is large enough to fill a group.** A group's statistics only
   engage once the trailing window holds at least `min_samples_per_group` points
   sharing the current point's seasonal key — and same-key points recur only once
   per *cardinality* of the key. So the window must span roughly:

   ```
   window_size ≳ min_samples_per_group × (number of distinct keys)
   ```

   For hourly data grouped by `hour` (24 keys) with the MAD default
   `min_samples_per_group = 10`, that means `window_size ≳ 240`. With the **default
   `window_size = 100`** only ~4 same-hour points land in the window (`< 10`), so
   **every point falls back to the global band and the seasonality has no effect**
   — which looks exactly like "the interval doesn't vary with seasonality". A
   conjunctive group like `[["hour", "day_of_week"]]` has up to 24 × 7 = 168 keys
   and needs `window_size ≳ 1680`. The detector logs a one-time warning when the
   window is too small to ever fill a group; raise `window_size`, lower
   `min_samples_per_group`, or use a coarser grouping.

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
apply). Autoreg — a separate, non-windowed dynamics model — supports
`input_type` and `stabilization` (defaulting to `clamp` there) but not
smoothing, recency weighting, detrending or seasonality; see its own
[reference page](../reference/detectors/autoreg.md) for the full parameter set.

The full reference for these shared parameters lives on one page —
**[Shared Detector Parameters](../reference/detectors/shared-parameters.md)** —
which documents each with defaults, examples and tuning recipes:

- [Input preprocessing](../reference/detectors/shared-parameters.md#input-preprocessing) — `values` / `changes` / `absolute_changes` / `log_changes`
- [Value smoothing](../reference/detectors/shared-parameters.md#value-smoothing) — EMA / SMA
- [Window weighting](../reference/detectors/shared-parameters.md#window-weighting) — `window_weights` / `half_life` recency weighting
- [Detrending](../reference/detectors/shared-parameters.md#detrending) — robust in-window trend removal
- [Stabilization](../reference/detectors/shared-parameters.md#stabilization) — `stabilization: clamp` keeps a sustained incident from poisoning its own baseline
- [Handling metrics with trends](../reference/detectors/shared-parameters.md#handling-metrics-with-trends) — the recommended recipe + its measured effect
- [Detector identity & recomputation](../reference/detectors/shared-parameters.md#detector-identity-and-recomputation)
- [Debugging preprocessed detections](../reference/detectors/shared-parameters.md#debugging-preprocessed-detections) — reading `detection_metadata`

## See Also

- [MAD Detector Reference](../reference/detectors/mad.md)
- [Z-Score Detector Reference](../reference/detectors/zscore.md)
- [IQR Detector Reference](../reference/detectors/iqr.md)
- [Manual Bounds Detector Reference](../reference/detectors/manual_bounds.md)
- [Autoreg Detector Reference](../reference/detectors/autoreg.md)
- [Configuration Guide](configuration.md)
- [Alerting Guide](alerting.md)

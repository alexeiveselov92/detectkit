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
      threshold: 3.0        # 3 MAD units (similar to 3-sigma)
      window_size: 100      # Historical window size
      min_samples: 30       # Warm-up period
```

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
# Extract seasonality features
seasonality_columns:
  - name: hour_of_day
    extract: hour
  - name: day_of_week
    extract: dow

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 2016      # 2 weeks of hourly data
      min_samples: 500

      # Apply seasonality grouping
      seasonality_components:
        - "hour_of_day"      # Different intervals per hour
        # OR combine multiple:
        # - ["hour_of_day", "day_of_week"]  # Different per hour+day combo
```

**Seasonality components**:
- **Single**: `["hour_of_day"]` - One group per hour (24 groups)
- **Multiple separate**: `["hour", "dow"]` - Two separate adjustments
- **Combined**: `[["hour", "dow"]]` - One group per hour+day combo (168 groups)

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
- No seasonality support yet

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
- Seasonal patterns (use MAD with seasonality)

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
- No seasonality support yet
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
  min_detectors: 2  # Both must agree to trigger alert
  direction: "same"  # Both must agree on direction (above/below)
```

## Common Patterns

### Pattern 1: High-Traffic Website

```yaml
name: website_visitors
interval: 10min

seasonality_columns:
  - name: hour
    extract: hour
  - name: dow
    extract: dow

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 4320    # 30 days
      min_samples: 1000
      seasonality_components:
        - ["hour", "dow"]
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

**Recommended**: 20-40% of `window_size`

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
- Add `seasonality_components` (MAD only)
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
1. ✅ `seasonality_columns` extracts features
2. ✅ `query_columns.seasonality` lists column names
3. ✅ `seasonality_components` uses those column names
4. ✅ Enough data per group (`min_samples_per_group`)

**Example**:
```yaml
# Extract features
seasonality_columns:
  - name: hour_of_day    # Must match below
    extract: hour

# Tell query about columns
query_columns:
  seasonality:
    - hour_of_day        # Must match above

# Use in detector
detectors:
  - type: mad
    params:
      seasonality_components:
        - "hour_of_day"  # Must match above
```

## Advanced Detector Features (v0.2.0+)

**New in v0.2.0** - All statistical detectors support preprocessing, smoothing, and value weighting.

### Input Preprocessing

Transform input values before detection to detect on changes rather than absolute values.

#### Available Transformations

**`input_type: "raw"`** (default) - Use values as-is:
```yaml
detectors:
  - type: mad
    params:
      input_type: "raw"  # Default
      threshold: 3.5
```

**`input_type: "diff"`** - Detect on differences between consecutive points:
```yaml
detectors:
  - type: mad
    params:
      input_type: "diff"
      threshold: 3.0
```

**Example:**
```
Original values: [100, 102, 105, 150, 152]
After diff:      [2,   3,   45,  2]
                           ↑ Anomaly detected (spike in change)
```

**`input_type: "pct_change"`** - Detect on percentage changes:
```yaml
detectors:
  - type: mad
    params:
      input_type: "pct_change"
      threshold: 3.0
```

**Example:**
```
Original values: [100, 102, 105, 200, 202]
After pct_change: [2%,  2.9%, 90%, 1%]
                          ↑ Anomaly detected (90% jump)
```

#### When to Use Each Type

**Use `"raw"`** (default):
- Absolute values matter (CPU %, memory usage, latency)
- Thresholds are meaningful (>500ms is bad regardless of trend)
- Baseline is stable

**Use `"diff"`**:
- Changes matter more than absolute values
- Sudden jumps/drops are anomalies
- Examples: Error counts increasing rapidly, queue depth changes

**Use `"pct_change"`**:
- Relative changes matter (revenue, traffic, conversions)
- Different baselines (10 vs 10,000 - both can have 50% spike)
- Growth rates, ratios, percentages

#### Complete Example

**Scenario**: Detect abnormal revenue growth

```yaml
name: daily_revenue_growth
description: Daily revenue percentage change monitoring
interval: "1day"

query: |
  SELECT
    date AS timestamp,
    SUM(amount) AS value
  FROM sales
  WHERE date >= %(from_date)s
    AND date < %(to_date)s
  GROUP BY date
  ORDER BY date

detectors:
  - type: mad
    params:
      input_type: "pct_change"  # Detect on % growth
      threshold: 3.5
      window_size: 90           # 90 days baseline

alerting:
  enabled: true
  channels:
    - slack_finance
  consecutive_anomalies: 2
```

**What it detects:**
```
Day 1: $10,000 revenue
Day 2: $10,200 revenue → +2% growth (normal)
Day 3: $10,300 revenue → +1% growth (normal)
Day 4: $18,000 revenue → +75% growth → ANOMALY DETECTED
```

### Value Smoothing

Reduce noise with moving average before detection.

```yaml
detectors:
  - type: mad
    params:
      smoothing_window: 5  # 5-point moving average
      threshold: 3.0
```

**How it works:**

```
Original values: [10, 12, 50, 11, 9, 10, 11]  # 50 is noise spike
After smoothing:  [10, 12, 18.4, 18.4, 18, 10, 11]
                              ↑ Spike smoothed out
```

**When to use:**
- Noisy metrics with high-frequency fluctuations
- Single-point spikes that aren't real issues
- Reduce false positives from measurement errors

**Typical values:**
- `smoothing_window: 3` - Light smoothing
- `smoothing_window: 5` - Standard smoothing
- `smoothing_window: 7-10` - Heavy smoothing

**Trade-off**: Reduces noise but also reduces sensitivity to short-lived anomalies.

### Recent Value Weighting

Weight recent values more heavily in calculations.

```yaml
detectors:
  - type: mad
    params:
      recent_weight: 0.7  # 70% weight to recent 20% of window
      window_size: 100
```

**How it works:**

Without weighting (default `recent_weight: 0.0`):
```
All 100 points contribute equally to median/std calculation
```

With weighting (`recent_weight: 0.7`):
```
Oldest 80 points:  30% of total weight
Recent 20 points:  70% of total weight
→ Recent data influences threshold more
```

**When to use:**
- Metrics with trends or changing baselines
- Faster adaptation to new "normal" levels
- Seasonal metrics that shift over time

**When NOT to use:**
- Stable baselines (wastes computation)
- Want to detect return to old baseline as anomaly

**Typical values:**
- `recent_weight: 0.0` - No weighting (default)
- `recent_weight: 0.5` - Moderate weighting
- `recent_weight: 0.7` - Aggressive weighting

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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
  ORDER BY timestamp

detectors:
  - type: mad
    params:
      # Detect on percentage changes (not absolute error rate)
      input_type: "pct_change"

      # Smooth out noise from low-traffic periods
      smoothing_window: 3

      # Weight recent data more (baseline shifts over time)
      recent_weight: 0.6

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
1. Converts error rate to percentage changes (10% → 15% is 50% increase)
2. Applies 3-point smoothing to reduce noise
3. Weights recent 20% of window at 60% (adapts to new baselines faster)
4. Uses MAD detector with 3.5 threshold
5. Alerts only after 2 consecutive anomalies
6. Prevents spam with 15-minute cooldown

### Feature Compatibility

All preprocessing features work with all statistical detectors:

| Feature | MAD | Z-Score | IQR | Manual Bounds |
|---------|-----|---------|-----|---------------|
| `input_type` | ✅ | ✅ | ✅ | ✅ |
| `smoothing_window` | ✅ | ✅ | ✅ | ✅ |
| `recent_weight` | ✅ | ✅ | ✅ | ❌ (N/A) |

**Note**: Manual Bounds detector doesn't use `recent_weight` because it uses fixed thresholds, not calculated statistics.

### Performance Considerations

- **`input_type: "diff"` or `"pct_change"`**: Minimal overhead (~5%)
- **`smoothing_window`**: Adds ~10-20% overhead (rolling window calculation)
- **`recent_weight`**: Adds ~15-25% overhead (weighted statistics)

All preprocessing is vectorized using numpy, so overhead is minimal even for large datasets.

### Debugging Preprocessed Detections

Detection metadata includes preprocessing information:

```python
{
  "preprocessing": {
    "input_type": "pct_change",
    "smoothing": "ma3",  # 3-point moving average
    "recent_weight": 0.7
  },
  "global_median": 2.5,  # Statistics on preprocessed values
  "adjusted_median": 2.3,
  ...
}
```

This helps understand what the detector "saw" after preprocessing.

## See Also

- [MAD Detector Reference](../reference/detectors/mad.md)
- [Z-Score Detector Reference](../reference/detectors/zscore.md)
- [IQR Detector Reference](../reference/detectors/iqr.md)
- [Manual Bounds Detector Reference](../reference/detectors/manual_bounds.md)
- [Configuration Guide](configuration.md)
- [Alerting Guide](alerting.md)

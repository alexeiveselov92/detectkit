# IQR Detector (Interquartile Range)

The IQR (Interquartile Range) detector is a robust statistical method for anomaly detection based on Tukey's fences, using quartiles instead of mean-based statistics.

## Overview

IQR is particularly effective for:
- **Skewed distributions** - Works well with asymmetric data
- **Data with outliers** - More robust than Z-Score
- **Box plot visualization** - Natural match for box-and-whisker plots
- **Non-parametric detection** - No distribution assumptions required

## Algorithm

The IQR detector works by:

1. **Calculate Q1** (25th percentile) of historical window
2. **Calculate Q3** (75th percentile) of historical window
3. **Calculate IQR** = Q3 - Q1
4. **Build confidence interval**: `[Q1 - threshold × IQR, Q3 + threshold × IQR]`
5. **Detect anomalies** when values fall outside the interval

### Tukey's Fences

The IQR method is based on **Tukey's fences** for outlier detection:

```
Lower fence = Q1 - k × IQR
Upper fence = Q3 + k × IQR

k = 1.5  → Standard outliers
k = 3.0  → Extreme outliers
```

**Note**: IQR is similar to MAD in robustness but uses quartiles (25%/75%) instead of median (50%).

## Parameters

### Algorithm Parameters

#### `threshold` (float, default: 1.5)
IQR multiplier for determining confidence bounds (Tukey's k-value).

- **Higher values** (e.g., 3.0) = less sensitive, fewer anomalies (extreme outliers)
- **Lower values** (e.g., 1.0) = more sensitive, more anomalies
- **Default 1.5** is standard Tukey's fences for outliers
- **Common values**:
  - `1.5` = Standard outliers (recommended default)
  - `3.0` = Extreme outliers only
  - `1.0` = Very sensitive detection

**Example:**
```yaml
detectors:
  - type: iqr
    params:
      threshold: 1.5  # Standard Tukey's fences
```

#### `window_size` (int, default: 100)
Number of historical points to use for computing statistics.

- **Larger windows** (e.g., 1000) = more stable, less responsive to changes
- **Smaller windows** (e.g., 50) = more responsive, less stable
- **Recommended**: At least 30-50 points for reliable quartile estimation
  - For 10-minute intervals: `window_size = 288` (2 days)
  - For hourly data: `window_size = 168` (1 week)
  - For daily data: `window_size = 30` (1 month)

**Example:**
```yaml
detectors:
  - type: iqr
    params:
      window_size: 288  # 2 days of 10-min intervals
```

#### `min_samples` (int, default: 30, minimum: 4)
Minimum valid samples required before detection starts.

- Ensures statistical reliability for quartile calculation
- Points before this threshold are marked as "insufficient_data"
- Must be at least 4 (minimum for quartiles)
- **Typical**: 10-30% of `window_size`

**Example:**
```yaml
detectors:
  - type: iqr
    params:
      min_samples: 50  # Wait for 50 valid samples
```

#### `seasonality_components` (list, optional)
Seasonality groupings for adaptive intervals — works exactly like MAD's
(global statistics adjusted by per-group multipliers). Single components
(`"hour"`), multiple separate components, or combined components
(`["hour", "day_of_week"]`) are supported. Names must match the metric's
built-in `seasonality_columns` features (`hour`, `day_of_week`,
`day_of_month`, `month`, `is_weekend`, `is_holiday`) or custom columns
declared in `query_columns.seasonality`.

**Example:**
```yaml
detectors:
  - type: iqr
    params:
      seasonality_components:
        - "hour"
```

#### `min_samples_per_group` (int, default: 4, minimum: 4)
Minimum samples required in each seasonality group for applying multipliers.
Groups below this threshold fall back to global statistics.

### Shared Parameters (Preprocessing, Weighting, Detrending)

These parameters are shared by MAD, Z-Score and IQR and behave identically.
See the [Detectors Guide](../../guides/detectors.md#advanced-detector-features)
for detailed explanations and recipes.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `input_type` | str | `"values"` | `"values"`, `"changes"`, `"absolute_changes"` or `"log_changes"` |
| `smoothing` | str/null | `null` | `null`, `"ema"` or `"sma"` — applied before `input_type` |
| `smoothing_alpha` | float | `0.3` | EMA factor, 0 < alpha ≤ 1 |
| `smoothing_window` | int | `10` | SMA window in points |
| `window_weights` | str/null | `null` | `null` (uniform), `"exponential"` or `"linear"` recency weighting |
| `half_life` | int/str/null | `null` | Exponential half-life: int points or duration string (`"3d"`, `"12h"`). Default when unset: `window_size / 20` |
| `weight_decay` | float/null | `null` | **Deprecated** alias for `half_life` (per-point multiplier in (0, 1)); mutually exclusive with `half_life` |
| `detrend` | str/null | `null` | `null` or `"linear"` — robust in-window detrending |

### Execution Parameters

Execution parameters control how detection runs; they don't affect results
and are **not** part of the detector ID hash.

#### `start_time` (string, optional)
Start detecting anomalies from this timestamp. Data before is used only for building history.

**Format**: `"YYYY-MM-DD HH:MM:SS"`

**Example:**
```yaml
detectors:
  - type: iqr
    params:
      threshold: 1.5
      window_size: 288
      start_time: "2024-03-01 00:00:00"  # Start detection after 2 days
```

#### `batch_size` (int, optional)
Number of points to process per batch. Useful for large datasets.

**Example:**
```yaml
detectors:
  - type: iqr
    params:
      batch_size: 1440  # Process 10 days at a time (10-min intervals)
```

### Detector Identity

All result-affecting parameters (everything except `start_time` and
`batch_size`) are hashed into the `detector_id` (non-default values only).
Changing any of them creates a new detector ID and detections are recomputed
from scratch on the next run; old rows stay under the previous ID
(`--full-refresh` purges them).

## Configuration Examples

### Basic Usage

Minimal configuration:
```yaml
name: request_latency
interval: 1min
query: "SELECT timestamp, p95_latency_ms FROM metrics"

detectors:
  - type: iqr
    params:
      threshold: 1.5
```

### With Historical Window

Recommended for production:
```yaml
detectors:
  - type: iqr
    params:
      threshold: 1.5
      window_size: 288     # 2 days of 1-min data
      min_samples: 60      # Wait for 1 hour of data
```

### Extreme Outliers Only

For very noisy metrics:
```yaml
name: network_jitter
interval: 5min
query: "SELECT timestamp, jitter_ms FROM network_metrics"

detectors:
  - type: iqr
    params:
      threshold: 3.0      # Only extreme outliers
      window_size: 288    # 1 day of 5-min data
      min_samples: 50
```

### High Sensitivity Detection

For stable metrics where small deviations matter:
```yaml
name: cache_hit_rate
interval: 1min
query: "SELECT timestamp, hit_rate FROM cache_stats"

detectors:
  - type: iqr
    params:
      threshold: 1.0      # More sensitive than default
      window_size: 1440   # 1 day of 1-min data
      min_samples: 100
```

### Skewed Distribution

Perfect for metrics with heavy tails:
```yaml
name: response_time_p99
interval: 5min
query: "SELECT timestamp, p99_response_ms FROM logs"

detectors:
  - type: iqr
    params:
      threshold: 1.5      # Standard outliers
      window_size: 576    # 2 days of 5-min data
      min_samples: 100
```

## When to Use IQR Detector

### ✅ Best For:
- **Skewed distributions** - Asymmetric, heavy-tailed data
- **Data with outliers** - More robust than Z-Score
- **Non-parametric detection** - No distribution assumptions
- **Box plot fans** - Natural visualization match
- **Percentile-based metrics** - P95, P99, etc.

### ⚠️ Consider Alternatives:
- **Normally distributed data** → Z-Score (more sensitive)
- **Symmetric distributions** → MAD may be slightly better
- **Known bounds** → Manual Bounds for strict thresholds

## Advantages and Disadvantages

### ✅ Advantages:
- **Robust to outliers** - Uses quartiles, not mean
- **No distribution assumption** - Works with any data shape
- **Interpretable** - Box plot visualization
- **Handles skewness** - Naturally asymmetric bounds
- **Well-established** - Tukey's fences widely used

### ❌ Disadvantages:
- **Less sensitive than MAD** - Quartiles span 50% of data
- **May be too permissive** - 1.5×IQR captures ~99.3% of normal data, leaving ~0.7% false positives
- **Slower than MAD** - Percentile calculation slightly more expensive

## Performance Characteristics

- **Speed**: ~1,400 points/second (including I/O)
- **Memory**: O(window_size) per metric
- **CPU**: Lightweight (percentile calculation)
- **Compared to MAD**: Slightly slower (percentile vs median)

## Detection Metadata

Each detection result includes metadata:

```python
{
    "global_q1": 0.4234,         # 25th percentile of window
    "global_q3": 0.6123,         # 75th percentile of window
    "global_iqr": 0.1889,        # Q3 - Q1
    "adjusted_q1": 0.4301,       # After seasonality adjustment
    "adjusted_q3": 0.6087,       # After seasonality adjustment
    "adjusted_iqr": 0.1786,      # After seasonality adjustment
    "window_size": 288,          # Actual valid samples used
    "ess": 102.5,                # Effective sample size (Kish) — when window_weights is set
    "trend_slope_per_point": 0.0003,  # Estimated trend slope — when detrend is set

    # Only for anomalies:
    "direction": "above",        # "above" or "below"
    "severity": 2.34,            # How many (adjusted) IQR units beyond the fence
    "distance": 0.4421           # Absolute distance beyond the violated fence (>= 0)
}
```

### Severity Calculation

Severity is the distance *beyond* the violated fence, in (adjusted) IQR
units. It starts at 0 *at* the bound (not measured from the center), using
the seasonality-adjusted statistics and the preprocessed value:

```python
severity = distance / adjusted_iqr
# where distance = how far the value sits outside [lower_fence, upper_fence]
```

This is the same "0 at the bound" convention as MAD (σ-equivalents) and
Z-Score, so the alert layer can compare severities across detectors when
several fire at once.

**Interpretation** (with `threshold: 1.5`):
- `severity ≈ 0` → Just outside the fence
- `severity ≥ 1.0` → One full IQR beyond the fence — strong anomaly
- `severity ≥ 2.0` → Two+ IQR beyond the fence — extreme anomaly

## Edge Cases

### Zero IQR

When Q1 = Q3 (all values in same quartile range):
- Confidence interval becomes: `[Q1 - ε, Q3 + ε]` where ε = 1e-10
- Any value outside the Q1-Q3 range is considered anomalous
- This typically happens with discrete/categorical metrics

### Inverted Bounds Under Seasonality

Seasonality multipliers are applied per statistic (Q1, Q3, IQR separately)
and can in rare degenerate cases produce `lower > upper`. Bounds are
automatically normalized (swapped) so the interval is always valid.

### Small Windows

With `window_size < min_samples`:
- Detection is skipped until enough data is collected
- Results are marked with `"reason": "insufficient_data"`
- Need at least 4 samples for quartile calculation

## Mathematical Background

### Quartiles and IQR

Quartiles divide sorted data into four equal parts:

```
Q1 = 25th percentile (lower quartile)
Q2 = 50th percentile (median)
Q3 = 75th percentile (upper quartile)

IQR = Q3 - Q1  (middle 50% of data)
```

### Tukey's Fences

John Tukey proposed using 1.5×IQR for outlier detection:

```
Lower fence = Q1 - 1.5×IQR
Upper fence = Q3 + 1.5×IQR

Points outside fences = outliers
```

**For normal distribution**:
- 1.5×IQR fences capture ~99.3% of data (similar to 2.7σ)
- 3.0×IQR fences capture ~99.99% of data (similar to 4.5σ)

### Percentile Calculation

Quartiles are computed with
`detectkit.utils.stats.weighted_percentile`, which uses the midpoint
(Hazen) convention and supports recency weights:

```python
Q1 = weighted_percentile(data, weights, 25)
Q3 = weighted_percentile(data, weights, 75)
```

With uniform weights this reproduces `np.median` exactly (and gives
quartiles consistent with it); when `window_weights` is set, the recency
weights enter Q1/Q3 directly. It is **not** `np.percentile` linear
interpolation.

## Comparison with MAD and Z-Score

### IQR vs MAD:
- **Similarity**: Both robust to outliers
- **Difference**: IQR uses Q1/Q3 (25%/75%), MAD uses median (50%)
- **Robustness**: MAD ~37% breakdown point, IQR ~25% breakdown point
- **Skewness**: IQR naturally creates asymmetric bounds

### IQR vs Z-Score:
- **Distribution**: IQR works with any distribution, Z-Score needs normal
- **Outliers**: IQR robust, Z-Score sensitive
- **Sensitivity**: Z-Score more sensitive on clean normal data
- **Speed**: Z-Score slightly faster

## Comparison with Other Detectors

| Feature | IQR | MAD | Z-Score | Manual |
|---------|-----|-----|---------|--------|
| Robust to outliers | ✅ Very | ✅ Very | ❌ No | N/A |
| Distribution-free | ✅ Yes | ✅ Yes | ❌ No | N/A |
| Seasonality support | ✅ Yes | ✅ Excellent | ✅ Yes | ❌ No |
| Skewed data | ✅ Excellent | ✅ Good | ❌ Poor | N/A |
| Sensitivity | ⚠️ Medium | ⚠️ Medium | ✅ High | ✅ Exact |
| Performance | ✅ Fast | ✅ Fast | ✅ Very Fast | ✅ Very Fast |
| Visualization | ✅ Box plot | ⚠️ N/A | ⚠️ N/A | ⚠️ N/A |

## References

- [Interquartile Range (Wikipedia)](https://en.wikipedia.org/wiki/Interquartile_range)
- [Tukey's Fences (Wikipedia)](https://en.wikipedia.org/wiki/Outlier#Tukey's_fences)
- [Box Plot (NIST)](https://www.itl.nist.gov/div898/handbook/eda/section3/boxplot.htm)

## See Also

- [MAD Detector](mad.md) - Similar robustness with seasonality support
- [Z-Score Detector](zscore.md) - For normally distributed data
- [Detectors Guide](../../guides/detectors.md) - Choosing the right detector
- [Configuration Guide](../../guides/configuration.md) - Complete config reference

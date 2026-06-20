# MAD Detector (Median Absolute Deviation)

The MAD (Median Absolute Deviation) detector is a robust statistical method for anomaly detection that uses median-based statistics instead of mean-based approaches.

## Overview

MAD is particularly effective for:
- **Data with outliers** - More robust than standard deviation methods
- **Skewed distributions** - Works well with non-normal data
- **Time-series with seasonality** - Supports seasonality grouping
- **General-purpose detection** - Good default choice for most metrics

## Algorithm

The MAD detector works by:

1. **Calculate median** of historical window values
2. **Calculate MAD** (median of absolute deviations from median)
3. **Scale MAD to σ-equivalents**: `sigma_est = 1.4826 × MAD` (normal-consistency constant)
4. **Build confidence interval**: `[median - threshold × 1.4826 × MAD, median + threshold × 1.4826 × MAD]`
5. **Detect anomalies** when values fall outside the interval

Thanks to the 1.4826 scaling, `threshold` is expressed in σ-equivalents
exactly like Z-Score: `threshold=3.0` corresponds to 3-sigma on Gaussian
noise (~0.27% false positives). Without scaling, 3×MAD would only be ≈2σ and
fire on ~4% of normal points.

### With Seasonality Grouping

When seasonality is configured:
1. Compute **global statistics** (entire window)
2. For each seasonality group:
   - Compute **group statistics** (matching seasonality values only)
   - Calculate **multipliers** (group_stat / global_stat)
3. Apply multipliers to adjust confidence intervals
4. Detect anomalies using adjusted intervals

This creates **adaptive intervals** that vary per seasonality pattern (e.g., different intervals for each hour of day).

## Parameters

### Algorithm Parameters

#### `threshold` (float, default: 3.0)
Number of σ-equivalents from median to consider anomalous. MAD is multiplied
by the normal-consistency constant 1.4826, so the interval is
`median ± threshold × 1.4826 × MAD`.

- **Higher values** (e.g., 5.0) = less sensitive, fewer anomalies
- **Lower values** (e.g., 2.0) = more sensitive, more anomalies
- **Default 3.0** genuinely corresponds to 3-sigma on Gaussian noise (~0.27% false positives)
- **Typical range**: 2.0 - 5.0

**Example:**
```yaml
detectors:
  - type: mad
    params:
      threshold: 3.0  # Standard sensitivity
```

#### `window_size` (int, default: 100)
Number of historical points to use for computing statistics.

- **Larger windows** (e.g., 1000) = more stable, less responsive to changes
- **Smaller windows** (e.g., 50) = more responsive, less stable
- **Recommended**: 2-4 weeks of data for daily seasonality
  - For 10-minute intervals: `window_size = 8640` (60 days)
  - For hourly data: `window_size = 672` (4 weeks)
  - For daily data: `window_size = 60` (2 months)

**Example:**
```yaml
detectors:
  - type: mad
    params:
      window_size: 8640  # 60 days of 10-min intervals
```

#### `min_samples` (int, default: 30, minimum: 1)
Minimum valid samples required before detection starts.

- Ensures statistical reliability
- Points before this threshold are marked as "insufficient_data"
- Should be significantly smaller than `window_size`
- **Typical**: 10-30% of `window_size`

**Example:**
```yaml
detectors:
  - type: mad
    params:
      min_samples: 1000  # Wait for 1000 valid samples
```

#### `seasonality_components` (list, optional)
List of seasonality groups to apply adaptive intervals.

**Format**: List of column names or lists of column names

Names must match the metric's seasonality features: the built-in
`seasonality_columns` names (`hour`, `day_of_week`, `day_of_month`,
`month`, `is_weekend`, `is_holiday`) or custom columns returned by the
query and declared in `query_columns.seasonality`.

**Examples:**

Single seasonality component:
```yaml
detectors:
  - type: mad
    params:
      seasonality_components:
        - "hour"  # Different intervals per hour
```

Multiple separate components:
```yaml
detectors:
  - type: mad
    params:
      seasonality_components:
        - "day_of_week"   # Different intervals per weekday
        - "hour"          # Different intervals per hour
```

Combined component (interaction):
```yaml
detectors:
  - type: mad
    params:
      seasonality_components:
        - ["hour", "day_of_week"]  # Different per hour+weekday combo
```

#### `min_samples_per_group` (int, default: 10)
Minimum samples required in each seasonality group for applying multipliers.
Groups below this threshold fall back to global statistics.

**Example:**
```yaml
detectors:
  - type: mad
    params:
      seasonality_components:
        - ["offset_10minutes", "league_day"]  # custom columns from query_columns.seasonality
      min_samples_per_group: 15  # Need 15 samples per group
```

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

**Example** (trending metric):
```yaml
detectors:
  - type: mad
    params:
      window_size: 8640
      min_samples: 1000
      seasonality_components: ["hour"]
      window_weights: exponential
      half_life: "3d"
      detrend: linear
```

### Execution Parameters

Execution parameters control how detection runs; they don't affect results
and are **not** part of the detector ID hash.

#### `start_time` (string, optional)
Start detecting anomalies from this timestamp. Data before is used only for building history.

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

#### `batch_size` (int, optional)
Number of points to process per batch. Useful for large datasets.

**Example:**
```yaml
detectors:
  - type: mad
    params:
      batch_size: 2160  # Process 15 days at a time (10-min intervals)
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
name: cpu_usage
interval: 1min
query: "SELECT timestamp, cpu_percent FROM metrics"

detectors:
  - type: mad
    params:
      threshold: 3.0
```

### With Historical Window

Recommended for production:
```yaml
detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 2880   # 2 days of 1-min data
      min_samples: 500    # Wait for 500 valid samples
```

### With Seasonality (Single Component)

For metrics with daily patterns:
```yaml
name: website_traffic
interval: 1hour
query: "SELECT timestamp, visitor_count FROM traffic"

# Extract hour-of-day seasonality from timestamp (built-in feature "hour")
seasonality_columns:
  - hour

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 672    # 4 weeks of hourly data
      seasonality_components:
        - "hour"          # Different intervals for each hour
```

### With Combined Seasonality

For complex patterns (e.g., gaming metrics with multi-day tournaments):
```yaml
name: group_assigned_users_pct
interval: 10min
query_file: sql/group_assigned.sql

query_columns:
  timestamp: period_time
  metric: group_assigned_users_pct
  seasonality:
    - offset_10minutes  # 0-143 (10-min intervals in day)
    - league_day        # 1-3 (tournament days)

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 8640   # 60 days
      min_samples: 1000
      start_time: "2024-03-01 00:00:00"
      batch_size: 2160
      seasonality_components:
        - ["offset_10minutes", "league_day"]  # 432 unique combinations
      min_samples_per_group: 10
```

## When to Use MAD Detector

### Best For:
- **General-purpose anomaly detection** - Good default choice
- **Data with outliers** - More robust than Z-Score
- **Skewed distributions** - Doesn't assume normality
- **Metrics with seasonality** - Excellent seasonality support
- **Production systems** - Stable and predictable behavior

### Consider Alternatives:
- **Symmetric distributions with no outliers** → Z-Score may be more sensitive
- **Known bounds** → Manual Bounds for strict thresholds
- **Extreme skewness** → IQR detector

## Performance Characteristics

- **Speed**: ~1,500 points/second (including I/O)
- **Memory**: O(window_size) per metric
- **CPU**: Lightweight (median calculation only)
- **Seasonality impact**: Minimal performance penalty

Detection runs a per-point window loop, so large initial backfills are the slow path; incremental runs only score the few new points and are cheap.

## Detection Metadata

Each detection result includes metadata:

```python
{
    "global_median": 0.5123,        # Median of entire window
    "global_mad": 0.0234,           # MAD of entire window
    "adjusted_median": 0.5234,      # After seasonality adjustment
    "adjusted_mad": 0.0187,         # After seasonality adjustment
    "window_size": 8640,            # Actual valid samples used
    "ess": 412.7,                   # Effective sample size (Kish) — when window_weights is set
    "trend_slope_per_point": -0.0002,  # Estimated trend slope — when detrend is set
    "seasonality_groups": [         # Applied adjustments
        {
            "group": ["offset_10minutes", "league_day"],
            "median_multiplier": 1.023,
            "mad_multiplier": 0.876,
            "group_size": 23
        }
    ],
    # Only for anomalies:
    "direction": "above",           # "above" or "below"
    "severity": 4.52,               # σ-equivalents beyond the bound (distance / (1.4826 × adjusted_mad); equals global_mad only when no seasonality multiplier applies)
    "distance": 0.2298              # Absolute distance from bound
}
```

## Comparison with Other Detectors

| Feature | MAD | Z-Score | IQR | Manual |
|---------|-----|---------|-----|--------|
| Robust to outliers | Very | No | Very | N/A |
| Normal distribution | Not required | Required | Not required | N/A |
| Seasonality support | Excellent | Yes | Yes | No |
| Sensitivity tuning | Threshold | Threshold | Threshold | Bounds |
| Performance | Fast | Fast | Fast | Very Fast |

## References

- [Median Absolute Deviation (Wikipedia)](https://en.wikipedia.org/wiki/Median_absolute_deviation)
- [Robust Statistics (NIST)](https://www.itl.nist.gov/div898/handbook/eda/section3/eda356.htm)

## See Also

- [Z-Score Detector](zscore.md) - For normally distributed data
- [IQR Detector](iqr.md) - For extremely skewed data
- [Detectors Guide](../../guides/detectors.md) - Choosing the right detector
- [Configuration Guide](../../guides/configuration.md) - Complete config reference

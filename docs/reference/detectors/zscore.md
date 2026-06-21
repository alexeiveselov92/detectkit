# Z-Score Detector

The Z-Score detector is a classical statistical method for anomaly detection that uses mean-based statistics and assumes approximately normal distribution.

## Overview

Z-Score is particularly effective for:
- **Normally distributed data** - Optimal for symmetric, bell-curve distributions
- **Clean metrics** - Data without significant outliers
- **Sensitive detection** - More responsive than MAD to small deviations
- **Well-understood thresholds** - 3σ rule (99.7% of data within ±3 standard deviations)

## Algorithm

The Z-Score detector works by:

1. **Calculate mean** of historical window values
2. **Calculate standard deviation** (with Bessel's correction)
3. **Build confidence interval**: `[mean - threshold × std, mean + threshold × std]`
4. **Detect anomalies** when values fall outside the interval

### Z-Score Formula

```
z_score = (value - mean) / std
confidence_interval = [mean - threshold × std, mean + threshold × std]
```

**Note**: Z-Score is more sensitive to outliers than MAD because both mean and standard deviation are affected by extreme values.

## Parameters

### Algorithm Parameters

#### `threshold` (float, default: 3.0)
Number of standard deviations from mean to consider anomalous.

- **Higher values** (e.g., 5.0) = less sensitive, fewer anomalies
- **Lower values** (e.g., 2.0) = more sensitive, more anomalies
- **Default 3.0** follows the 3-sigma rule (99.7% confidence)
- **Typical range**: 2.0 - 4.0

**Statistical interpretation**:
- `threshold=1.0` → 68.3% of data within bounds
- `threshold=2.0` → 95.4% of data within bounds
- `threshold=3.0` → 99.7% of data within bounds

**Example:**
```yaml
detectors:
  - type: zscore
    params:
      threshold: 3.0  # Standard 3-sigma rule
```

#### `window_size` (int, default: 100)
Number of historical points to use for computing statistics.

- **Larger windows** (e.g., 1000) = more stable, less responsive to changes
- **Smaller windows** (e.g., 50) = more responsive, less stable
- **Recommended**: At least 30-50 points for reliable mean/std estimation
  - For 10-minute intervals: `window_size = 288` (2 days)
  - For hourly data: `window_size = 168` (1 week)
  - For daily data: `window_size = 30` (1 month)

**Example:**
```yaml
detectors:
  - type: zscore
    params:
      window_size: 288  # 2 days of 10-min intervals
```

#### `min_samples` (int, default: 30, minimum: 2)
Minimum valid samples required before detection starts.

- Ensures statistical reliability (rule of thumb: ≥30 for normal approximation)
- Points before this threshold are marked as "insufficient_data"
- Should be significantly smaller than `window_size`
- **Typical**: 10-30% of `window_size`

**Example:**
```yaml
detectors:
  - type: zscore
    params:
      min_samples: 50  # Wait for 50 valid samples
```

#### `seasonality_components` (list, optional)
Seasonality groupings for adaptive intervals — works exactly like MAD's
(global statistics adjusted by per-group multipliers). Single components
(`"hour"`), multiple separate components, or combined components
(`["hour", "day_of_week"]`) are supported. Names must match the metric's
built-in `seasonality_columns` features or custom columns declared in
`query_columns.seasonality`.

**Example:**
```yaml
detectors:
  - type: zscore
    params:
      seasonality_components:
        - "hour"
```

#### `min_samples_per_group` (int, default: 3)
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
| `half_life` | int/str/null | `null` | Exponential half-life: int points or duration string (`"3d"`, `"12h"`). Default when unset: `max(window_size / 20, min_samples / 2)` |
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
  - type: zscore
    params:
      threshold: 3.0
      window_size: 288
      start_time: "2024-03-01 00:00:00"  # Start detection after 2 days
```

#### `batch_size` (int, optional)
Number of points to process per batch. Useful for large datasets.

**Example:**
```yaml
detectors:
  - type: zscore
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
name: response_time
interval: 1min
query: "SELECT timestamp, avg_response_ms FROM metrics"

detectors:
  - type: zscore
    params:
      threshold: 3.0
```

### With Historical Window

Recommended for production:
```yaml
detectors:
  - type: zscore
    params:
      threshold: 3.0
      window_size: 288     # 2 days of 1-min data
      min_samples: 60      # Wait for 1 hour of data
```

### High Sensitivity Detection

For critical metrics where false positives are acceptable:
```yaml
name: error_rate
interval: 5min
query: "SELECT timestamp, error_rate FROM logs"

detectors:
  - type: zscore
    params:
      threshold: 2.0      # More sensitive (95.4% confidence)
      window_size: 288    # 1 day of 5-min data
      min_samples: 30
```

### Low Sensitivity Detection

For noisy metrics where false positives are costly:
```yaml
name: cpu_usage
interval: 1min
query: "SELECT timestamp, cpu_percent FROM system_metrics"

detectors:
  - type: zscore
    params:
      threshold: 4.0      # Less sensitive (~99.99% confidence)
      window_size: 1440   # 1 day of 1-min data
      min_samples: 100
```

### With Warm-up Period

Build history before starting detection:
```yaml
detectors:
  - type: zscore
    params:
      threshold: 3.0
      window_size: 288
      min_samples: 100
      start_time: "2024-03-01 00:00:00"  # Start after 100 points collected
```

## When to Use Z-Score Detector

### Best For:
- **Normally distributed data** - Symmetric, bell-curve distributions
- **Clean metrics** - Data without significant outliers
- **Sensitive detection** - Need to catch small deviations
- **Real-time systems** - Fast computation with simple statistics
- **Well-behaved metrics** - Stable mean and variance

### Consider Alternatives:
- **Data with outliers** → MAD detector (more robust)
- **Skewed distributions** → IQR or MAD detector
- **Known bounds** → Manual Bounds for strict thresholds
- **Heavy tails** → MAD or IQR detector

## Advantages and Disadvantages

### Advantages:
- **Fast computation** - Simple mean/std calculations
- **Well-understood** - 3-sigma rule is widely known
- **Sensitive** - Catches subtle anomalies in clean data
- **Memory efficient** - O(window_size) per metric
- **Mathematical foundation** - Based on normal distribution theory

### Disadvantages:
- **Sensitive to outliers** - Mean and std affected by extreme values
- **Assumes normality** - May produce false positives on skewed data
- **Biased by history** - Outliers in window affect future detection

## Performance Characteristics

- **Speed**: ~1,800 points/second (including I/O)
- **Memory**: O(window_size) per metric
- **CPU**: Lightweight (mean/std calculation only)
- **Compared to MAD**: Slightly faster (mean vs median)

## Detection Metadata

Each detection result includes metadata:

```python
{
    "global_mean": 0.5234,       # Mean of entire window
    "global_std": 0.0421,        # Std of entire window
    "adjusted_mean": 0.5301,     # After seasonality adjustment
    "adjusted_std": 0.0398,      # After seasonality adjustment
    "window_size": 288,          # Actual valid samples used
    "ess": 96.4,                 # Effective sample size (Kish) — when window_weights is set
    "trend_slope_per_point": 0.0001,  # Estimated trend slope — when detrend is set
    "preprocessing": {           # Only when smoothing or non-default input_type is set
        "input_type": "values",
        "smoothing": "ema",
        "smoothed_value": 0.5288  # Only when smoothing is set
    },
    "seasonality_groups": [      # Applied adjustments — when seasonality_components is set
        {
            "group": ["hour"],
            "mean_multiplier": 1.013,
            "std_multiplier": 0.945,
            "group_size": 12
        }
    ],
    # Only for anomalies:
    "direction": "above",        # "above" or "below"
    "severity": 1.12,            # σ beyond the violated bound (0 = at the bound)
    "distance": 0.1732           # Absolute distance from bound
}
```

For NaN / gap-filled points (or values that become NaN after preprocessing),
detection is skipped with `is_anomaly=False` and
`detection_metadata = {"reason": "missing_data"}`.

### Severity Calculation

Severity is the distance beyond the violated bound, in standard deviations
(dividing by `adjusted_std`, not `global_std`, and using the preprocessed
value):

```python
severity = distance / adjusted_std
# where distance = how far the value sits outside [lower, upper]
```

This is the same "0 at the bound" convention as MAD (σ-equivalents) and IQR
(IQR units), so the alert layer can compare severities across detectors when
several fire at once.

**Interpretation** (with `threshold: 3.0`):
- `severity ≈ 0` → Barely outside the 3σ interval
- `severity ≥ 1.0` → 4σ+ from the mean — strong anomaly
- `severity ≥ 2.0` → 5σ+ from the mean — extreme anomaly

## Edge Cases

### Zero Standard Deviation

When all values in the window are identical (`std = 0`):
- Confidence interval becomes: `[mean - ε, mean + ε]` where ε = 1e-10
- Any deviation from the constant value is considered anomalous
- This is intentional: if metric is always constant, deviation indicates anomaly

### Small Windows

With `min_samples > window_size`:
- The detector **raises `ValueError`** at construction
  (`"min_samples cannot exceed window_size"`) — the metric fails to load
  rather than running with an unsatisfiable threshold.

### Insufficient Data (warm-up / after gaps)

When the trailing window holds fewer than `min_samples` valid (non-NaN)
points — during warm-up or after data gaps:
- Detection is skipped for that point (`is_anomaly=False`)
- Results are marked with `"reason": "insufficient_data"` (plus the current
  valid `window_size` and the configured `min_samples`)
- Ensures statistical reliability (central limit theorem requires ≥30 samples)

## Comparison with Other Detectors

| Feature | Z-Score | MAD | IQR | Manual |
|---------|---------|-----|-----|--------|
| Robust to outliers | No | Very | Very | N/A |
| Normal distribution | Required | Not required | Not required | N/A |
| Seasonality support | Yes | Excellent | Yes | No |
| Sensitivity | High | Medium | Medium | Exact |
| Performance | Very Fast | Fast | Fast | Very Fast |
| Mathematical basis | Strong | Good | Good | None |

## Mathematical Background

### Normal Distribution Assumption

Z-Score assumes data follows a normal distribution N(μ, σ²):

```
P(|X - μ| ≤ kσ) ≈ confidence level

k=1.0 → 68.3% (±1σ)
k=2.0 → 95.4% (±2σ)
k=3.0 → 99.7% (±3σ)
```

If data is **not** normally distributed:
- Confidence levels may not hold
- False positives may increase
- Consider using MAD (distribution-free) instead

### Bessel's Correction

Standard deviation uses `ddof=1` (Bessel's correction):

```python
std = sqrt(sum((x - mean)²) / (n - 1))
```

This provides an unbiased estimate of population standard deviation from sample data.

## References

- [Standard Score (Wikipedia)](https://en.wikipedia.org/wiki/Standard_score)
- [68-95-99.7 Rule (Wikipedia)](https://en.wikipedia.org/wiki/68%E2%80%9395%E2%80%9399.7_rule)
- [Normal Distribution (NIST)](https://www.itl.nist.gov/div898/handbook/eda/section3/eda3661.htm)

## See Also

- [MAD Detector](mad.md) - For data with outliers or seasonality
- [IQR Detector](iqr.md) - For extremely skewed data
- [Detectors Guide](../../guides/detectors.md) - Choosing the right detector
- [Configuration Guide](../../guides/configuration.md) - Complete config reference

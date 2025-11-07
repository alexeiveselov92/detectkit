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

#### `min_samples` (int, default: 30)
Minimum valid samples required before detection starts.

- Ensures statistical reliability (rule of thumb: ≥30 for normal approximation)
- Points before this threshold are marked as "insufficient_data"
- Should be significantly smaller than `window_size`
- **Typical**: 20-40% of `window_size`

**Example:**
```yaml
detectors:
  - type: zscore
    params:
      min_samples: 50  # Wait for 50 valid samples
```

### Execution Parameters

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

#### `seasonality_components` (list, optional)
⚠️ **Not yet implemented** - Seasonality support planned for future versions.

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
      threshold: 4.0      # Less sensitive (99.99% confidence)
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

### ✅ Best For:
- **Normally distributed data** - Symmetric, bell-curve distributions
- **Clean metrics** - Data without significant outliers
- **Sensitive detection** - Need to catch small deviations
- **Real-time systems** - Fast computation with simple statistics
- **Well-behaved metrics** - Stable mean and variance

### ⚠️ Consider Alternatives:
- **Data with outliers** → MAD detector (more robust)
- **Skewed distributions** → IQR or MAD detector
- **Seasonal patterns** → MAD detector with seasonality (Z-Score doesn't support yet)
- **Known bounds** → Manual Bounds for strict thresholds
- **Heavy tails** → MAD or IQR detector

## Advantages and Disadvantages

### ✅ Advantages:
- **Fast computation** - Simple mean/std calculations
- **Well-understood** - 3-sigma rule is widely known
- **Sensitive** - Catches subtle anomalies in clean data
- **Memory efficient** - O(window_size) per metric
- **Mathematical foundation** - Based on normal distribution theory

### ❌ Disadvantages:
- **Sensitive to outliers** - Mean and std affected by extreme values
- **Assumes normality** - May produce false positives on skewed data
- **No seasonality** - Doesn't adapt to time-based patterns yet
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
    "mean": 0.5234,              # Mean of entire window
    "std": 0.0421,               # Standard deviation of window
    "window_size": 288,          # Actual valid samples used

    # Only for anomalies:
    "direction": "above",        # "above" or "below"
    "severity": 4.12,            # Z-score (number of std away)
    "distance": 0.1732           # Absolute distance from bound
}
```

### Severity Calculation

Severity represents the Z-score (how many standard deviations away from mean):

```python
severity = abs(value - mean) / std
```

**Interpretation**:
- `severity < 3.0` → Within 99.7% confidence (not anomalous with default threshold)
- `severity ≥ 3.0` → Outside 99.7% confidence (anomalous with default threshold)
- `severity ≥ 4.0` → Highly anomalous (99.99% confidence)
- `severity ≥ 5.0` → Extremely anomalous (99.9999% confidence)

## Edge Cases

### Zero Standard Deviation

When all values in the window are identical (`std = 0`):
- Confidence interval becomes: `[mean - ε, mean + ε]` where ε = 1e-10
- Any deviation from the constant value is considered anomalous
- This is intentional: if metric is always constant, deviation indicates anomaly

### Small Windows

With `window_size < min_samples`:
- Detection is skipped until enough data is collected
- Results are marked with `"reason": "insufficient_data"`
- Ensures statistical reliability (central limit theorem requires ≥30 samples)

## Comparison with Other Detectors

| Feature | Z-Score | MAD | IQR | Manual |
|---------|---------|-----|-----|--------|
| Robust to outliers | ❌ No | ✅ Very | ✅ Very | N/A |
| Normal distribution | ✅ Required | ❌ Not required | ❌ Not required | N/A |
| Seasonality support | ✅ Yes | ✅ Excellent | ✅ Yes | ❌ No |
| Sensitivity | ✅ High | ⚠️ Medium | ⚠️ Medium | ✅ Exact |
| Performance | ✅ Very Fast | ✅ Fast | ✅ Fast | ✅ Very Fast |
| Mathematical basis | ✅ Strong | ✅ Good | ✅ Good | ❌ None |

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

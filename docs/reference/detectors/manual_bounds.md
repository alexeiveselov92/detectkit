# Manual Bounds Detector

The Manual Bounds detector is a simple threshold-based method that uses user-specified bounds for anomaly detection. Ideal when domain knowledge exists about acceptable ranges.

## Overview

Manual Bounds is particularly effective for:
- **Known thresholds** - Clear business rules or SLA requirements
- **Hard limits** - Physical or logical constraints (e.g., percentages 0-100%)
- **Binary alerts** - Simple "too high" or "too low" notifications
- **Real-time detection** - No historical data needed
- **Compliance monitoring** - Regulatory or contractual limits

## Algorithm

The Manual Bounds detector works by:

1. **Define bounds** - User specifies `lower_bound` and/or `upper_bound`
2. **Compare values** - Check if current value is outside bounds
3. **Detect anomalies** - Any value outside bounds is anomalous

**No historical data required** - purely threshold-based comparison.

## Parameters

### Algorithm Parameters

#### `lower_bound` (float or None, default: None)
Minimum acceptable value. Values below this are considered anomalous.

- `None` = no lower limit
- Must be less than `upper_bound` if both specified
- At least one of `lower_bound` or `upper_bound` must be specified

**Example:**
```yaml
detectors:
  - type: manual_bounds
    params:
      lower_bound: 0.0  # Values below 0 are anomalies
```

#### `upper_bound` (float or None, default: None)
Maximum acceptable value. Values above this are considered anomalous.

- `None` = no upper limit
- Must be greater than `lower_bound` if both specified
- At least one of `lower_bound` or `upper_bound` must be specified

**Example:**
```yaml
detectors:
  - type: manual_bounds
    params:
      upper_bound: 100.0  # Values above 100 are anomalies
```

### No Execution Parameters

Manual Bounds detector does not use:
- `window_size` - No historical window needed
- `min_samples` - No warm-up period needed
- `threshold` - Bounds are explicit
- `seasonality_components` - No seasonality support

However, you can still use:
- `start_time` - Start detecting from this timestamp (optional)
- `batch_size` - Process data in batches (optional)

## Configuration Examples

### Upper Bound Only

Alert when values exceed maximum:
```yaml
name: cpu_usage
interval: 1min
query: "SELECT timestamp, cpu_percent FROM system_metrics"

detectors:
  - type: manual_bounds
    params:
      upper_bound: 90.0  # Alert when CPU > 90%
```

### Lower Bound Only

Alert when values drop below minimum:
```yaml
name: cache_hit_rate
interval: 5min
query: "SELECT timestamp, hit_rate FROM cache_stats"

detectors:
  - type: manual_bounds
    params:
      lower_bound: 0.8  # Alert when hit rate < 80%
```

### Both Bounds (Range Check)

Alert when values are outside acceptable range:
```yaml
name: queue_size
interval: 1min
query: "SELECT timestamp, queue_length FROM processing_queue"

detectors:
  - type: manual_bounds
    params:
      lower_bound: 0     # Alert if queue is negative (impossible)
      upper_bound: 10000  # Alert if queue exceeds capacity
```

### Response Time SLA

Monitor service level agreement:
```yaml
name: api_response_time
interval: 1min
query: "SELECT timestamp, p95_response_ms FROM api_logs"

detectors:
  - type: manual_bounds
    params:
      upper_bound: 1000  # SLA: 95th percentile < 1000ms
```

### Percentage Bounds

Monitor metrics with natural 0-100% range:
```yaml
name: disk_usage
interval: 5min
query: "SELECT timestamp, disk_used_pct FROM storage_metrics"

detectors:
  - type: manual_bounds
    params:
      upper_bound: 85.0  # Alert when disk > 85% full
```

### Error Rate Threshold

Zero-tolerance error monitoring:
```yaml
name: critical_errors
interval: 1min
query: "SELECT timestamp, error_count FROM application_logs"

detectors:
  - type: manual_bounds
    params:
      upper_bound: 0  # Any error is anomalous
```

### Temperature Monitoring

Physical system with operating range:
```yaml
name: server_temperature
interval: 30s
query: "SELECT timestamp, temp_celsius FROM hardware_sensors"

detectors:
  - type: manual_bounds
    params:
      lower_bound: 10.0   # Too cold (cooling failure)
      upper_bound: 75.0   # Too hot (overheating)
```

## When to Use Manual Bounds Detector

### ✅ Best For:
- **Known thresholds** - Clear business rules or requirements
- **SLA monitoring** - Contractual limits (response time, uptime)
- **Hard constraints** - Physical/logical limits (0-100%, positive values)
- **Compliance** - Regulatory requirements
- **Simple alerting** - Binary "too high/low" notifications
- **Real-time detection** - No historical warm-up period needed

### ⚠️ Consider Alternatives:
- **No clear threshold** → Statistical detectors (MAD, Z-Score, IQR)
- **Dynamic patterns** → MAD with seasonality
- **Relative anomalies** → Z-Score or MAD (detect deviations from normal)
- **Exploratory analysis** → Start with MAD to discover natural thresholds

## Advantages and Disadvantages

### ✅ Advantages:
- **Instant detection** - No warm-up period, works from first point
- **Simple** - Easy to understand and explain to stakeholders
- **Predictable** - No statistical variability
- **Fast** - Fastest detector (simple comparison)
- **Transparent** - Clear why something is anomalous
- **Domain knowledge** - Leverages expert knowledge of acceptable ranges

### ❌ Disadvantages:
- **Manual tuning** - Requires domain knowledge to set bounds
- **No adaptation** - Doesn't learn from data patterns
- **Static** - Can't handle seasonality or trends
- **False positives** - May alert on valid but unusual spikes
- **Maintenance** - Bounds may need updating as system changes

## Performance Characteristics

- **Speed**: ~3,000 points/second (including I/O)
- **Memory**: O(1) - No historical data stored
- **CPU**: Minimal (simple comparison)
- **Fastest detector** - No statistical calculations

## Detection Metadata

Each detection result includes metadata:

```python
{
    # Only for anomalies:
    "direction": "above",         # "above" or "below"
    "distance": 15.32,            # Absolute distance from bound
    "severity": 0.152             # Relative severity
}
```

### Severity Calculation

Severity represents relative distance from bound:

**With both bounds**:
```python
bound_range = upper_bound - lower_bound
severity = distance / bound_range
```

**With only one bound**:
```python
severity = distance  # Absolute distance
```

**Interpretation**:
- `severity = 0.1` → 10% of range outside bounds
- `severity = 0.5` → 50% of range outside bounds
- `severity = 1.0` → Full range width outside bounds
- `severity > 1.0` → More than full range outside

**Example**:
```yaml
lower_bound: 10
upper_bound: 90
value: 100

distance = 100 - 90 = 10
bound_range = 90 - 10 = 80
severity = 10 / 80 = 0.125
```

## Edge Cases

### NaN Values

- NaN values are skipped
- Marked as `is_anomaly=False` with `"reason": "missing_data"`
- No alert triggered

### Equal Bounds

```yaml
lower_bound: 50.0
upper_bound: 50.0  # ERROR: Invalid configuration
```

Validation will fail: `lower_bound must be less than upper_bound`

### No Bounds

```yaml
params: {}  # ERROR: Invalid configuration
```

Validation will fail: `At least one of lower_bound or upper_bound must be specified`

### Negative Infinity / Positive Infinity

Not supported - use `None` instead:

```yaml
# WRONG:
lower_bound: -inf
upper_bound: inf

# CORRECT:
lower_bound: null    # No lower limit
upper_bound: null    # Error: at least one bound required
```

## Comparison with Other Detectors

| Feature | Manual Bounds | MAD | Z-Score | IQR |
|---------|---------------|-----|---------|-----|
| Historical data | ❌ Not needed | ✅ Required | ✅ Required | ✅ Required |
| Warm-up period | ✅ None | ⚠️ min_samples | ⚠️ min_samples | ⚠️ min_samples |
| Adaptivity | ❌ Static | ✅ Adapts | ✅ Adapts | ✅ Adapts |
| Seasonality | ❌ No | ✅ Excellent | ❌ Not yet | ❌ Not yet |
| Domain knowledge | ✅ Required | ❌ Not needed | ❌ Not needed | ❌ Not needed |
| Setup effort | ⚠️ Manual tuning | ✅ Auto | ✅ Auto | ✅ Auto |
| Performance | ✅ Fastest | ✅ Fast | ✅ Fast | ✅ Fast |
| Transparency | ✅ Very clear | ⚠️ Statistical | ⚠️ Statistical | ⚠️ Statistical |

## Use Cases

### 1. SLA Monitoring

```yaml
# API response time must be < 500ms (P95)
name: api_latency_p95
detectors:
  - type: manual_bounds
    params:
      upper_bound: 500.0
```

### 2. Resource Limits

```yaml
# Memory usage should not exceed 8GB
name: memory_usage_gb
detectors:
  - type: manual_bounds
    params:
      upper_bound: 8.0
```

### 3. Business Metrics

```yaml
# Daily revenue should be > $10,000
name: daily_revenue
detectors:
  - type: manual_bounds
    params:
      lower_bound: 10000.0
```

### 4. Compliance

```yaml
# Uptime must be > 99.9%
name: service_uptime_pct
detectors:
  - type: manual_bounds
    params:
      lower_bound: 99.9
```

### 5. Physical Constraints

```yaml
# Temperature sensor range: 0-100°C
name: sensor_temperature
detectors:
  - type: manual_bounds
    params:
      lower_bound: 0.0
      upper_bound: 100.0
```

## Best Practices

### 1. Use for Well-Defined Limits

✅ Good:
```yaml
# Clear business rule
upper_bound: 100  # Max 100 concurrent users
```

❌ Avoid:
```yaml
# Arbitrary threshold without justification
upper_bound: 42.7  # Why 42.7?
```

### 2. Combine with Statistical Detectors

Use Manual Bounds for hard limits + statistical detector for unusual patterns:

```yaml
detectors:
  # Hard limit: CPU should never exceed 95%
  - type: manual_bounds
    params:
      upper_bound: 95.0

  # Soft limit: detect unusual CPU patterns
  - type: mad
    params:
      threshold: 3.0
      window_size: 288
```

### 3. Document Rationale

Add comments explaining why bounds were chosen:

```yaml
detectors:
  - type: manual_bounds
    params:
      upper_bound: 1000  # SLA requirement: P95 < 1000ms
```

### 4. Review Periodically

- System capacity changes → update bounds
- Business requirements change → update bounds
- False positive/negative rate too high → reconsider bounds

### 5. Start Simple

When starting monitoring:
1. Use Manual Bounds for known hard limits
2. Use MAD/Z-Score to discover natural patterns
3. Convert learned patterns to Manual Bounds if stable

## References

- [Threshold-based Anomaly Detection](https://en.wikipedia.org/wiki/Anomaly_detection#Threshold-based)

## See Also

- [MAD Detector](mad.md) - For adaptive, data-driven detection
- [Z-Score Detector](zscore.md) - For normally distributed data
- [IQR Detector](iqr.md) - For skewed distributions
- [Detectors Guide](../../guides/detectors.md) - Choosing the right detector
- [Configuration Guide](../../guides/configuration.md) - Complete config reference

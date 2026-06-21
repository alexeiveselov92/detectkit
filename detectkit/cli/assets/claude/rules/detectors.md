# detectkit — Detectors

A metric's `detectors:` is a list; each entry runs independently and writes its
own detection rows. A detector flags points whose value falls outside an
expected confidence interval it computes from history.

```yaml
detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 288
```

## Choosing a detector

| Detector | Use when | Robust to outliers | Seasonality |
|---|---|---|---|
| `manual_bounds` | You know the acceptable bounds (SLA, hard limit) | n/a | no |
| `mad` | General-purpose default; outliers / non-normal data | yes | yes |
| `zscore` | Clean, normally distributed data | no | yes |
| `iqr` | Skewed distributions, percentile metrics (p95/p99) | yes | yes |

Quick decision: known bounds → `manual_bounds`; seasonal → `mad` with
`seasonality_components`; normal & clean → `zscore`; skewed/heavy-tailed →
`mad` or `iqr`; unsure → `mad`.

You can combine detectors — e.g. a `manual_bounds` hard cap plus a `mad`
pattern detector. The alerting `min_detectors` quorum then decides how many
must agree (see `alerting.md`).

## `manual_bounds`

Fixed thresholds, no window, instant (no warm-up). Supports `input_type` only.

```yaml
- type: manual_bounds
  params:
    upper_bound: 90.0     # alert when value > 90
    lower_bound: 0.8      # alert when value < 0.8  (use either or both)
```

## Windowed detectors (`mad`, `zscore`, `iqr`)

These three **share one implementation** and accept an identical parameter set.
Each computes statistics over a trailing window (current point excluded) and an
expected interval for the current point.

```yaml
- type: mad                  # same params for zscore / iqr
  params:
    # --- core (all participate in the detector_id hash) ---
    threshold: 3.0           # defaults: mad 3.0, zscore 3.0, iqr 1.5
    window_size: 100         # trailing window in points
    min_samples: 30          # min valid points in window before detection runs
    seasonality_components: null   # e.g. ["hour"] or [["hour","day_of_week"]]
    min_samples_per_group: 10      # defaults: mad 10, zscore 3, iqr 4
    input_type: values       # values | changes | absolute_changes | log_changes
    smoothing: null          # null | ema | sma
    smoothing_alpha: 0.3     # EMA factor, 0 < a <= 1
    smoothing_window: 10     # SMA window in points
    window_weights: null     # null (uniform) | exponential | linear
    half_life: null          # exponential half-life: int points or "3d"/"12h"
    detrend: null            # null | linear
    # --- execution (NOT hashed) ---
    start_time: "2024-01-01 00:00:00"   # when detection begins
    batch_size: 500
```

**Threshold semantics:**
- `mad` is scaled by the normal-consistency constant 1.4826, so `threshold` is
  in **σ-equivalents** — `3.0` ≈ 3-sigma, just like `zscore`. Lower = more
  sensitive.
- `zscore`: `threshold` = number of standard deviations (3.0 ≈ 99.7%).
- `iqr`: `threshold` = Tukey fence multiplier (1.5 = standard outliers, 3.0 =
  extreme only).

**Window sizing:** for non-seasonal metrics 100–500 points; for seasonal
metrics size the window to contain several full cycles (10-min data: 4320–8640
≈ 30–60 days; hourly: 672–2016 ≈ 1–3 weeks; daily: 60–90). `min_samples` ≈
10–30% of `window_size`.

## Seasonality grouping

Statistics are computed within seasonality buckets so peak vs off-peak get
different expected ranges. Component names must match the metric's seasonality
feature names (built-in `seasonality_columns` or query-provided — see
`metrics.md`).

```yaml
seasonality_components:
  - "hour"                   # 24 separate per-hour adjustments
  # - ["hour", "day_of_week"]  # one combined group per hour+day (168 groups)
```

- `["hour"]` — single component (24 groups).
- `["hour", "day_of_week"]` — two *separate* adjustments.
- `[["hour", "day_of_week"]]` — one *combined* group per pair.

`min_samples_per_group` is the floor of points required per bucket.

## Preprocessing — `input_type`

Detect on transformed values (applied after smoothing):

- `values` (default) — raw values; absolute thresholds meaningful (CPU%, latency).
- `absolute_changes` — `v[t] - v[t-1]`; sudden jumps/drops matter.
- `changes` — `(v[t] - v[t-1]) / v[t-1]`; relative moves (traffic, revenue).
- `log_changes` — `log1p(v[t]) - log1p(v[t-1])`; near-symmetric for big % moves,
  tolerates zeros (values must be > −1).

The first point has no predecessor → NaN; the detect context pulls one extra
point to compensate.

## Smoothing

Reduce noise before detection: `smoothing: sma` (`smoothing_window`) or
`smoothing: ema` (`smoothing_alpha`, higher = less smoothing). Trade-off: less
noise but reduced sensitivity to short spikes.

## Trending metrics (avoid alert spam)

A gradual trend drifts a uniform window's interval behind the current level, so
every point starts to look "below" → false alerts. Two shared params fix this:

- `window_weights: exponential` + `half_life: "3d"` — recent points weigh more,
  so the interval follows the new normal. `half_life` is the age at which a
  point's weight halves (int = points; `"3d"`/`"12h"` converted via the grid
  step; default `max(window_size/20, min_samples/2)`). `linear` weighting is
  also available.
- `detrend: linear` — removes a robust in-window linear trend before computing
  statistics; gradual drift no longer pulls the metric out of its interval,
  while sharp deviations are still caught.

**Recommended recipe for trending, seasonal metrics:**
```yaml
seasonality_columns: [hour]
detectors:
  - type: mad
    params:
      window_size: 8640
      min_samples: 1000
      seasonality_components: ["hour"]
      window_weights: exponential
      half_life: "3d"
      detrend: linear          # optional, on top of weighting
```
Trade-off: a shorter `half_life` adapts faster but also "accepts" a real
sustained degradation as the new normal sooner. (`weight_decay` is a deprecated
alias for `half_life`; prefer `half_life`.)

## Feature compatibility

| Feature | mad | zscore | iqr | manual_bounds |
|---|---|---|---|---|
| `input_type` | Yes | Yes | Yes | Yes |
| `smoothing` | Yes | Yes | Yes | No |
| `window_weights` / `half_life` | Yes | Yes | Yes | No |
| `detrend` | Yes | Yes | Yes | No |
| `seasonality_components` | Yes | Yes | Yes | No |

`manual_bounds` has no window, so window-based features don't apply.

## Detector identity & recomputation

Every parameter that affects results (threshold, window_size, min_samples,
seasonality_components, min_samples_per_group, input_type, smoothing*,
window_weights, half_life, detrend) is hashed into the `detector_id` — only
non-default values participate. Execution params (`start_time`, `batch_size`)
are **not** hashed.

Changing any hashed parameter creates a new `detector_id` and recomputes that
detector's detections from scratch on the next run; old rows stay under the
previous id. To recompute over history immediately:
`dtk run --select <m> --steps detect --full-refresh`. To prune the orphaned old
rows: `dtk clean --select <m> --execute`.

Parameters are validated when the detector is constructed at the start of the
`detect` step (per run, not at YAML load) — a typo like `input_type: "diff"`
fails fast with a clear error.

## Tuning

- Too many false positives → raise `threshold`, add seasonality, add
  `window_weights`/`detrend` for trends, or raise `consecutive_anomalies` in
  alerting.
- Missing real anomalies → lower `threshold`, lower `window_size`, lower
  `consecutive_anomalies`/`min_detectors`.
- All "insufficient_data" → lower `min_samples` or backfill more history.

Detection metadata records what the detector saw (`global_median`,
`adjusted_median`, `ess` = Kish effective sample size when weighting,
`trend_slope_per_point` when detrending, and a `preprocessing` block) — useful
for debugging.

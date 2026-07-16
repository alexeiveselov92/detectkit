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
| `autoreg` | Fast-moving, non-seasonal metrics; catches "unusual dynamics" (a jump/reversal), not just an unusual level | via stabilization (default on) | no (v1) |

Quick decision: known bounds → `manual_bounds`; seasonal → `mad` with
`seasonality_components`; normal & clean → `zscore`; skewed/heavy-tailed →
`mad` or `iqr`; fast-moving/non-seasonal, care about dynamics breaks →
`autoreg`; unsure → `mad`.

To choose and tune the detector automatically from the data (and labeled
incidents), use `dtk autotune` — it runs this same decision tree per seasonality
group plus a hyperparameter search. See `autotune.md`.

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

## `autoreg`

A **dynamics** detector, not windowed like mad/zscore/iqr: it fits an AR(`lags`)
model (intercept + one coefficient per lag, OLS) over the trailing
`window_size` window and flags a point when it falls outside `threshold`
residual-sigma of the model's own one-step-ahead prediction — a prediction-based
band, not a level statistic. Catches "right level, wrong dynamics": a value
that sits inside the metric's normal historical range but breaks its usual
short-range trajectory (a jump, a reversal) — a level detector can miss this
if the jump lands inside the historical value range.

```yaml
- type: autoreg
  params:
    lags: 5                # AR order — predictors = last N values (default 5)
    window_size: 200        # trailing history refit at each point (default 200)
    threshold: 3.0           # residual-sigma band half-width (default 3.0)
    min_samples: 30          # min valid fit rows required (default 30); >= lags + 2
    input_type: values        # values | changes | absolute_changes | log_changes
    stabilization: clamp      # clamp (DEFAULT — unlike windowed detectors' null) | null
```

**v1 limits** (deliberate): `seasonality_components` is rejected at
construction (`ValueError`) — a lag model already captures local dynamics and
a per-group multiplier doesn't compose with AR coefficients; no smoothing, no
recency weighting, no detrending — the AR residual model already adapts to
the local level/dynamics on its own. **Strict NaN policy**: a gap inside the
lag window or at the fit target drops that row entirely rather than being
imputed (`missing_lags` for the scored point itself). `window_size` and
`min_samples` must both be >= `lags + 2`.

**`stabilization: clamp` defaults ON** here (unlike the windowed detectors,
where it defaults to `None`) — once a point is flagged, later fit windows see
it clamped to the confidence bound it violated (never the raw value or the
model's prediction), so a sustained incident can't collapse the residual
scale into false-flag cascades.

**When to use it**: fast-moving, non-seasonal metrics (queue depth, request
rate, in-flight count) where the *trajectory* matters more than a static
band, or paired with a level detector (`mad`/`zscore`/`iqr`) via
`min_detectors` to catch both "unusual level" and "unusual dynamics" in one
alert rule. Not a drop-in replacement — a metric with seasonal patterns still
wants a windowed detector.

**Autotune-eligible** via its own axis set — `autotune.detector_types` may
include `autoreg`, and the grid search sweeps threshold / `lags` /
stabilization / window size for it (no weighting, detrend or seasonality; a
mildly conservative suitability vote favors it on clean/normal data, but all
four types are still grid-searched). It's also **tunable in the `dtk tune`
cockpit**: picking Autoreg swaps in a **Lags** knob and hides the
windowed-only controls. (v0.53.0, `ALGORITHM_VERSION` 2: each fit window is
centered/scaled before the normal equations, and the clamp substitution above
is capped to the observed window range — detector ids change and detections
recompute on the next run.)

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
    stabilization: null      # null (off) | clamp
    # --- execution (NOT hashed) ---
    start_time: "2024-01-01 00:00:00"   # optional; when detection begins (default: loading_start_time)
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

`min_samples_per_group` is the floor of points required per bucket. **Size the
window to fill a bucket:** a group engages only when the window holds
`min_samples_per_group` points of the current key, and same-key points recur once
per *cardinality*, so `window_size ≳ min_samples_per_group × distinct_keys`. With
hourly `["hour"]` (24 keys, mad default 10) that's `≳ 240` — the default
`window_size = 100` fills no bucket, so seasonality silently falls back to the
global band (the detector logs a one-time warning). Raise `window_size`, lower
`min_samples_per_group`, or use a coarser grouping. `dtk autotune` now offers a
fill-sized window candidate automatically.

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

## Stabilization — sustained incidents poisoning their own baseline

A sustained incident's anomalous points enter the trailing window and inflate
the spread / drag the center toward it, so the band widens mid-incident and the
detector stops flagging the tail ("the incident becomes the new normal") —
z-score (mean/std) is the most vulnerable; median/quartile-based mad/iqr resist
short incidents but still bend under a long one. `stabilization: clamp` fixes
this: once a point is flagged anomalous, subsequent trailing windows see it
**clamped to the confidence bound it violated** (winsorized) instead of the
raw value — only the statistics windows read the substituted history; scored
and persisted values are unchanged, and anomalies still render as anomalies.
Reach for it when alerting on metrics with occasional sustained incidents; it
composes with `window_weights`/`half_life` (where it matters most, since
recency weighting gives an ongoing incident's points more weight), `detrend`,
`smoothing`, `input_type` and seasonality groups, and is near-neutral on clean
series. Enabling it is a hashed change — it produces a new `detector_id` and
recomputes on the next run; existing configs that don't set it keep their ids.
It also adds one extra `window_size` of warm-up *context* (`mad`/`zscore`/`iqr`
and `autoreg` alike) — this is how much trailing history the pipeline loads, not
where a band appears: the `dtk tune` cockpit draws the band wherever the detector
actually scores (as the pipeline persists it), only lightly dimming the cold-start
lead-in, so `clamp` no longer blanks the cockpit chart on a short view.

## Feature compatibility

| Feature | mad | zscore | iqr | manual_bounds | autoreg |
|---|---|---|---|---|---|
| `input_type` | Yes | Yes | Yes | Yes | Yes |
| `smoothing` | Yes | Yes | Yes | No | No (v1) |
| `window_weights` / `half_life` | Yes | Yes | Yes | No | No (v1) |
| `detrend` | Yes | Yes | Yes | No | No (v1) |
| `stabilization` | Yes | Yes | Yes | No | Yes (default `clamp`) |
| `seasonality_components` | Yes | Yes | Yes | No | No — rejected (v1) |

`manual_bounds` has no window, so window-based features don't apply.
`autoreg` fits its own lag-based (AR) model instead, so those features are
unsupported in v1 rather than N/A.

## Detector identity & recomputation

Every parameter that affects results (threshold, window_size, min_samples,
seasonality_components, min_samples_per_group, input_type, smoothing*,
window_weights, half_life, detrend, stabilization) is hashed into the
`detector_id` — only non-default values participate. Execution params
(`start_time`, `batch_size`) are **not** hashed.

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

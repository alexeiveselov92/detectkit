# Tuning a Detector by Hand

`dtk tune` lets you tune a metric's detector **interactively, on its real data**,
and then write the config you settled on back into the metric — safely. It is the
manual, human-in-the-loop sibling of [`dtk autotune`](autotuning.md): instead of
searching automatically, you turn the detector's knobs and watch the confidence
band, flagged anomalies and would-fire alerts recompute live in the browser, then
click **Apply** to commit.

It reads the metric's already-loaded `_dtk_datapoints` and recomputes everything
client-side — the same faithful detector port that powers the landing playground,
fed your real series instead of synthetic data. No data leaves the machine.

## `dtk tune` vs `dtk autotune`

Two complementary ways to optimize a metric:

| | `dtk autotune` | `dtk tune` |
|---|---|---|
| Who chooses | the engine (cross-validated search) | **you**, by eye, on the real series |
| Feedback | a decision log after the fact | the band **recomputes live** as you drag a slider |
| Output | a **new** `metrics/<name>__tuned_<id>.yml` (original untouched) | the metric YAML, edited **in place** (previous version archived) |
| Best when | you have labels or want a strong starting point | you know the metric and want to dial it in by feel |

A natural workflow is to use both: let `dtk autotune` propose a config, then
`dtk tune` to refine it by eye and commit.

## Prerequisites

Tuning reads the metric's persisted datapoints, so load some history first:

```bash
dtk run --select api_error_rate --steps load --from "2026-01-01"
```

## Tune interactively

```bash
dtk tune --select api_error_rate
```

This starts a local `127.0.0.1` server and opens your browser. The selector must
resolve to a **single** metric. Restrict the window shown with `--from` / `--to`:

```bash
dtk tune --select api_error_rate --from 2026-05-01 --to 2026-06-01
```

In the browser you can adjust:

- **Detector** — MAD, Z-Score or IQR.
- **Threshold** — interval width in σ-equivalent units.
- **Window size** — the trailing window each point is compared against.
- **Recency weighting** + **half-life** — none / exponential / linear, with the
  half-life (in points) when exponential.
- **Detrend** — none / linear (robust split-median slope).
- **Smoothing** — none / EMA / SMA.
- **Seasonality conditioning** — toggle each seasonality column the metric has;
  optionally conjoin the selected columns into one group.
- **Alert: consecutive anomalies** — the alert window (`consecutive_anomalies`).

The confidence band, the flagged points and the would-fire alert markers update
on every change, and the "effective config" readout shows exactly what will be
written.

## Apply the config back

Click **Apply to metric**. detectkit then, in order:

1. **Validates** the chosen detector through the same `DetectorFactory` and
   `MetricConfig` the pipeline uses — a broken or untunable config is rejected and
   **nothing is written** (fix the knobs and click Apply again).
2. **Archives** the current metric YAML verbatim (comments and all) to
   `metrics/.history/<metric>/<metric>-<timestamp>.yml`, so you keep a trackable
   history of chosen parameters and can always recover the previous version.
3. **Re-emits** the metric file in place with the tuned detector — the `detectors`
   list becomes the single tuned detector, and the first `alerting` block's
   `consecutive_anomalies` is updated if the metric has one.

`dtk tune` takes **no pipeline lock** — it only edits a config file. The live
preview is a faithful approximation; the **next `dtk run` is the source of truth**.
Because the detector parameters changed, the detector's identity changes too, so
detections recompute under the new configuration on the next run:

```bash
dtk run --select api_error_rate
```

## Preview without writing (`--no-serve`)

To share or inspect the interactive view without any write-back, write a static
HTML file instead of serving:

```bash
dtk tune --select api_error_rate --no-serve
```

This writes `metrics/<metric>__tuner.html`. The sliders still recompute the band
live, but there is no **Apply** button — the file is read-only.

## See also

- [Auto-tuning a Detector](autotuning.md) — the automatic search.
- [Visualizing Results](visualizing-results.md) — the read-only HTML report and
  BI recipes.
- [Detectors](detectors.md) — what each parameter does.

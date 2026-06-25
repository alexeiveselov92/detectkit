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

- **Detector** — MAD, Z-Score, IQR (all windowed statistical) or **Manual**
  (fixed bounds; see below). Switching to Manual swaps the windowed knobs for the
  bound sliders.
- **Threshold** — interval width in σ-equivalent units.
- **Window size** — the trailing window each point is compared against. The
  readout shows the equivalent **wall-clock span** on the metric grid next to the
  point count (e.g. `2000 · 83d 8h`), so "how much history is this window" reads
  at a glance.
- **Recency weighting** + **half-life** — none / exponential / linear, with the
  half-life (in points) when exponential. Half-life also echoes its wall-clock
  span next to the point count.
- **Detrend** — none / linear (robust split-median slope).
- **Smoothing** — none / EMA / SMA.
- **Lower bound** / **Upper bound** *(Manual detector only)* — the fixed
  thresholds a value is compared against. They are seeded from the metric's bounds
  (or the data's p5/p95 band when switching from a windowed detector) and ranged
  over the real value domain, so you can drag them in and watch how many points
  fall outside (and how many alerts that yields). **Apply** writes a stateless
  [`manual_bounds`](../reference/detectors/manual_bounds.md) detector.
- **Seasonality groups** — assign each seasonality column the metric has to a
  group (Off, G1, G2, …). Columns in the **same** group are conjoined into one
  seasonal key (e.g. `dow`×`hour`); **separate** groups each apply their own
  correction. This is the full `seasonality_components` grouping — you can mix one
  conjunctive group with other standalone columns, not just "all-separate" or
  "all-in-one".
- **Direction** — **both / up / down**: which anomalies are shown and counted
  toward alerts. Pick *up* to focus on spikes above the band, *down* for drops
  below it. It is a preview filter mirroring the alert `direction` policy (seeded
  from the metric's alerting, with the multi-detector `same` reading as `any`) —
  it never changes the band itself.
- **Alert: consecutive anomalies** — the alert window (`consecutive_anomalies`).

Every control carries an **ⓘ tooltip** explaining what it does. The confidence
band, the flagged points and the would-fire alert markers update on every change
(a small **computing…** spinner shows while a recompute is in flight), a **legend**
labels the series / band / center / anomalies / alerts, and the "effective config"
readout shows exactly what will be written.

### Navigate a dense series

The chart is **zoomable** — scroll to zoom where you point, **drag to pan**,
double-click to reset, and drag the **navigator strip** below the chart to move
the view (the strip shows the whole series, the alert firings as red ticks, and a
time axis). Zooming in lets you inspect alert quality region-by-region on a long,
busy metric.

A **Points shown** slider above the chart **trims the active sample** to the most
recent N points. Recompute cost grows with *points × window*, so once you can see
a shorter period is enough, trimming it makes every knob-drag noticeably faster
(and the period easier to read). Trimming only affects the live view — it never
changes what **Apply** writes.

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

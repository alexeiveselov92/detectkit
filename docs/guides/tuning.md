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

A **y = 0 line** toggle draws a horizontal reference line at zero and folds zero
into the vertical scale, so a real-valued metric (one best read *relative to zero*)
shows where it sits against zero. It is also available
on the [HTML report](visualizing-results.md). Off by default.

## One chart, three modes

`dtk tune` is a **chart-first cockpit**: a single chart fills the screen (the
windshield), the live **metrics ride pinned over the chart** (your speedometer —
always in view), and every control lives in an **always-visible side rail** beside
the chart — so the first thing you do is turn a knob and watch the band, with no
scrolling. The rail is **mode-aware**: it shows only the controls the current mode
needs (the detector knobs + Apply in Tune, the verdict actions in Review, the
capture tools + Save in Label), and collapses to give the chart the whole width. A
**mode switch** above the chart picks the job; the layers that don't matter to it
dim to context instead of competing for pixels:

- **Tune** — steer the band. The confidence corridor leads, marked incidents recede
  to read-only context, and hovering a point shows the trailing window that scored
  it.
- **Review** — confirm the fired alerts (see below). The band ghosts so the alert
  markers lead.
- **Label** — mark the real incidents. The band hides so incidents lead, and the
  capture tools (Lasso / Threshold) are armed.

## Confirm the alerts (Review mode)

Often a config is already good — the alerts that would fire all look real. Rather
than hand-draw an incident for each, switch to **Review** and **click an alert
marker** to cycle its verdict:

- **red** → not yet reviewed
- **green** → **valid** (you confirmed it's a real alert)
- **slate** → **false alarm**

A confirmed (valid) alert is you asserting *a real incident happened here*, so it
counts toward recall and as a correct alert — a clean metric can be validated in a
few clicks **without drawing any spans**. **Confirm all unreviewed valid** does the
lot. Confirmed alerts are also **written as incidents on Save**, so they feed the
next supervised [`dtk autotune`](autotuning.md) too; the verdicts themselves persist
as `alert_reviews` metadata and re-seed (re-bound to the moved alerts by streak
overlap) when you reopen.

## Mark incidents (Label mode)

To mark ground truth directly, switch to **Label**:

- **Drag** across the chart to mark an incident span; **drag its edges** to adjust,
  **drag its middle** to move, and click its **✕** (or select it and press
  **Delete**) to remove it.
- **Lasso anomalies** — the fastest way to turn what the detector flags into ground
  truth: click **Lasso anomalies**, then **draw a freeform loop** around a cloud of
  anomaly dots. Each **run of consecutive anomalies** (small gaps — up to your
  `consecutive_anomalies` setting — are bridged) becomes **one proper incident
  span** sized to the run, not a single point; a separate burst inside the loop
  becomes its own incident.
- **Threshold capture** — grab every contiguous span past a horizontal line in one
  shot (the same tool as the [autotune labeler](autotuning.md)): click to set the
  line (or type a value), choose **above**/**below**, optionally **bridge gaps**, and
  drag across the chart to limit the capture to a time window. **Add N spans** marks
  them all. Each captured span is widened to a full interval, so a single matching
  point becomes a real incident the alert lands inside; the painted window is saved
  as `capture_windows` and restored on reopen.

Already-saved incidents are seeded from the newest file in `incidents/<metric>/`
when `dtk tune` opens, and the (budget-sized) loaded window is **anchored on your
incidents** — it ends just past the latest one rather than at the last datapoint —
so they render and count without loading the whole history. Incidents older than the
loaded window stay in the list but aren't scored; pass `--from`/`--to` to tune
against a specific older window.

## Read the alert quality

As you tune, the **metrics bar** under the chart recomputes:

- **Incident catch rate (recall)** — what share of the ground-truth incidents
  (marked **+ confirmed-valid alerts**) your config catches. An incident counts as
  *caught* when an alert's whole **anomaly streak overlaps** it — not just the
  instant the alert fires (which lands a few intervals into the streak), so a streak
  that clearly covers an incident is scored as caught.
- **False-alert rate** — what share of fired alerts fall **outside** every incident
  and aren't confirmed valid, shown as a percentage and as "≈1 in N false". The
  complement is the share of alerts that are *correct*.
- **Reviewed N/M** — how many of the fired alerts you've looked at (and how many you
  confirmed valid).

This is the loop the cockpit was built for: pick a detector, see the flagged points
and the alerts they'd fire, confirm the good ones (or mark the real incidents), and
tune until you catch what you care about without drowning in false alerts.

Click **Save incidents** to persist the marked spans to
`incidents/<metric>/<metric>-<timestamp>.yml` — the **same versioned store
[`dtk autotune`](autotuning.md) reads**, so the labels you draw here also feed the
next supervised auto-tune (one source of truth). `dtk tune` seeds the labeler from
the newest file in that directory when it opens, so labeling round-trips across both
tools. Saving incidents does **not** end the session (only **Apply** does) — keep
adjusting and save again, or save labels and then tune the detector against them.

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
live and you can still mark incidents, but there is no **Apply** button — the file
is read-only, and **Save incidents** downloads the labels file (drop it into
`incidents/<metric>/` yourself) instead of writing it directly.

## See also

- [Auto-tuning a Detector](autotuning.md) — the automatic search.
- [Visualizing Results](visualizing-results.md) — the read-only HTML report and
  BI recipes.
- [Detectors](detectors.md) — what each parameter does.

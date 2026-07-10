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

A natural workflow is to use both — and you can do it **without leaving the
cockpit**: `dtk tune` has an **Autotune** mode that runs the autotune engine
server-side and re-seeds the knobs with the winner, which you then refine by eye and
**Apply**. See [Auto-tune in place](#auto-tune-in-place-autotune-mode) below.

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

- **Detector** — MAD, Z-Score, IQR (all windowed statistical), **Autoreg**
  (predicts each point from its previous values — see below), or **Manual**
  (fixed bounds; see below). Switching to Manual swaps the windowed knobs for the
  bound sliders; switching to Autoreg swaps the windowed-only knobs (recency
  weighting, detrend, smoothing, seasonality) for a single **Lags** (AR order)
  knob, keeping threshold, window size and stabilization.
- **Threshold** — interval width in σ-equivalent units.
- **Window size** — the trailing window each point is compared against. The
  readout shows the equivalent **wall-clock span** on the metric grid next to the
  point count (e.g. `2000 · 83d 8h`), so "how much history is this window" reads
  at a glance.
- **Recency weighting** + **half-life** — none / exponential / linear, with the
  half-life (in points) when exponential. Half-life also echoes its wall-clock
  span next to the point count.
- **Detrend** — none / linear (robust split-median slope).
- **Stabilization** — none / clamp. Once a point is flagged anomalous, `clamp`
  substitutes a winsorized value (clamped to the violated confidence bound) for
  it in later windows, so a sustained incident can't widen the band and become
  "the new normal" (see
  [Stabilization](../reference/detectors/shared-parameters.md#stabilization)).
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
- **Alert: anomaly window (points)** / **Alert: min share in window** — the
  fraction-alert pair (`anomaly_window` + `min_anomaly_share`), OR-ed with the
  consecutive rule; leaving the window below 2 points keeps the legacy
  consecutive-only behavior.

Every control carries an **ⓘ tooltip** explaining what it does. The confidence
band, the flagged points and the would-fire alert markers update when you
**release** a slider (the value echo tracks live while you drag, so mid-drag pauses
don't kick off a recompute); a small **computing…** spinner shows while a recompute
is in flight, and moving another knob **cancels** the in-flight one so the newest
config isn't left waiting behind a stale computation. A **legend** labels the
series / band / center / anomalies / alerts, and the "effective config" readout
shows exactly what will be written.

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

### Warm-up: why the band can start late (or not appear at all)

The chart hides the confidence band and anomaly dots over each detector's
warm-up lead-in — the trailing history it needs before it can score its first
point — so what you see matches what an incremental pipeline run would
actually compute; the pipeline and the [HTML report](visualizing-results.md)
always have a band for every point they score. Turning on **Stabilization**
roughly doubles that requirement (Autoreg needs close to two window-lengths of
history — the window size plus the lag order — at its default settings, over
400 points), so an aggressively trimmed **Points shown** can leave nothing left
to look at. When the shown window is *entirely* warm-up, the chart dims
completely with a centered "all shown points are detector warm-up — nothing to
score yet" message instead of a bare, bandless line, and an inline warning
beneath the chart states the exact point count still needed with three fixes:
raise **Points shown**, lower **Window size**, or turn **Stabilization** off.

A **y = 0 line** toggle draws a horizontal reference line at zero and folds zero
into the vertical scale, so a real-valued metric (one best read *relative to zero*)
shows where it sits against zero. It is also available
on the [HTML report](visualizing-results.md). Off by default.

## One chart, four modes

`dtk tune` is a **chart-first cockpit**: a single chart fills the screen (the
windshield), the live **metrics ride pinned over the chart** (your speedometer —
always in view), and every control lives in an **always-visible side rail** beside
the chart — so the first thing you do is turn a knob and watch the band, with no
scrolling. The rail is **mode-aware**: it shows only the controls the current mode
needs (the detector knobs + Apply in Tune, the verdict actions in Review, the
capture tools + Save in Label, the search button + result in Autotune), and
collapses to give the chart the whole width.
The controls that aren't detector-specific — the **Points shown** data window, the
alert rule (**direction** + **consecutive anomalies** + the
**anomaly-window/min-share** pair) and the **y = 0** toggle —
stay visible in every mode, since they shape the band, the alerts you review, and
the recall/FDR you watch while labeling. A
**mode switch** above the chart picks the job; the layers that don't matter to it
dim to context instead of competing for pixels:

- **Tune** — steer the band. The confidence corridor leads, marked incidents recede
  to read-only context, and hovering a point shows the trailing window that scored
  it.
- **Review** — confirm the fired alerts (see below). The band ghosts so the alert
  markers lead.
- **Label** — mark the real incidents. The band hides so incidents lead, and the
  capture tools (Lasso / Threshold) are armed.
- **Autotune** — let the [`dtk autotune`](autotuning.md) engine search for the best
  detector **server-side** and re-seed the knobs with the winner (see below). The
  chart leads with the band, like Tune, so you immediately see the recomputed
  corridor.

## Confirm the alerts (Review mode)

Often a config is already good — the alerts that would fire all look real. Rather
than hand-draw an incident for each, switch to **Review** and **click an alert
marker** to cycle its verdict:

- **red** → not yet reviewed
- **green** → **valid** (you confirmed it's a real alert)
- **slate** → **false alarm**

**Confirming an alert valid is just a fast way to mark an incident.** A valid alert
is you asserting *a real incident happened here*, so the confirmed streak becomes a
first-class incident: it shows up in the **Marked incidents** list (in Label mode) as
a read-only **"✓ confirmed alert"** row — focus it, or remove it to un-confirm the
alert — and it counts toward recall and as a correct alert. So a clean metric can be
validated in a few clicks **without drawing any spans**. **Confirm all unreviewed
valid** does the lot. Confirmed alerts are **written as incidents on Save**, so they
feed the next supervised [`dtk autotune`](autotuning.md) too; the verdicts themselves
also persist as `alert_reviews` metadata and re-seed (re-bound to the moved alerts by
streak overlap) when you reopen. A confirmed incident stays in the ground truth even
if you then tune the detector so it no longer fires there — which correctly shows up
as a **recall miss**, not a silent disappearance.

## Mark incidents (Label mode)

To mark ground truth directly, switch to **Label**:

- **Drag** across the chart to mark an incident span; **drag its edges** to adjust,
  **drag its middle** to move, and click its **✕** (or select it and press
  **Delete**) to remove it. Removing an incident this way also **un-confirms** any
  overlapping confirmed-valid alert, so it's fully gone — it won't pop back as a
  "✓ confirmed alert" row (the chart's ✕ and the list's ✕ behave the same).
- **Lasso anomalies** — the fastest way to turn what the detector flags into ground
  truth: click **Lasso anomalies**, then **draw a freeform loop** around a cloud of
  anomaly dots. Each **run of consecutive anomalies** (small gaps — up to your
  `consecutive_anomalies` setting — are bridged) becomes **one proper incident
  span** sized to the run, not a single point; a separate burst inside the loop
  becomes its own incident.
- **Threshold capture** — grab every contiguous span past a horizontal line in one
  shot: click to set the
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

## Auto-tune in place (Autotune mode)

You don't have to leave the cockpit to run [`dtk autotune`](autotuning.md). Switch
to **Autotune** and click **Run autotune**: the **same engine** (seasonality →
detector → grid → window search, cross-validated) runs **server-side** over the
**window you're looking at** — the **Points shown** trim, the same series the cockpit
displays and scores, not the full history — not a browser re-implementation — using
the incidents you've marked (and confirmed-valid alerts) as **ground truth**. When it
finishes it **re-seeds every knob** with the winning detector, recomputes the live
band, and shows the winner, the score, and the **decision log** in the rail. Review
the band, then **Apply** (in Autotune or Tune mode) to write it back.

- Trim **Points shown** to focus the search on a recent period — the engine tunes on
  exactly that window, so what you see is what's optimized.
- Watch the **terminal** you launched `dtk tune` from: each run streams a structured,
  blocked log (`LABELS → SEASONALITY → … → RESULT`, the same look as `dtk run` and
  `dtk autotune`) so you can follow what it's computing.
- With incidents marked, the search is **supervised** (it also sweeps the alert
  window — `consecutive_anomalies` first, then the 2-D `anomaly_window` ×
  `min_anomaly_share` pair OR-ed with it); with none, it falls back to the
  **unsupervised** objective. Mark a few incidents first for a sharper result —
  the Autotune panel tells you which mode it ran.
- It honours the metric's `autotune:` config block (`scoring_metric`, `folds`,
  `detector_types`, `force_seasonality`, …), exactly like the CLI.
- It is **advisory**: nothing is written until you **Apply**. Unlike `dtk autotune`,
  it does **not** persist a run record, emit a `__tuned_<id>.yml`, or write
  detections — so `dtk tune` stays lock-free. The re-seeded band is the TS
  approximation; the next `dtk run` recomputes detections under the applied config
  and is the source of truth.
- Autotune needs the live server, so it is unavailable under `--no-serve`. If the
  metric has `autotune: { enabled: false }`, the button reports that and does nothing.

This closes the loop in one place: **Label** the incidents, **Autotune** to a strong
config, then **Tune** by eye and **Apply**.

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

The marked incidents and the confirmed-valid alerts are **one** ground-truth set, so
it never matters whether you draw a span or confirm an alert — both feed recall and
the false-alert rate, and both are saved.

### A false-alert budget (optional)

You can give a metric a **target false-alert rate** so the cockpit tells you when
you've drifted past it:

```yaml
# metrics/<name>.yml
false_alert_budget: 0.3   # at most 30% of fired alerts should be false
```

or project-wide as a default (a per-metric value wins):

```yaml
# detectkit_project.yml
false_alert_budget: 0.3
```

When the false-alert rate exceeds the budget, the **false alerts** chip flags it
(`▲ over 30% budget`) — gently, never blocking anything. Unset, a lax built-in
default of `0.5` is used. This is purely a tuning aid: it only colours a number you
can already see, it never affects the load/detect/alert pipeline, and labeling stays
entirely optional — mark a short window when you want to put a number on your error,
or ignore it and just work with the alerts.

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

1. **Validates** the chosen detector and the whole metric config with the same validation the pipeline uses — a broken or untunable config is rejected and
   **nothing is written** (fix the knobs and click Apply again).
2. **Archives** the current metric YAML verbatim (comments and all) to
   `metrics/.history/<metric>/<metric>-<timestamp>.yml`, so you keep a trackable
   history of chosen parameters and can always recover the previous version.
   (These archives are **not** loaded as live metrics, so a tuned metric never
   trips a "duplicate metric name" error against its own snapshots.)
3. **Re-emits** the metric file in place, **merging** the tuned detector(s) back
   in — only the detector(s) you tuned are rewritten; every **other** detector is
   kept **verbatim**, and the first `alerting` block's `consecutive_anomalies`
   and `anomaly_window`/`min_anomaly_share` pair are updated if the metric has
   one (the pair is removed together when turned off — never a half-pair). The
   re-emitted header names what was updated vs preserved.

**Metrics with more than one detector.** If a metric configures several detectors
— e.g. a `mad` pattern detector **plus** a
[`manual_bounds`](../reference/detectors/manual_bounds.md) hard floor with a
`min_detectors: 2` alert — the cockpit shows a **Tuning detector** picker in the
Tune rail. Pick which detector to tune (the chart shows one band at a time);
switching re-seeds every knob from that detector. On **Apply**, the detectors you
tuned are rewritten and the rest are **preserved unchanged**, so the quorum keeps
firing — a tune never silently drops your other detectors. Non-tunable detectors
(`prophet`/`timesfm`) are listed as preserved.

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
- [Project UI](project-ui.md) — the cockpit that launches this session and can
  also create/edit/delete metric YAML files directly.

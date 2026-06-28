---
name: dtk-tune
description: >-
  Interactively tune a detectkit metric's detector in the browser cockpit: stand
  up a sandbox config, open `dtk tune`, and guide the user to turn the detector's
  knobs on their real series and watch the confidence band recompute live —
  **with the autotune engine built in** (an Autotune mode that searches
  server-side and re-seeds the knobs), plus Label/Review to mark or confirm
  incidents — then write the chosen config back into the metric YAML. Use when
  the user wants to tune a detector by hand / interactively / in the browser, see
  and adjust the band or alerts live, set up a tuning sandbox to "turn the knobs"
  themselves, reduce false alerts hands-on, or visually mark/confirm incidents.
  This is the primary, hands-on entry point for dialing in a metric; it contains
  autotune, so prefer it whenever the user wants to be in the loop.
---

# Tune a detectkit metric interactively (the cockpit)

`dtk tune` opens a localhost **browser cockpit** over a metric's **real**
persisted series. The user turns the detector's knobs and the confidence band,
flagged anomalies and would-fire alerts **recompute live** — no DB round-trip,
nothing leaves the machine — then clicks **Apply** to write the chosen config
**back into the metric YAML in place** (safely: validated, with the previous
version archived first).

It is the **hands-on umbrella** for tuning. The cockpit has four modes and one of
them runs the **real `dtk autotune` engine server-side** and re-seeds every knob
with the winner — so the user can auto-search *and* hand-tune *and* label
incidents without leaving the page. **Prefer this skill whenever the user wants
to be in the loop** (see, judge, adjust). Use the **`dtk-autotune`** skill
instead only for a fully hands-off, command-line search (e.g. CI, "just pick one
for me, I won't look").

Your job is to **set up the sandbox, open it, and guide the user through it** —
they drive the chart; you prepare it, explain each control in plain language, and
handle the follow-up (`dtk run` / `dtk clean`). This skill is the procedure; for
field detail read the matching file under `.claude/rules/detectkit/` (`cli.md`
has the full `dtk tune` reference, plus `detectors.md`, `autotune.md`,
`alerting.md`).

## Step 0 — A metric with loaded data (the sandbox)

The cockpit charts a metric's **already-loaded** `_dtk_datapoints`, so you need a
metric that exists and has some history loaded.

- **A project root** contains `detectkit_project.yml`. If `profiles.yml` is still
  the `dtk init` placeholder, set up the DB first with **`dtk-setup-project`**.
- **No metric yet?** This is the "stand up a sandbox to turn the knobs" path: hand
  off to **`dtk-new-metric`** to design the query + a robust **starter** detector
  (e.g. `mad`, `threshold: 3.0`) — that starter is exactly the sandbox the user
  will refine here. Keep query design in that skill; never fabricate SQL here.
- **Load some history** (the more, the better the picture):

  ```bash
  dtk run --select <name> --steps load                 # incremental
  dtk run --select <name> --steps load --from 2026-01-01   # backfill more history
  ```

  If the chart later looks empty or too short, load more with `--from`.

## Step 1 — Open the cockpit

```bash
dtk tune --select <name>
```

The selector must resolve to a **single** metric. This starts a `127.0.0.1`
server and opens the browser. Useful flags:

- **Remote / headless machine** — add `--no-open` and share the printed URL (the
  server is localhost-only; the user opens it via a tunnel/port-forward).
- **Focus a window** — `--from <date>` / `--to <date>` bound what's loaded.
- **No write-back / share a snapshot** — `--no-serve` writes a static read-only
  HTML preview instead: the sliders still recompute, but there is **no Apply**
  (and **no Autotune** — that needs the live server); **Save incidents**
  downloads the labels file instead of writing it.

Tell the user plainly: *"I've opened an interactive chart of your metric — turn
the knobs and watch the band; tell me what you see and I'll help you decide."*

## Step 2 — Orient the user to the cockpit

One chart fills the screen (the **windshield**); the live quality metrics ride
**pinned over it**; every control lives in an **always-visible side rail** that is
**mode-aware** (it shows only the current mode's controls). A **mode switch** above
the chart picks the job. Navigate a dense series by **scrolling to zoom**,
**dragging to pan**, double-clicking to reset, and dragging the **navigator
strip** below the chart. The **Points shown** slider trims to the most-recent N
points so recompute (and the read) is faster — view-only, never written.

These controls stay visible in **every** mode (they shape the band and the
alerts): **Points shown**, the alert rule (**direction** + **consecutive
anomalies**), and the **y = 0** reference-line toggle.

## Step 3 — The four modes (autotune is one of them)

Walk the user to the mode that fits what they want to do:

- **Tune** — *turn the knobs.* The band leads. Adjust **detector type** (MAD /
  Z-Score / IQR, or **Manual** = fixed lower/upper bounds), **threshold**,
  **window size**, **recency weighting + half-life**, **detrend**, **smoothing**,
  and **seasonality groups**; the band + anomalies + would-fire alerts recompute
  on every change. The window-size / half-life readouts show the equivalent
  wall-clock span. This is the core "turn the knobs yourself" loop.

- **Autotune** — *let the engine search, then refine.* Click **Run autotune** and
  the **same engine `dtk autotune` uses** (seasonality → detector → grid → window,
  cross-validated) runs **server-side over the window currently shown** (the
  **Points shown** trim — the exact series on screen, not the full history), using
  any marked/confirmed incidents as ground truth. It then **re-seeds every knob**
  with the winner and shows the score + decision log. It's **advisory** — it
  computes and re-seeds only, persists nothing (no run record, no `__tuned_<id>`
  file, no detections), so the session stays lock-free; the user reviews the band
  and **Applies**. Each run also streams a structured `LABELS → … → RESULT` log to
  the terminal you launched from. (This is why `dtk tune` is the umbrella: the user
  gets autotune **and** hand-tuning in one place.)

- **Label** — *mark the real incidents* (ground truth that sharpens both the live
  quality metrics and a supervised Autotune). **Drag a span** over each incident;
  or **Lasso anomalies** (loop a cloud of anomaly dots into one span per run); or
  **Threshold capture** (grab every span past a horizontal line). **Save
  incidents** writes a versioned `incidents/<metric>/*.yml` — the same store
  `dtk autotune` reads.

- **Review** — *confirm the fired alerts.* When a config already looks good, click
  each alert marker to cycle its verdict un-reviewed → **valid** (green) → **false
  alarm** (slate). **Confirming an alert valid marks it as a ground-truth
  incident**, and **Confirm all unreviewed valid** does the lot — so a clean
  metric is validated in a few clicks **without hand-drawing spans**.

**Suggesting a path.** If the user *can recognise* their incidents on the chart,
start in **Label** (or **Review** to confirm good alerts) to give the engine
ground truth, then **Autotune** for a strong config, then **Tune** by eye, then
**Apply**. If they just want a quick strong default, go straight to **Autotune**
(unsupervised) and refine. If they want full manual control, stay in **Tune**.

## Step 4 — Read the live quality, then Apply

As they tune, the metrics bar shows **incident catch rate (recall)**,
**false-alert rate** ("≈1 in N false"), and **reviewed N/M** — recomputed against
the marked + confirmed incidents (only those inside the loaded window are scored).
An optional **false-alert budget** (`false_alert_budget`, a fraction in `(0, 1]`,
on the metric then project, default `0.5`) gently flags the chip when the
false-alert rate exceeds it (tuning-only; labeling stays optional).

When the user is happy, they click **Apply to metric**. detectkit then, in order:
**validates** the config (a bad/untunable config is rejected and **nothing is
written**), **archives** the current YAML verbatim under
`metrics/.history/<metric>/`, and **re-emits** the metric in place with the tuned
detector (and updates the first alerting block's `consecutive_anomalies` if it has
one). Applying ends the session; saving incidents does not.

## Step 5 — Recompute under the new config

`dtk tune` takes **no pipeline lock** and the live preview is a faithful
*approximation* — the **next `dtk run` is the source of truth**. Because the
detector params changed, the detector's identity changed, so detections recompute
under the new id and the old rows are orphaned:

```bash
dtk run --select <name>                    # load → detect → alert under the new config
dtk run --select <name> --report           # optional: a self-contained HTML report to confirm behavior
dtk clean --select <name> --execute        # prune the orphaned old detector rows
dtk test-alert <name>                      # if alerting is configured
```

## When to hand off instead

- **Fully automatic, no browser** (CI, "just pick one for me") → the
  **`dtk-autotune`** skill (it runs the same engine from the command line and
  writes an annotated `__tuned_<id>.yml` without touching the original).
- **No metric yet** → **`dtk-new-metric`** to scaffold the sandbox, then come back.
- **DB not connected** → **`dtk-setup-project`**.

## Final checklist — verify before declaring done

- [ ] Metric exists, resolves to a **single** selector, and has loaded datapoints
      (ran `--steps load`, backfilled with `--from` if the chart was thin).
- [ ] You opened `dtk tune` (with `--no-open` + shared URL on a remote machine)
      and told the user it's an interactive chart they drive.
- [ ] You explained the relevant mode(s) — including that **Autotune is built in**
      and runs over the window shown — and which controls stay visible everywhere.
- [ ] After **Apply**, you ran `dtk run` to recompute and `dtk clean --execute`
      to prune the orphaned old detector rows (and `dtk test-alert` if alerting).

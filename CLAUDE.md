# detectkit — contributor & AI-assistant guide

**detectkit** is a Python library + CLI (`dtk`) for monitoring time-series
metrics with anomaly detection and multi-channel alerting. It is dbt-like:
metrics are YAML + SQL run through a `load → detect → alert` pipeline.
numpy-first (no pandas in core logic), ClickHouse / PostgreSQL / MySQL backends, Python 3.10+.

> **Using detectkit, not hacking on it?** See the [README](README.md), the
> [docs](docs/), and `dtk init-claude` (which sets up assistant context inside
> *your own* project).

## Working context lives in `.claude/rules/`

The detailed dev context is kept as focused rules (the single source — also
rendered on the docs site under **For developers**). Read the relevant one:

| If you're working on… | Read |
|---|---|
| Pipeline, module map, database layer, internal `_dtk_*` tables, detectors, alerting, design decisions | [.claude/rules/architecture.md](.claude/rules/architecture.md) |
| Dev setup, running tests, lint/format/types, conventions, adding a detector or channel, release checklist | [.claude/rules/contributing.md](.claude/rules/contributing.md) |

## Quick reference

- **Tests:** `python3 -m pytest tests/unit` — **lint/format/types:** `pre-commit run --all-files`
- `__version__` lives in `detectkit/__init__.py`; **`CHANGELOG.md` is authoritative** for behavior changes.
- User-facing docs are in `docs/`. The context that `dtk init-claude` ships to
  users lives in `detectkit/cli/assets/claude/` — **keep both in sync on every
  release** (see the contributing rule's release checklist).
- Keep the library **detector-agnostic** (new statistical detectors reuse
  `WindowedStatDetector`) and use the **generic** database manager
  (`insert_batch(table_name=...)`, never hardcoded per-table logic).
- **Auto-tuning** lives in `detectkit/autotune/` (the `dtk autotune` command,
  separate from load/detect/alert), records each run in the `_dtk_autotune_runs`
  internal table, and ships a `dtk-autotune` skill + `autotune.md` rule — keep
  those in sync on release.
- **Reporting** lives in `detectkit/reporting/` (`dtk run --report` /
  `dtk autotune --report`): it reads the `_dtk_*` tables and **replays alerts**
  into one self-contained HTML report per metric, sharing a framework-free JS
  rendering core with the website landing demo. The committed
  `assets/report.js` bundle ships in the wheel — regenerate it (and keep it in
  sync on release) when the report renderer TS changes.
- **Manual tuning** lives in `detectkit/tuning/` (the `dtk tune` command): the
  human-in-the-loop sibling of `dtk autotune`. It serves an interactive view of a
  metric's real series (recomputing the band live via the **same** TS detector
  port as the landing playground) and, on **Apply**, writes the chosen config
  back into the metric YAML — validating first, archiving the previous version to
  `metrics/.history/<metric>/`, then re-emitting in place. The whole screen is a
  **chart-first cockpit**: ONE mode-driven chart (the windshield) fills the view,
  the live **metrics ride pinned in a HUD over the chart** (the speedometer —
  always in view), and every control lives in an **always-visible side rail**
  beside the chart with its own scroll. The rail is **mode-aware** — it shows only
  the current mode's panel (detector knobs + effective config + Apply in **Tune**,
  verdict actions in **Review**, capture tools + incident list + Save in **Label**,
  the search button + winner/decision-log in **Autotune**)
  and collapses to give the chart the whole width — but the controls that aren't
  detector-specific stay visible in **every** mode (the **Points shown** data
  window, the alert rule — **direction** + **consecutive anomalies** — and the
  **y = 0** toggle). A **mode switch** picks which layers lead / dim / hide and
  which interactions are armed — **Tune** (band leads), **Review** (confirm the
  fired alerts: click a marker to cycle un-reviewed → valid (green) → false alarm
  (slate); **confirming an alert valid IS marking an incident** — the confirmed
  streak becomes a first-class **ground-truth incident** that shows in the
  Marked-incidents list as a "✓ confirmed alert" row, counts toward recall/FDR, and
  is written on Save, so a clean metric is validated in a few clicks without
  hand-drawing spans), **Label** (band hides,
  incidents editable; **Lasso anomalies** loops a cloud of anomaly dots into
  per-streak incident spans, **Threshold capture** grabs every span past a line),
  and **Autotune** (runs the **real** `dtk autotune` engine **server-side** over the
  **window the cockpit is showing** — the page posts its current **Points shown**
  trim window so the engine tunes on exactly the series the user sees and scores, not
  the full history — via a repeatable `POST /autotune`, using the marked incidents
  as ground truth, then **re-seeds every knob** with the winner + renders the
  decision log; the band leads like Tune). The run also **streams a structured
  run-log to the terminal** (cyan banner → `LABELS → SEASONALITY → … → RESULT`
  blocks via the same `StageLogRenderer` `dtk autotune` uses, matching `dtk run`'s
  format; the per-candidate "falls back to global" warning flood is quieted during
  the search). Autotune-in-tune is **advisory** — it
  computes + re-seeds only, persisting **no** run/`__tuned_<id>.yml`/detections (so
  `dtk tune` stays lock-free); the user reviews and **Apply**s, and the next
  `dtk run` is source of truth. The CLI command and the server share one
  `autotune/runner.py` (`autotune_from_data` — cap history → resolve scoring →
  ground truth → settings → `run_autotune_engine`), and the result re-seeds via the
  same `payload.seed_detector_params` the controls were first seeded from.
  The incident list, the live metrics and Save share **one** ground-truth set —
  hand-marked spans **plus** confirmed-valid alerts (derived from the stored
  verdict, not the current fire, so a confirmed incident stays scored — as a recall
  *miss* — even if the detector no longer fires there), deduped by overlap.
  **Deleting** a hand-marked incident (chart ✕ / Delete key **or** the list ✕)
  **retracts any confirmed-valid verdict it overlapped** (`retractConfirmationFor`,
  mirroring `unconfirmAlert`), so the span is fully removed instead of the hidden
  verdict **resurfacing** as a "✓ confirmed alert" row — the two delete paths stay in
  lockstep (the chart threads the removed span via `onIncidentsChange(incidents,
  removed)`); explicit `false` verdicts and non-overlapping confirmed alerts are left
  alone.
  Watch live **catch-rate (recall)** / **false-alert rate (FDR)** / **reviewed**
  metrics — matched on each alert's anomaly **streak span**, not just the fire
  instant — as you tune; an optional **false-alert budget** (`false_alert_budget`,
  a fraction in `(0, 1]`, on the **metric** then **project**, default `0.5`) gently
  flags the false-alert chip when the FDR exceeds it (tuning-only — labeling stays
  optional and it never touches the pipeline).
  **Save incidents** writes versioned `incidents/<metric>/*.yml` (the same store
  `dtk autotune` reads, including the painted `capture_windows` and per-alert
  `alert_reviews` metadata; confirmed alerts are written as incidents too) via a
  `POST /labels` endpoint, reusing `autotune/labels.py`. Seeded incidents from that
  store **anchor the (budget-sized) loaded window** — it ends just past the latest
  incident rather than at the last datapoint, so they render/score without an old
  outlier dragging the whole history in. A **y = 0 reference line** toggle is shared with
  `dtk run --report`. Committed bundle `assets/tune.js` (built by
  `website/scripts/gen-tune-bundle.mjs`) ships in the wheel — regenerate it when
  the renderer TS changes. Takes no pipeline lock. `dtk init-claude` ships a
  `dtk-tune` skill (the hands-on entry point for the user's assistant — the
  cockpit umbrella, with autotune built in) — keep it in sync on release.
- **OSI interop** lives in `detectkit/semantic/` (the `dtk osi import` /
  `export` / `compile` commands): an **isolated, additive** bridge to
  [Open Semantic Interchange](https://github.com/open-semantic-interchange/OSI) —
  the pipeline never imports it, so it can't affect a running project. OSI is an
  *interchange* format (define a KPI once, consume in BI + AI), not an execution
  engine, so detectkit converts at the edges rather than running OSI live:
  `import` scaffolds a **normal native metric** from an OSI model metric
  (`--target clickhouse` compiles from `dataset.source` via **sqlglot**;
  `--target cube` emits a Cube SQL-API `MEASURE(...)` query for dashboard
  number-parity), compiling only provably per-bucket-additive measures and
  hard-refusing the rest; `export` publishes metrics back as an OSI fragment with
  the exact config in `custom_extensions[detectkit]`. The metric-level
  `ai_context` (`{instructions, synonyms, examples}`, mirroring OSI) is
  descriptive grounding — opt-in `{synonyms}`/`{synonyms_line}` alert vars (no
  default-message change) + the tune cockpit payload. sqlglot is the optional
  `[osi]` extra (lazy import). A live runtime `osi_source` binding is deliberately
  deferred. Keep the `dtk osi` docs (cli reference + the OSI guide) in sync on
  release.

Repo: https://github.com/alexeiveselov92/detectkit

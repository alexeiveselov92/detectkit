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
  `metrics/.history/<metric>/`, then re-emitting in place. It also hosts a
  **synced incident-labeler chart**: mark real incidents (drag, or **Threshold
  capture** every span past a horizontal line at once) and watch live
  **catch-rate (recall)** / **false-alert rate (FDR)** metrics as you tune;
  **Save incidents** writes versioned `incidents/<metric>/*.yml` (the same store
  `dtk autotune` reads, including the painted `capture_windows`) via a
  `POST /labels` endpoint, reusing `autotune/labels.py`. Seeded incidents from that
  store are loaded with the **window widened to cover them** (so older ones still
  render and score). A **y = 0 reference line** toggle is shared with
  `dtk run --report`. Committed bundle `assets/tune.js` (built by
  `website/scripts/gen-tune-bundle.mjs`) ships in the wheel — regenerate it when
  the renderer TS changes. Takes no pipeline lock.

Repo: https://github.com/alexeiveselov92/detectkit

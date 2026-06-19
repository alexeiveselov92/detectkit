# detectkit — Contributor & AI-assistant guide

This file gives contributors (and AI tools like Claude Code) the context to work
in this repository effectively. It is committed to the repo on purpose: anyone
cloning detectkit gets the same working context.

> **User of detectkit, not a contributor?** You don't need this file. Start with
> the [README](README.md), the [docs](docs/), and `dtk init-claude` (which sets
> up assistant context *inside your own project*).

## Project overview

**detectkit** is a Python library and CLI (`dtk`) for data analysts and
engineers to monitor time-series metrics with automatic anomaly detection and
multi-channel alerting. It is **dbt-like**: metrics live as YAML + SQL in a
project directory and run through a `load → detect → alert` pipeline.

**Core principles:**
- Pure numpy arrays in core logic (no pandas — only in optional helpers)
- Batch processing for efficiency; idempotent, resumable operations
- Database-agnostic architecture (ClickHouse is the implemented backend;
  PostgreSQL/MySQL are planned and currently raise `NotImplementedError`)
- dbt-like CLI and project structure

## Technology stack

- **Core:** Python 3.10+, numpy, pydantic v2, click (CLI), Jinja2, PyYAML,
  requests, orjson. The authoritative dependency list is
  [`pyproject.toml`](pyproject.toml) `[project].dependencies`.
- **Optional extras:** database drivers (ClickHouse/Postgres/MySQL) and advanced
  detectors (prophet, timesfm — planned).

## Project structure

```
detectkit/
├── detectkit/             # Main package
│   ├── cli/               # Command-line interface (+ assets/claude for init-claude)
│   ├── config/            # Pydantic config models (project, profiles, metric)
│   ├── core/              # Core functionality (Interval, dataclasses)
│   ├── database/          # Database managers + internal table schemas
│   ├── loaders/           # Metric data loading
│   ├── detectors/         # Anomaly detectors
│   ├── alerting/          # Alert orchestration & channels
│   ├── orchestration/     # Task management & pipeline
│   └── utils/             # Utilities
├── tests/                 # Unit tests
└── docs/                  # User-facing documentation
```

## Authoritative sources

- **[CHANGELOG.md](CHANGELOG.md)** — release history; the most reliable record of
  behavior changes. **This is the source of truth for "what changed when".**
- **[docs/](docs/)** — user-facing documentation, kept in sync with the code.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — high-level design and patterns.
- **The code itself** — for current behavior, the code + `docs/` win over any
  prose. (Pre-0.3 historical design specs exist but are kept by the maintainer
  outside the repo; don't rely on them.)

## AI assistant context (`dtk init-claude`)

`dtk init-claude` scaffolds Claude Code context into a *user's* project folder so
an assistant can help them operate detectkit. **The canonical source of truth for
that context lives in [`detectkit/cli/assets/claude/`](detectkit/cli/assets/claude/)**
and ships as package data (see `pyproject.toml` `[tool.setuptools.package-data]`
and `MANIFEST.in`):

- `CLAUDE.section.md` — the block injected into the user's `CLAUDE.md` (between
  `<!-- BEGIN detectkit … -->` / `<!-- END detectkit -->` markers).
- `rules/*.md` — reference docs copied to `.claude/rules/detectkit/`
  (`overview`, `cli`, `project`, `metrics`, `detectors`, `alerting`).
- `skills/<name>/SKILL.md` — user-facing skills copied to `.claude/skills/`
  (`dtk-setup-project` for first-time DB/channel configuration in `profiles.yml`,
  `dtk-new-metric` for scaffolding a metric).

Implemented in `detectkit/cli/commands/init_claude.py` (idempotent, marker-based
injection; re-runnable to refresh after an upgrade). Tests:
`tests/unit/test_init_claude.py`.

> **⚠️ Release checklist — keep this context current.** These asset files are
> user-facing documentation. **Before every release**, review
> `detectkit/cli/assets/claude/` against the behavior changes in that release
> (same as you would `docs/`): if metric/detector/alerting/CLI behavior changed,
> update the matching `rules/*.md` (and the skill / `CLAUDE.section.md` if
> relevant) so a freshly-run `dtk init-claude` matches the shipped version. The
> generated block records the detectkit version, and users are told to re-run
> after upgrading — so stale assets surface directly in their assistant.

## Development guidelines

1. **English only** — code, comments, docstrings, documentation.
2. **No pandas in core logic** — numpy arrays only; pandas only in optional
   helpers or data loading.
3. **Type hints everywhere**; pydantic models for configs.
4. **Numpy-first** — vectorized operations; avoid Python-level loops in hot paths.
5. **Modular design** — small, focused modules (avoid 2K+ line files).
6. **Tests** for all core functionality.

### Running tests & linters

```bash
python3 -m pytest tests/unit        # unit test suite
pre-commit run --all-files          # ruff + black + mypy (config in pyproject.toml)
```

### Contribution workflow

- Match the surrounding code's conventions and the patterns documented below.
- For non-trivial changes, outline the approach (in the issue or PR description)
  before a large implementation — it's cheaper to align early.
- Preserve idempotency, the database-agnostic interface, and the
  detector-agnostic design (see *Key design decisions*).
- When behavior changes: update `CHANGELOG.md`, the relevant `docs/`, **and** the
  `dtk init-claude` assets in `detectkit/cli/assets/claude/`.
- Run the test suite and `pre-commit` before opening a PR.

## CLI commands

```bash
dtk init <project_name>                      # Initialize a project
dtk init-claude                              # Scaffold Claude Code context (CLAUDE.md + .claude/rules + skills)
dtk run --select <selector>                  # Run the load → detect → alert pipeline
dtk run --select <selector> --steps load     # Partial pipeline
dtk run --select <selector> --from DATE      # Reload from a date
dtk run --select <selector> --force          # Ignore locks
dtk run --select <selector> --full-refresh   # Complete reload
dtk test-alert <metric_name>                 # Send a test alert to channels
dtk unlock --select <selector>               # Clear a stuck pipeline lock
dtk clean --select <selector>                # Prune data orphaned by config edits
```

## Configuration files

**Project config** (`detectkit_project.yml`): `paths` (metrics/sql/templates),
default tables & timeouts, `default_profile`, optional `error_alerting`.

**Metric config** (`metrics/*.yml`): SQL `query`/`query_file`, `interval`
(e.g. `"10min"` or seconds), loading parameters, `detectors`, `alerting`.

**Profiles** (`profiles.yml`): database connections (ClickHouse needs
`internal_database` for `_dtk_*` tables and `data_database` for source tables)
and `alert_channels`. Secrets via `{{ env_var('VAR') }}` / `${VAR}`.

## Current status

**Production-ready and in active use.** Check [`CHANGELOG.md`](CHANGELOG.md) for
the latest version and behavior changes.

### What works
- Full load → detect → alert pipeline with idempotency (resume from the last
  timestamp in `_dtk_datapoints` / `_dtk_detections`), batching for both load
  and detect, gap filling, self-healing pipeline locks (+ `dtk unlock`).
- 4 detectors: `mad`, `zscore`, `iqr` (thin subclasses of the shared
  `WindowedStatDetector` in `detectors/statistical/_windowed.py`) and
  `manual_bounds`. Seasonality grouping, preprocessing (input_type, smoothing),
  recency weighting (`window_weights` + `half_life`), robust detrending
  (`detrend: linear`).
- MAD threshold is σ-equivalent (×1.4826 normal-consistency scaling).
- Direction-aware multi-detector alert quorum (`min_detectors` × `direction` ×
  `consecutive_anomalies`, grid-adjacent consecutive points), cooldown,
  recovery, no-data alerts, project-level error alerting, 5 channels
  (Mattermost, Slack, Telegram, Email, webhook).

### Known gaps / open work
- Per-point Python loop in `WindowedStatDetector.detect()` — acceptable for
  incremental runs, slow for large backfills. Vectorization is the main
  performance opportunity.
- PostgreSQL / MySQL backends are scaffolded but not implemented (their profiles
  validate, but building a manager raises `NotImplementedError`).

## Key design decisions

1. **Universal database manager**: `BaseDatabaseManager` exposes GENERIC methods
   (`insert_batch()`, `execute_query()`, …) that work with ANY table via a
   `table_name` parameter — never hardcoded for specific internal tables.
2. **Intervals**: custom parser (no pandas) — supports `"10min"`, `"1h"`,
   `"1d"`, or seconds (int).
3. **Seasonality**: JSON storage in a single column for flexibility.
4. **Duplicates**: PRIMARY KEY + INSERT IGNORE strategy.
5. **Idempotency**: check the last timestamp from `_dtk_datapoints` (not
   `_dtk_tasks`).
6. **Detector identity**: hash = class name + sorted non-default params. EVERY
   parameter that changes detection output is hashed (incl.
   seasonality_components, smoothing, weighting, detrend) — changing one creates
   a new `detector_id` and recomputes detections. Only `start_time` and
   `batch_size` are execution-level (not hashed).
7. **Consecutive alerts**: load N recent points and recompute each time;
   consecutive points must be exactly one interval apart (grid adjacency).
8. **Detector template**: MAD/ZScore/IQR share `WindowedStatDetector`
   (windowing, weighting, detrend, seasonality); a new statistical detector
   implements only `_compute_stats` / `_build_interval` / `_severity` +
   class-level defaults. **Keep it this way — the library must stay
   detector-agnostic.**
9. **Recency weighting is time-aware**: weights are looked up by a point's age on
   the time grid (gaps don't compress decay; seasonality groups share the global
   recency horizon). Expressed as `half_life` (points or duration string);
   `weight_decay` is a deprecated alias.
10. **Table schemas**: defined via `TableModel` dataclasses for database-agnostic
    DDL generation.

## Repository

https://github.com/alexeiveselov92/detectkit

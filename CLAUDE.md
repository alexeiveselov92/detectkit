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

Repo: https://github.com/alexeiveselov92/detectkit

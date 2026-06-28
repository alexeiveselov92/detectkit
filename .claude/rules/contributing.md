# Contributing

This guide covers how to set up, test, lint, and extend **detectkit**. It is
both an in-context rule for AI assistants working on the repo and the
contributor reference rendered on the docs site. For internals and design
rationale, see the architecture rule: [./architecture.md](./architecture.md).

## Project layout

```
detectkit/
├── detectkit/            # Main package
│   ├── cli/              # `dtk` command-line interface
│   │   └── assets/claude # AI-assistant context shipped by `dtk init-claude`
│   ├── config/           # Pydantic config models & loaders
│   ├── core/             # Interval parsing, dataclasses, table models
│   ├── database/         # Database managers (ClickHouse, Postgres, MySQL)
│   ├── loaders/          # Metric data loading + gap filling
│   ├── detectors/        # Anomaly detectors (statistical/ + factory)
│   ├── alerting/         # Alert orchestration + channels
│   ├── orchestration/    # Task management & load→detect→alert pipeline
│   ├── autotune/         # `dtk autotune` engine (seasonality/detector/grid search)
│   ├── reporting/        # Self-contained HTML reports (`dtk run/autotune --report`)
│   ├── tuning/           # `dtk tune` interactive manual tuning (write-back in place)
│   └── utils/            # Numpy/stats helpers, env interpolation
├── tests/                # Unit (numpy/mock) + integration (testcontainers)
└── docs/                 # User-facing docs (guides, reference, examples)
```

## Dev setup

Requires **Python 3.10+**. Install editable with the `dev` extra plus whichever
database driver you work against (extra names are defined in `pyproject.toml`
under `[project.optional-dependencies]`):

```bash
# dev tooling + ClickHouse driver (other extras: postgres, mysql, all-db)
pip install -e ".[dev,clickhouse]"

# install the git hooks
pre-commit install
```

Other extras: `prophet`, `timesfm`, `advanced-detectors`, `all`, and
`integration` (testcontainers for Docker-backed integration tests).

The `dtk` console script is wired in `pyproject.toml`
(`[project.scripts] dtk = "detectkit.cli.main:cli"`).

## Running tests

```bash
python3 -m pytest tests/unit
```

Unit tests are numpy/mock-based and do **not** require a live database — they
mock the database managers. Pytest config (testpaths, markers, coverage) lives
in `pyproject.toml` under `[tool.pytest.ini_options]`; markers are `unit`,
`integration`, `slow`. Integration tests (marked `integration`) need Docker and
the `integration` extra.

## Lint, format, type-check

All checks run through pre-commit; config lives in `pyproject.toml`:

```bash
pre-commit run --all-files
```

Hooks (`.pre-commit-config.yaml`):

- **trailing-whitespace / end-of-file-fixer / check-yaml /
  check-added-large-files (max 500kb) / check-merge-conflict** — basic hygiene.
- **ruff `--fix`** — lint + import sorting (`[tool.ruff]`: line length 100,
  rule sets `E`, `W`, `F`, `I`, `B`, `C4`, `UP`; `E501` deferred to black).
- **black** — formatting (`[tool.black]`: line length 100, target py310).
- **mypy** — type checking, scoped to `^detectkit/` only (`[tool.mypy]` is
  strict: `disallow_untyped_defs`, `no_implicit_optional`, etc.).

## Code conventions

- **English only** — all code, comments, docstrings, and documentation.
- **No pandas in core logic** — detection and loading operate on numpy arrays;
  pandas is allowed only in optional helper/export methods.
- **Type hints everywhere** — mypy strict mode is enforced over `detectkit/`.
- **Pydantic for configs** — config models live in `detectkit/config/`.
- **Small, focused modules** — avoid 2K-line files; split by responsibility.
- **Keep the library detector-agnostic** — new statistical detectors reuse the
  shared windowing pipeline (`WindowedStatDetector`); never fork the pipeline
  or special-case a detector type in the orchestrator.

## How to extend

### Add a statistical detector

The detection pipeline (preprocessing, trailing window, recency weighting,
detrending, seasonality multipliers, metadata) lives entirely in
`WindowedStatDetector` (`detectkit/detectors/statistical/_windowed.py`). A new
detector subclasses it and implements only what differs — it inherits
windowing, weighting, detrending and seasonality for free.

1. Create `detectkit/detectors/statistical/<name>.py` subclassing
   `WindowedStatDetector` (see `mad.py` for a reference implementation).
2. Set the class-level attributes:
   - `THRESHOLD_DEFAULT` (float) — default interval width.
   - `MIN_SAMPLES_FLOOR`, `MIN_SAMPLES_PER_GROUP_DEFAULT`,
     `MIN_SAMPLES_PER_GROUP_FLOOR`.
   - `STATS` — ordered tuple of `(name, kind)` pairs, `kind` in
     `{"center", "spread"}` (controls the seasonality-multiplier guard).
3. Implement the three abstract hooks:
   - `_compute_stats(self, values, weights) -> dict[str, float]` — compute the
     statistics named in `STATS`.
   - `_build_interval(self, stats, threshold) -> tuple[float, float]` — build
     the `(lower, upper)` confidence interval.
   - `_severity(self, current, stats, distance) -> float` — severity score for
     an anomalous point.
4. Register it in `DetectorFactory.DETECTOR_TYPES`
   (`detectkit/detectors/factory.py`), mapping a lowercase type name to the
   class (e.g. `"mynew": MyNewDetector`).
5. Add unit tests under `tests/unit/`.

Every parameter that changes detection output is hashed into the detector ID,
so reusing `WindowedStatDetector` gets you correct identity/recompute behavior
automatically — do not add per-detector params that bypass the hash.

For `dtk autotune` to consider the new detector, add a one-line entry to the
suitability spec in `detectkit/autotune/detector_select.py`
(`detector_suitability(type, features)`) and, if its hyperparameters differ, a
threshold grid / axis in `grid_search.py`. The spec is keyed by type name (not
on the detector class) on purpose, so the detector stays autotune-agnostic; an
unlisted type just gets a neutral suitability.

### Add a scoring metric

Autotune optimizes a binary-classification metric chosen via
`--scoring` / the `autotune:` block. To add one:

1. Implement it as a pure-numpy function in `detectkit/autotune/scoring.py`
   (binary metrics take `(y_true, y_pred)`; ranking metrics take
   `(y_true, y_score)`). **No scipy/sklearn** — the engine has no such runtime
   dependency.
2. Add the name to `ScoringMetric` (`detectkit/autotune/_types.py`) and a branch
   in `score_predictions()`.
3. Add the name to `_AUTOTUNE_SCORING_METRICS` in
   `detectkit/config/metric_config.py` so the `autotune.scoring_metric` validator
   accepts it.
4. Add unit tests under `tests/unit/test_autotune_scoring.py`.

### Add an alert channel

Channels live in `detectkit/alerting/channels/`. The base class
`BaseAlertChannel` (`base.py`) already provides `format_message`,
`format_title`, `format_mentions`, all the default templates, and
`build_context` / `status_color` / `status_word` / `status_emoji` helpers.

For a **rich, platform-native** layout (the webhook/Telegram/email channels do
this), build the message from `build_context(alert_data)` — the single dict of
display-ready values (`value_display`, `expected_range`, `timestamp`,
`detector_params`, `dashboard_url`, …) shared with the template path — and apply
your platform's own escaping (HTML for Telegram/email, markdown for webhook).
Fall back to `format_message(alert_data, template)` when the caller passes a
custom `template`. Lead the title/headline with `status_emoji(alert_data)` and
pick accents with `status_color(alert_data)` so status reads from color.

1. Create `detectkit/alerting/channels/<name>.py`. Subclass
   `BaseAlertChannel`, or `WebhookChannel` (`webhook.py`) for a
   webhook/POST-style channel.
2. Implement `send(self, alert_data: AlertData, template=None) -> bool` (return
   `True`/`False`; log and swallow transport errors rather than crashing the
   pipeline). Build the body natively from `build_context`, or override the
   `get_default_*_template()` / `get_default_*_title_template()` methods only if
   the channel needs a different plain-text layout from the base defaults.
3. Override `format_mentions` for platform-native mention syntax if needed.
4. Register the type in `AlertChannelFactory.CHANNEL_TYPES`
   (`detectkit/alerting/channels/factory.py`), mapping a lowercase type name to
   the class.
5. Add unit tests under `tests/unit/`.

## Release checklist

1. **Bump the version** — `__version__` in `detectkit/__init__.py` (the only
   source; `pyproject.toml` reads it dynamically via
   `[tool.setuptools.dynamic]`).
2. **Update `CHANGELOG.md`** — Keep a Changelog format; it is the authoritative
   record of behavior changes.
3. **Update `docs/`** — keep user-facing guides/reference in sync with behavior.
4. **Regenerate the report + tune bundles** — if you changed the HTML report's
   renderer TS (`website/src/scripts/core/canvas.ts`, `report/report.ts`, or
   anything they pull in), rebuild the committed bundle with
   `node website/scripts/gen-report-bundle.mjs` (esbuild) so
   `detectkit/reporting/assets/report.js` matches the source. If you changed the
   interactive tuning renderer (`website/src/scripts/report/tune.ts` or the shared
   `demo/` detector/chart it reuses), also rebuild
   `node website/scripts/gen-tune-bundle.mjs` so
   `detectkit/tuning/assets/tune.js` matches — same generated-asset pattern as
   `make-bot-icon.mjs`. The renderers share the detector
   port with the landing playground, so run the demo parity check
   (`npm run check:demo-parity`) to confirm the TS detector port still matches the
   Python detectors.
5. **Update the `dtk init-claude` assets** in `detectkit/cli/assets/claude/`
   (`rules/*.md`, `skills/*/SKILL.md`, `CLAUDE.section.md`) so a freshly-run
   `dtk init-claude` matches the shipped version. These assets are user-facing
   docs, ship in the wheel (`pyproject.toml`
   `[tool.setuptools.package-data]` + `MANIFEST.in`), and are exactly what a
   freshly-run `dtk init-claude` writes — users are told to re-run after
   upgrading, so out-of-sync assets reach their assistant directly. (The managed
   `CLAUDE.md` block is intentionally version-less, so a no-op upgrade doesn't
   churn it; it changes only when the shipped content changes.) The command lives in
   `detectkit/cli/commands/init_claude.py` (tests:
   `tests/unit/test_init_claude.py`). Adding or removing a shipped rule or skill
   (e.g. `rules/autotune.md`, `skills/dtk-autotune/`) also means: (a) extending
   `test_init_claude.py` — `RULE_FILES` is matched as an **exact set** and each
   skill is asserted present; **and (b)** updating the landing's `dtk init-claude`
   terminal block (`claudeLines`) and the "_… skills_" prose in
   `website/src/pages/index.astro`, which reproduce the real command output —
   the rule/skill list and the "(N created)" total must match
   `dtk init-claude --target-dir <tmp>` (the marketing page deliberately drops the
   `vX.Y.Z` suffix the CLI prints so it doesn't churn every release).
6. **Run the gate** — `python3 -m pytest tests/unit` and
   `pre-commit run --all-files` must pass.
7. **Build & publish** the wheel/sdist.

## PR workflow

- Discuss non-trivial changes (new detectors, channels, schema/config changes)
  before implementing.
- Match existing patterns — reuse `WindowedStatDetector` / `BaseAlertChannel`,
  use generic database-manager methods (`insert_batch(table_name=...)`), keep
  idempotency intact.
- All unit tests pass and pre-commit is clean.
- Update `CHANGELOG.md`, `docs/`, and the `dtk init-claude` assets when behavior
  changes.

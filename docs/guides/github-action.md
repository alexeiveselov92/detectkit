# GitHub Action

detectkit ships a composite GitHub Action — a thin wrapper around the `dtk`
CLI — so you can run `dtk run` (or `autotune` / `clean`) as a CI check or a
scheduled job without hand-rolling the "install Python, pip install
detectkit, run the command, gate on the exit code" boilerplate yourself.

It **installs detectkit from PyPI** (pinned by the `version` input, or the
latest release if you leave it unset) — it does not run this repository's
own checked-out library code. Point it at your own project with
`project-dir` (a directory containing `detectkit_project.yml` and
`profiles.yml`, exactly like running `dtk` locally).

## Quickstart

```yaml
# .github/workflows/detectkit.yml
name: detectkit

on:
  schedule:
    - cron: "*/10 * * * *"   # every 10 minutes
  workflow_dispatch:

jobs:
  monitor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run detectkit
        uses: alexeiveselov92/detectkit@v0.62.1   # pin to a released tag
        env:
          CLICKHOUSE_PASSWORD: ${{ secrets.CLICKHOUSE_PASSWORD }}
          MATTERMOST_WEBHOOK_URL: ${{ secrets.MATTERMOST_WEBHOOK_URL }}
        with:
          extras: clickhouse
          select: "*"
```

That's it: the job fails whenever `dtk run` would — a failed metric, a
selector matching nothing, a dead database — because the action preserves
`dtk`'s own [exit code](#exit-codes-and-ci-gating) as the step's outcome.
Check the [Releases page](https://github.com/alexeiveselov92/detectkit/releases)
for the latest tag; the action versions ride the library's own `vX.Y.Z` tags
(see [Environment Variables](#secrets) below for how `${{ secrets.* }}`
reaches your `profiles.yml`).

## Inputs

| Input | Default | Notes |
|---|---|---|
| `command` | `run` | `run`, `autotune`, or `clean`. Anything else fails the step (exit `2`) before `dtk` is invoked. |
| `select` | `*` | Passed as `--select`. `run`/`autotune` require a selector; `clean` accepts either a selector (drift mode) or `--orphaned-metrics` via `extra-args` — set `select: ""` to use the latter. |
| `steps` | `""` | Passed as `--steps` for `command: run` (e.g. `load,detect`). Empty uses `dtk run`'s own default (`load,detect,alert`). Ignored (with a warning) for `autotune`/`clean`. |
| `profile` | `""` | Passed as `--profile`. Empty uses the project's `default_profile`. |
| `project-dir` | `.` | Directory containing `detectkit_project.yml` / `profiles.yml`, relative to the checkout. |
| `version` | `""` | detectkit PyPI version spec. A bare version (`0.61.0`) is pinned exactly; a string starting with a pip operator (`>=0.60,<0.62`, `~=0.61`) is used as-is. Empty installs the latest release. |
| `extras` | `""` | Comma-separated pip extras, e.g. `clickhouse` or `duckdb,mysql` — match whatever backend your `profiles.yml` points at. See the [Databases guide](databases.md). |
| `python-version` | `3.12` | Passed to `actions/setup-python` (detectkit requires 3.10+). |
| `json-summary` | `true` | For `command: run` only: pass `--json` and capture the summary into the `summary`/`summary-path` outputs. No effect on `autotune`/`clean` (they have no `--json` flag). |
| `extra-args` | `""` | Extra raw arguments appended to the `dtk` command line, e.g. `--full-refresh --force`. Parsed with real shell quoting, so a quoted value with spaces round-trips correctly (`extra-args: '--from "2026-01-01 00:00:00"'`). |

## Outputs

| Output | Description |
|---|---|
| `exit-code` | `dtk`'s exit code as a string (`"0"` / `"1"` / `"2"`). |
| `summary` | The raw `dtk run --json` document, when `command: run` and `json-summary: true`; empty otherwise. |
| `summary-path` | Path to the saved summary file on the runner, under the same condition. |

## Exit codes and CI gating

`dtk run` / `dtk autotune` / `dtk clean` return a reliable exit code — `0`
success, `1` failure, `2` usage error — documented in full in the
[CLI reference's Exit Codes section](../reference/cli.md#exit-codes). The
action's own final step re-exits with that exact code, so **the job already
fails on a real pipeline failure with no extra configuration** — the whole
point of the exit-code contract is that a failing metric fails your job, not
just prints red text into a log nobody reads.

If you want a *softer* gate (e.g. one metric's failure should page on-call
without failing the whole workflow, or you want to branch on something finer
than "did anything fail"), read the summary output instead of relying on the
step's own pass/fail:

```yaml
- name: Run detectkit
  id: dtk
  uses: alexeiveselov92/detectkit@v0.62.1
  continue-on-error: true   # don't fail the job here — we'll decide below
  with:
    select: "tag:critical"

- name: Only page on-call for specific failures
  if: steps.dtk.outputs.exit-code != '0'
  run: |
    echo "detectkit run failed (exit ${{ steps.dtk.outputs.exit-code }})"
    # page-oncall.sh ...
    exit 1   # still fail the job — just after your own logic ran
```

See also the CLI reference's
[Scheduling section](../reference/cli.md#scheduling), which covers
orchestrator recipes (Airflow, Dagster, Prefect) alongside GitHub Actions for
non-Actions schedulers.

## The JSON summary

With the default `json-summary: true` (and `command: run`), the action's
`summary` output carries the same `schema_version: 1` document described in
the [CLI reference](../reference/cli.md#--json-flag) — per-metric status,
counters, timing, and the exit code, as one JSON document. Pull it apart with
`jq` in a follow-up step:

```yaml
- name: Run detectkit
  id: dtk
  uses: alexeiveselov92/detectkit@v0.62.1
  with:
    select: "*"

- name: Fail only if a specific metric errored
  if: always()
  run: |
    echo '${{ steps.dtk.outputs.summary }}' > summary.json
    jq -e '.metrics[] | select(.name == "checkout_errors" and .status == "failed")' summary.json \
      && exit 1 || true

- name: Post a run digest
  if: always()
  run: |
    jq -r '.totals | "metrics=\(.metrics) failed=\(.failed) anomalies=\(.anomalies_detected)"' \
      "${{ steps.dtk.outputs.summary-path }}"
```

Both `summary` (the value directly) and `summary-path` (the file on disk) are
available — use whichever is more convenient for the step.

## Secrets

Nothing about the action changes how detectkit resolves secrets: `profiles.yml`
and `alert_channels` support environment-variable interpolation via `${VAR}`
or `{{ env_var('VAR') }}` (see
[Environment Variables](../reference/cli.md#environment-variables)), and
those variables just need to be present in the process environment when `dtk`
actually runs.

GitHub Actions applies a step's `env:` context to a composite action's
*internal* steps too, so set your secrets on the step that calls this action:

```yaml
- name: Run detectkit
  uses: alexeiveselov92/detectkit@v0.62.1
  env:
    CLICKHOUSE_PASSWORD: ${{ secrets.CLICKHOUSE_PASSWORD }}
    MATTERMOST_WEBHOOK_URL: ${{ secrets.MATTERMOST_WEBHOOK_URL }}
  with:
    extras: clickhouse
```

```yaml
# profiles.yml
profiles:
  prod:
    type: clickhouse
    host: "{{ env_var('CLICKHOUSE_HOST') }}"
    password: "${CLICKHOUSE_PASSWORD}"

alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "{{ env_var('MATTERMOST_WEBHOOK_URL') }}"
```

Never hardcode a webhook URL or database password directly in `profiles.yml`
— commit the `${VAR}` / `env_var(...)` placeholder and store the real value
as a GitHub Actions [repository or environment
secret](https://docs.github.com/actions/security-guides/using-secrets-in-github-actions).

## Hybrid mode on CI: warehouse source, ephemeral state caveat

If your metrics read from a cloud warehouse, [hybrid mode](hybrid-mode.md)
(`source_profile`) lets the query run against the warehouse while detectkit's
own `_dtk_*` bookkeeping lives in a cheap separate database — often
[DuckDB](databases-duckdb.md), a single local file with no server to
provision.

On a **GitHub-hosted runner, the filesystem is thrown away at the end of
every job** — a DuckDB state file at `./detectkit.duckdb` starts empty on
every run unless you do something to persist it. That breaks detectkit's
resume-from-last-timestamp idempotency: instead of "load what's new since
the last run," every scheduled run becomes "load everything since
`loading_start_time`, from scratch." For a smoke test or an ad hoc backfill
that's fine (it's what the example project in `examples/action-smoke/`
does). For **scheduled, ongoing monitoring**, it defeats the purpose:

- **Recommended**: point the state profile at a real, always-on database —
  a small managed PostgreSQL/MySQL instance, or a self-hosted one — so state
  actually persists between runs the way it would on a long-lived server or
  container. This is the pattern hybrid mode is designed for: cheap
  persistent state, expensive warehouse queried only for the metric's own
  SQL.
- **Best-effort alternative**: [`actions/cache`](https://github.com/actions/cache)
  the DuckDB file between runs, keyed on something stable (the metric name,
  not the commit SHA). This can work for light, non-critical schedules, but
  the cache is explicitly **best-effort** — GitHub evicts entries under
  storage pressure or after ~7 days of no access, and a cache miss silently
  resets your state to empty (the next run just reloads from
  `loading_start_time`, no error, no alert). Don't rely on it for anything
  where a silent state reset would be a problem — a real database removes
  the failure mode entirely.

Either way, `dtk run` in the action is oblivious to *how* the state database
persists — persistence is entirely a property of your workflow (or your
infrastructure), not something the action or hybrid mode manage for you.

## The example project

`examples/action-smoke/` is a complete, self-contained detectkit project used
by this repository's own action smoke test
(`.github/workflows/action-smoke.yml`) — and doubles as a runnable example
you can copy: a DuckDB profile, no external database, and one metric whose
query synthesizes its own series with DuckDB's `generate_series()` instead of
reading from a real table. Point the action at a copy of it (`extras:
duckdb`) to try the action end-to-end with nothing to provision.

## See also

- [CLI reference](../reference/cli.md) — every `dtk` command and flag,
  including [Exit Codes](../reference/cli.md#exit-codes),
  [`--json`](../reference/cli.md#--json-flag), and
  [Scheduling](../reference/cli.md#scheduling) (Airflow/Dagster/Prefect
  recipes for non-Actions orchestrators).
- [Hybrid mode](hybrid-mode.md) — splitting warehouse source queries from
  detectkit's own state.
- [DuckDB](databases-duckdb.md) — the file-based backend used by the example
  project and a common choice for detectkit state.
- [Alerting channels](alerting-channels.md) — configuring the channels your
  scheduled runs will actually notify.

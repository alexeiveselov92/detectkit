# MCP server

detectkit ships a **read-only** [Model Context Protocol](https://modelcontextprotocol.io)
(MCP) server (`dtk mcp`) — a window an AI assistant (Claude Code, Claude
Desktop, an IDE extension, any MCP-capable client) can open onto a project's
**already-monitored** state: metric configs, loaded datapoints, detector
results, replayed alert history, autotune runs, and labeled incidents. It
turns "which metrics fired this week, and why?" or "what does the
`checkout_errors` config actually detect?" into a question the assistant can
answer directly, instead of you copy-pasting query results or opening
`dtk ui` yourself.

It is **isolated and additive**, the same design as `dtk osi`: nothing in the
load → detect → alert pipeline imports it, so it can never affect a running
project. `dtk mcp` never writes to the database and never writes to the
filesystem — see [Read-only guarantees](#read-only-guarantees) below. To
change a metric's config, tune a detector, or run the pipeline, an assistant
still uses `dtk tune` / `dtk run` / `dtk ui` directly (or the CLAUDE.md
context `dtk init-claude` sets up, which points to those tools for anything
that mutates state).

> **Not the same thing as a database MCP.** A generic database MCP (if you
> already use one) gives an assistant raw SQL access to your warehouse —
> useful, but it doesn't know detectkit's decision logic. `dtk mcp` answers in
> detectkit's own terms: it replays the **real** alert quorum/cooldown/recovery
> logic instead of a raw table scan, and understands metric configs, detector
> identity, and labeled incidents. The two are complementary — nothing stops
> you running both.

## Install

```bash
pip install 'detectkit[mcp]'
```

This installs the [`mcp`](https://pypi.org/project/mcp/) SDK
(`mcp>=1.27,<2`). The core library and the rest of the `dtk` CLI never import
it — only `dtk mcp` needs the extra, and it fails with a clear
`pip install 'detectkit[mcp]'` message if you run it without installing first.

## Quickstart

```bash
cd my_monitoring   # a directory containing detectkit_project.yml
dtk mcp
```

This serves the MCP protocol over **stdio** until EOF/Ctrl-C — it's meant to
be launched by an MCP client, not run standalone in a terminal you watch. One
startup line goes to stderr (project name, resolved root, selector, profile,
metric count, whether the internal tables exist yet); stdout is reserved for
the protocol itself once the server starts.

## Setting it up

An MCP client generally launches `dtk mcp` with **no working-directory
guarantee** — its config passes an absolute command + args, not a `cwd`. So
point it at your project explicitly with `--project-dir` (or the
`DETECTKIT_PROJECT_DIR` environment variable) rather than relying on the
current-directory fallback — see [Project directory
resolution](#project-directory-resolution).

### Claude Code

Register it once, from anywhere:

```bash
claude mcp add dtk -- dtk mcp --project-dir /abs/path/to/my_monitoring
```

Or check in a project-scoped `.mcp.json` (so everyone on the repo gets it
automatically) at the repo root:

```json
{
  "mcpServers": {
    "dtk": {
      "command": "dtk",
      "args": ["mcp"],
      "env": {
        "DETECTKIT_PROJECT_DIR": "/abs/path/to/my_monitoring"
      }
    }
  }
}
```

Both forms are equivalent — `--project-dir` and `$DETECTKIT_PROJECT_DIR` are
just two ways to pass the same path (see resolution order below). Narrow what
the assistant can see by adding `--select`:

```json
{
  "mcpServers": {
    "dtk": {
      "command": "dtk",
      "args": ["mcp", "--project-dir", "/abs/path/to/my_monitoring", "--select", "tag:critical"]
    }
  }
}
```

### Claude Desktop

Add a `dtk` entry to `claude_desktop_config.json`
(`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS,
`%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "dtk": {
      "command": "dtk",
      "args": ["mcp", "--project-dir", "/abs/path/to/my_monitoring"]
    }
  }
}
```

Restart Claude Desktop after editing the file. If `dtk` isn't on the `PATH`
Claude Desktop launches with, use the full path to the executable (e.g. the
one inside your virtualenv, `which dtk` to find it) as `command`.

### Any other MCP client

`dtk mcp` is a standard stdio MCP server, so any client that can launch a
subprocess and speak the protocol over stdin/stdout works — point its
"command" at `dtk`, its "args" at `["mcp", "--project-dir", "<path>"]` (or set
`DETECTKIT_PROJECT_DIR` in the process environment it launches with).

## Project directory resolution

`--project-dir` (or the fallback below) is a **starting point**, not
necessarily the project root itself — each mechanism searches upward from it
for `detectkit_project.yml`, so pointing at a subdirectory still resolves. In
order:

1. **`--project-dir <path>`** — searched upward for `detectkit_project.yml`.
2. **`$DETECTKIT_PROJECT_DIR`** environment variable — same upward search.
3. **The current working directory** — searched upward. Only useful when
   `dtk mcp` is launched with a known `cwd` (e.g. you start it by hand from
   inside the project to test it); most MCP clients don't guarantee one, so
   don't rely on this in a client config.

If none resolves, the server refuses to start with an error naming all three
mechanisms it tried.

## Tools

Every tool call is read-only and answers within the server's session scope
(see [Session scope](#session-scope-select) below).

| Tool | Parameters | Returns |
|---|---|---|
| `list_metrics` | `selector="*"` | Every matching metric's name, `metrics/` location, tags, enabled flag, interval, configured detector types, and a one-line alert-rule summary. |
| `get_metric` | `name` | One metric's full config: description, tags, interval, loading params (start time, batch size, resolved `loading_delay`, resolved hybrid-mode `source_profile` *name*), seasonality columns, every detector's type + params, every alerting block (channels by *name* only), `ai_context`, `false_alert_budget`, and the metric's SQL text (inline or read from `query_file`). |
| `get_metric_status` | `name`, `window="7d"` | One metric's live health: the same row `dtk ui`'s overview table shows — freshness, point/anomaly counts, per-day alert frequency, stale-detector-generation count, and (when labels exist) recall/false-alert-rate quality — computed by **replaying** alerts, not by reading last-writer-wins state. `window` is `24h`/`7d`/`30d`/`90d`/`all`. |
| `get_project_status` | `window="7d"`, `selector="*"`, `limit=50` | `get_metric_status` for every metric matching `selector`, capped at `limit` (hard cap 200) even though `total_metrics` reports the full matched count. |
| `query_datapoints` | `metric`, `from_ts=None`, `to_ts=None`, `limit=1000` | Raw loaded `{timestamp, value}` rows, newest first (`value` is `null` for a gap-filled missing point). `limit` hard cap 5000; page by moving `to_ts` backward for a longer span. |
| `query_detections` | `metric`, `detector_id=None`, `from_ts=None`, `to_ts=None`, `anomalies_only=False`, `limit=1000` | Per-detector results: value, confidence band, anomaly flag; newest first. Omitting `detector_id` returns every stored generation, including ones superseded by a retune. `limit` hard cap 5000. |
| `replay_alerts` | `metric`, `from_ts=None`, `to_ts=None` | Reconstructs the anomaly/recovery/no-data timeline a period actually fired, using the same pure replay engine `dtk run --report` and `dtk ui` use (re-walks quorum/consecutive/fraction-rule/cooldown/recovery over stored detections) — **not** `_dtk_alert_states` (last-writer-wins state, not an event log). No dispatch happens; nothing is sent. |
| `get_autotune_history` | `metric`, `limit=5`, `include_decision_log=False` | Past `dtk autotune` runs, newest first: run id/timestamp/status/mode/scoring metric/score, chosen detector type + params + seasonality, winning `detector_id`. `limit` hard cap 50; the full per-stage decision log is opt-in (large). |
| `get_incidents` | `metric` | The ground-truth incidents labeled via `dtk tune` (Label/Review mode + Save incidents) — the newest versioned file under `incidents/<metric>/`. An empty list is normal (never labeled), not an error. |
| `get_server_info` | — | This server's identity: detectkit version, project name/root, profile/backend type, the session's `selector`, metric count, `tables_ready`, and `read_only: true`. A good first call to confirm which project/scope you're talking to. |

Every timestamp crossing the tool boundary is an ISO-8601 UTC string
(`2026-07-01T00:00:00Z`); every number is a plain JSON `float`/`int`/`null`
(never a numpy type, never `NaN`).

## Read-only guarantees

`dtk mcp` contains **zero write paths** — by design, not by convention:

- **No DDL.** It never calls `ensure_tables()`. If the internal `_dtk_*`
  tables don't exist yet (no `dtk run` has ever completed for this project),
  every data tool answers with a clear "no data yet — run `dtk run` first"
  error instead of creating them or leaking a raw driver error.
- **No pipeline execution.** It never runs load/detect/alert, and it holds
  the `dtk run` pipeline lock at no point — a live `dtk run` and a live
  `dtk mcp` session can coexist without contention (the server serializes its
  own tool calls over one DB connection; see [Caveats](#caveats)).
- **No config/label writes.** Explicitly excluded: applying a tuned config
  (`dtk tune`'s Apply), the `dtk ui` metric-file create/edit/delete routes,
  job/subprocess spawning, writing incident labels (`dtk tune`'s Save
  incidents), and any `save_*`/`delete_*` internal-table call. Nothing here
  can edit a metric YAML, spawn a subprocess, or mutate a database row.
- **Channel secrets are never exposed.** `get_metric`'s alerting blocks list
  channels by **name** only (`channels: ["mattermost_ops"]`) — webhook URLs,
  passwords, tokens and other connection details live in `profiles.yml`,
  which this server never reads. The resolved hybrid-mode `source_profile` is
  likewise surfaced as a profile *name*, never its connection.

### Session scope (`--select`)

The server's startup `--select` selector (default `*`, everything) is an
access-control boundary, not just a default filter: every tool that names a
metric refuses one outside that set, and `list_metrics` /
`get_project_status` intersect their own `selector` argument with it — a
tool-call selector can **narrow** the session's scope but never **escape**
it. Whoever launches the server decides which metrics an assistant may read
by choosing `--select` at startup; a second, more permissive `--select`
argument at call time can't widen that later.

## Caveats

- **One DB connection, serialized.** Like `dtk ui`, `dtk mcp` holds a single
  database connection for its whole session; every tool call takes an
  in-process lock around it, so concurrent tool calls from one client queue up
  rather than racing. This is fine for interactive assistant use — it isn't
  built for high-throughput automated querying.
- **"No data yet" means run the pipeline first, not that the server is
  broken.** A fresh project (or one you haven't run `dtk run` on yet) answers
  every data tool with the friendly error described above. `get_server_info`
  reports `tables_ready: false` so an assistant can check this proactively
  before calling anything else.
- **No ephemeral/in-memory state to worry about.** Unlike a demo MCP server
  backed by `:memory:` storage, `dtk mcp` reads your project's real,
  persistent `_dtk_*` tables through the same profile `dtk run` uses —
  restarting the MCP server loses nothing, because it holds no state of its
  own. (The one exception is a `:memory:`-mode DuckDB *profile*, if you've
  configured one — that's a property of your `profiles.yml`, not of `dtk mcp`.)
- **A session's scope is fixed at startup.** Adding a metric to the project
  after `dtk mcp` starts won't appear in that session (`list_metrics`
  re-evaluates `selector` against the metric set snapshotted at startup, not
  a live filesystem watch) — restart the server to pick it up.

## See also

- [CLI reference](../reference/cli.md#dtk-mcp) — `dtk mcp` flags.
- [GitHub Action](github-action.md) — the other automation surface: run the
  pipeline itself in CI, rather than reading its results.
- [Project UI](project-ui.md) — the same replayed-alert data as a browser
  cockpit, for a human instead of an assistant.
- [Tuning by hand](tuning.md) — where labeled incidents (`get_incidents`) come
  from, and where a config an assistant investigated gets changed.

---
name: dtk-setup-project
description: >-
  Configure a detectkit project's database connection (and optionally a first
  alert channel) in profiles.yml so `dtk run` works end to end. Use for
  first-time setup, right after `dtk init`, when the user asks to connect
  detectkit to their database or set up profiles.yml, or when a run fails with
  "internal_database must be set", "data_database must be set", "profiles.yml
  not found", or "Connection refused". Interactive and database-type-aware.
---

# Set up a detectkit project (database + channels)

Turn the placeholder `profiles.yml` that `dtk init` writes into a **runnable**
connection, branching on the database backend, then verify it. Do not invent
hosts, ports, databases or webhook URLs — gather them from the user. For field
detail, read `.claude/rules/detectkit/project.md`; this skill is the procedure,
that file is the reference.

## What this skill does (read first)

`dtk init` ships a `profiles.yml` whose `dev` profile is a **placeholder**: it
validates and would run against a *local* ClickHouse, but its values
(`host: localhost`, empty password, `internal_database: detectkit`,
`data_database: default`) almost never match a real setup. Your job is to gather
the user's real connection details, point the profile at their database, and —
if they want alerts — add a working channel, then verify.

(If a run ever fails with `internal_database must be set for ClickHouse`, a
required location field was blanked or deleted — Step 3 restores it. Note there
is no `database:` field; ClickHouse needs `internal_database` **and**
`data_database`.)

## Step 0 — Locate or create the project

A project root contains `detectkit_project.yml` and `profiles.yml`. Find it (or
the nearest ancestor that has it). If there is none, ask for a project name and
run `dtk init <name>`, then work inside that folder. If several projects sit
side by side, ask which one to set up.

## Step 1 — Pick the database backend

**ClickHouse, PostgreSQL and MySQL are all fully supported.** Ask which one the
project uses (default to ClickHouse if unsure). `dtk init --db-type
{clickhouse,postgres,mysql}` scaffolds `profiles.yml` for the chosen backend.
The location fields differ:
- **ClickHouse** / **MySQL** — two *databases*: `internal_database` / `data_database`.
- **PostgreSQL** — connect to a `database` (must already exist), then two
  *schemas*: `internal_schema` / `data_schema`.

The metric query SQL dialect also differs (e.g. `toStartOfInterval` on
ClickHouse vs `date_trunc`/`to_timestamp` on Postgres vs `FROM_UNIXTIME` on
MySQL). Everything else — detectors, alerting, the CLI — is identical.

## Step 2 — Connection details (gather, don't guess)

Ask for, and confirm:

- `host` — ClickHouse host (e.g. `localhost`, `clickhouse.internal`).
- `port` — **native protocol** port (commonly `9000`, sometimes `9100`; TLS
  `9440`). Not the HTTP port `8123`.
- `user` — defaults to `default`.
- `password` — defaults to empty.

**Keep secrets out of YAML.** For passwords (and remote hosts) use environment
interpolation: `password: "{{ env_var('CLICKHOUSE_PASSWORD') }}"` (`${VAR}`
also works). `profiles.yml` resolves these when it loads; an *unresolved*
placeholder is kept as the literal string (not blanked to empty), so a missing
variable fails later at connect/send time, not at load — remind the user to
export it before running.

## Step 3 — Internal vs data location (both required)

Point **both** at the user's real databases (the placeholder ships example
values):

- `internal_database` — a dedicated database for detectkit's own `_dtk_*` tables
  (created automatically on first run). Keep it **separate** from your analytics
  data, e.g. `detectkit` or `monitoring`.
- `data_database` — where the source tables your metric queries read from live.

For Postgres these are `internal_schema` / `data_schema` (inside the connected
`database`); for MySQL they are `internal_database` / `data_database`.

## Step 4 — Profile name & `default_profile`

`dtk run` (with no `--profile`) uses **`profiles.yml`'s `default_profile`**, so
it must name a profile that exists in the same file (this is validated). Replace
the placeholder `dev`/`prod` profiles with the one you just configured — or keep
one and delete the other — and point `default_profile` at it. Set the
`default_profile` in `detectkit_project.yml` to the same value too (it isn't
read at runtime, but matching avoids confusion).

A clean result:

```yaml
# profiles.yml
default_profile: prod

profiles:
  prod:
    type: clickhouse
    host: "{{ env_var('CLICKHOUSE_HOST') }}"
    port: 9000
    user: "{{ env_var('CLICKHOUSE_USER') }}"
    password: "{{ env_var('CLICKHOUSE_PASSWORD') }}"
    internal_database: detectkit     # _dtk_* tables (kept separate from data)
    data_database: analytics         # where your source tables live
    settings:
      max_execution_time: 600
```

## Step 5 — First alert channel (optional)

If the user wants alerts now, add one channel under `alert_channels:` (it is
referenced by name from each metric's `alerting.channels`). Pick the type and
gather its required fields (see `project.md` for the full set per type):

The bot defaults to the **detectkit brand** name + avatar everywhere; the
identity fields below are optional overrides.

- **mattermost** / **slack** — `webhook_url` (use `env_var`); optional
  `channel`, `username`, `icon_url` (avatar; default brand), `icon_emoji`.
- **telegram** — `bot_token` (env_var) + `chat_id`. (Bot avatar is set in
  @BotFather, not by detectkit.)
- **email** — `smtp_host`, `smtp_port`, `from_email`, `to_emails` (list);
  optional `from_name` (From display name, default `detectkit`);
  `smtp_username` / `smtp_password` via env_var.
- **webhook** — generic `webhook_url` (required) + optional `extra_headers`
  (also accepts `username` / `icon_url` / `icon_emoji` / `channel`). There is
  no `url`, `method` or `headers` field.

```yaml
# at the end of profiles.yml
alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "{{ env_var('MATTERMOST_WEBHOOK_URL') }}"
    channel: "alerts"
    username: "detectkit"
```

If they don't want alerts yet, leave `alert_channels` empty — metrics still
load and detect; only the `alert` step needs a channel.

## Step 6 — Validate before declaring done

There is no `dtk validate` command, so verify with the cheapest real calls.
First re-read `profiles.yml` to confirm the YAML is well-formed, then:

```bash
# Connectivity + config + internal-table creation, non-destructive.
# Needs a metric to select; the `dtk init` starter is example_cpu_usage
# (its query won't match real tables, but `--steps load` still proves the
# connection and that _dtk_* tables get created).
dtk run --select example_cpu_usage --steps load

# If a channel was configured and a metric references it:
dtk test-alert <metric_name>
```

Interpret failures:

- `internal_database must be set` / `data_database must be set` → that Step 3
  location field is blank or missing (a `database:` key does nothing — it is not
  a real field; use `internal_database` / `data_database`).
- `Connection refused` / timeout → host/port wrong, or DB unreachable; check the
  native port (not `8123`).
- `default_profile '<x>' not found` → Step 4: `default_profile` names a profile
  that isn't defined.
- unresolved `{{ env_var('…') }}` → the variable isn't exported in the shell.

## Step 7 — Final checklist

- [ ] The active profile has `type`, `host`, `port`, **`internal_database`**,
      **`data_database`** (no leftover `database:` key).
- [ ] Secrets use `env_var`/`${VAR}`, and the user knows which vars to export.
- [ ] `profiles.yml`'s `default_profile` names an existing profile (and
      `detectkit_project.yml` matches).
- [ ] Any configured channel has all required fields for its type.
- [ ] A `--steps load` run connects and creates the `_dtk_*` tables.

Then point the user at the **`dtk-new-metric`** skill to scaffold their first
real metric, and at `dtk run --select <metric>` to run the full pipeline.

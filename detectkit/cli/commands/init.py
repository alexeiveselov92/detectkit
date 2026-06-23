"""
Implementation of 'dtk init' command.

Creates a new detectkit project with proper structure.
"""

from pathlib import Path

import click

# Active dev/prod profile blocks per backend (indented under `profiles:`).
_ACTIVE_PROFILES = {
    "clickhouse": """  # Local dev — runnable against a local ClickHouse once the databases exist.
  # ClickHouse needs BOTH locations (there is no `database:` field):
  #   internal_database -> where detectkit's own _dtk_* tables live
  #   data_database     -> where your metric source tables live
  dev:
    type: clickhouse
    host: localhost
    port: 9000            # native protocol (not the 8123 HTTP port)
    user: default
    password: ""
    internal_database: detectkit   # _dtk_* tables (create this database once)
    data_database: default         # your source data lives here

  # Production — keep secrets in env vars, never commit credentials.
  prod:
    type: clickhouse
    host: "{{ env_var('CLICKHOUSE_HOST') }}"
    port: 9000
    user: "{{ env_var('CLICKHOUSE_USER') }}"
    password: "{{ env_var('CLICKHOUSE_PASSWORD') }}"
    internal_database: detectkit   # _dtk_* tables
    data_database: monitoring      # your source data
""",
    "postgres": """  # Local dev — runnable against a local PostgreSQL. PostgreSQL uses SCHEMAS:
  #   database        -> the database to connect to (must already exist)
  #   internal_schema -> schema for detectkit's own _dtk_* tables (auto-created)
  #   data_schema     -> schema your metric source tables live in
  dev:
    type: postgres
    host: localhost
    port: 5432
    user: postgres
    password: postgres
    database: detectkit
    internal_schema: detectkit
    data_schema: public

  # Production — keep secrets in env vars, never commit credentials.
  prod:
    type: postgres
    host: "{{ env_var('POSTGRES_HOST') }}"
    port: 5432
    user: "{{ env_var('POSTGRES_USER') }}"
    password: "{{ env_var('POSTGRES_PASSWORD') }}"
    database: "{{ env_var('POSTGRES_DB') }}"
    internal_schema: detectkit
    data_schema: public
""",
    "mysql": """  # Local dev — runnable against a local MySQL (8.0+). MySQL uses DATABASES:
  #   internal_database -> database for detectkit's own _dtk_* tables (auto-created)
  #   data_database     -> database your metric source tables live in
  dev:
    type: mysql
    host: localhost
    port: 3306
    user: root
    password: ""
    internal_database: detectkit
    data_database: analytics

  # Production — keep secrets in env vars, never commit credentials.
  prod:
    type: mysql
    host: "{{ env_var('MYSQL_HOST') }}"
    port: 3306
    user: "{{ env_var('MYSQL_USER') }}"
    password: "{{ env_var('MYSQL_PASSWORD') }}"
    internal_database: detectkit
    data_database: monitoring
""",
}

# Commented single-profile examples for the backends that are NOT active.
_COMMENTED_EXAMPLES = {
    "clickhouse": """  # Example ClickHouse profile (needs internal_database + data_database)
  # clickhouse_dev:
  #   type: clickhouse
  #   host: localhost
  #   port: 9000
  #   user: default
  #   password: ""
  #   internal_database: detectkit
  #   data_database: default
""",
    "postgres": """  # Example PostgreSQL profile (connect to `database`; tables live in schemas)
  # postgres_dev:
  #   type: postgres
  #   host: localhost
  #   port: 5432
  #   user: postgres
  #   password: postgres
  #   database: detectkit
  #   internal_schema: detectkit
  #   data_schema: public
""",
    "mysql": """  # Example MySQL profile (8.0+; internal_database + data_database)
  # mysql_dev:
  #   type: mysql
  #   host: localhost
  #   port: 3306
  #   user: root
  #   password: ""
  #   internal_database: detectkit
  #   data_database: analytics
""",
}

# Timestamp-bucketing expression for the example metric query, per dialect.
_BUCKET_SQL = {
    "clickhouse": "toStartOfInterval(event_time, INTERVAL {{ interval_seconds }} SECOND)",
    "postgres": (
        "to_timestamp(floor(extract(epoch from event_time) / {{ interval_seconds }})"
        " * {{ interval_seconds }})"
    ),
    "mysql": (
        "FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(event_time) / {{ interval_seconds }})"
        " * {{ interval_seconds }})"
    ),
}

# Example incidents (labels) file for supervised `dtk autotune`. Lives in
# incidents/ beside metrics/; pointed at via `--incidents` or a metric's
# `autotune.labels_file`. See docs/guides/autotuning.md.
_EXAMPLE_INCIDENTS = """# Example incidents (labels) file for supervised `dtk autotune`.
#
# Tell autotune WHICH points were real incidents so it can pick the detector,
# threshold, seasonality and alert window that catch them while keeping false
# positives down. Hand it to autotune with:
#
#   dtk autotune --select example_cpu_usage --incidents incidents/example_cpu_usage.yml
#
# ...or reference it from the metric's `autotune.labels_file:` (see
# metrics/example_cpu_usage.yml). Without any labels, autotune falls back to an
# unsupervised objective (low false-positive rate + stable cross-fold separation).
#
# Format:
# - YAML or JSON. ALL times are UTC unless `timezone:` says otherwise.
# - Each incident is EITHER an interval ({start, end}) for a sustained problem
#   OR a point ({at}) for a single spike — never both keys. `end` is inclusive.
# - `label` is optional free text (documentation only).
#
# Tip: can't list incidents from memory? Run
#   dtk autotune --select example_cpu_usage --label
# to get a clickable HTML chart; mark incidents in a browser and export this file.

# Optional — must match the metric `name:` it labels (autotune refuses a mismatch).
metric: example_cpu_usage

# Optional — interprets the naive times below (defaults to UTC).
timezone: UTC

incidents:
  # Interval incident (a sustained problem):
  - start: "2026-05-02 14:00:00"
    end:   "2026-05-02 16:30:00"
    label: example sustained spike      # optional, free text

  # Point incident (a single anomalous timestamp):
  - at: "2026-05-11 09:05:00"
    label: example one-off spike
"""

# Alert-channel section (backend-independent); appended after the profiles.
_ALERT_CHANNELS = """
# Alert channels (referenced by name from a metric's alerting.channels)
alert_channels:
  # Mattermost. Supported keys: webhook_url, username, icon_url, icon_emoji,
  # channel, timeout. The bot name + avatar default to the detectkit brand;
  # override the avatar with icon_url (an image URL) or icon_emoji (an emoji).
  mattermost_alerts:
    type: mattermost
    webhook_url: "{{ env_var('MATTERMOST_WEBHOOK_URL') }}"
    # username: detectkit              # optional — override the display name
    # icon_url: "https://.../bot.png"  # optional — override the brand avatar
    # icon_emoji: ":warning:"          # optional — emoji instead of an avatar

  # Slack example (same fields as mattermost)
  # slack_alerts:
  #   type: slack
  #   webhook_url: "{{ env_var('SLACK_WEBHOOK_URL') }}"
  #   channel: "#alerts"

  # Telegram example (required: bot_token, chat_id)
  # telegram_alerts:
  #   type: telegram
  #   bot_token: "{{ env_var('TELEGRAM_BOT_TOKEN') }}"
  #   chat_id: "{{ env_var('TELEGRAM_CHAT_ID') }}"

  # Email example (required: smtp_host, smtp_port, from_email, to_emails)
  # email_alerts:
  #   type: email
  #   smtp_host: smtp.gmail.com
  #   smtp_port: 587
  #   from_email: alerts@example.com
  #   from_name: detectkit          # optional — From display name (default: detectkit)
  #   to_emails:
  #     - team@example.com
  #   smtp_username: "{{ env_var('SMTP_USERNAME') }}"
  #   smtp_password: "{{ env_var('SMTP_PASSWORD') }}"

  # Generic webhook example (required: webhook_url; optional extra_headers)
  # webhook_alerts:
  #   type: webhook
  #   webhook_url: "{{ env_var('WEBHOOK_URL') }}"
  #   extra_headers:
  #     Authorization: "Bearer {{ env_var('WEBHOOK_TOKEN') }}"
"""


def run_init(project_name: str, target_dir: str, db_type: str = "clickhouse"):
    """
    Initialize a new detectkit project.

    Args:
        project_name: Name of the project (or path - will extract basename)
        target_dir: Directory to create project in

    Creates:
        project_name/
        ├── detectkit_project.yml
        ├── profiles.yml
        ├── metrics/
        │   └── example_cpu_usage.yml
        ├── incidents/
        │   └── example_cpu_usage.yml   # labels for supervised `dtk autotune`
        └── sql/
            └── .gitkeep
    """
    # Extract just the directory name in case user passes a full path
    project_name_clean = Path(project_name).name
    target_path = Path(target_dir) / project_name_clean

    # Check if project already exists
    if target_path.exists():
        click.echo(
            click.style(
                f"Error: Directory '{target_path}' already exists!",
                fg="red",
                bold=True,
            )
        )
        return

    # Create project directory
    click.echo(f"Creating detectkit project '{project_name_clean}' in {target_dir}...")

    target_path.mkdir(parents=True, exist_ok=True)

    # Create subdirectories
    (target_path / "metrics").mkdir(exist_ok=True)
    (target_path / "incidents").mkdir(exist_ok=True)
    (target_path / "sql").mkdir(exist_ok=True)

    # Create .gitkeep files (incidents/ is kept by its example file below)
    (target_path / "metrics" / ".gitkeep").touch()
    (target_path / "sql" / ".gitkeep").touch()

    # Example incidents (labels) file for supervised `dtk autotune`
    (target_path / "incidents" / "example_cpu_usage.yml").write_text(_EXAMPLE_INCIDENTS)

    # Create detectkit_project.yml
    project_config = f"""# detectkit project configuration
name: {project_name_clean}
version: '1.0'

# Directory paths. These are the real config keys (nested under `paths:`);
# a flat `metrics_path:` / `sql_path:` is not a recognized field and is ignored.
paths:
  metrics: metrics
  sql: sql
  templates: templates

# Default profile to use (must exist in profiles.yml)
default_profile: dev

# Default table names (can be overridden in metrics)
tables:
  datapoints: _dtk_datapoints
  detections: _dtk_detections
  tasks: _dtk_tasks

# Default timeouts (seconds)
timeouts:
  load: 1800      # 30 minutes
  detect: 3600    # 1 hour
  alert: 300      # 5 minutes
"""

    (target_path / "detectkit_project.yml").write_text(project_config)

    # Create profiles.yml (must validate against ProfilesConfig: connections
    # live under a top-level 'profiles:' mapping). The active dev/prod profiles
    # are scaffolded for the chosen --db-type; the other backends are included
    # as commented examples. See the per-database docs for connection details.
    other_backends = [t for t in ("clickhouse", "postgres", "mysql") if t != db_type]
    commented = "\n".join(_COMMENTED_EXAMPLES[t] for t in other_backends)
    profiles_config = (
        "# Database connection profiles\n\n"
        "default_profile: dev\n\n"
        "profiles:\n"
        f"{_ACTIVE_PROFILES[db_type]}\n"
        f"{commented}"
        f"{_ALERT_CHANNELS}"
    )

    (target_path / "profiles.yml").write_text(profiles_config)

    # Create example metric (must validate against MetricConfig). The
    # timestamp-bucketing expression is dialect-specific; it is substituted for
    # the __DTK_BUCKET__ sentinel below so the Jinja `{{ }}` placeholders in the
    # rest of the query are left untouched.
    example_metric = """# Example metric configuration
name: example_cpu_usage
description: CPU usage monitoring example

# Data source. Built-in template variables:
#   {{ dtk_start_time }} / {{ dtk_end_time }} - load window bounds
#   {{ interval_seconds }} - metric interval in seconds
query: |
  SELECT
    __DTK_BUCKET__ AS timestamp,
    avg(cpu_usage) AS value
  FROM system_metrics
  WHERE event_time >= '{{ dtk_start_time }}'
    AND event_time < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

# Or use external SQL file:
# query_file: sql/cpu_usage.sql

# Time interval between datapoints
interval: 1min

# Seasonality features extracted from timestamps (used by detectors
# with seasonality_components)
seasonality_columns:
  - hour
  - day_of_week

# Anomaly detectors
detectors:
  - type: mad
    params:
      threshold: 3.0       # sigma-equivalents (MAD is scaled by 1.4826)
      window_size: 1440    # 1 day of 1-min points
      min_samples: 100
      # Group statistics by seasonality (uses seasonality_columns):
      # seasonality_components: ["hour"]
      # For metrics with a gradual trend, enable recency weighting:
      # window_weights: exponential
      # half_life: "6h"
      # detrend: linear

  - type: zscore
    params:
      threshold: 3.0
      window_size: 1440
      min_samples: 100

# Alerting (optional)
alerting:
  enabled: true

  # Alert channel names (defined in profiles.yml)
  channels:
    - mattermost_alerts

  # Alert conditions
  min_detectors: 1            # detectors that must agree
  direction: same             # same | any | up | down
  consecutive_anomalies: 3    # adjacent anomalous points required
  no_data_alert: false        # alert when the latest interval has no data
  # alert_cooldown: "2h"      # recommended: suppress repeats of a persisting anomaly

# Auto-tuning (optional) — `dtk autotune --select example_cpu_usage` picks the
# detector config for you. Supply known incidents to tune supervised; either
# point at a labels file OR declare them inline (the two are mutually exclusive).
# autotune:
#   enabled: true
#   # (a) external labels file (see incidents/example_cpu_usage.yml):
#   labels_file: incidents/example_cpu_usage.yml
#   # (b) — or — inline incidents:
#   # incidents:
#   #   - {start: "2026-05-02 14:00:00", end: "2026-05-02 16:30:00", label: outage}
#   #   - {at: "2026-05-11 09:05:00", label: deploy spike}
#   # incidents_timezone: UTC   # interprets the naive times above (default UTC)

# Tags for selection
tags:
  - critical
  - system
"""

    example_metric = example_metric.replace("__DTK_BUCKET__", _BUCKET_SQL[db_type])
    (target_path / "metrics" / "example_cpu_usage.yml").write_text(example_metric)

    # Create README
    readme = f"""# {project_name}

detectkit monitoring project.

## Getting Started

1. Configure your database connection in `profiles.yml`

2. Create metric definitions in `metrics/` directory

3. Run metrics:
   ```bash
   cd {project_name}
   dtk run --select example_cpu_usage
   ```

## Project Structure

- `detectkit_project.yml` - Project configuration
- `profiles.yml` - Database connection profiles
- `metrics/` - Metric definitions (YAML files)
- `incidents/` - Labeled incidents for supervised `dtk autotune` (optional)
- `sql/` - SQL query files (optional)

## Commands

```bash
# Run single metric
dtk run --select cpu_usage

# Run with specific steps
dtk run --select cpu_usage --steps load,detect

# Run metrics by tag
dtk run --select tag:critical

# Reload data from specific date
dtk run --select cpu_usage --from 2024-01-01

# Full refresh
dtk run --select cpu_usage --full-refresh

# Clear a stuck lock left by a crashed run (e.g. DB restarted mid-run)
dtk unlock --select cpu_usage
```

## Documentation

See https://github.com/alexeiveselov92/detectkit for full documentation.
"""

    (target_path / "README.md").write_text(readme)

    # Success message
    click.echo()
    click.echo(click.style("✓ Project created successfully!", fg="green", bold=True))
    click.echo()
    click.echo("Your new detectkit project is ready!")
    click.echo()
    click.echo("Next steps:")
    click.echo(f"  1. cd {project_name}")
    click.echo(f"  2. Configure your {db_type} connection in profiles.yml")
    click.echo("  3. Create or edit metric definitions in metrics/")
    click.echo("  4. Run: dtk run --select example_cpu_usage")
    click.echo()

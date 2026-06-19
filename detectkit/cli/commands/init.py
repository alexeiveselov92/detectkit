"""
Implementation of 'dtk init' command.

Creates a new detectkit project with proper structure.
"""

from pathlib import Path

import click


def run_init(project_name: str, target_dir: str):
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
        │   └── .gitkeep
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
    (target_path / "sql").mkdir(exist_ok=True)

    # Create .gitkeep files
    (target_path / "metrics" / ".gitkeep").touch()
    (target_path / "sql" / ".gitkeep").touch()

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
    # live under a top-level 'profiles:' mapping). ClickHouse needs BOTH
    # `internal_database` (for the _dtk_* tables) and `data_database` (where the
    # metric queries read from) — there is no `database:` field, so the dev
    # profile below is runnable as-is against a local ClickHouse.
    profiles_config = """# Database connection profiles

default_profile: dev

profiles:
  # Local dev — runnable against a local ClickHouse once the databases exist.
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

  # Example PostgreSQL profile (uses internal_schema / data_schema)
  # postgres_dev:
  #   type: postgres
  #   host: localhost
  #   port: 5432
  #   user: postgres
  #   password: postgres
  #   internal_schema: detectkit
  #   data_schema: public

  # Example MySQL profile
  # mysql_dev:
  #   type: mysql
  #   host: localhost
  #   port: 3306
  #   user: root
  #   password: root
  #   internal_database: detectkit
  #   data_database: analytics

# Alert channels (referenced by name from a metric's alerting.channels)
alert_channels:
  # Mattermost. Supported keys: webhook_url, username, icon_emoji, channel,
  # timeout. NOTE: there is no `icon_url` param — use `icon_emoji`.
  mattermost_alerts:
    type: mattermost
    webhook_url: "{{ env_var('MATTERMOST_WEBHOOK_URL') }}"
    username: detectkit
    icon_emoji: ":warning:"

  # Slack example (same fields as mattermost)
  # slack_alerts:
  #   type: slack
  #   webhook_url: "{{ env_var('SLACK_WEBHOOK_URL') }}"
  #   channel: "#alerts"
  #   username: detectkit

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

    (target_path / "profiles.yml").write_text(profiles_config)

    # Create example metric (must validate against MetricConfig)
    example_metric = """# Example metric configuration
name: example_cpu_usage
description: CPU usage monitoring example

# Data source. Built-in template variables:
#   {{ dtk_start_time }} / {{ dtk_end_time }} - load window bounds
#   {{ interval_seconds }} - metric interval in seconds
query: |
  SELECT
    toStartOfInterval(event_time, INTERVAL {{ interval_seconds }} SECOND) AS timestamp,
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

# Tags for selection
tags:
  - critical
  - system
"""

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
    click.echo("  2. Configure database connection in profiles.yml")
    click.echo("  3. Create or edit metric definitions in metrics/")
    click.echo("  4. Run: dtk run --select example_cpu_usage")
    click.echo()

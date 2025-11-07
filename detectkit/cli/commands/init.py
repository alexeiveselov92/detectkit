"""
Implementation of 'dtk init' command.

Creates a new detectkit project with proper structure.
"""

import os
from pathlib import Path

import click


def run_init(project_name: str, target_dir: str):
    """
    Initialize a new detectkit project.

    Args:
        project_name: Name of the project
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
    target_path = Path(target_dir) / project_name

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
    click.echo(f"Creating detectkit project '{project_name}' in {target_dir}...")

    target_path.mkdir(parents=True, exist_ok=True)

    # Create subdirectories
    (target_path / "metrics").mkdir(exist_ok=True)
    (target_path / "sql").mkdir(exist_ok=True)

    # Create .gitkeep files
    (target_path / "metrics" / ".gitkeep").touch()
    (target_path / "sql" / ".gitkeep").touch()

    # Create detectkit_project.yml
    project_config = f"""# detectkit project configuration
name: {project_name}
version: '1.0'

# Paths
metrics_path: metrics
sql_path: sql

# Default profile to use
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

    # Create profiles.yml
    profiles_config = """# Database connection profiles
# Copy this file to ~/.detectkit/profiles.yml for user-level config

dev:
  type: clickhouse
  host: localhost
  port: 9000
  database: default
  user: default
  password: ""

  # ClickHouse specific settings
  settings:
    max_execution_time: 300

prod:
  type: clickhouse
  host: "{{ env_var('CLICKHOUSE_HOST') }}"
  port: 9000
  database: monitoring
  user: "{{ env_var('CLICKHOUSE_USER') }}"
  password: "{{ env_var('CLICKHOUSE_PASSWORD') }}"

  settings:
    max_execution_time: 600

# Example PostgreSQL profile
# postgres_dev:
#   type: postgres
#   host: localhost
#   port: 5432
#   database: monitoring
#   user: postgres
#   password: postgres
#   schema: public

# Example MySQL profile
# mysql_dev:
#   type: mysql
#   host: localhost
#   port: 3306
#   database: monitoring
#   user: root
#   password: root

# Alert channels configuration
alert_channels:
  # Mattermost channel
  mattermost_alerts:
    type: mattermost
    webhook_url: "{{ env_var('MATTERMOST_WEBHOOK_URL') }}"
    username: detectkit
    icon_url: https://example.com/detectkit-icon.png

  # Slack channel example
  # slack_alerts:
  #   type: slack
  #   webhook_url: "{{ env_var('SLACK_WEBHOOK_URL') }}"
  #   channel: "#alerts"
  #   username: detectkit

  # Generic webhook example
  # webhook_alerts:
  #   type: webhook
  #   url: "{{ env_var('WEBHOOK_URL') }}"
  #   method: POST
  #   headers:
  #     Authorization: "Bearer {{ env_var('WEBHOOK_TOKEN') }}"
"""

    (target_path / "profiles.yml").write_text(profiles_config)

    # Create example metric
    example_metric = """# Example metric configuration
name: example_cpu_usage
description: CPU usage monitoring example

# Data source
query: |
  SELECT
    timestamp,
    cpu_usage as value
  FROM system_metrics
  WHERE metric_name = 'cpu_usage'
    AND timestamp >= {{ from_date }}
    AND timestamp < {{ to_date }}
  ORDER BY timestamp

# Or use external SQL file:
# query_file: sql/cpu_usage.sql

# Time interval between datapoints
interval: 1min

# Loading configuration
loading:
  fill_gaps: true
  max_gap_fill: 10  # Fill up to 10 missing points

  # Seasonality extraction
  extract_seasonality:
    - minute_of_hour
    - hour_of_day
    - day_of_week

# Anomaly detectors
detectors:
  - type: zscore
    params:
      threshold: 3.0
      window_size: 100

  - type: mad
    params:
      threshold: 3.0
      window_size: 100

# Alerting (optional)
alerting:
  enabled: true

  # Alert channel names (defined in profiles.yml)
  channels:
    - mattermost_alerts

  # Alert conditions
  consecutive_anomalies: 3
  alert_on_missing_data: false

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

"""
Main CLI entry point for detectkit.

Provides dbt-like commands:
- dtk init <project_name>
- dtk run --select <selector>
"""

import click


@click.group()
@click.version_option(version="0.1.0", prog_name="detectkit")
def cli():
    """
    detectkit - Metric monitoring with automatic anomaly detection.

    A dbt-like tool for monitoring time-series metrics with anomaly detection
    and alerting.

    Examples:
        dtk init my_project
        dtk run --select cpu_usage
        dtk run --select tag:critical --steps load,detect
    """
    pass


@cli.command()
@click.argument("project_name")
@click.option(
    "--target-dir",
    "-d",
    default=".",
    help="Directory to create project in (default: current directory)",
)
def init(project_name: str, target_dir: str):
    """
    Initialize a new detectkit project.

    Creates project structure with configuration files and directories:
    - detectkit_project.yml (project config)
    - profiles.yml (database connections)
    - metrics/ (metric definitions)
    - sql/ (SQL queries)

    Example:
        dtk init my_monitoring_project
        dtk init analytics --target-dir /opt/projects
    """
    from detectkit.cli.commands.init import run_init

    run_init(project_name, target_dir)


@cli.command()
@click.option(
    "--select",
    "-s",
    help="Selector for metrics to run (metric name, path, or tag)",
    required=True,
)
@click.option(
    "--exclude",
    "-e",
    help="Selector for metrics to exclude (metric name, path, or tag)",
)
@click.option(
    "--steps",
    default="load,detect,alert",
    help="Pipeline steps to execute (default: load,detect,alert)",
)
@click.option(
    "--from",
    "from_date",
    help="Start date for data loading (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)",
)
@click.option(
    "--to",
    "to_date",
    help="End date for data loading (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)",
)
@click.option(
    "--full-refresh",
    is_flag=True,
    help="Delete all existing data and reload from scratch",
)
@click.option(
    "--force",
    is_flag=True,
    help="Ignore task locks (use with caution)",
)
@click.option(
    "--profile",
    help="Profile to use (default: from project config)",
)
def run(
    select: str,
    exclude: str,
    steps: str,
    from_date: str,
    to_date: str,
    full_refresh: bool,
    force: bool,
    profile: str,
):
    """
    Run metric processing pipeline.

    Select metrics to process using --select:
    - Metric name: --select cpu_usage
    - Path pattern: --select metrics/critical/*.yml
    - Tag: --select tag:critical

    Control pipeline steps with --steps:
    - All steps: --steps load,detect,alert (default)
    - Load only: --steps load
    - Detect and alert: --steps detect,alert

    Examples:
        # Run all steps for single metric
        dtk run --select cpu_usage

        # Load data only for multiple metrics
        dtk run --select "tag:critical" --steps load

        # Reload data from specific date
        dtk run --select cpu_usage --from 2024-01-01

        # Full refresh (delete and reload all data)
        dtk run --select cpu_usage --full-refresh

        # Force run (ignore locks)
        dtk run --select cpu_usage --force
    """
    from detectkit.cli.commands.run import run_command

    run_command(
        select=select,
        exclude=exclude,
        steps=steps,
        from_date=from_date,
        to_date=to_date,
        full_refresh=full_refresh,
        force=force,
        profile=profile,
    )


@cli.command()
@click.argument("metric_name")
@click.option(
    "--profile",
    help="Profile to use (default: from project config)",
)
def test_alert(metric_name: str, profile: str):
    """
    Send test alert for a metric.

    Sends a test alert with mock anomaly data to all configured channels
    for the specified metric. Useful for:
    - Testing alert channel connectivity
    - Verifying message formatting and rendering
    - Previewing custom alert templates

    The test alert uses realistic mock data:
    - Current timestamp
    - Mock anomaly value (0.8532)
    - Mock confidence interval [0.4521, 0.6234]
    - Mock severity (4.52)
    - 3 consecutive anomalies

    Examples:
        # Test alert for single metric
        dtk test-alert cpu_usage

        # Test with specific profile
        dtk test-alert cpu_usage --profile production
    """
    from detectkit.cli.commands.test_alert import run_test_alert

    run_test_alert(metric_name=metric_name, profile=profile)


if __name__ == "__main__":
    cli()

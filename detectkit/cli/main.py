"""
Main CLI entry point for detectkit.

Provides dbt-like commands:
- dtk init <project_name>
- dtk run --select <selector>
"""

import click

from detectkit import __version__


@click.group()
@click.version_option(version=__version__, prog_name="detectkit")
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
@click.option(
    "--db-type",
    type=click.Choice(["clickhouse", "postgres", "mysql"]),
    default="clickhouse",
    show_default=True,
    help="Database backend to scaffold the dev/prod profiles and example query for.",
)
def init(project_name: str, target_dir: str, db_type: str):
    """
    Initialize a new detectkit project.

    Creates project structure with configuration files and directories:
    - detectkit_project.yml (project config)
    - profiles.yml (database connections — for the chosen --db-type)
    - metrics/ (metric definitions)
    - sql/ (SQL queries)

    Example:
        dtk init my_monitoring_project
        dtk init analytics --target-dir /opt/projects
        dtk init my_project --db-type postgres
    """
    from detectkit.cli.commands.init import run_init

    run_init(project_name, target_dir, db_type=db_type)


@cli.command(name="init-claude")
@click.option(
    "--target-dir",
    "-d",
    default=".",
    help="Folder holding your detectkit project(s) (default: current directory)",
)
def init_claude(target_dir: str):
    """
    Set up Claude Code context for working with detectkit.

    Scaffolds AI-assistant context into the folder that holds your detectkit
    project(s), so Claude can natively help you create metrics, tune detectors,
    configure alerts and run the pipeline. Writes:

    - CLAUDE.md (created, or a managed detectkit block is injected/refreshed —
      your own content is preserved)
    - .claude/rules/detectkit/ (reference docs the assistant reads on demand)
    - .claude/skills/ (e.g. the dtk-new-metric skill)

    The content ships with detectkit and tracks the installed version, so
    re-run this after upgrading to refresh it. The operation is idempotent.

    Example:
        dtk init-claude
        dtk init-claude --target-dir /opt/monitoring
    """
    from detectkit.cli.commands.init_claude import run_init_claude

    run_init_claude(target_dir)


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


@cli.command()
@click.option(
    "--select",
    "-s",
    help="Selector for metrics to unlock (metric name, path, or tag)",
    required=True,
)
@click.option(
    "--profile",
    help="Profile to use (default: from project config)",
)
def unlock(select: str, profile: str):
    """
    Clear stale pipeline locks for the selected metric(s).

    Use this to recover from a run that died without releasing its lock
    (e.g. the database restarted mid-run), which would otherwise make
    subsequent runs fail with "Failed to acquire lock ... Use --force".

    Locks also auto-expire after their timeout, so this is only needed to
    clear a stuck lock immediately. Selector semantics match `dtk run`.

    Examples:
        # Unlock a single metric
        dtk unlock --select cpu_usage

        # Unlock everything matching a tag
        dtk unlock --select "tag:critical"
    """
    from detectkit.cli.commands.unlock import run_unlock

    run_unlock(select=select, profile=profile)


@cli.command()
@click.option(
    "--select",
    "-s",
    help="Selector for metrics whose stale detector/alert data to prune (name, path, or tag)",
)
@click.option(
    "--orphaned-metrics",
    is_flag=True,
    help="Purge all data for metrics no longer present in the project (renamed/deleted YAML)",
)
@click.option(
    "--execute",
    is_flag=True,
    help="Actually delete (default: dry-run, only report what would be removed)",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip the confirmation prompt (for --orphaned-metrics --execute)",
)
@click.option(
    "--profile",
    help="Profile to use (default: from project config)",
)
def clean(select: str, orphaned_metrics: bool, execute: bool, yes: bool, profile: str):
    """
    Remove internal data that no longer matches the project's YAML configs.

    Over time, editing metrics on production leaves stale rows behind: changing
    a detector parameter (or removing a detector) orphans its old results in
    _dtk_detections, changing an alerting block orphans its state in
    _dtk_alert_states, and renaming/deleting a metric orphans everything under
    its old name. This command finds and removes that drift.

    Both modes default to a dry-run; pass --execute to actually delete.
    Selector semantics match `dtk run`.

    Examples:
        # Prune stale detector/alert data for one metric (dry-run)
        dtk clean --select cpu_usage

        # ...and actually delete it
        dtk clean --select cpu_usage --execute

        # Prune everything matching a tag
        dtk clean --select "tag:critical" --execute

        # Purge metrics that no longer exist in the project
        dtk clean --orphaned-metrics
        dtk clean --orphaned-metrics --execute
    """
    from detectkit.cli.commands.clean import run_clean

    run_clean(
        select=select,
        orphaned_metrics=orphaned_metrics,
        execute=execute,
        yes=yes,
        profile=profile,
    )


if __name__ == "__main__":
    cli()

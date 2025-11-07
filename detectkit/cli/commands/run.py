"""
Implementation of 'dtk run' command.

Executes metric processing pipeline.
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional

import click

from detectkit.config.metric_config import MetricConfig
from detectkit.config.profile import ProfilesConfig
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.orchestration.task_manager import PipelineStep, TaskManager


def run_command(
    select: str,
    exclude: Optional[str],
    steps: str,
    from_date: Optional[str],
    to_date: Optional[str],
    full_refresh: bool,
    force: bool,
    profile: Optional[str],
):
    """
    Execute metric processing pipeline.

    Args:
        select: Metric selector (name, path, or tag)
        exclude: Metrics to exclude (name, path, or tag)
        steps: Comma-separated pipeline steps
        from_date: Start date string
        to_date: End date string
        full_refresh: Delete and reload all data
        force: Ignore task locks
        profile: Profile name to use
    """
    # Parse steps
    step_list = parse_steps(steps)

    # Parse dates
    from_dt = parse_date(from_date) if from_date else None
    to_dt = parse_date(to_date) if to_date else None

    # Find project root and load config
    project_root = find_project_root()
    if not project_root:
        click.echo(
            click.style(
                "Error: Not in a detectkit project directory!",
                fg="red",
                bold=True,
            )
        )
        click.echo("Run 'dtk init <project_name>' to create a new project.")
        return

    click.echo(f"Project root: {project_root}")

    # Load project config
    # project_config = load_project_config(project_root)

    # Select metrics based on selector
    metrics = select_metrics(select, project_root)

    # Exclude metrics if specified
    if exclude:
        excluded_metrics = select_metrics(exclude, project_root)
        excluded_names = {m.name for m in excluded_metrics}
        metrics = [m for m in metrics if m.name not in excluded_names]

        if excluded_metrics:
            click.echo(f"Excluded {len(excluded_metrics)} metric(s) matching: {exclude}")

    if not metrics:
        click.echo(
            click.style(
                f"No metrics found matching selector: {select}",
                fg="yellow",
            )
        )
        return

    click.echo(f"Found {len(metrics)} metric(s) to process")
    click.echo()

    # Load profiles.yml
    profiles_path = project_root / "profiles.yml"
    if not profiles_path.exists():
        click.echo(
            click.style(
                "Error: profiles.yml not found!",
                fg="red",
                bold=True,
            )
        )
        click.echo(f"Expected at: {profiles_path}")
        return

    try:
        profiles_config = ProfilesConfig.from_yaml(profiles_path)
    except Exception as e:
        click.echo(
            click.style(
                f"Error loading profiles.yml: {e}",
                fg="red",
                bold=True,
            )
        )
        return

    # Create database manager
    try:
        db_manager = profiles_config.create_manager(profile)
    except Exception as e:
        click.echo(
            click.style(
                f"Error creating database manager: {e}",
                fg="red",
                bold=True,
            )
        )
        return

    # Create internal tables manager
    internal_manager = InternalTablesManager(db_manager)

    # Initialize internal tables if needed
    try:
        internal_manager.ensure_tables()
    except Exception as e:
        click.echo(
            click.style(
                f"Error initializing internal tables: {e}",
                fg="red",
                bold=True,
            )
        )
        return

    # Create task manager
    task_manager = TaskManager(
        internal_manager=internal_manager,
        db_manager=db_manager,
        profiles_config=profiles_config,
    )

    # Process each metric
    for metric_path in metrics:
        process_metric(
            metric_path=metric_path,
            project_root=project_root,
            task_manager=task_manager,
            steps=step_list,
            from_date=from_dt,
            to_date=to_dt,
            full_refresh=full_refresh,
            force=force,
        )


def parse_steps(steps_str: str) -> List[PipelineStep]:
    """
    Parse comma-separated steps string.

    Args:
        steps_str: Comma-separated steps (e.g., "load,detect,alert")

    Returns:
        List of PipelineStep enums

    Example:
        >>> parse_steps("load,detect")
        [PipelineStep.LOAD, PipelineStep.DETECT]
    """
    step_map = {
        "load": PipelineStep.LOAD,
        "detect": PipelineStep.DETECT,
        "alert": PipelineStep.ALERT,
    }

    steps = []
    for step_str in steps_str.split(","):
        step_str = step_str.strip().lower()
        if step_str not in step_map:
            raise click.BadParameter(
                f"Invalid step: {step_str}. Valid steps: load, detect, alert"
            )
        steps.append(step_map[step_str])

    return steps


def parse_date(date_str: str) -> datetime:
    """
    Parse date string to datetime.

    Supports formats:
    - YYYY-MM-DD
    - YYYY-MM-DD HH:MM:SS

    Args:
        date_str: Date string

    Returns:
        datetime object

    Raises:
        click.BadParameter: If date format is invalid
    """
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    raise click.BadParameter(
        f"Invalid date format: {date_str}. "
        f"Use YYYY-MM-DD or 'YYYY-MM-DD HH:MM:SS'"
    )


def find_project_root() -> Optional[Path]:
    """
    Find detectkit project root by looking for detectkit_project.yml.

    Searches current directory and parent directories.

    Returns:
        Path to project root or None if not found
    """
    current = Path.cwd()

    # Search up to 10 levels up
    for _ in range(10):
        if (current / "detectkit_project.yml").exists():
            return current

        if current.parent == current:
            # Reached filesystem root
            break

        current = current.parent

    return None


def select_metrics(selector: str, project_root: Path) -> List[Path]:
    """
    Select metrics based on selector.

    Selector types:
    - Metric name: "cpu_usage"
    - Path pattern: "metrics/critical/*.yml"
    - Tag: "tag:critical"

    Args:
        selector: Selector string
        project_root: Project root path

    Returns:
        List of metric file paths
    """
    metrics_dir = project_root / "metrics"

    if not metrics_dir.exists():
        return []

    # Tag selector
    if selector.startswith("tag:"):
        tag = selector[4:]
        return find_metrics_by_tag(metrics_dir, tag)

    # Path pattern selector
    if "*" in selector or "/" in selector:
        pattern = selector if selector.startswith("metrics/") else f"metrics/{selector}"
        return list(project_root.glob(pattern))

    # Metric name selector
    metric_file = metrics_dir / f"{selector}.yml"
    if metric_file.exists():
        return [metric_file]

    # Try with .yaml extension
    metric_file = metrics_dir / f"{selector}.yaml"
    if metric_file.exists():
        return [metric_file]

    return []


def find_metrics_by_tag(metrics_dir: Path, tag: str) -> List[Path]:
    """
    Find all metrics with specific tag.

    Args:
        metrics_dir: Metrics directory path
        tag: Tag to search for

    Returns:
        List of metric paths with this tag
    """
    import yaml

    matching_metrics = []

    for metric_file in metrics_dir.glob("**/*.yml"):
        try:
            with open(metric_file) as f:
                config = yaml.safe_load(f)

            if config and "tags" in config:
                if tag in config["tags"]:
                    matching_metrics.append(metric_file)
        except Exception:
            # Skip files that can't be parsed
            continue

    return matching_metrics


def process_metric(
    metric_path: Path,
    project_root: Path,
    task_manager: TaskManager,
    steps: List[PipelineStep],
    from_date: Optional[datetime],
    to_date: Optional[datetime],
    full_refresh: bool,
    force: bool,
):
    """
    Process a single metric.

    Args:
        metric_path: Path to metric YAML file
        project_root: Project root directory
        task_manager: Task manager instance
        steps: Pipeline steps to execute
        from_date: Start date
        to_date: End date
        full_refresh: Full refresh flag
        force: Force flag
    """
    metric_name = metric_path.stem

    click.echo(click.style(f"Processing: {metric_name}", fg="cyan", bold=True))
    click.echo(f"  File: {metric_path}")
    click.echo(f"  Steps: {', '.join(s.value for s in steps)}")

    if from_date:
        click.echo(f"  From: {from_date}")
    if to_date:
        click.echo(f"  To: {to_date}")
    if full_refresh:
        click.echo(click.style("  Full refresh: YES", fg="yellow"))
    if force:
        click.echo(click.style("  Force: YES (ignoring locks)", fg="yellow"))

    click.echo()

    # Load metric configuration
    try:
        config = MetricConfig.from_yaml_file(metric_path)
    except Exception as e:
        click.echo(
            click.style(
                f"  ✗ Error loading metric config: {e}",
                fg="red",
            )
        )
        click.echo()
        return

    # Run pipeline
    try:
        result = task_manager.run_metric(
            config=config,
            steps=steps,
            from_date=from_date,
            to_date=to_date,
            full_refresh=full_refresh,
            force=force,
        )

        # Display results
        if result["status"] == "success":
            click.echo(click.style("  ✓ Success!", fg="green", bold=True))

            if PipelineStep.LOAD in steps:
                click.echo(f"    Loaded: {result['datapoints_loaded']} datapoints")

            if PipelineStep.DETECT in steps:
                click.echo(f"    Detected: {result['anomalies_detected']} anomalies")

            if PipelineStep.ALERT in steps:
                click.echo(f"    Sent: {result['alerts_sent']} alerts")
        else:
            click.echo(
                click.style(
                    f"  ✗ Failed: {result['error']}",
                    fg="red",
                    bold=True,
                )
            )

    except Exception as e:
        click.echo(
            click.style(
                f"  ✗ Pipeline error: {e}",
                fg="red",
                bold=True,
            )
        )
        import traceback
        click.echo(traceback.format_exc())

    click.echo()

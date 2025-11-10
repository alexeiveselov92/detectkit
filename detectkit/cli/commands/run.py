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
from detectkit.config.project_config import ProjectConfig
from detectkit.config.validator import validate_metric_uniqueness
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
    project_config_path = project_root / "detectkit_project.yml"
    try:
        project_config = ProjectConfig.from_yaml_file(project_config_path)
    except Exception as e:
        click.echo(
            click.style(
                f"Error loading detectkit_project.yml: {e}",
                fg="red",
                bold=True,
            )
        )
        return

    # Select metrics based on selector
    # Returns list of (path, config) tuples with uniqueness validation
    try:
        metrics = select_metrics(select, project_root)
    except ValueError as e:
        click.echo(
            click.style(
                f"Error: {e}",
                fg="red",
                bold=True,
            )
        )
        return

    # Exclude metrics if specified
    if exclude:
        try:
            excluded_metrics = select_metrics(exclude, project_root)
            excluded_names = {config.name for _, config in excluded_metrics}
            metrics = [(path, config) for path, config in metrics if config.name not in excluded_names]

            if excluded_metrics:
                click.echo(f"Excluded {len(excluded_metrics)} metric(s) matching: {exclude}")
        except ValueError as e:
            click.echo(
                click.style(
                    f"Error in exclusion selector: {e}",
                    fg="red",
                    bold=True,
                )
            )
            return

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
        project_config=project_config,
    )

    # Process each metric
    for metric_path, config in metrics:
        process_metric(
            metric_path=metric_path,
            config=config,
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


def select_metrics(selector: str, project_root: Path) -> List[tuple[Path, MetricConfig]]:
    """
    Select metrics based on selector and validate uniqueness.

    Selector types:
    - Metric name: "cpu_usage" (searches by 'name' field recursively in subdirectories)
    - Path pattern: "metrics/critical/*.yml" or "league/cpu_usage"
    - Tag: "tag:critical"

    For name selector:
    1. First tries filename-based search in root metrics/ directory
    2. If not found, searches recursively by 'name' field in all subdirectories

    Args:
        selector: Selector string
        project_root: Project root path

    Returns:
        List of (path, config) tuples for selected metrics

    Raises:
        ValueError: If duplicate metric names found or configs invalid
    """
    metrics_dir = project_root / "metrics"

    if not metrics_dir.exists():
        return []

    # Collect metric paths based on selector
    metric_paths: List[Path] = []

    # Tag selector
    if selector.startswith("tag:"):
        tag = selector[4:]
        metric_paths = find_metrics_by_tag(metrics_dir, tag)
    # Path pattern selector
    elif "*" in selector or "/" in selector:
        pattern = selector if selector.startswith("metrics/") else f"metrics/{selector}"
        metric_paths = list(project_root.glob(pattern))
    # Metric name selector
    else:
        # First try filename-based search in root (backward compatibility)
        metric_file = metrics_dir / f"{selector}.yml"
        if metric_file.exists():
            metric_paths = [metric_file]
        else:
            # Try with .yaml extension
            metric_file = metrics_dir / f"{selector}.yaml"
            if metric_file.exists():
                metric_paths = [metric_file]
            else:
                # Fall back to recursive search by 'name' field
                found_metric = find_metric_by_name(metrics_dir, selector)
                if found_metric:
                    metric_paths = [found_metric]

    if not metric_paths:
        return []

    # Validate uniqueness and load configs
    # This will raise ValueError if duplicate metric names found
    return validate_metric_uniqueness(metric_paths)


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


def find_metric_by_name(metrics_dir: Path, name: str) -> Optional[Path]:
    """
    Find metric by name field (searches recursively in subdirectories).

    Args:
        metrics_dir: Metrics directory path
        name: Metric name to search for (from 'name' field in YAML)

    Returns:
        Path to metric file if found, None otherwise
    """
    import yaml

    # Search both .yml and .yaml extensions
    for pattern in ["**/*.yml", "**/*.yaml"]:
        for metric_file in metrics_dir.glob(pattern):
            try:
                with open(metric_file) as f:
                    config = yaml.safe_load(f)

                if config and config.get("name") == name:
                    return metric_file
            except Exception:
                # Skip files that can't be parsed
                continue

    return None


def process_metric(
    metric_path: Path,
    config: MetricConfig,
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
        config: Loaded and validated metric configuration
        project_root: Project root directory
        task_manager: Task manager instance
        steps: Pipeline steps to execute
        from_date: Start date
        to_date: End date
        full_refresh: Full refresh flag
        force: Force flag
    """
    # Use config.name (not metric_path.stem) for consistency
    metric_name = config.name

    click.echo(click.style(f"Processing metric: {metric_name}", fg="cyan", bold=True))
    click.echo(f"  Config file: {metric_path.relative_to(project_root)}")
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

    # Run pipeline
    try:
        # Log step headers
        if PipelineStep.LOAD in steps:
            click.echo()
            click.echo(click.style("  ┌─ LOAD", fg="cyan", bold=True))

        result = task_manager.run_metric(
            config=config,
            steps=steps,
            from_date=from_date,
            to_date=to_date,
            full_refresh=full_refresh,
            force=force,
            metric_file_path=str(metric_path),
        )

        # Display results - task_manager already printed details
        click.echo()
        if result["status"] == "success":
            click.echo(click.style("✓ Pipeline completed successfully", fg="green", bold=True))
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

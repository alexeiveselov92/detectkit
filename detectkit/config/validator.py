"""
Metric configuration validation.

This module provides validation functions for metric configurations,
ensuring data integrity and preventing configuration errors.
"""

from pathlib import Path

from detectkit.config.metric_config import MetricConfig


def is_discoverable_metric_file(path: Path, metrics_dir: Path) -> bool:
    """True for a *live* metric YAML — excludes the ``metrics/.history/`` archive.

    ``dtk tune`` archives the previous metric config under
    ``metrics/.history/<metric>/`` before writing the tuned version in place. Those
    snapshots keep the original ``name:``, so discovering them as live metrics would
    (a) flag every tuned metric as a duplicate-name conflict and (b) run stale
    configs. Python's ``pathlib`` glob traverses hidden directories (unlike shell
    globbing), so they must be filtered out explicitly. Any hidden path component
    (a leading dot) *under* ``metrics/`` is skipped — this covers ``.history`` and
    any editor/VCS scratch dir a user drops there, while a project rooted under a
    dot-directory (checked only below ``metrics/``) is unaffected.
    """
    if not path.is_file() or path.suffix not in (".yml", ".yaml"):
        return False
    try:
        parts = path.relative_to(metrics_dir).parts
    except ValueError:
        parts = path.parts
    return not any(part.startswith(".") for part in parts)


def discover_metric_files(metrics_dir: Path) -> list[Path]:
    """All live metric YAMLs under ``metrics/`` (recursive), excluding the ``.history`` archive.

    The single discovery seam shared by project validation and CLI metric selection,
    so the ``.history`` exclusion can't drift between them. Returns a sorted list for
    deterministic ordering.
    """
    files = [
        p
        for pattern in ("**/*.yml", "**/*.yaml")
        for p in metrics_dir.glob(pattern)
        if is_discoverable_metric_file(p, metrics_dir)
    ]
    return sorted(set(files))


def validate_metric_uniqueness(metric_paths: list[Path]) -> list[tuple[Path, MetricConfig]]:
    """
    Load all metrics and validate that metric names are unique.

    This validation is CRITICAL for data integrity because duplicate metric names
    would cause:
    - Data corruption (mixed data in _dtk_datapoints table)
    - Task blocking (lock conflicts in _dtk_tasks table)
    - Wrong anomaly detection (detectors receive mixed data from different sources)
    - Data loss (ReplacingMergeTree ignores duplicate inserts)

    Args:
        metric_paths: List of paths to metric YAML files

    Returns:
        List of (path, config) tuples for all valid metrics

    Raises:
        ValueError: If duplicate metric names are found, with clear error message
            showing which files have conflicting names
        ValidationError: If any metric config fails to parse

    Example:
        >>> paths = [Path("metrics/api/cpu.yml"), Path("metrics/system/cpu.yml")]
        >>> validate_metric_uniqueness(paths)
        ValueError: Duplicate metric name 'cpu_usage' found:
          - metrics/api/cpu.yml
          - metrics/system/cpu.yml

        Metric names must be unique across the project.
        Please rename one of the metrics.
    """
    configs: list[tuple[Path, MetricConfig]] = []
    seen_names: dict[str, Path] = {}

    for metric_path in metric_paths:
        # Load and parse config
        try:
            config = MetricConfig.from_yaml_file(metric_path)
        except Exception as e:
            raise ValueError(f"Failed to parse metric config at {metric_path}:\n{e}") from e

        # Check for duplicate metric names
        if config.name in seen_names:
            conflicting_path = seen_names[config.name]
            raise ValueError(
                f"Duplicate metric name '{config.name}' found:\n"
                f"  - {conflicting_path}\n"
                f"  - {metric_path}\n\n"
                f"Metric names must be unique across the project.\n"
                f"Please rename one of the metrics to avoid data corruption."
            )

        seen_names[config.name] = metric_path
        configs.append((metric_path, config))

    return configs


def validate_project_metrics(project_root: Path) -> list[tuple[Path, MetricConfig]]:
    """
    Load and validate all metrics in the project.

    This is a convenience function that:
    1. Finds all *.yml and *.yaml files in the metrics/ directory (recursively)
    2. Validates uniqueness of metric names
    3. Returns validated list of (path, config) tuples

    Args:
        project_root: Path to project root directory (contains metrics/ folder)

    Returns:
        List of (path, config) tuples for all valid metrics

    Raises:
        ValueError: If duplicate metric names found or configs fail validation
        FileNotFoundError: If metrics/ directory doesn't exist

    Example:
        >>> from pathlib import Path
        >>> project_root = Path("/path/to/project")
        >>> metrics = validate_project_metrics(project_root)
        >>> for path, config in metrics:
        ...     print(f"{config.name}: {path}")
    """
    metrics_dir = project_root / "metrics"

    if not metrics_dir.exists():
        raise FileNotFoundError(
            f"Metrics directory not found: {metrics_dir}\n"
            f"Expected structure:\n"
            f"  {project_root}/\n"
            f"    metrics/\n"
            f"      your_metric.yml\n"
        )

    # Find all metric files recursively (excluding the metrics/.history/ archive).
    metric_paths = discover_metric_files(metrics_dir)

    if not metric_paths:
        raise ValueError(
            f"No metric files found in {metrics_dir}\n"
            f"Expected at least one *.yml or *.yaml file."
        )

    # Validate uniqueness
    return validate_metric_uniqueness(metric_paths)

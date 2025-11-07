"""
Metric configuration validation.

This module provides validation functions for metric configurations,
ensuring data integrity and preventing configuration errors.
"""

from pathlib import Path
from typing import List, Tuple

from detectkit.config.metric_config import MetricConfig


def validate_metric_uniqueness(metric_paths: List[Path]) -> List[Tuple[Path, MetricConfig]]:
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
    configs: List[Tuple[Path, MetricConfig]] = []
    seen_names: dict[str, Path] = {}

    for metric_path in metric_paths:
        # Load and parse config
        try:
            config = MetricConfig.from_yaml_file(metric_path)
        except Exception as e:
            raise ValueError(
                f"Failed to parse metric config at {metric_path}:\n{e}"
            ) from e

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


def validate_project_metrics(project_root: Path) -> List[Tuple[Path, MetricConfig]]:
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

    # Find all metric files recursively
    metric_paths = []
    for pattern in ["**/*.yml", "**/*.yaml"]:
        metric_paths.extend(metrics_dir.glob(pattern))

    if not metric_paths:
        raise ValueError(
            f"No metric files found in {metrics_dir}\n"
            f"Expected at least one *.yml or *.yaml file."
        )

    # Validate uniqueness
    return validate_metric_uniqueness(metric_paths)

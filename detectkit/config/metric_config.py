"""
Metric configuration models.

Defines configuration structure for individual metrics loaded from YAML files.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from detectkit.core.interval import Interval


class DetectorConfig(BaseModel):
    """
    Configuration for a single detector.

    Attributes:
        type: Detector type ("mad", "zscore", "iqr", "manual_bounds", etc.)
        params: Detector-specific parameters including:
            - Algorithm params: threshold, window_size, etc.
            - Execution params: start_time, batch_size, min_samples, etc.
            - Seasonality params: seasonality_components (with grouping support)

    Example YAML:
        ```yaml
        detectors:
          - type: mad
            params:
              # Algorithm parameters
              threshold: 3.0
              window_size: 4320

              # Execution parameters (optional)
              start_time: "2024-02-01 00:00:00"  # When to start detection
              batch_size: 500                     # Detection batch size
              min_samples: 100                    # Min points before detection
              min_samples_per_group: 10           # Min points per seasonal group
              weighting: null                     # null, 'linear', 'exponential'

              # Seasonality grouping (optional)
              seasonality_components:
                - "day_of_week"                   # Single component
                - ["league_day", "hour"]          # Grouped components
        ```
    """

    type: str = Field(..., description="Detector type")
    params: Dict[str, Any] = Field(
        default_factory=dict, description="Detector parameters"
    )

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate detector type."""
        allowed_types = {
            "mad",
            "zscore",
            "iqr",
            "manual_bounds",
            "prophet",
            "timesfm",
        }
        if v not in allowed_types:
            raise ValueError(
                f"Invalid detector type: {v}. "
                f"Allowed: {', '.join(sorted(allowed_types))}"
            )
        return v

    def get_algorithm_params(self) -> Dict[str, Any]:
        """
        Extract algorithm parameters (exclude execution parameters).

        Execution parameters that are filtered out:
        - start_time: When to start detection
        - batch_size: Detection batch size
        - seasonality_components: Seasonality grouping config

        Returns:
            Dict with only algorithm parameters
        """
        execution_params = {"start_time", "batch_size", "seasonality_components"}
        return {k: v for k, v in self.params.items() if k not in execution_params}

    def get_start_time(self) -> Optional[str]:
        """Get start_time execution parameter if configured."""
        return self.params.get("start_time")

    def get_batch_size(self) -> Optional[int]:
        """Get batch_size execution parameter if configured."""
        return self.params.get("batch_size")

    def get_seasonality_components(self) -> Optional[List[Union[str, List[str]]]]:
        """Get seasonality_components configuration if configured."""
        return self.params.get("seasonality_components")


class QueryColumnsConfig(BaseModel):
    """
    Column name mapping for SQL query results.

    Allows mapping custom column names from query to internal names.

    Attributes:
        timestamp: Name of timestamp column in query results (default: "timestamp")
        metric: Name of metric value column in query results (default: "value")
        seasonality: List of seasonality column names in query results (optional)

    Example YAML:
        ```yaml
        query_columns:
          timestamp: "time_interval"
          metric: "metric_value"
          seasonality: ["day_of_week", "league_day", "hour"]
        ```
    """

    timestamp: str = Field(
        default="timestamp", description="Timestamp column name in query"
    )
    metric: str = Field(default="value", description="Metric value column name in query")
    seasonality: Optional[List[str]] = Field(
        default=None, description="Seasonality column names in query"
    )


class AlertConfig(BaseModel):
    """
    Alert configuration for a metric.

    Attributes:
        enabled: Whether alerting is enabled
        timezone: Timezone for displaying timestamps in alerts (e.g., "Europe/Moscow")
        channels: List of alert channels to use
        min_detectors: Minimum number of detectors that must agree
        direction: Required anomaly direction ("same", "any", "up", "down")
        consecutive_anomalies: Minimum consecutive anomalies to trigger alert
        no_data_alert: Whether to alert when data is missing
        template_single: Custom template for single anomaly alert
        template_consecutive: Custom template for consecutive anomalies alert
    """

    enabled: bool = Field(default=True, description="Enable alerting")
    timezone: Optional[str] = Field(
        default=None, description="Timezone for displaying timestamps (e.g., 'Europe/Moscow')"
    )
    channels: List[str] = Field(
        default_factory=list, description="Alert channel names"
    )
    min_detectors: int = Field(
        default=1, description="Minimum detectors that must agree"
    )
    direction: str = Field(
        default="same", description="Required anomaly direction: 'same', 'any', 'up', 'down'"
    )
    consecutive_anomalies: int = Field(
        default=3, description="Consecutive anomalies to trigger alert"
    )
    no_data_alert: bool = Field(
        default=False, description="Alert when no data is available"
    )
    template_single: Optional[str] = Field(
        default=None, description="Custom template for single anomaly"
    )
    template_consecutive: Optional[str] = Field(
        default=None, description="Custom template for consecutive anomalies"
    )

    @field_validator("consecutive_anomalies")
    @classmethod
    def validate_consecutive(cls, v: int) -> int:
        """Validate consecutive anomalies threshold."""
        if v < 1:
            raise ValueError("consecutive_anomalies must be at least 1")
        return v

    @field_validator("min_detectors")
    @classmethod
    def validate_min_detectors(cls, v: int) -> int:
        """Validate min_detectors."""
        if v < 1:
            raise ValueError("min_detectors must be at least 1")
        return v

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        """Validate direction."""
        allowed = {"same", "any", "up", "down"}
        if v not in allowed:
            raise ValueError(f"direction must be one of: {', '.join(allowed)}")
        return v


class TablesConfig(BaseModel):
    """
    Custom table names for a specific metric.

    Allows overriding default internal table names on a per-metric basis.

    Attributes:
        datapoints: Custom name for datapoints table
        detections: Custom name for detections table

    Note: tasks table cannot be overridden (shared across all metrics)

    Example YAML:
        ```yaml
        tables:
          datapoints: "_dtk_datapoints_sales"
          detections: "_dtk_detections_sales"
        ```
    """

    datapoints: Optional[str] = Field(
        default=None, description="Custom datapoints table name"
    )
    detections: Optional[str] = Field(
        default=None, description="Custom detections table name"
    )


class MetricConfig(BaseModel):
    """
    Configuration for a single metric.

    Loaded from YAML files in metrics/ directory.

    Attributes:
        name: Metric name (unique identifier)
        tags: Optional list of tags for metric selection (e.g., ["critical", "api"])
        profile: Profile name to use (overrides default_profile from project config)
        query: Inline SQL query (mutually exclusive with query_file)
        query_file: Path to SQL file (mutually exclusive with query)
        query_columns: Column name mapping for query results
        interval: Data interval ("10min", "1h", or seconds as int)
        loading_start_time: Start time for initial data loading (UTC)
        seasonality_columns: List of seasonality features to extract
        loading_batch_size: Number of rows to load per batch
        detectors: List of detector configurations
        alerting: Alert configuration (optional)
        enabled: Whether metric is enabled for processing

    Example YAML:
        ```yaml
        name: cpu_usage
        tags: ["critical", "infrastructure", "10min"]
        profile: clickhouse_prod
        query_file: sql/cpu_usage.sql
        query_columns:
          timestamp: "time_interval"
          metric: "cpu_pct"
          seasonality: ["hour", "day_of_week"]
        interval: 10min
        loading_start_time: "2024-01-01 00:00:00"
        seasonality_columns:
          - hour
          - day_of_week
          - is_weekend
        loading_batch_size: 10000
        detectors:
          - type: mad
            params:
              threshold: 3.0
          - type: zscore
            params:
              threshold: 3.0
        alerting:
          enabled: true
          channels:
            - mattermost_alerts
          consecutive_anomalies: 3
        ```
    """

    name: str = Field(..., description="Metric name")
    tags: Optional[List[str]] = Field(
        default=None,
        description="Optional tags for metric selection (e.g., ['critical', 'api', '10min'])",
    )
    profile: Optional[str] = Field(
        default=None, description="Profile name to use (overrides default_profile)"
    )
    query: Optional[str] = Field(default=None, description="Inline SQL query")
    query_file: Optional[Path] = Field(default=None, description="Path to SQL file")
    query_columns: Optional[QueryColumnsConfig] = Field(
        default=None, description="Column name mapping for query results"
    )
    interval: Union[int, str] = Field(..., description="Data interval")
    loading_start_time: Optional[str] = Field(
        default=None,
        description="Start time for initial data loading (UTC, format: YYYY-MM-DD HH:MM:SS)",
    )
    seasonality_columns: List[str] = Field(
        default_factory=list, description="Seasonality features to extract"
    )
    loading_batch_size: int = Field(
        default=10000, description="Batch size for loading"
    )
    detectors: List[DetectorConfig] = Field(
        default_factory=list, description="Detector configurations"
    )
    alerting: Optional[AlertConfig] = Field(
        default=None, description="Alert configuration"
    )
    tables: Optional[TablesConfig] = Field(
        default=None, description="Custom table names (overrides defaults)"
    )
    enabled: bool = Field(default=True, description="Whether metric is enabled")

    # Parsed interval (computed from string/int)
    _interval: Optional[Interval] = None

    @model_validator(mode="after")
    def validate_query_source(self) -> "MetricConfig":
        """Validate that exactly one of query or query_file is specified."""
        if self.query is None and self.query_file is None:
            raise ValueError("Either 'query' or 'query_file' must be specified")

        if self.query is not None and self.query_file is not None:
            raise ValueError(
                "Only one of 'query' or 'query_file' can be specified, not both"
            )

        return self

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate metric name."""
        if not v:
            raise ValueError("Metric name cannot be empty")
        # Allow alphanumeric, underscore, dash
        if not all(c.isalnum() or c in ("_", "-") for c in v):
            raise ValueError(
                "Metric name can only contain alphanumeric characters, "
                "underscores, and dashes"
            )
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate tags field."""
        if v is None:
            return v

        if not v:
            raise ValueError("tags list cannot be empty (use null instead)")

        # Check for duplicate tags
        if len(v) != len(set(v)):
            raise ValueError("Duplicate tags not allowed")

        # Validate each tag format (alphanumeric + underscore + dash)
        for tag in v:
            if not tag:
                raise ValueError("Empty tag not allowed")
            if not all(c.isalnum() or c in ("_", "-") for c in tag):
                raise ValueError(
                    f"Invalid tag '{tag}': only alphanumeric characters, "
                    f"underscores, and dashes allowed"
                )

        return v

    @field_validator("loading_batch_size")
    @classmethod
    def validate_batch_size(cls, v: int) -> int:
        """Validate batch size."""
        if v < 1:
            raise ValueError("loading_batch_size must be at least 1")
        if v > 1_000_000:
            raise ValueError(
                "loading_batch_size too large (max 1,000,000). "
                "Use smaller batches to avoid memory issues."
            )
        return v

    @field_validator("seasonality_columns")
    @classmethod
    def validate_seasonality_columns(cls, v: List[str]) -> List[str]:
        """Validate seasonality columns."""
        allowed_columns = {
            "hour",
            "day_of_week",
            "day_of_month",
            "month",
            "is_weekend",
            "is_holiday",
        }

        for col in v:
            if col not in allowed_columns:
                raise ValueError(
                    f"Invalid seasonality column: '{col}'. "
                    f"Allowed: {', '.join(sorted(allowed_columns))}"
                )

        # Check for duplicates
        if len(v) != len(set(v)):
            raise ValueError("Duplicate seasonality columns not allowed")

        return v

    def get_interval(self) -> Interval:
        """
        Get parsed Interval object.

        Returns:
            Interval instance

        Example:
            >>> config = MetricConfig(name="test", interval="10min", query="SELECT 1")
            >>> config.get_interval().seconds
            600
        """
        if self._interval is None:
            self._interval = Interval(self.interval)
        return self._interval

    def get_query_text(self, project_root: Optional[Path] = None) -> str:
        """
        Get SQL query text (from inline query or file).

        Args:
            project_root: Root directory for resolving query_file paths

        Returns:
            SQL query text

        Raises:
            FileNotFoundError: If query_file doesn't exist

        Example:
            >>> config = MetricConfig(
            ...     name="test",
            ...     interval=600,
            ...     query="SELECT timestamp, value FROM metrics"
            ... )
            >>> config.get_query_text()
            'SELECT timestamp, value FROM metrics'
        """
        if self.query is not None:
            return self.query

        # Load from file
        if project_root is not None:
            query_path = project_root / self.query_file
        else:
            query_path = self.query_file

        if not query_path.exists():
            raise FileNotFoundError(f"Query file not found: {query_path}")

        with open(query_path, "r") as f:
            return f.read()

    @classmethod
    def from_yaml_file(cls, path: Path) -> "MetricConfig":
        """
        Load metric configuration from YAML file.

        Supports both flat and nested structures:
        - Flat: name: "cpu_usage" at root level
        - Nested: metric: { name: "cpu_usage", ... }

        Args:
            path: Path to YAML file

        Returns:
            MetricConfig instance

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If YAML is invalid

        Example:
            >>> config = MetricConfig.from_yaml_file(Path("metrics/cpu_usage.yml"))
        """
        import yaml

        if not path.exists():
            raise FileNotFoundError(f"Metric config file not found: {path}")

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError(f"Empty metric config file: {path}")

        # Support nested structure: metric: { ... }
        if "metric" in data and isinstance(data["metric"], dict):
            data = data["metric"]

        return cls.model_validate(data)

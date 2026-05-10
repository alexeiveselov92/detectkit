"""
Project configuration models.

Defines configuration structure for detectkit_project.yml.
"""

from pathlib import Path
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


class ProjectPathsConfig(BaseModel):
    """
    Project directory paths configuration.

    Attributes:
        metrics: Directory containing metric YAML files
        sql: Directory containing SQL query files
        templates: Directory containing alert templates
    """

    metrics: str = Field(default="metrics", description="Metrics directory")
    sql: str = Field(default="sql", description="SQL files directory")
    templates: str = Field(default="templates", description="Templates directory")


class ProjectTablesConfig(BaseModel):
    """
    Default internal table names for the project.

    Attributes:
        datapoints: Default datapoints table name
        detections: Default detections table name
        tasks: Default tasks table name
        metrics: Default metrics configuration table name
    """

    datapoints: str = Field(
        default="_dtk_datapoints", description="Default datapoints table"
    )
    detections: str = Field(
        default="_dtk_detections", description="Default detections table"
    )
    tasks: str = Field(default="_dtk_tasks", description="Default tasks table")
    metrics: str = Field(default="_dtk_metrics", description="Default metrics config table")


class ProjectTimeoutsConfig(BaseModel):
    """
    Default timeout values for operations (in seconds).

    Attributes:
        load: Timeout for data loading operations
        detect: Timeout for detection operations
        alert: Timeout for alerting operations
    """

    load: int = Field(default=3600, description="Load timeout (seconds)")
    detect: int = Field(default=7200, description="Detect timeout (seconds)")
    alert: int = Field(default=300, description="Alert timeout (seconds)")

    @field_validator("load", "detect", "alert")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        """Validate timeout value."""
        if v < 1:
            raise ValueError("Timeout must be at least 1 second")
        if v > 86400:  # 24 hours
            raise ValueError("Timeout cannot exceed 24 hours (86400 seconds)")
        return v


class ProjectErrorAlertingConfig(BaseModel):
    """
    Project-level error alerting configuration.

    Sent when ``TaskManager.run_metric`` raises any exception (including
    DB connection errors that affect every metric in the run). Channels
    are looked up by name in the channel profile, just like per-metric
    alerts.

    Behaviour:
    - At most one alert per ``dtk run`` invocation. Subsequent metric
      failures in the same run are suppressed (an in-memory flag), and
      the run aborts after the first error alert is dispatched — there's
      no point loading the rest if e.g. the DB is unreachable.
    - No persistent cooldown between separate ``dtk run`` invocations.
      Persisting state in the DB would not help when the DB itself is
      down, and a local file would break the dbt-style stateless model.

    Attributes:
        enabled: Master switch for project error alerting.
        channels: Channel names from the channel profile to dispatch to.
        template: Custom message body. Supports ``{metric_name}``,
            ``{error_type}``, ``{error_message}``, ``{description}``,
            ``{description_line}``, ``{mentions}``, ``{mentions_line}``,
            ``{status}``, ``{timestamp}``, ``{timezone}``.
        mentions: Users/groups to mention in the alert.
        timezone: Optional display timezone for ``{timestamp}``.
    """

    enabled: bool = Field(default=False, description="Enable project error alerting")
    channels: List[str] = Field(
        default_factory=list, description="Channel names to dispatch error alerts to"
    )
    template: Optional[str] = Field(
        default=None, description="Custom error message template"
    )
    mentions: List[str] = Field(
        default_factory=list, description="Users/groups to mention in error alerts"
    )
    timezone: Optional[str] = Field(
        default=None, description="Optional display timezone for {timestamp}"
    )


class ProjectConfig(BaseModel):
    """
    Project configuration loaded from detectkit_project.yml.

    Attributes:
        name: Project name
        version: Project version
        paths: Directory paths configuration
        tables: Default table names
        timeouts: Operation timeouts
        default_profile: Default database profile to use

    Example YAML:
        ```yaml
        name: "my_analytics_project"
        version: "1.0"

        paths:
          metrics: "metrics"
          sql: "sql"
          templates: "templates"

        tables:
          datapoints: "_dtk_datapoints"
          detections: "_dtk_detections"
          tasks: "_dtk_tasks"
          metrics: "_dtk_metrics"

        timeouts:
          load: 3600
          detect: 7200
          alert: 300

        default_profile: "clickhouse_prod"
        ```
    """

    name: str = Field(..., description="Project name")
    version: str = Field(default="1.0", description="Project version")
    paths: ProjectPathsConfig = Field(
        default_factory=ProjectPathsConfig, description="Directory paths"
    )
    tables: ProjectTablesConfig = Field(
        default_factory=ProjectTablesConfig, description="Default table names"
    )
    timeouts: ProjectTimeoutsConfig = Field(
        default_factory=ProjectTimeoutsConfig, description="Operation timeouts"
    )
    default_profile: str = Field(..., description="Default database profile")
    error_alerting: Optional[ProjectErrorAlertingConfig] = Field(
        default=None,
        description="Project-level error alerting (DB outages, query failures, etc.)",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate project name."""
        if not v:
            raise ValueError("Project name cannot be empty")
        # Allow alphanumeric, underscore, dash, space
        if not all(c.isalnum() or c in ("_", "-", " ") for c in v):
            raise ValueError(
                "Project name can only contain alphanumeric characters, "
                "underscores, dashes, and spaces"
            )
        return v

    @classmethod
    def from_yaml_file(cls, path: Path) -> "ProjectConfig":
        """
        Load project configuration from YAML file.

        Args:
            path: Path to detectkit_project.yml

        Returns:
            ProjectConfig instance

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If YAML is invalid

        Example:
            >>> config = ProjectConfig.from_yaml_file(Path("detectkit_project.yml"))
        """
        import yaml

        if not path.exists():
            raise FileNotFoundError(f"Project config file not found: {path}")

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError(f"Empty project config file: {path}")

        return cls.model_validate(data)

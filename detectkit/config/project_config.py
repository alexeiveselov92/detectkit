"""
Project configuration models.

Defines configuration structure for detectkit_project.yml.
"""

from pathlib import Path
from typing import Dict, Optional

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
    """

    datapoints: str = Field(
        default="_dtk_datapoints", description="Default datapoints table"
    )
    detections: str = Field(
        default="_dtk_detections", description="Default detections table"
    )
    tasks: str = Field(default="_dtk_tasks", description="Default tasks table")


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

"""
Project configuration models.

Defines configuration structure for detectkit_project.yml.
"""

from pathlib import Path

from pydantic import BaseModel, Field, field_validator


def resolve_alert_help_url(value: "str | bool | None") -> "str | None":
    """Resolve a raw ``alert_help_url`` config value to a concrete URL or None.

    Shared by :meth:`ProjectConfig.resolve_alert_help_url` and the ``dtk
    test-alert`` preview (which reads the project YAML as a raw dict), so the
    tri-state rule lives in one place:

    - ``False`` → ``None`` (the link is hidden).
    - a non-empty string → that URL (a custom runbook/wiki page).
    - ``None`` / ``True`` / empty → the official detectkit guide.
    """
    from detectkit.alerting.channels.branding import BRAND_ALERT_GUIDE_URL

    if value is False:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return BRAND_ALERT_GUIDE_URL


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

    datapoints: str = Field(default="_dtk_datapoints", description="Default datapoints table")
    detections: str = Field(default="_dtk_detections", description="Default detections table")
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
    channels: list[str] = Field(
        default_factory=list, description="Channel names to dispatch error alerts to"
    )
    template: str | None = Field(default=None, description="Custom error message template")
    mentions: list[str] = Field(
        default_factory=list, description="Users/groups to mention in error alerts"
    )
    timezone: str | None = Field(
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
    error_alerting: ProjectErrorAlertingConfig | None = Field(
        default=None,
        description="Project-level error alerting (DB outages, query failures, etc.)",
    )
    # "How to read this alert" link surfaced on every default-rendered alert so
    # stakeholders (PMs, analysts, on-call) can click through to a plain-language
    # explanation of what they're seeing. Tri-state:
    #   - unset / None  → the official detectkit guide (brand default)
    #   - a URL string  → your own runbook/wiki page instead
    #   - false         → hide the link entirely
    # Resolved via ``resolve_alert_help_url()`` and stamped onto ``AlertData``.
    alert_help_url: str | bool | None = Field(
        default=None,
        description=(
            "Link to a guide explaining how to read an alert, shown on every "
            "alert. Defaults to the official docs; set a URL for your own page, "
            "or false to hide it."
        ),
    )
    # Project-wide default false-alert-rate (FDR) budget for manual tuning. The
    # `dtk tune` cockpit flags — non-intrusively — when the share of fired alerts
    # that don't overlap a real incident exceeds this fraction, so you have a
    # target to tune against. A per-metric `false_alert_budget` overrides it.
    # Labeling stays optional: the budget only colours an already-computed number,
    # it never blocks anything or affects the load/detect/alert pipeline.
    false_alert_budget: float | None = Field(
        default=None,
        description=(
            "Default false-alert-rate budget (a fraction in (0, 1], e.g. 0.3 = "
            "30%) the `dtk tune` cockpit flags when exceeded. Per-metric "
            "`false_alert_budget` takes priority; unset → a built-in default."
        ),
    )

    @field_validator("false_alert_budget")
    @classmethod
    def validate_false_alert_budget(cls, v: float | None) -> float | None:
        """A budget, if set, is a false-alert-rate fraction in ``(0, 1]``."""
        if v is None:
            return v
        if not 0.0 < v <= 1.0:
            raise ValueError("false_alert_budget must be a fraction in (0, 1] (e.g. 0.3 = 30%)")
        return v

    @field_validator("alert_help_url")
    @classmethod
    def validate_alert_help_url(cls, v: "str | bool | None") -> "str | bool | None":
        """A string override must look like an http(s) URL; ``True`` means default."""
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return None  # empty string behaves like "use the default"
            if not (v.startswith("http://") or v.startswith("https://")):
                raise ValueError(
                    "alert_help_url must be an http(s) URL, false (to hide), "
                    "or unset (to use the default)"
                )
        return v

    def resolve_alert_help_url(self) -> str | None:
        """Resolve the configured ``alert_help_url`` to a concrete URL or None.

        Defaults to the official detectkit guide; a string redirects to your own
        page; ``false`` hides the link. See :func:`resolve_alert_help_url`.
        """
        return resolve_alert_help_url(self.alert_help_url)

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

        with open(path) as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError(f"Empty project config file: {path}")

        return cls.model_validate(data)

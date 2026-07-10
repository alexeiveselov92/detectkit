"""
Metric configuration models.

Defines configuration structure for individual metrics loaded from YAML files.
"""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from detectkit.core.interval import Interval


class DetectorConfig(BaseModel):
    """
    Configuration for a single detector.

    Attributes:
        type: Detector type ("mad", "zscore", "iqr", "manual_bounds", "autoreg", etc.)
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
    params: dict[str, Any] = Field(default_factory=dict, description="Detector parameters")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate detector type."""
        allowed_types = {
            "mad",
            "zscore",
            "iqr",
            "manual_bounds",
            "autoreg",
            "prophet",
            "timesfm",
        }
        if v not in allowed_types:
            raise ValueError(
                f"Invalid detector type: {v}. " f"Allowed: {', '.join(sorted(allowed_types))}"
            )
        return v

    def get_algorithm_params(self) -> dict[str, Any]:
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

    def get_start_time(self) -> str | None:
        """Get start_time execution parameter if configured."""
        return self.params.get("start_time")

    def get_batch_size(self) -> int | None:
        """Get batch_size execution parameter if configured."""
        return self.params.get("batch_size")

    def get_seasonality_components(self) -> list[str | list[str]] | None:
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

    timestamp: str = Field(default="timestamp", description="Timestamp column name in query")
    metric: str = Field(default="value", description="Metric value column name in query")
    seasonality: list[str] | None = Field(
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
        alert_cooldown: Minimum interval between alerts (e.g., "30min", 1800 seconds)
        cooldown_reset_on_recovery: Whether to reset cooldown when anomaly recovers
    """

    enabled: bool = Field(default=True, description="Enable alerting")
    suppress_until: str | None = Field(
        default=None,
        description="Suppress alerts until this UTC datetime (e.g., '2026-04-11 18:00:00'). "
        "Load and detect steps still run. Alerts auto-resume after this time.",
    )
    timezone: str | None = Field(
        default=None, description="Timezone for displaying timestamps (e.g., 'Europe/Moscow')"
    )
    channels: list[str] = Field(default_factory=list, description="Alert channel names")
    min_detectors: int = Field(default=1, description="Minimum detectors that must agree")
    direction: str = Field(
        default="same", description="Required anomaly direction: 'same', 'any', 'up', 'down'"
    )
    consecutive_anomalies: int = Field(
        default=3, description="Consecutive anomalies to trigger alert"
    )
    anomaly_window: str | int | None = Field(
        default=None,
        description="Trailing window for the fraction-based alert rule (duration string like "
        "'30min' or seconds as int; converted to grid points via the metric interval). Must be "
        "set together with min_anomaly_share. When set, an alert also fires when the share of "
        "window points meeting the quorum reaches min_anomaly_share AND the latest point itself "
        "meets the quorum — tolerant of scattered normal points inside a real incident, where "
        "consecutive_anomalies alone would reset. The two rules are OR-ed.",
    )
    min_anomaly_share: float | None = Field(
        default=None,
        description="Fraction in (0, 1] of anomaly_window points that must meet the quorum for "
        "the fraction rule to fire (e.g. 0.3 = 30% of the window). Must be set together with "
        "anomaly_window. Missing/no-data points count in the denominator (an outage makes the "
        "rule harder to fire, not easier); the no-data alert covers outages separately.",
    )
    no_data_alert: bool = Field(default=False, description="Alert when no data is available")
    template_single: str | None = Field(
        default=None, description="Custom template for single anomaly"
    )
    template_consecutive: str | None = Field(
        default=None, description="Custom template for consecutive anomalies"
    )
    alert_cooldown: str | int | None = Field(
        default=None,
        description="Minimum interval between alerts (e.g., '30min', 1800). "
        "If None, no cooldown is applied (alerts sent every time conditions are met).",
    )
    cooldown_reset_on_recovery: bool = Field(
        default=True,
        description="Reset cooldown timer when anomaly recovers to normal. "
        "Only applies if alert_cooldown is set. "
        "True = cooldown resets on recovery, False = strict cooldown independent of recovery.",
    )
    notify_on_recovery: bool = Field(
        default=False,
        description="Send notification when metric recovers from anomaly state. "
        "Recovery is detected when consecutive anomalies drop below threshold "
        "after an alert was previously sent.",
    )
    template_recovery: str | None = Field(
        default=None,
        description="Custom template for recovery notification message. "
        "Supports same variables as anomaly templates plus {status}.",
    )
    template_no_data: str | None = Field(
        default=None,
        description="Custom template for no-data alert message. "
        "Used when no_data_alert is true and the latest expected "
        "interval has no datapoint. Supports {metric_name}, "
        "{timestamp}, {timezone}, {description}, {description_line}, "
        "{mentions}, {mentions_line}, {status}.",
    )
    mentions: list[str] = Field(
        default_factory=list,
        description="Users/groups to mention in alerts. Plain usernames without @. "
        "Special keywords: 'channel', 'all', 'here' for broadcast mentions. "
        "Each channel formats mentions in its native syntax.",
    )
    dashboard_url: str | None = Field(
        default=None,
        description="Optional dashboard/runbook URL surfaced as a first-class action in "
        "every alert: a clickable title + 'Open dashboard' link on Slack/Mattermost, "
        "an inline link on Telegram, and a button in email. Also available to custom "
        "templates as {dashboard_url}.",
    )
    links: dict[str, str] = Field(
        default_factory=dict,
        description="Additional 'label: url' links appended to the alert alongside "
        "dashboard_url (e.g. {'Runbook': 'https://...', 'Grafana': 'https://...'}).",
    )

    @field_validator("consecutive_anomalies")
    @classmethod
    def validate_consecutive(cls, v: int) -> int:
        """Validate consecutive anomalies threshold."""
        if v < 1:
            raise ValueError("consecutive_anomalies must be at least 1")
        return v

    @field_validator("min_anomaly_share")
    @classmethod
    def validate_min_anomaly_share(cls, v: float | None) -> float | None:
        """The fraction threshold, if set, must be in ``(0, 1]``."""
        if v is None:
            return v
        if not 0.0 < v <= 1.0:
            raise ValueError("min_anomaly_share must be a fraction in (0, 1] (e.g. 0.3 = 30%)")
        return v

    @field_validator("anomaly_window")
    @classmethod
    def validate_anomaly_window(cls, v: str | int | None) -> str | int | None:
        """The window, if set, must parse as an interval (e.g. '30min', '1h', 1800)."""
        if v is None:
            return v
        try:
            Interval(v)
        except Exception as exc:
            raise ValueError(f"anomaly_window must be a valid interval: {exc}") from exc
        return v

    @model_validator(mode="after")
    def validate_fraction_rule(self) -> "AlertConfig":
        """``anomaly_window`` and ``min_anomaly_share`` come as a pair."""
        if (self.anomaly_window is None) != (self.min_anomaly_share is None):
            raise ValueError(
                "anomaly_window and min_anomaly_share must be set together "
                "(the fraction rule needs both the window and the share threshold)"
            )
        return self

    @field_validator("dashboard_url")
    @classmethod
    def validate_dashboard_url(cls, v: str | None) -> str | None:
        """Only allow http(s) links — they become clickable titles/buttons in
        alerts, so a ``javascript:``/``data:`` URL must never slip through."""
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("dashboard_url must be an http:// or https:// URL")
        return v

    @field_validator("links")
    @classmethod
    def validate_links(cls, v: dict[str, str]) -> dict[str, str]:
        """Each link URL must be http(s) for the same reason as dashboard_url."""
        for label, url in v.items():
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"links['{label}'] must be an http:// or https:// URL")
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

    datapoints: str | None = Field(default=None, description="Custom datapoints table name")
    detections: str | None = Field(default=None, description="Custom detections table name")


# Detector types the autotune engine can select between (statistical, windowed).
# ``manual_bounds`` is excluded — it needs domain thresholds, not tuning.
_AUTOTUNE_DETECTOR_TYPES = {"mad", "zscore", "iqr"}
# Scoring metrics the grid search can optimize. MCC is the default;
# ``event_f1`` is segment-aware (point-adjusted): one flagged point inside a
# labeled incident counts the whole incident as caught, aligning the engine
# with the alert pipeline and the `dtk tune` cockpit's recall/FDR bar.
_AUTOTUNE_SCORING_METRICS = {
    "mcc",
    "f1",
    "f_beta",
    "balanced_accuracy",
    "roc_auc",
    "pr_auc",
    "event_f1",
}
# Seasonality columns the search may consider (mirrors MetricConfig).
_AUTOTUNE_SEASONALITY_COLUMNS = {
    "hour",
    "day_of_week",
    "day_of_month",
    "month",
    "is_weekend",
    "is_holiday",
}


class AutoTuneConfig(BaseModel):
    """
    Optional per-metric auto-tuning constraints (for ``dtk autotune``).

    The block is entirely optional: when absent, ``dtk autotune`` tunes the
    metric fully automatically. Experts use it to narrow the search — restrict
    the candidate detectors, pin some hyperparameters, point at a labels file,
    or change the scoring metric.

    Example YAML:
        ```yaml
        autotune:
          enabled: true
          detector_types: [mad, zscore]   # restrict candidates
          scoring_metric: mcc              # optimization target
          beta: 1.0                        # only for scoring_metric: f_beta
          labels_file: incidents/orders.yml   # external labels file, OR inline:
          incidents:                          # inline labels (mutually exclusive)
            - {start: "2026-05-02 14:00:00", end: "2026-05-02 16:30:00"}
            - {at: "2026-05-11 09:05:00"}
          incidents_timezone: UTC          # interprets the naive times above
          seasonality_candidates: [hour, day_of_week]
          fixed_params:                    # pinned, not searched
            window_size: 4320
          folds: 5
          max_history: 50000               # cap training points
        ```
    """

    enabled: bool = Field(default=True, description="Set false to refuse autotuning this metric")
    detector_types: list[str] | None = Field(
        default=None, description="Restrict candidate detector types (subset of mad/zscore/iqr)"
    )
    scoring_metric: str | None = Field(
        default=None,
        description="Optimization target: mcc (default), f1, f_beta, balanced_accuracy, "
        "roc_auc, pr_auc, event_f1 (segment-aware: one flag inside a labeled incident "
        "counts the whole incident as caught)",
    )
    beta: float = Field(
        default=1.0, description="Beta for scoring_metric: f_beta (recall weight); >0"
    )
    labels_file: str | None = Field(
        default=None, description="Project-relative path to a canonical labels file"
    )
    incidents: list[dict[str, Any]] | None = Field(
        default=None,
        description="Inline labeled incidents (alternative to labels_file). Each entry is "
        "{start, end} for a sustained incident or {at} for a single point; an optional "
        "'label' is free-text documentation.",
    )
    incidents_timezone: str | None = Field(
        default=None,
        description="Timezone that interprets the naive times in `incidents` (default UTC)",
    )
    seasonality_candidates: list[str] | None = Field(
        default=None, description="Restrict the seasonality columns the search may use"
    )
    force_seasonality: list[str | list[str]] | None = Field(
        default=None,
        description="Pin the seasonality grouping instead of searching it. Each entry is a "
        "column name or a list of columns for a conjunctive group "
        "(e.g. [hour] or [[day_of_week, hour]]).",
    )
    fixed_params: dict[str, Any] = Field(
        default_factory=dict, description="Hyperparameters pinned across the whole search"
    )
    folds: int = Field(default=5, description="Cross-validation folds")
    stability_lambda: float = Field(
        default=0.5,
        description="Weight on the cross-fold downside-dispersion penalty "
        "(aggregate = mean - lambda * downside_semideviation). Lower it (e.g. 0.0) for a "
        "metric whose behavior differs across a regime shift, so a config that adapts to "
        "the recent regime isn't penalized for fold-to-fold variance.",
    )
    max_history: int | None = Field(
        default=None, description="Cap on training points used during the search"
    )

    @field_validator("detector_types")
    @classmethod
    def validate_detector_types(cls, v: list[str] | None) -> list[str] | None:
        """Restrict to detector types the engine can actually tune."""
        if v is None:
            return v
        if not v:
            raise ValueError("detector_types cannot be empty (omit it to allow all)")
        bad = [t for t in v if t not in _AUTOTUNE_DETECTOR_TYPES]
        if bad:
            raise ValueError(
                f"Invalid autotune detector_types: {bad}. "
                f"Allowed: {', '.join(sorted(_AUTOTUNE_DETECTOR_TYPES))}"
            )
        return v

    @field_validator("scoring_metric")
    @classmethod
    def validate_scoring_metric(cls, v: str | None) -> str | None:
        """Validate the optimization target."""
        if v is None:
            return v
        if v not in _AUTOTUNE_SCORING_METRICS:
            raise ValueError(
                f"Invalid scoring_metric: '{v}'. "
                f"Allowed: {', '.join(sorted(_AUTOTUNE_SCORING_METRICS))}"
            )
        return v

    @field_validator("beta")
    @classmethod
    def validate_beta(cls, v: float) -> float:
        """Beta must be positive (only meaningful for f_beta)."""
        if v <= 0:
            raise ValueError("beta must be positive")
        return v

    @field_validator("seasonality_candidates")
    @classmethod
    def validate_seasonality_candidates(cls, v: list[str] | None) -> list[str] | None:
        """Restrict to the same allowed columns as MetricConfig.seasonality_columns."""
        if v is None:
            return v
        bad = [c for c in v if c not in _AUTOTUNE_SEASONALITY_COLUMNS]
        if bad:
            raise ValueError(
                f"Invalid autotune seasonality_candidates: {bad}. "
                f"Allowed: {', '.join(sorted(_AUTOTUNE_SEASONALITY_COLUMNS))}"
            )
        return v

    @field_validator("force_seasonality")
    @classmethod
    def validate_force_seasonality(
        cls, v: list[str | list[str]] | None
    ) -> list[str | list[str]] | None:
        """Validate the pinned grouping against the allowed seasonality columns."""
        if v is None:
            return v
        if not v:
            raise ValueError("force_seasonality cannot be empty (omit it to search)")
        cols: list[str] = []
        for comp in v:
            cols.extend([comp] if isinstance(comp, str) else list(comp))
        bad = [c for c in cols if c not in _AUTOTUNE_SEASONALITY_COLUMNS]
        if bad:
            raise ValueError(
                f"Invalid autotune force_seasonality: {bad}. "
                f"Allowed: {', '.join(sorted(_AUTOTUNE_SEASONALITY_COLUMNS))}"
            )
        return v

    @field_validator("folds")
    @classmethod
    def validate_folds(cls, v: int) -> int:
        """Need at least 2 folds for cross-validation."""
        if v < 2:
            raise ValueError("folds must be at least 2")
        return v

    @field_validator("max_history")
    @classmethod
    def validate_max_history(cls, v: int | None) -> int | None:
        """A history cap, if set, must be positive."""
        if v is not None and v < 1:
            raise ValueError("max_history must be at least 1")
        return v

    @field_validator("stability_lambda")
    @classmethod
    def validate_stability_lambda(cls, v: float) -> float:
        """The dispersion-penalty weight must be non-negative."""
        if v < 0:
            raise ValueError("stability_lambda must be >= 0")
        return v

    @model_validator(mode="after")
    def validate_inline_incidents(self) -> "AutoTuneConfig":
        """Validate inline incidents: not alongside labels_file, and well-formed.

        Reuses the canonical labels parser so an inline block is validated by the
        same rules as a labels file (timestamp formats, interval-vs-point shape,
        timezone), failing fast at config load.
        """
        if self.labels_file and self.incidents:
            raise ValueError(
                "Set either 'labels_file' or 'incidents', not both "
                "(inline incidents and an external labels file are mutually exclusive)"
            )
        if self.incidents_timezone and not self.incidents:
            raise ValueError("incidents_timezone has no effect without 'incidents'")
        if self.incidents is not None:
            # Local import to avoid a config <-> autotune import cycle at module load.
            from detectkit.autotune.labels import parse_incident_labels

            try:
                parse_incident_labels(
                    {"incidents": self.incidents, "timezone": self.incidents_timezone},
                    interval_seconds=1,
                )
            except Exception as exc:  # ValueError, bad timezone (KeyError), etc.
                raise ValueError(f"invalid 'incidents': {exc}") from exc
        return self


class AiContextConfig(BaseModel):
    """OSI-compatible AI grounding for a metric (purely descriptive).

    Mirrors the OSI ``ai_context`` shape (``instructions`` / ``synonyms`` /
    ``examples``) verbatim, so a metric's business meaning, alternative names and
    example values are portable to and from an OSI semantic model (Open Semantic
    Interchange). It is surfaced to humans and agents — synonyms ride into alerts
    as an "Also known as" line, the whole block is baked into the ``dtk tune``
    cockpit payload, and it is shipped to the assistant via ``dtk init-claude`` —
    but it **never** affects the load/detect/alert pipeline or the detector id. A
    metric with no ``ai_context`` behaves exactly as before.

    Accepts either the full mapping or a bare string (lifted to ``instructions``):

        ```yaml
        ai_context: "Revenue recognized at order completion, net of refunds."
        # or
        ai_context:
          instructions: "Revenue recognized at order completion, net of refunds."
          synonyms: ["total revenue", "gross sales"]
          examples: ["12030.50", "9821.00"]
        ```
    """

    instructions: str | None = Field(
        default=None,
        description="Business meaning / how to interpret the metric (grounds humans + LLMs)",
    )
    synonyms: list[str] = Field(
        default_factory=list,
        description="Alternative names for the metric (grounding + the alert 'Also known as' line)",
    )
    examples: list[str] = Field(
        default_factory=list,
        description="Illustrative example values or phrasings (grounding only)",
    )

    @field_validator("synonyms", "examples")
    @classmethod
    def _clean_str_list(cls, v: list[str]) -> list[str]:
        """Drop blank/whitespace-only entries (trimming each), preserving order and
        de-duplicating, so a stray empty YAML entry can't leak a bare comma into the
        rendered "Also known as" line."""
        seen: set[str] = set()
        cleaned: list[str] = []
        for item in v:
            s = str(item).strip()
            if s and s not in seen:
                seen.add(s)
                cleaned.append(s)
        return cleaned


class MetricConfig(BaseModel):
    """
    Configuration for a single metric.

    Loaded from YAML files in metrics/ directory.

    Attributes:
        name: Metric name (unique identifier)
        description: Optional metric description (supports multi-line text)
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
        description: |
          CPU usage monitoring metric.
          Tracks system load over time.
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
    description: str | None = Field(
        default=None, description="Optional metric description (supports multi-line text)"
    )
    tags: list[str] | None = Field(
        default=None,
        description="Optional tags for metric selection (e.g., ['critical', 'api', '10min'])",
    )
    profile: str | None = Field(
        default=None, description="Profile name to use (overrides default_profile)"
    )
    query: str | None = Field(default=None, description="Inline SQL query")
    query_file: Path | None = Field(default=None, description="Path to SQL file")
    query_columns: QueryColumnsConfig | None = Field(
        default=None, description="Column name mapping for query results"
    )
    interval: int | str = Field(..., description="Data interval")
    loading_start_time: str | None = Field(
        default=None,
        description="Start time for initial data loading (UTC, format: YYYY-MM-DD HH:MM:SS)",
    )
    seasonality_columns: list[str] = Field(
        default_factory=list, description="Seasonality features to extract"
    )
    loading_batch_size: int = Field(default=10000, description="Batch size for loading")
    detectors: list[DetectorConfig] = Field(
        default_factory=list, description="Detector configurations"
    )
    alerting: list[AlertConfig] | None = Field(
        default=None, description="Alert configuration(s) — single dict or list of dicts"
    )

    @field_validator("alerting", mode="before")
    @classmethod
    def normalize_alerting(cls, v):
        """Normalize alerting to list. Accepts single dict/AlertConfig (backward compat) or list."""
        if v is None:
            return None
        if isinstance(v, dict | AlertConfig):
            return [v]
        return v

    tables: TablesConfig | None = Field(
        default=None, description="Custom table names (overrides defaults)"
    )
    autotune: AutoTuneConfig | None = Field(
        default=None, description="Optional auto-tuning constraints (for `dtk autotune`)"
    )
    # OSI-compatible AI grounding (instructions/synonyms/examples). Descriptive
    # only: surfaced in alerts (synonyms → "Also known as"), the `dtk tune`
    # cockpit and assistant grounding, but never touches load/detect/alert or the
    # detector id. Mirrors OSI's `ai_context` so a metric's meaning is portable to
    # and from an OSI semantic model. Accepts a bare string (→ instructions).
    ai_context: AiContextConfig | None = Field(
        default=None,
        description=(
            "Optional OSI-compatible AI grounding (instructions/synonyms/examples). "
            "Descriptive only — surfaced in alerts, the tune cockpit and assistant "
            "grounding; never affects load/detect/alert or the detector id."
        ),
    )
    # Per-metric false-alert-rate (FDR) budget for manual tuning, overriding the
    # project-wide `false_alert_budget`. The `dtk tune` cockpit flags — non
    # intrusively — when the share of fired alerts that don't overlap a real
    # incident exceeds this fraction. Tuning-only: it never affects load/detect/
    # alert and labeling stays optional.
    false_alert_budget: float | None = Field(
        default=None,
        description=(
            "False-alert-rate budget (a fraction in (0, 1], e.g. 0.3 = 30%) the "
            "`dtk tune` cockpit flags when exceeded. Overrides the project-wide "
            "default; unset → fall back to project, then a built-in default."
        ),
    )
    enabled: bool = Field(default=True, description="Whether metric is enabled")

    @field_validator("false_alert_budget")
    @classmethod
    def validate_false_alert_budget(cls, v: float | None) -> float | None:
        """A budget, if set, is a false-alert-rate fraction in ``(0, 1]``."""
        if v is None:
            return v
        if not 0.0 < v <= 1.0:
            raise ValueError("false_alert_budget must be a fraction in (0, 1] (e.g. 0.3 = 30%)")
        return v

    @field_validator("ai_context", mode="before")
    @classmethod
    def _accept_ai_context_string(cls, v: Any) -> Any:
        """Allow ``ai_context: "free text"`` as shorthand for ``{instructions: ...}``,
        mirroring OSI's ``ai_context`` which is itself either a string or a struct."""
        if isinstance(v, str):
            return {"instructions": v}
        return v

    # Parsed interval (computed from string/int)
    _interval: Interval | None = None

    @model_validator(mode="after")
    def validate_query_source(self) -> "MetricConfig":
        """Validate that exactly one of query or query_file is specified."""
        if self.query is None and self.query_file is None:
            raise ValueError("Either 'query' or 'query_file' must be specified")

        if self.query is not None and self.query_file is not None:
            raise ValueError("Only one of 'query' or 'query_file' can be specified, not both")

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
                "Metric name can only contain alphanumeric characters, " "underscores, and dashes"
            )
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
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
    def validate_seasonality_columns(cls, v: list[str]) -> list[str]:
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

    def get_query_text(self, project_root: Path | None = None) -> str:
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

        with open(query_path) as f:
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

        with open(path) as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError(f"Empty metric config file: {path}")

        # Support nested structure: metric: { ... } (shared unwrap seam)
        from detectkit.config.metric_io import unwrap_metric_mapping

        data = unwrap_metric_mapping(data)

        return cls.model_validate(data)

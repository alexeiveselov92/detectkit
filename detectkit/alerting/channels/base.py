"""
Base alert channel interface.

All alert channels must inherit from BaseAlertChannel and implement
the send() method for delivering alerts to specific destinations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from detectkit.alerting.channels.branding import ALERT_GUIDE_LABEL


@dataclass
class AlertData:
    """
    Data for alert message.

    Contains all information needed to format and send an alert.

    Attributes:
        metric_name: Name of the metric
        timestamp: Timestamp of the anomaly (datetime64)
        timezone: Timezone for display (e.g., "Europe/Moscow")
        value: Actual metric value (None for no-data alerts)
        confidence_lower: Lower confidence bound
        confidence_upper: Upper confidence bound
        detector_name: Name/ID of detector that found the anomaly
        detector_params: Detector parameters (JSON string)
        direction: Direction of anomaly ("above" or "below")
        severity: Severity score
        detection_metadata: Additional metadata from detector
        consecutive_count: Number of consecutive anomalies
        is_recovery: True for recovery notifications
        is_no_data: True for missing-data alerts (no_data_alert)
        project_name: Optional ``detectkit_project.yml`` name. Surfaces as
            ``{project_name}`` / ``{project_name_prefix}`` in templates and, by
            default, as a ``[name] `` prefix on every alert title/headline
            (anomaly, recovery, no-data, error) plus a brand-paired footer
            ("detectkit · name" on webhook/email). The detectkit pipeline stamps
            it from the project config; direct-API callers leave it ``None`` and
            render unchanged. Lets multiple projects share one alert channel —
            keeping the default brand bot name + avatar — without ambiguity.

    Alert-rule fields (``min_detectors``, ``direction_policy``,
    ``consecutive_required``, ``detector_count``) describe *why the alert
    fired* — the configured quorum/direction/consecutive thresholds plus
    the observed number of agreeing detectors. They are filled by the
    orchestrator from :class:`AlertConditions` and are deliberately kept
    distinct from the observed ``direction``/``consecutive_count`` above so
    templates can contrast "required vs actual". They default to ``None``
    so direct-API callers (and non-anomaly alerts) still render cleanly.
    """

    metric_name: str
    timestamp: Any  # datetime64 or datetime
    timezone: str
    value: float | None
    confidence_lower: float | None
    confidence_upper: float | None
    detector_name: str
    detector_params: str
    direction: str
    severity: float
    detection_metadata: dict[str, Any]
    consecutive_count: int = 1
    is_recovery: bool = False
    is_no_data: bool = False
    is_error: bool = False
    error_type: str | None = None
    error_message: str | None = None
    description: str | None = None
    mentions: list[str] = field(default_factory=list)
    project_name: str | None = None
    # Optional actionable links surfaced in the message. ``dashboard_url`` is the
    # headline link (rendered natively as a clickable title/link on
    # Slack/Mattermost, an ``<a>`` on Telegram, a button in email, and exposed as
    # the ``{dashboard_url}`` template variable). ``links`` adds further
    # ``label -> url`` pairs for advanced use. Both default to empty so existing
    # callers and templates render unchanged.
    dashboard_url: str | None = None
    links: dict[str, str] = field(default_factory=dict)
    # "How to read this alert" link surfaced on every default-rendered message so
    # non-operator stakeholders can click through to a plain-language guide. The
    # orchestrator resolves it from ``ProjectConfig.alert_help_url`` (defaulting to
    # the official docs); direct-API callers leave it ``None`` and render unchanged.
    # Exposed to templates as ``{help_url}`` / ``{help_line}``.
    help_url: str | None = None
    # Alert rule (the parameters the alert fired with) — see class docstring.
    min_detectors: int | None = None
    direction_policy: str | None = None
    consecutive_required: int | None = None
    detector_count: int = 1


class BaseAlertChannel(ABC):
    """
    Abstract base class for alert channels.

    Alert channels deliver notifications to external systems when
    anomalies are detected. Each channel implements a specific
    delivery mechanism (webhook, email, etc.).

    Example:
        >>> class MyChannel(BaseAlertChannel):
        ...     def send(self, alert_data, template=None):
        ...         message = self.format_message(alert_data, template)
        ...         # Send via specific mechanism
        ...         return True
    """

    @abstractmethod
    def send(
        self,
        alert_data: AlertData,
        template: str | None = None,
    ) -> bool:
        """
        Send alert to this channel.

        Args:
            alert_data: Alert data to send
            template: Optional custom message template
                     Uses default template if None

        Returns:
            True if sent successfully, False otherwise

        Raises:
            Exception: If sending fails critically

        Example:
            >>> alert = AlertData(
            ...     metric_name="cpu_usage",
            ...     timestamp=datetime.now(),
            ...     value=95.0,
            ...     ...
            ... )
            >>> success = channel.send(alert)
        """
        pass

    def format_message(
        self,
        alert_data: AlertData,
        template: str | None = None,
        recovery_template: str | None = None,
    ) -> str:
        """
        Format alert message from template.

        Uses default template if none provided. Template variables:
        - {metric_name}
        - {timestamp}
        - {timezone}
        - {value} / {value_display}
        - {confidence_lower}
        - {confidence_upper}
        - {confidence_interval} — "[lower, upper]" or "N/A"
        - {expected_range} — one-sided aware: ">= lo", "<= hi",
          "[lo, hi]" or "N/A" (renders one-sided detector bounds cleanly)
        - {detector_name}
        - {detector_count} — observed detectors that agreed (the quorum)
        - {direction} — observed/locked direction of the anomaly
        - {direction_policy} — configured direction rule ("same"/"any"/...)
        - {min_detectors} — configured quorum threshold (the rule)
        - {consecutive_count} — observed consecutive points
        - {consecutive_required} — configured consecutive threshold (rule)
        - {severity}
        - {status}

        Args:
            alert_data: Alert data to format
            template: Optional custom template string

        Returns:
            Formatted message string

        Example:
            >>> template = "Anomaly in {metric_name}: {value}"
            >>> message = channel.format_message(alert_data, template)
        """
        if template is None:
            if alert_data.is_error:
                template = self.get_default_error_template()
            elif alert_data.is_no_data:
                template = self.get_default_no_data_template()
            elif alert_data.is_recovery:
                template = recovery_template or self.get_default_recovery_template()
            else:
                template = self.get_default_template()

        ctx = self.build_context(alert_data)

        try:
            message = template.format(**ctx)
        except (KeyError, ValueError, TypeError):
            # Template has an unknown variable or a format spec that doesn't fit
            # the actual value (e.g. ``{value:.2f}`` in a no-data template where
            # value is a string). Fall back to the kind-appropriate default.
            if alert_data.is_error:
                fallback = self.get_default_error_template()
            elif alert_data.is_no_data:
                fallback = self.get_default_no_data_template()
            elif alert_data.is_recovery:
                fallback = self.get_default_recovery_template()
            else:
                fallback = self.get_default_template()
            if template == fallback:
                # Already on the default — re-raise instead of recursing.
                raise
            message = self.format_message(alert_data, fallback)

        return message

    def build_context(self, alert_data: AlertData) -> dict[str, Any]:
        """Compute the display-ready variables for *alert_data*.

        This is the **single source** of the values injected into message
        templates *and* consumed by channels that render natively (the webhook
        attachment fields, the Telegram HTML message, the email HTML card), so
        every surface stays consistent. It does no escaping — each channel
        applies its own (HTML for Telegram/email, markdown for webhook).

        Returns a dict whose keys are exactly the ``{placeholders}`` the default
        templates use, plus a few extras (``dashboard_url``, ``dashboard_line``).
        """
        import math
        from datetime import datetime

        import numpy as np

        # Format timestamp to string
        ts = alert_data.timestamp
        if isinstance(ts, np.datetime64):
            ts = ts.astype(datetime)

        # Convert naive UTC timestamp to target timezone if specified
        if alert_data.timezone:
            from zoneinfo import ZoneInfo

            ts = ts.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(alert_data.timezone))
            ts_str = f"{ts.strftime('%Y-%m-%d %H:%M:%S')} ({alert_data.timezone})"
        else:
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")

        # Format confidence interval
        if alert_data.confidence_lower is not None and alert_data.confidence_upper is not None:
            confidence_str = (
                f"[{alert_data.confidence_lower:.2f}, {alert_data.confidence_upper:.2f}]"
            )
        else:
            confidence_str = "N/A"

        # One-sided-aware expected range. A NaN/inf bound means "no bound on
        # that side" (e.g. ManualBounds with only ``lower_bound`` set), so we
        # render ">= lo" / "<= hi" instead of the confusing "[7.00, nan]".
        def _bounded(b: Any) -> bool:
            return b is not None and not (isinstance(b, float) and (math.isnan(b) or math.isinf(b)))

        lo_ok = _bounded(alert_data.confidence_lower)
        hi_ok = _bounded(alert_data.confidence_upper)
        if lo_ok and hi_ok:
            expected_range = (
                f"[{alert_data.confidence_lower:.2f}, {alert_data.confidence_upper:.2f}]"
            )
        elif lo_ok:
            expected_range = f">= {alert_data.confidence_lower:.2f}"
        elif hi_ok:
            expected_range = f"<= {alert_data.confidence_upper:.2f}"
        else:
            expected_range = "N/A"

        # Alert-rule display values. The orchestrator fills these from the
        # configured AlertConditions; for direct-API/non-anomaly callers that
        # leave them unset we fall back to the observed counts so the default
        # templates never render a bare "None".
        detector_count = alert_data.detector_count
        min_detectors = (
            alert_data.min_detectors if alert_data.min_detectors is not None else detector_count
        )
        consecutive_required = (
            alert_data.consecutive_required
            if alert_data.consecutive_required is not None
            else alert_data.consecutive_count
        )
        direction_policy = alert_data.direction_policy or alert_data.direction

        # Display-safe value: stays usable even when value is None/NaN (no-data).
        raw_value = alert_data.value
        if raw_value is None or (isinstance(raw_value, float) and math.isnan(raw_value)):
            value_display = "no data"
            value_for_template: Any = "no data"
        else:
            value_display = f"{raw_value}"
            value_for_template = raw_value

        # Format description line (empty string if no description)
        description_line = f"{alert_data.description}\n" if alert_data.description else ""

        # Format mentions
        mentions_str = self.format_mentions(alert_data.mentions)
        mentions_line = f"\n{mentions_str}" if mentions_str else ""

        # Optional dashboard link surfaced both as a raw placeholder and a ready
        # "Dashboard: <url>" line (empty when unset so templates stay clean).
        dashboard_url = alert_data.dashboard_url or ""
        dashboard_line = f"Dashboard: {dashboard_url}\n" if dashboard_url else ""

        # "How to read this alert" link (same shape as dashboard): a raw
        # placeholder plus a ready-to-drop line, both empty when unset.
        help_url = alert_data.help_url or ""
        help_line = f"{ALERT_GUIDE_LABEL}: {help_url}\n" if help_url else ""

        # Project name + synth prefix for templates. Prefix is empty when
        # project_name is None so default templates render cleanly for
        # callers that don't set it.
        project_name = alert_data.project_name or ""
        project_name_prefix = f"[{alert_data.project_name}] " if alert_data.project_name else ""

        # Status keyword
        if alert_data.is_error:
            status = "ERROR"
        elif alert_data.is_no_data:
            status = "NO_DATA"
        elif alert_data.is_recovery:
            status = "RECOVERED"
        else:
            status = "ANOMALY"

        return {
            "metric_name": alert_data.metric_name,
            "project_name": project_name,
            "project_name_prefix": project_name_prefix,
            "timestamp": ts_str,
            "timezone": alert_data.timezone,
            "value": value_for_template,
            "value_display": value_display,
            "confidence_lower": alert_data.confidence_lower,
            "confidence_upper": alert_data.confidence_upper,
            "confidence_interval": confidence_str,
            "expected_range": expected_range,
            "detector_name": alert_data.detector_name,
            "detector_count": detector_count,
            "detector_params": alert_data.detector_params,
            "direction": alert_data.direction,
            "direction_policy": direction_policy,
            "min_detectors": min_detectors,
            "severity": alert_data.severity,
            "consecutive_count": alert_data.consecutive_count,
            "consecutive_required": consecutive_required,
            "status": status,
            "error_type": alert_data.error_type or "",
            "error_message": alert_data.error_message or "",
            "description": alert_data.description or "",
            "description_line": description_line,
            "dashboard_url": dashboard_url,
            "dashboard_line": dashboard_line,
            "help_url": help_url,
            "help_line": help_line,
            "help_label": ALERT_GUIDE_LABEL,
            "mentions": mentions_str,
            "mentions_line": mentions_line,
        }

    # ---- Status presentation (shared accents across all channels) ----
    # Kept in sync with the brand status tokens (.claude/rules/design.md) and the
    # website status colors so chat, email and dashboards read the same way.
    _STATUS_COLORS = {
        "anomaly": "#D63232",
        "recovery": "#36A64F",
        "no_data": "#F0AD4E",
        "error": "#5A7A8C",
    }
    _STATUS_WORDS = {
        "anomaly": "Anomaly",
        "recovery": "Recovered",
        "no_data": "No data",
        "error": "Pipeline error",
    }
    # Colored status dots — the at-a-glance status cue that leads every alert
    # title/headline (and the only color cue on Telegram, which has no bar).
    _STATUS_EMOJI = {
        "anomaly": "\U0001f534",  # red circle
        "recovery": "\U0001f7e2",  # green circle
        "no_data": "\U0001f7e1",  # yellow circle
        "error": "\U0001f535",  # blue circle
    }

    @staticmethod
    def status_kind(alert_data: AlertData) -> str:
        """Return the alert kind: ``anomaly`` / ``recovery`` / ``no_data`` / ``error``."""
        if alert_data.is_error:
            return "error"
        if alert_data.is_no_data:
            return "no_data"
        if alert_data.is_recovery:
            return "recovery"
        return "anomaly"

    def status_color(self, alert_data: AlertData) -> str:
        """Accent color for this alert kind (hex)."""
        return self._STATUS_COLORS[self.status_kind(alert_data)]

    def status_word(self, alert_data: AlertData) -> str:
        """Human-readable status word for this alert kind."""
        return self._STATUS_WORDS[self.status_kind(alert_data)]

    def status_emoji(self, alert_data: AlertData) -> str:
        """Colored status dot for channels without a native color bar."""
        return self._STATUS_EMOJI[self.status_kind(alert_data)]

    def format_mentions(self, mentions: list[str]) -> str:
        """
        Format mentions list into platform-native syntax.

        Override in subclasses for platform-specific formatting.
        Default implementation prepends @ to each mention.

        Args:
            mentions: List of usernames or special keywords
                      ("channel", "all", "here")

        Returns:
            Formatted mentions string (e.g., "@john @here")
        """
        if not mentions:
            return ""
        return " ".join(f"@{m}" for m in mentions)

    def format_title(
        self,
        alert_data: AlertData,
    ) -> str:
        """
        Format alert title from template.

        Used by channels that support separate title fields (e.g., webhook attachments).

        Args:
            alert_data: Alert data to format

        Returns:
            Formatted title string
        """
        if alert_data.is_error:
            title_template = self.get_default_error_title_template()
        elif alert_data.is_no_data:
            title_template = self.get_default_no_data_title_template()
        elif alert_data.is_recovery:
            title_template = self.get_default_recovery_title_template()
        else:
            title_template = self.get_default_title_template()

        project_name = alert_data.project_name or ""
        project_name_prefix = f"[{alert_data.project_name}] " if alert_data.project_name else ""

        return title_template.format(
            metric_name=alert_data.metric_name,
            project_name=project_name,
            project_name_prefix=project_name_prefix,
        )

    def get_default_template(self) -> str:
        """
        Get default message template for anomaly alerts.

        Returns:
            Default template string
        """
        return (
            "🔴 {project_name_prefix}Alert: {metric_name}\n"
            "{description_line}"
            "Quorum {detector_count}/{min_detectors} · "
            "direction {direction} (policy {direction_policy}) · "
            "consecutive {consecutive_count}/{consecutive_required}\n"
            "Rule: min_detectors={min_detectors} · "
            "direction={direction_policy} · consecutive={consecutive_required}\n"
            "\n"
            "Latest point (evidence):\n"
            "· Time: {timestamp}\n"
            "· Value: {value_display} | Expected: {expected_range}\n"
            "· Severity: {severity:.2f}\n"
            "Detectors: {detector_name}\n"
            "Parameters: {detector_params}\n"
            "{dashboard_line}"
            "{help_line}"
            "{mentions_line}"
        )

    def get_default_recovery_template(self) -> str:
        """
        Get default message template for recovery alerts.

        Returns:
            Default recovery template string
        """
        return (
            "🟢 {project_name_prefix}Alert cleared: {metric_name}\n"
            "{description_line}"
            "The alert condition no longer holds — "
            "the metric is back within expected bounds.\n"
            "Rule: min_detectors={min_detectors} · "
            "direction={direction_policy} · consecutive={consecutive_required}\n"
            "\n"
            "Latest point:\n"
            "· Time: {timestamp}\n"
            "· Value: {value_display} | Expected: {expected_range}\n"
            "Detectors: {detector_name}\n"
            "{dashboard_line}"
            "{help_line}"
            "{mentions_line}"
        )

    def get_default_title_template(self) -> str:
        """
        Get default title template for anomaly alerts.

        Used by channels that support separate title fields (e.g., webhook attachments).

        Returns:
            Default title template string
        """
        return "🔴 {project_name_prefix}Alert: {metric_name}"

    def get_default_recovery_title_template(self) -> str:
        """
        Get default title template for recovery alerts.

        Returns:
            Default recovery title template string
        """
        return "🟢 {project_name_prefix}Alert cleared: {metric_name}"

    def get_default_no_data_template(self) -> str:
        """
        Get default message template for no-data alerts.

        Used when ``no_data_alert: true`` and the latest expected interval
        has no datapoint (no row OR row with NULL/NaN value).
        """
        return (
            "🟡 {project_name_prefix}No data for metric: {metric_name}\n"
            "{description_line}"
            "Time: {timestamp}\n"
            "Status: query returned no datapoint for the latest interval\n"
            "{dashboard_line}"
            "{help_line}"
            "{mentions_line}"
        )

    def get_default_no_data_title_template(self) -> str:
        """Get default title template for no-data alerts."""
        return "🟡 {project_name_prefix}No data: {metric_name}"

    def get_default_error_template(self) -> str:
        """Default body template for project-level error alerts."""
        return (
            "🔵 {project_name_prefix}Pipeline failed for metric: {metric_name}\n"
            "{description_line}"
            "Time: {timestamp}\n"
            "Error: {error_type}: {error_message}\n"
            "{dashboard_line}"
            "{help_line}"
            "{mentions_line}"
        )

    def get_default_error_title_template(self) -> str:
        """Default title template for project-level error alerts.

        Includes the project name as a ``[name] `` prefix when set so
        multiple detectkit projects routed to the same alert channel
        stay distinguishable. The prefix collapses to an empty string
        when ``AlertData.project_name`` is None.
        """
        return "🔵 {project_name_prefix}Pipeline error: {metric_name}"

    def __repr__(self) -> str:
        """String representation of channel."""
        return f"{self.__class__.__name__}()"

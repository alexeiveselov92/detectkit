"""
ntfy.sh alert channel.

Publishes alerts as push notifications to an ntfy (https://ntfy.sh) topic —
delivered to any subscribed phone, desktop, or browser. ntfy has no bot
identity / avatar / color-bar concept (a push notification is title + body +
tags), so the status cue rides on the kind's tag emoji, which ntfy renders as
the leading glyph of the notification title — the status dot that
:meth:`BaseAlertChannel.format_title` bakes in is stripped from the title so
the glyph isn't doubled.
"""

import requests

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel

# ntfy's default per-message limit is ~4096 bytes; cap comfortably under it so
# a long detector-params JSON / description can never trip the server-side
# limit and get silently converted into a file attachment.
_MESSAGE_CAP_BYTES = 3800

# Alert kind -> ntfy tag (rendered as a leading emoji by ntfy clients). The
# tag becomes the notification's leading glyph; the status dot format_title
# bakes in is stripped (see ``_strip_status_dot``) so the two don't double up.
_TAGS: dict[str, list[str]] = {
    "anomaly": ["rotating_light"],
    "recovery": ["white_check_mark"],
    "no_data": ["warning"],
    "error": ["large_blue_circle"],
}

# Default ntfy priority (1 min .. 5 max, 3 = default) per alert kind. Only
# the urgent kinds (anomaly/error) are overridable via ``priority=`` — a
# recovery or a no-data notice stays calm even when the user wants urgent
# anomalies to buzz the phone.
_DEFAULT_PRIORITY: dict[str, int] = {
    "anomaly": 4,
    "recovery": 3,
    "no_data": 3,
    "error": 4,
}

_OVERRIDABLE_KINDS = ("anomaly", "error")


class NtfyChannel(BaseAlertChannel):
    """
    ntfy.sh push-notification alert channel.

    Publishes via ntfy's **JSON publishing** endpoint (``POST`` to the server
    root with a JSON body carrying ``topic``) rather than the simpler
    header-based ``PUT``/``POST`` (topic in the URL, fields in HTTP headers).
    JSON publishing is used instead because HTTP headers cannot reliably
    carry UTF-8 titles/bodies (a metric name or detector-params JSON with
    non-ASCII characters) — the JSON body has no such restriction.

    Rendering: the notification **title** is
    :meth:`~BaseAlertChannel.format_title` with its leading status-dot emoji
    (and the space after it) stripped — ntfy already prepends the kind's
    ``tags`` as emoji, so keeping the dot would show it twice. The
    **message** body is the plain-text :meth:`~BaseAlertChannel.format_message`
    (default or custom ``template``), since the notification title already
    carries the headline; it is capped at ``_MESSAGE_CAP_BYTES`` UTF-8 bytes
    (truncated on a character boundary, with a trailing ``"…"``) to stay under
    ntfy's own ~4096-byte message limit. ``dashboard_url`` becomes the
    notification's ``click`` target (tapping it opens the dashboard); the
    extra ``links`` plus the "how to read this alert" help link become up to
    three ``view`` **actions** — the dashboard deliberately never doubles as
    an action since it already rides on ``click``.

    Priority defaults to 4 (high) for anomaly/error and 3 (default) for
    recovery/no-data. An explicit ``priority`` overrides **only** the
    anomaly/error value — a calmer recovery/no-data notification is a
    deliberate choice, not a bug, so it is never bumped by the same knob.

    Parameters:
        topic (str): ntfy topic to publish to (required).
        server (str): ntfy server base URL (default: the public
            ``https://ntfy.sh``; a trailing slash is stripped). Self-hosted
            servers work the same way.
        token (str | None): ntfy access token, sent as
            ``Authorization: Bearer <token>``. Wins over ``user``/``password``
            when both are set.
        user (str | None): Username for HTTP basic auth (used only when
            ``token`` is unset).
        password (str | None): Password for HTTP basic auth (used only when
            ``token`` is unset).
        priority (int | None): 1 (min) .. 5 (max) ntfy priority override for
            anomaly/error notifications only (default: ``None``, i.e. use the
            kind's built-in default). Must be in ``1..5`` when set.
        timeout (int): Request timeout in seconds (default: 10).

    Example:
        >>> channel = NtfyChannel(topic="my-alerts")
        >>> channel.send(alert_data)

        >>> # Self-hosted server with a token
        >>> channel = NtfyChannel(
        ...     topic="prod-alerts",
        ...     server="https://ntfy.example.com",
        ...     token="tk_xxx",
        ... )
    """

    def __init__(
        self,
        topic: str,
        server: str = "https://ntfy.sh",
        token: str | None = None,
        user: str | None = None,
        password: str | None = None,
        priority: int | None = None,
        timeout: int = 10,
    ) -> None:
        """Initialize the ntfy channel."""
        if not topic:
            raise ValueError("topic is required for NtfyChannel")
        if priority is not None and not (1 <= priority <= 5):
            raise ValueError("priority must be between 1 and 5")

        self.topic = topic
        self.server = server.rstrip("/")
        self.token = token
        self.user = user
        self.password = password
        self.priority = priority
        self.timeout = timeout

    def send(
        self,
        alert_data: AlertData,
        template: str | None = None,
    ) -> bool:
        """
        Publish the alert as an ntfy push notification.

        Args:
            alert_data: Alert data to send.
            template: Optional custom plain-text message template (rendered
                via :meth:`~BaseAlertChannel.format_message`, same as the
                default body). Title, tags, priority, click and actions are
                unaffected by a custom template.

        Returns:
            True if the ntfy server accepted the publish, False otherwise.
        """
        kind = self.status_kind(alert_data)
        ctx = self.build_context(alert_data)

        title = self._strip_status_dot(self.format_title(alert_data))
        message = self._cap_message(self.format_message(alert_data, template))

        payload: dict[str, object] = {
            "topic": self.topic,
            "title": title,
            "message": message,
            "priority": self._priority_for(kind),
            "tags": _TAGS[kind],
        }
        if alert_data.dashboard_url:
            payload["click"] = alert_data.dashboard_url

        actions = self._build_actions(alert_data, ctx)
        if actions:
            payload["actions"] = actions

        headers: dict[str, str] = {}
        auth: tuple[str, str] | None = None
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        elif self.user and self.password:
            auth = (self.user, self.password)

        try:
            response = requests.post(
                self.server,
                json=payload,
                headers=headers,
                auth=auth,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"Failed to send ntfy alert: {e}")
            return False

    # ------------------------------------------------------------------
    # Payload construction helpers
    # ------------------------------------------------------------------
    def _priority_for(self, kind: str) -> int:
        """Resolve the ntfy priority for *kind*, honoring the anomaly/error-only override."""
        if self.priority is not None and kind in _OVERRIDABLE_KINDS:
            return self.priority
        return _DEFAULT_PRIORITY[kind]

    @staticmethod
    def _build_actions(alert_data: AlertData, ctx: dict[str, object]) -> list[dict[str, str]]:
        """Up to three ``view`` action buttons: extra links, then the help link.

        ``dashboard_url`` is deliberately excluded — it already rides on the
        notification's ``click`` target and would otherwise be duplicated.
        """
        actions: list[dict[str, str]] = []
        for label, url in alert_data.links.items():
            actions.append({"action": "view", "label": label, "url": url})
        help_url = ctx.get("help_url")
        if help_url:
            actions.append(
                {"action": "view", "label": str(ctx["help_label"]), "url": str(help_url)}
            )
        return actions[:3]

    def _strip_status_dot(self, title: str) -> str:
        """Strip a leading ``BaseAlertChannel._STATUS_EMOJI`` dot + space.

        ntfy already renders the kind's ``tags`` as a leading emoji, so
        keeping the status dot baked into ``format_title`` would show the
        same status twice.
        """
        for emoji in self._STATUS_EMOJI.values():
            prefix = f"{emoji} "
            if title.startswith(prefix):
                return title[len(prefix) :]
        return title

    @staticmethod
    def _cap_message(text: str, limit: int = _MESSAGE_CAP_BYTES) -> str:
        """Truncate *text* to *limit* UTF-8 bytes on a character boundary.

        Encodes once, slices the bytes, then decodes with ``errors="ignore"``
        so a multi-byte character straddling the cut is dropped rather than
        corrupted, and appends an ellipsis to signal truncation happened.
        """
        encoded = text.encode("utf-8")
        if len(encoded) <= limit:
            return text
        ellipsis = "…"
        budget = max(limit - len(ellipsis.encode("utf-8")), 0)
        truncated = encoded[:budget].decode("utf-8", errors="ignore")
        return truncated + ellipsis

    # ------------------------------------------------------------------
    # Plain-text bodies — the notification title already carries the
    # headline, so these are the webhook plain bodies verbatim (no status
    # dot / "Alert:"/"Alert cleared:" prefix line).
    # ------------------------------------------------------------------
    def get_default_template(self) -> str:
        """Plain-text anomaly body (metric name lives in the title)."""
        return (
            "{description_line}"
            "{anomaly_lead}\n"
            "Rule: {rule_display}\n"
            "\n"
            "Value: {value_display} | Expected: {expected_range}\n"
            "Quorum: {detector_count}/{min_detectors} · {direction}\n"
            "Severity: {severity:.2f}\n"
            "{window_line}"
            "Detectors: {detector_name}\n"
            "Parameters: {detector_params}\n"
            "{dashboard_line}"
            "{help_line}"
            "{mentions_line}"
        )

    def get_default_recovery_template(self) -> str:
        """Plain-text recovery body (metric name lives in the title)."""
        return (
            "{description_line}"
            "{recovery_lead}\n"
            "Rule: {rule_display}\n"
            "\n"
            "Value: {value_display} | Expected: {expected_range}\n"
            "{window_line}"
            "Detectors: {detector_name}\n"
            "{dashboard_line}"
            "{help_line}"
            "{mentions_line}"
        )

    def get_default_no_data_template(self) -> str:
        """Plain-text no-data body (metric name lives in the title)."""
        return (
            "{description_line}"
            "Time: {timestamp}\n"
            "Status: query returned no datapoint for the latest interval\n"
            "{dashboard_line}"
            "{help_line}"
            "{mentions_line}"
        )

    def get_default_error_template(self) -> str:
        """Plain-text error body (metric name lives in the title)."""
        return (
            "{description_line}"
            "Time: {timestamp}\n"
            "Error: {error_type}: {error_message}\n"
            "{dashboard_line}"
            "{help_line}"
            "{mentions_line}"
        )

    def __repr__(self) -> str:
        """String representation of the channel."""
        return f"NtfyChannel(server='{self.server}', topic='{self.topic}')"

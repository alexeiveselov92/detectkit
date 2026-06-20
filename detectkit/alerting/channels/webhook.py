"""
Generic webhook alert channel.

Sends alerts to any webhook endpoint that accepts JSON payload.
Compatible with Mattermost, Slack, and other webhook-based systems.
"""

from datetime import datetime, timezone
from typing import Any

import numpy as np
import requests

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.channels.branding import BRAND_ICON_URL, BRAND_USERNAME


class WebhookChannel(BaseAlertChannel):
    """
    Generic webhook alert channel.

    Sends formatted alert messages to any webhook URL with JSON payload.
    Compatible with:
    - Mattermost incoming webhooks
    - Slack incoming webhooks
    - Custom webhook endpoints

    Rendering: the default (no custom ``template``) payload is a single
    **Slack/Mattermost message attachment** — a colored accent bar, a title,
    a short markdown lead, and a compact **fields grid** (Value / Expected /
    Quorum / Severity, then full-width Detected-at / Detectors / Parameters),
    branded with a ``footer`` + ``footer_icon``. This renders richly on both
    Slack and Mattermost from one payload. A custom ``template`` degrades to a
    plain text-only attachment (the template is one opaque string that can't be
    sliced into fields), keeping the color, title and branding.

    Mentions ride in the **top-level** ``text`` (mentions inside attachments do
    not reliably notify on Slack). A ``dashboard_url`` makes the attachment
    title clickable (``title_link``) — native on both platforms, so it avoids
    the Slack ``<url|text>`` vs Mattermost ``[text](url)`` link-syntax split.

    The payload shape::

        {
            "username": "detectkit",
            "icon_url": "https://.../bot-icon.png",   # or "icon_emoji"
            "text": "<!here> ...",                      # mentions (top level)
            "channel": "#channel",                      # optional (Slack)
            "attachments": [{"color": ..., "title": ..., "fields": [...], ...}]
        }

    Branding: the bot defaults to the **detectkit brand avatar** (``icon_url``)
    and name (``username``). An explicit ``icon_url`` overrides it with a custom
    image; an explicit ``icon_emoji`` opts out of the avatar in favor of an
    emoji. Only one icon field is sent (``icon_url`` wins when both are set).

    Parameters:
        webhook_url (str): Webhook URL to send alerts to
        username (str): Bot username to display (default: "detectkit")
        icon_url (str): Bot avatar image URL (default: detectkit brand avatar)
        icon_emoji (str): Bot emoji icon — use instead of an avatar image
            (default: None; falls back to the brand avatar)
        channel (str): Target channel (optional, for Slack/Mattermost)
        timeout (int): Request timeout in seconds (default: 10)
        extra_headers (dict): Additional HTTP headers (optional)

    Example:
        >>> # Mattermost
        >>> channel = WebhookChannel(
        ...     webhook_url="https://mattermost.example.com/hooks/xxx"
        ... )
        >>>
        >>> # Slack
        >>> channel = WebhookChannel(
        ...     webhook_url="https://hooks.slack.com/services/xxx",
        ...     channel="#alerts"
        ... )
        >>>
        >>> # Custom webhook
        >>> channel = WebhookChannel(
        ...     webhook_url="https://custom.example.com/webhook",
        ...     extra_headers={"Authorization": "Bearer token"}
        ... )
    """

    def __init__(
        self,
        webhook_url: str,
        username: str = BRAND_USERNAME,
        icon_url: str | None = None,
        icon_emoji: str | None = None,
        channel: str | None = None,
        timeout: int = 10,
        extra_headers: dict[str, str] | None = None,
    ):
        """Initialize webhook channel."""
        if not webhook_url:
            raise ValueError("webhook_url is required")

        self.webhook_url = webhook_url
        self.username = username
        # Default to the detectkit brand avatar. An explicit icon_url or
        # icon_emoji opts out of the default; we only fill in the brand avatar
        # when the user configured neither.
        if icon_url is None and icon_emoji is None:
            icon_url = BRAND_ICON_URL
        self.icon_url = icon_url
        self.icon_emoji = icon_emoji
        self.channel = channel
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    def send(
        self,
        alert_data: AlertData,
        template: str | None = None,
    ) -> bool:
        """
        Send alert to webhook.

        Args:
            alert_data: Alert data to send
            template: Optional custom message template. When given, the
                attachment carries the formatted template as a single text
                blob (no fields grid); otherwise the rich default is built.

        Returns:
            True if sent successfully, False otherwise

        Raises:
            requests.RequestException: If request fails critically

        Example:
            >>> channel = WebhookChannel(webhook_url="https://...")
            >>> success = channel.send(alert_data)
        """
        payload = self.build_payload(alert_data, template)

        # Prepare headers
        headers = {"Content-Type": "application/json"}
        headers.update(self.extra_headers)

        # Send to webhook
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            # Log error but don't crash
            print(f"Failed to send webhook alert: {e}")
            return False

    # ------------------------------------------------------------------
    # Payload construction
    # ------------------------------------------------------------------
    def build_payload(
        self,
        alert_data: AlertData,
        template: str | None = None,
    ) -> dict[str, Any]:
        """Build the Slack/Mattermost-compatible JSON payload.

        Split out from :meth:`send` so it can be unit-tested and reused by the
        website preview / docs without performing a network call.
        """
        title = self.format_title(alert_data)
        color = self.status_color(alert_data)
        ctx = self.build_context(alert_data)

        if template is not None:
            # Custom template → opaque text-only attachment (can't be sliced
            # into fields), but keep the color, title, branding and mrkdwn.
            attachment: dict[str, Any] = {
                "color": color,
                "title": title,
                "text": self.format_message(alert_data, template),
                "mrkdwn_in": ["text"],
            }
        else:
            attachment = self._build_rich_attachment(alert_data, ctx, color, title)

        # Dashboard link → clickable attachment title (native on both platforms).
        if alert_data.dashboard_url:
            attachment["title_link"] = alert_data.dashboard_url

        # Brand the attachment footer (reliable on Slack even when top-level
        # username/icon are locked to the app install). Pair the brand name with
        # the project name when set ("detectkit · my_project") so two projects
        # posting to the same channel stay distinguishable even past the title.
        footer = self.username or BRAND_USERNAME
        if alert_data.project_name:
            footer = f"{footer} · {alert_data.project_name}"
        attachment["footer"] = footer
        if self.icon_url:
            attachment["footer_icon"] = self.icon_url
        # Slack-only sugar: a real timestamp under the footer. Mattermost
        # ignores it; the human-readable "Detected at" field carries the time
        # on both.
        ts_unix = self._unix_ts(alert_data.timestamp)
        if ts_unix is not None:
            attachment["ts"] = ts_unix

        payload: dict[str, Any] = {
            "username": self.username,
            "attachments": [attachment],
        }

        # Mentions ride in TOP-LEVEL text — placed inside an attachment they
        # render but do not reliably notify on Slack.
        mentions = ctx["mentions"]
        if mentions:
            payload["text"] = mentions

        # Send exactly one icon field: the avatar image (brand default or a
        # custom override) takes precedence over an emoji.
        if self.icon_url:
            payload["icon_url"] = self.icon_url
        elif self.icon_emoji:
            payload["icon_emoji"] = self.icon_emoji

        # Add channel if specified (for Slack)
        if self.channel:
            payload["channel"] = self.channel

        return payload

    def _build_rich_attachment(
        self,
        alert_data: AlertData,
        ctx: dict[str, Any],
        color: str,
        title: str,
    ) -> dict[str, Any]:
        """Build the default fields-based attachment for *alert_data*.

        The lead text and which fields render depend on the alert kind
        (anomaly / recovery / no-data / error); long values (params, detectors,
        error message) use full-width fields, short stats use the 2-col grid.
        """
        kind = self.status_kind(alert_data)
        fields: list[dict[str, Any]] = []

        def short(name: str, value: str) -> None:
            if value:
                fields.append({"title": name, "value": value, "short": True})

        def full(name: str, value: str) -> None:
            if value:
                fields.append({"title": name, "value": value, "short": False})

        def code(s: str) -> str:
            return f"`{s}`" if s else ""

        # The configured firing rule, set apart as a bold "Rule" label + an
        # inline-code chip so it reads as "this is the config that fired" at a
        # glance. Backticks render identically on Slack and Mattermost; the bold
        # label is platform-aware (see ``_bold``).
        rule_chip = f"{self._bold('Rule')} " + code(
            f"min_detectors={ctx['min_detectors']} · "
            f"direction={ctx['direction_policy']} · "
            f"consecutive={ctx['consecutive_required']}"
        )

        if kind == "anomaly":
            lead = (
                f"{rule_chip}\n"
                f"Latest {ctx['consecutive_count']}/{ctx['consecutive_required']} "
                "consecutive points met the quorum."
            )
            short("Value", code(ctx["value_display"]))
            short("Expected", code(ctx["expected_range"]))
            short("Quorum", f"{ctx['detector_count']}/{ctx['min_detectors']} · {ctx['direction']}")
            short("Severity", f"{alert_data.severity:.2f}")
            full("Detected at", ctx["timestamp"])
            full("Detectors", code(ctx["detector_name"]))
            if ctx["detector_params"]:
                full("Parameters", f"```{ctx['detector_params']}```")
        elif kind == "recovery":
            lead = (
                "The alert condition no longer holds — the metric is back within "
                f"expected bounds.\n{rule_chip}"
            )
            short("Value", code(ctx["value_display"]))
            short("Expected", code(ctx["expected_range"]))
            full("Detected at", ctx["timestamp"])
            full("Detectors", code(ctx["detector_name"]))
        elif kind == "no_data":
            lead = "Query returned no datapoint for the latest expected interval."
            full("Expected at", ctx["timestamp"])
            short("Expected", code(ctx["expected_range"]))
        else:  # error
            lead = "The detectkit pipeline failed for this metric."
            full("Detected at", ctx["timestamp"])
            err = f"{ctx['error_type']}: {ctx['error_message']}".strip(": ")
            full("Error", code(err))

        # Links block — kept as its own flexible field, but every entry is a
        # compact clickable label, never a raw URL string. A Grafana dashboard
        # URL can be a paragraph long once it carries variables; nobody should
        # read that in an alert, so we hide it behind the label and render in the
        # platform's link syntax. Holds dashboard + any extra links + the "how to
        # read this alert" guide, joined by " · ".
        link_parts = []
        if alert_data.dashboard_url:
            link_parts.append(self._link_markup(alert_data.dashboard_url, "Dashboard"))
        for label, url in alert_data.links.items():
            link_parts.append(self._link_markup(url, label))
        if ctx["help_url"]:
            link_parts.append(self._link_markup(ctx["help_url"], ctx["help_label"]))
        if link_parts:
            full("Links", " · ".join(link_parts))

        # A plain-text one-liner for notification previews / unsupported clients.
        if kind == "no_data":
            fallback = f"{title} at {ctx['timestamp']}"
        elif kind == "error":
            fallback = f"{title} — {ctx['error_type']}: {ctx['error_message']}"
        else:
            fallback = (
                f"{title} — {ctx['value_display']} "
                f"(expected {ctx['expected_range']}) at {ctx['timestamp']}"
            )

        return {
            "fallback": fallback,
            "color": color,
            "title": title,
            "text": lead,
            "fields": fields,
            "mrkdwn_in": ["text", "fields"],
        }

    def _bold(self, text: str) -> str:
        """Render *text* bold in the target platform's markdown.

        Slack mrkdwn uses ``*bold*``; Mattermost and generic webhooks use
        CommonMark ``**bold**`` (where ``*x*`` would render as italic). Mirrors
        the platform branch in :meth:`_link_markup`, detecting Slack from the
        webhook host.
        """
        if not text:
            return ""
        if "hooks.slack.com" in self.webhook_url:
            return f"*{text}*"
        return f"**{text}**"

    def _link_markup(self, url: str, label: str) -> str:
        """Render *label* as a clickable link in the target platform's syntax.

        Slack incoming webhooks (``hooks.slack.com``) use ``<url|label>``;
        Mattermost and other webhooks use markdown ``[label](url)``. This keeps a
        link a short clickable phrase instead of a raw URL — important because a
        real dashboard URL (e.g. Grafana with many variables) can be extremely
        long, and no one should have to read it inside an alert.
        """
        if "hooks.slack.com" in self.webhook_url:
            return f"<{url}|{label}>"
        return f"[{label}]({url})"

    @staticmethod
    def _unix_ts(ts: Any) -> int | None:
        """Epoch seconds (UTC) for a naive-UTC timestamp, or None on failure."""
        try:
            if isinstance(ts, np.datetime64):
                ts = ts.astype("datetime64[s]").astype(datetime)
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                return int(ts.timestamp())
        except (ValueError, TypeError, OverflowError):
            return None
        return None

    def get_default_template(self) -> str:
        """
        Plain-text anomaly body — used for the attachment ``fallback`` and as
        the email plain-text part. Metric name lives in the title.
        """
        return (
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
        Plain-text recovery body. Metric name lives in the title.
        """
        return (
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
        """String representation."""
        url_preview = (
            self.webhook_url[:30] + "..." if len(self.webhook_url) > 30 else self.webhook_url
        )
        channel_info = f", channel='{self.channel}'" if self.channel else ""
        return f"WebhookChannel(url='{url_preview}', username='{self.username}'{channel_info})"

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

    Rendering: the default (no custom ``template``) anomaly/recovery payload is
    **two stacked Slack/Mattermost attachments** — a colored **base card** that
    is always visible (the title, a short markdown lead with the **Rule** chip,
    the Value / Expected fields and an always-visible compact **Links** field)
    and a neutral **detail card** carrying the verbose tail (Quorum / Severity /
    the anomalous span / Detectors / Parameters) as one markdown ``text`` block.
    Slack and Mattermost natively collapse only an attachment's ``text`` (Slack
    above 700 characters / 5 line breaks, Mattermost above ~200px of rendered
    height) and **never** collapse the ``fields`` grid — so routing the bulk
    into the detail card's ``text`` lets the platform fold it behind a
    "Show more" toggle while the base (value, expected and links) stays in view.
    Short kinds (no-data / error) render as a single base card. A custom
    ``template`` degrades to a plain text-only attachment (one opaque string
    that can't be sliced into fields), keeping the color, title and branding.
    Branding (``footer`` + ``footer_icon``) rides on the **last** attachment so
    it sits at the bottom of the whole message, below the folded detail card.

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
            "attachments": [
                # base card — always visible (never folds; fields don't collapse)
                {"color": ..., "title": ..., "fields": [Value, Expected, Links], ...},
                # detail card — neutral, foldable text (anomaly/recovery only)
                {"text": "<verbose tail>", "mrkdwn_in": ["text"]},
            ]
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
            attachments: list[dict[str, Any]] = [
                {
                    "color": color,
                    "title": title,
                    "text": self.format_message(alert_data, template),
                    "mrkdwn_in": ["text"],
                }
            ]
        else:
            attachments = self._build_rich_attachments(alert_data, ctx, color, title)

        # Dashboard link → clickable title on the base (first) attachment.
        if alert_data.dashboard_url:
            attachments[0]["title_link"] = alert_data.dashboard_url

        # Brand the LAST attachment's footer (reliable on Slack even when
        # top-level username/icon are locked to the app install) so the brand
        # line sits at the bottom of the whole message — below the folded detail
        # card when one is present. Pair the brand name with the project name
        # when set ("detectkit · my_project") so two projects posting to the same
        # channel stay distinguishable even past the title.
        footer = self.username or BRAND_USERNAME
        if alert_data.project_name:
            footer = f"{footer} · {alert_data.project_name}"
        attachments[-1]["footer"] = footer
        if self.icon_url:
            attachments[-1]["footer_icon"] = self.icon_url
        # Slack-only sugar: a real timestamp under the footer. Mattermost
        # ignores it; the human-readable timestamp rides in the cards on both.
        ts_unix = self._unix_ts(alert_data.timestamp)
        if ts_unix is not None:
            attachments[-1]["ts"] = ts_unix

        payload: dict[str, Any] = {
            "username": self.username,
            "attachments": attachments,
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

    def _build_rich_attachments(
        self,
        alert_data: AlertData,
        ctx: dict[str, Any],
        color: str,
        title: str,
    ) -> list[dict[str, Any]]:
        """Build the default attachment(s) for *alert_data*.

        Returns a **base card** (always visible) and, for anomaly/recovery, a
        neutral **detail card** whose long ``text`` block the chat client folds
        behind "Show more". Slack and Mattermost collapse only an attachment's
        ``text`` (never the ``fields`` grid), so the base keeps the value, the
        expected band and the links permanently in view while the verbose tail
        (quorum, severity, the anomalous span, detectors, parameters) rides in
        the foldable detail card. No-data / error are short, so they render as a
        single base card. Both cards render from one payload on Slack and
        Mattermost.
        """
        kind = self.status_kind(alert_data)
        base_fields: list[dict[str, Any]] = []
        detail_lines: list[str] = []

        def short(name: str, value: str) -> None:
            """Add a 2-col field to the always-visible base card."""
            if value:
                base_fields.append({"title": name, "value": value, "short": True})

        def full(name: str, value: str) -> None:
            """Add a full-width field to the always-visible base card."""
            if value:
                base_fields.append({"title": name, "value": value, "short": False})

        def detail(name: str, value: str) -> None:
            """Add one line to the foldable detail card: bold label + value."""
            if value:
                detail_lines.append(f"{self._bold(name)} {value}")

        def code(s: str) -> str:
            return f"`{s}`" if s else ""

        # The configured firing rule, set apart as a bold "Rule" label + an
        # inline-code chip so it reads as "this is the config that fired" at a
        # glance. Backticks render identically on Slack and Mattermost; the bold
        # label is platform-aware (see ``_bold``). Stays in the always-visible
        # base lead.
        rule_chip = f"{self._bold('Rule')} " + code(
            f"min_detectors={ctx['min_detectors']} · "
            f"direction={ctx['direction_policy']} · "
            f"consecutive={ctx['consecutive_required']}"
        )

        if kind == "anomaly":
            # Base (always visible): the lead (how long it's been going on), the
            # Rule chip, and the value vs the expected band.
            lead = f"{ctx['anomaly_lead']}\n{rule_chip}"
            short("Value", code(ctx["value_display"]))
            short("Expected", code(ctx["expected_range"]))
            # Detail (folds): quorum, severity, the span, detectors + params.
            detail(
                "Quorum",
                f"{ctx['detector_count']}/{ctx['min_detectors']} · {ctx['direction']}",
            )
            detail("Severity", f"{alert_data.severity:.2f}")
            if ctx["started_display"]:
                detail("Anomaly began", ctx["started_display"])
                detail("Latest reading", ctx["timestamp"])
            else:
                detail("Detected at", ctx["timestamp"])
            detail("Detectors", code(ctx["detector_name"]))
            if ctx["detector_params"]:
                # Fenced block on its own lines so it renders as a code block (and
                # adds line breaks that help trip the platform's fold).
                detail_lines.append(
                    f"{self._bold('Parameters')}\n```\n{ctx['detector_params']}\n```"
                )
        elif kind == "recovery":
            lead = f"{ctx['recovery_lead']}\n{rule_chip}"
            short("Value", code(ctx["value_display"]))
            short("Expected", code(ctx["expected_range"]))
            # Detail (folds): the incident timeline (onset → fired → recovered)
            # and the detectors. ``detail`` skips the fired line when unknown.
            if ctx["started_display"]:
                detail("Anomaly began", ctx["started_display"])
                detail("Alert fired", ctx["fired_display"])
                detail("Recovered", ctx["timestamp"])
            else:
                detail("Cleared at", ctx["timestamp"])
            detail("Detectors", code(ctx["detector_name"]))
        elif kind == "no_data":
            lead = "Query returned no datapoint for the latest expected interval."
            full("Expected at", ctx["timestamp"])
            short("Expected", code(ctx["expected_range"]))
        else:  # error
            lead = "The detectkit pipeline failed for this metric."
            full("Detected at", ctx["timestamp"])
            err = f"{ctx['error_type']}: {ctx['error_message']}".strip(": ")
            full("Error", code(err))

        # Links — always visible in the base card. The dashboard / "how to read
        # this alert" links are actionable, so they never fold. Every entry is a
        # compact clickable label, never a raw URL string (a Grafana URL can be a
        # paragraph long once it carries variables; nobody should read that in an
        # alert), rendered in the platform's link syntax and joined by " · " on a
        # single line to stay compact. (The title is also a clickable dashboard
        # link.)
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

        base: dict[str, Any] = {
            "fallback": fallback,
            "color": color,
            "title": title,
            "text": lead,
            "fields": base_fields,
            "mrkdwn_in": ["text", "fields"],
        }
        attachments: list[dict[str, Any]] = [base]
        # Detail card: neutral (no color bar) so it reads as a continuation of
        # the base rather than a second alert, with the verbose tail in one
        # foldable ``text`` block.
        if detail_lines:
            attachments.append(
                {
                    "text": "\n".join(detail_lines),
                    "mrkdwn_in": ["text"],
                }
            )
        return attachments

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
            "{anomaly_lead}\n"
            "Rule: min_detectors={min_detectors} · "
            "direction={direction_policy} · consecutive={consecutive_required}\n"
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
        """
        Plain-text recovery body. Metric name lives in the title.
        """
        return (
            "{description_line}"
            "{recovery_lead}\n"
            "Rule: min_detectors={min_detectors} · "
            "direction={direction_policy} · consecutive={consecutive_required}\n"
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
        """String representation."""
        url_preview = (
            self.webhook_url[:30] + "..." if len(self.webhook_url) > 30 else self.webhook_url
        )
        channel_info = f", channel='{self.channel}'" if self.channel else ""
        return f"WebhookChannel(url='{url_preview}', username='{self.username}'{channel_info})"

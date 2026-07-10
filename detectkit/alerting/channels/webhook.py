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

    Rendering: the default (no custom ``template``) payload is a **single
    status-colored Slack/Mattermost attachment** whose whole body rides in one
    markdown ``text`` block, ordered most-important-first — the lead + **Rule**
    chip, then Value / Expected, the action **Links**, and finally the verbose
    evidence tail (Quorum / Severity / the anomalous span / Detectors /
    Parameters). Both platforms natively collapse a long attachment ``text``
    behind a **"Show more"** toggle (Slack above 700 characters / 5 line breaks;
    Mattermost wraps only the ``text`` in its ``maxHeight`` 200px fold — the
    ``title``, the color bar and the ``footer`` render *outside* that fold), so a
    long anomaly folds its tail exactly like a reference AlertManager alert while
    the one colored bar, the clickable title and the **branded footer (with the
    logo)** stay in view even when the body is collapsed. No-data / error alerts
    stay short, single un-folded cards; a long anomaly — or a full recovery
    timeline (onset → fired → recovered) — folds its tail. A custom ``template``
    renders the same shape — one colored, branded, text-only attachment.
    Branding (``footer`` + ``footer_icon``, the brand logo) rides on that single
    attachment and, being outside the text fold, is always visible.

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
                # one colored card; the long body folds behind "Show more",
                # the footer (brand + logo) stays visible below the fold.
                {
                    "color": ...,
                    "title": ...,
                    "text": "<lead + Rule + value/expected + links + tail>",
                    "footer": "detectkit · <project>",
                    "footer_icon": "https://.../bot-icon.png",
                    "mrkdwn_in": ["text"],
                },
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
                attachment carries the formatted template verbatim as the body
                text (in place of the structured lead/Value/tail sections);
                otherwise the rich default is built.

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

        # Dashboard link → clickable title on the attachment.
        if alert_data.dashboard_url:
            attachments[0]["title_link"] = alert_data.dashboard_url

        # Brand the (single) attachment's footer (reliable on Slack even when
        # top-level username/icon are locked to the app install). Mattermost and
        # Slack render an attachment's footer *outside* the "Show more" text
        # fold, so the brand line — and its logo (``footer_icon``) — stays
        # visible at the bottom of the message even when the body is collapsed.
        # Pair the brand name with the project name when set
        # ("detectkit · my_project") so two projects posting to the same channel
        # stay distinguishable even past the title.
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
        """Build the default **single** attachment for *alert_data*.

        Everything rides in one status-colored attachment whose body is a single
        markdown ``text`` block, ordered most-important-first: the lead + Rule
        chip, then value / expected, the action links, and finally the verbose
        evidence tail (quorum, severity, the anomalous span, detectors,
        parameters). Mattermost wraps only an attachment's ``text`` in its
        "Show more" fold (``maxHeight`` 200px) and renders the ``title``, color
        bar and ``footer`` outside it; Slack folds a long ``text`` too. So a long
        anomaly collapses its tail behind "Show more" — exactly the one-block,
        one-color, foldable layout of a reference AlertManager alert — while the
        colored bar, the clickable title and the branded footer/logo (attached in
        :meth:`build_payload`) stay in view even when collapsed. No-data / error
        stay short, single un-folded cards; a long anomaly (or a full recovery
        timeline) folds its tail.
        """
        kind = self.status_kind(alert_data)

        def code(s: str) -> str:
            return f"`{s}`" if s else ""

        def line(name: str, value: str) -> str:
            """One ``bold label + value`` body line (empty value → dropped)."""
            return f"{self._bold(name)} {value}" if value else ""

        # The configured firing rule, set apart as a bold "Rule" label + an
        # inline-code chip so it reads as "this is the config that fired" at a
        # glance. Backticks render identically on Slack and Mattermost; the bold
        # label is platform-aware (see ``_bold``). Leads the body, above the fold.
        rule_chip = f"{self._bold('Rule')} " + code(ctx["rule_display"])

        # Links — compact clickable labels (never raw URL strings: a Grafana URL
        # can be a paragraph long once it carries variables), rendered in the
        # platform's link syntax and joined by " · ". Kept high in the body so
        # they stay above the fold and actionable at a glance. (The title is also
        # a clickable dashboard link.)
        link_parts: list[str] = []
        if alert_data.dashboard_url:
            link_parts.append(self._link_markup(alert_data.dashboard_url, "Dashboard"))
        for label, url in alert_data.links.items():
            link_parts.append(self._link_markup(url, label))
        if ctx["help_url"]:
            link_parts.append(self._link_markup(ctx["help_url"], ctx["help_label"]))
        links_line = line("Links", " · ".join(link_parts)) if link_parts else ""

        # The body is built as sections joined by a blank line; the verbose tail
        # is last so the platform fold hides it first.
        sections: list[list[str]] = []
        if kind == "anomaly":
            sections.append([ctx["anomaly_lead"], rule_chip])
            sections.append(
                [
                    line("Value", code(ctx["value_display"])),
                    line("Expected", code(ctx["expected_range"])),
                    links_line,
                ]
            )
            tail = [
                line(
                    "Quorum",
                    f"{ctx['detector_count']}/{ctx['min_detectors']} · {ctx['direction']}",
                ),
                line("Severity", f"{alert_data.severity:.2f}"),
            ]
            if ctx["started_display"]:
                tail.append(line("Anomaly began", ctx["started_display"]))
                tail.append(line("Latest reading", ctx["timestamp"]))
            else:
                tail.append(line("Detected at", ctx["timestamp"]))
            tail.append(line("Detectors", code(ctx["detector_name"])))
            if ctx["detector_params"]:
                # Fenced block on its own lines so it renders as a code block (and
                # adds line breaks that help trip the platform's fold).
                tail.append(f"{self._bold('Parameters')}\n```\n{ctx['detector_params']}\n```")
            sections.append(tail)
        elif kind == "recovery":
            sections.append([ctx["recovery_lead"], rule_chip])
            sections.append(
                [
                    line("Value", code(ctx["value_display"])),
                    line("Expected", code(ctx["expected_range"])),
                    links_line,
                ]
            )
            # The incident timeline (onset → fired → recovered) + detectors;
            # ``line`` drops the fired entry when unknown.
            if ctx["started_display"]:
                tail = [
                    line("Anomaly began", ctx["started_display"]),
                    line("Alert fired", ctx["fired_display"]),
                    line("Recovered", ctx["timestamp"]),
                ]
            else:
                tail = [line("Cleared at", ctx["timestamp"])]
            tail.append(line("Detectors", code(ctx["detector_name"])))
            sections.append(tail)
        elif kind == "no_data":
            sections.append(["Query returned no datapoint for the latest expected interval."])
            sections.append(
                [
                    line("Expected at", ctx["timestamp"]),
                    line("Expected", code(ctx["expected_range"])),
                    links_line,
                ]
            )
        else:  # error
            err = f"{ctx['error_type']}: {ctx['error_message']}".strip(": ")
            sections.append(["The detectkit pipeline failed for this metric."])
            sections.append(
                [
                    line("Detected at", ctx["timestamp"]),
                    line("Error", code(err)),
                    links_line,
                ]
            )

        text = "\n\n".join(
            "\n".join(entry for entry in section if entry)
            for section in sections
            if any(entry for entry in section)
        )

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

        return [
            {
                "fallback": fallback,
                "color": color,
                "title": title,
                "text": text,
                "mrkdwn_in": ["text"],
            }
        ]

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
        """
        Plain-text recovery body. Metric name lives in the title.
        """
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
        """String representation."""
        url_preview = (
            self.webhook_url[:30] + "..." if len(self.webhook_url) > 30 else self.webhook_url
        )
        channel_info = f", channel='{self.channel}'" if self.channel else ""
        return f"WebhookChannel(url='{url_preview}', username='{self.username}'{channel_info})"

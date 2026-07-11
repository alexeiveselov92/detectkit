"""
Discord incoming-webhook alert channel.

Sends alerts to a Discord channel via an "Execute Webhook" incoming webhook
URL (``https://discord.com/api/webhooks/<id>/<token>``).
"""

from datetime import datetime, timezone
from typing import Any

import numpy as np
import requests

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.channels.branding import BRAND_ICON_URL, BRAND_USERNAME

# Discord embed limits (https://discord.com/developers/docs/resources/message#embed-object).
# Enforced defensively so a verbose alert never triggers a 400 from Discord.
_TITLE_CAP = 256
_DESCRIPTION_CAP = 4096
_FIELD_NAME_CAP = 256
_FIELD_VALUE_CAP = 1024
_FOOTER_CAP = 2048
# Detector params are appended to the description as a fenced block; capped on
# their own, and the whole block is dropped if it would push the description
# past this budget (well under the hard 4096 cap, leaving headroom for the
# lead/rule/value/links sections that precede it).
_PARAMS_CAP = 900
_PARAMS_DESC_BUDGET = 3500
# Top-level message content (the mentions line) has its own 2000-char limit,
# and the SUM of title + description + field names/values + footer text across
# the embed must stay under 6000 or Discord rejects the whole message.
_CONTENT_CAP = 2000
_EMBED_TOTAL_CAP = 6000


class DiscordChannel(BaseAlertChannel):
    """
    Discord alert channel using an incoming webhook.

    Sends one **embed** per alert via Discord's "Execute Webhook" endpoint.
    Discord embeds have no "Show more" fold (unlike Slack/Mattermost
    attachments), so the verbose evidence that ``WebhookChannel`` collapses
    behind a fold instead rides in a compact inline **field grid** — Quorum /
    Severity / the anomalous span / Detectors for an anomaly, the incident
    timeline for a recovery. No-data and error alerts stay short (no fields).

    The default (no custom ``template``) embed body mirrors
    ``WebhookChannel._build_rich_attachments``' section order: the lead
    sentence + a **Rule** chip, then **Value** / **Expected** plus a compact
    **Links** line (Dashboard, any extra links, then the "how to read this
    alert" guide — clickable labels, never raw URLs). Detector parameters
    (anomaly only) are appended as a fenced code block, capped and dropped
    entirely if they would blow the description budget.

    Mentions ride in the top-level ``content`` field — Discord never delivers
    a ping placed inside an embed — paired with an ``allowed_mentions`` object
    so ``@everyone``/``@here``/role mentions actually notify.

    Parameters:
        webhook_url (str): Discord webhook URL
            (``https://discord.com/api/webhooks/<id>/<token>``).
        username (str): Bot username override (default: the detectkit brand
            name).
        avatar_url (str): Bot avatar image URL override (default: the
            detectkit brand avatar).
        timeout (int): Request timeout in seconds (default: 10).

    Example:
        >>> channel = DiscordChannel(
        ...     webhook_url="https://discord.com/api/webhooks/123/abc"
        ... )
        >>> channel.send(alert_data)
    """

    def __init__(
        self,
        webhook_url: str,
        username: str = BRAND_USERNAME,
        avatar_url: str | None = None,
        timeout: int = 10,
    ) -> None:
        """Initialize Discord channel."""
        if not webhook_url:
            raise ValueError("webhook_url is required")

        self.webhook_url = webhook_url
        self.username = username
        # Default to the detectkit brand avatar; an explicit avatar_url opts out.
        self.avatar_url = avatar_url if avatar_url is not None else BRAND_ICON_URL
        self.timeout = timeout

    def send(
        self,
        alert_data: AlertData,
        template: str | None = None,
    ) -> bool:
        """
        Send alert to Discord.

        Args:
            alert_data: Alert data to send.
            template: Optional custom message template. Renders as a single
                plain embed (color/title/footer/timestamp kept, no field
                grid) with the formatted template as the description.

        Returns:
            True if sent successfully, False otherwise.

        Example:
            >>> channel = DiscordChannel(webhook_url="https://...")
            >>> success = channel.send(alert_data)
        """
        if template is not None:
            embed = self._build_template_embed(alert_data, template)
        else:
            embed = self._build_embed(alert_data)

        payload: dict[str, Any] = {
            "username": self.username,
            "avatar_url": self.avatar_url,
            "embeds": [embed],
        }

        # Mentions inside an embed never ping on Discord — they must ride in
        # the top-level message content, paired with allowed_mentions so the
        # platform actually delivers the ping instead of just rendering text.
        mentions = self.format_mentions(alert_data.mentions)
        if mentions:
            payload["content"] = self._cap(mentions, _CONTENT_CAP)
            payload["allowed_mentions"] = {"parse": ["everyone", "users", "roles"]}

        try:
            response = requests.post(self.webhook_url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"Failed to send Discord alert: {e}")
            return False

    # ------------------------------------------------------------------
    # Embed construction
    # ------------------------------------------------------------------
    def _build_embed(self, alert_data: AlertData) -> dict[str, Any]:
        """Build the default rich embed for *alert_data*."""
        ctx = self.build_context(alert_data)
        kind = self.status_kind(alert_data)

        description = self._build_description(alert_data, ctx, kind)
        description = self._append_params(description, ctx, kind)
        description = self._cap_block(description, _DESCRIPTION_CAP)

        title = self._cap(self.format_title(alert_data), _TITLE_CAP)
        footer = self._footer(alert_data)
        fields = self._fields(alert_data, ctx, kind)

        # Discord also enforces a 6000-char cap on the SUM of title +
        # description + all field names/values + footer text; the description
        # is the biggest block, so it absorbs any overflow.
        overhead = (
            len(title) + len(footer["text"]) + sum(len(f["name"]) + len(f["value"]) for f in fields)
        )
        if overhead + len(description) > _EMBED_TOTAL_CAP:
            description = self._cap_block(description, max(_EMBED_TOTAL_CAP - overhead, 64))

        embed: dict[str, Any] = {
            "color": self._color_int(alert_data),
            "title": title,
            "description": description,
            "footer": footer,
        }
        if alert_data.dashboard_url:
            embed["url"] = alert_data.dashboard_url
        timestamp = self._iso_utc(alert_data.timestamp)
        if timestamp is not None:
            embed["timestamp"] = timestamp

        if fields:
            embed["fields"] = fields

        return embed

    def _build_template_embed(self, alert_data: AlertData, template: str) -> dict[str, Any]:
        """Build the plain embed used for a custom ``template`` (no fields)."""
        title = self._cap(self.format_title(alert_data), _TITLE_CAP)
        footer = self._footer(alert_data)
        # Same 6000-char embed-total guard as the rich embed (title + footer
        # alone can leave less than the 4096 description cap).
        budget = min(_DESCRIPTION_CAP, _EMBED_TOTAL_CAP - len(title) - len(footer["text"]))
        embed: dict[str, Any] = {
            "color": self._color_int(alert_data),
            "title": title,
            "description": self._cap_block(self.format_message(alert_data, template), budget),
            "footer": footer,
        }
        if alert_data.dashboard_url:
            embed["url"] = alert_data.dashboard_url
        timestamp = self._iso_utc(alert_data.timestamp)
        if timestamp is not None:
            embed["timestamp"] = timestamp
        return embed

    def _build_description(
        self,
        alert_data: AlertData,
        ctx: dict[str, Any],
        kind: str,
    ) -> str:
        """The CommonMark description body, blank-line-separated sections
        mirroring ``WebhookChannel._build_rich_attachments``'s section order:
        (1) the kind lead + the **Rule** chip; (2) Value/Expected (anomaly and
        recovery only) + the compact Links line. The verbose evidence tail
        that the webhook attachment folds moves to :meth:`_fields` instead —
        Discord embeds have no fold.
        """

        def bold_code(label: str, value: str) -> str:
            return f"**{label}** `{value}`" if value else ""

        links_line = self._links_line(alert_data, ctx)

        sections: list[list[str]] = []
        if kind == "anomaly":
            sections.append([ctx["anomaly_lead"], f"**Rule** `{ctx['rule_display']}`"])
            sections.append(
                [
                    f"{bold_code('Value', ctx['value_display'])} · "
                    f"{bold_code('Expected', ctx['expected_range'])}",
                    links_line,
                ]
            )
        elif kind == "recovery":
            sections.append([ctx["recovery_lead"], f"**Rule** `{ctx['rule_display']}`"])
            sections.append(
                [
                    f"{bold_code('Value', ctx['value_display'])} · "
                    f"{bold_code('Expected', ctx['expected_range'])}",
                    links_line,
                ]
            )
        elif kind == "no_data":
            sections.append(["Query returned no datapoint for the latest expected interval."])
            sections.append(
                [
                    bold_code("Expected at", ctx["timestamp"]),
                    bold_code("Expected", ctx["expected_range"]),
                    links_line,
                ]
            )
        else:  # error
            err = f"{ctx['error_type']}: {ctx['error_message']}".strip(": ")
            sections.append(["The detectkit pipeline failed for this metric."])
            sections.append(
                [
                    bold_code("Detected at", ctx["timestamp"]),
                    bold_code("Error", err),
                    links_line,
                ]
            )

        return "\n\n".join(
            "\n".join(entry for entry in section if entry)
            for section in sections
            if any(entry for entry in section)
        )

    @staticmethod
    def _links_line(alert_data: AlertData, ctx: dict[str, Any]) -> str:
        """ "**Links** [Dashboard](url) · [label](url) · [How to read this
        alert](help)" — clickable labels, never raw URLs (empty when none)."""
        parts: list[str] = []
        if alert_data.dashboard_url:
            parts.append(f"[Dashboard]({alert_data.dashboard_url})")
        for label, url in alert_data.links.items():
            parts.append(f"[{label}]({url})")
        if ctx["help_url"]:
            parts.append(f"[{ctx['help_label']}]({ctx['help_url']})")
        if not parts:
            return ""
        return "**Links** " + " · ".join(parts)

    def _append_params(self, description: str, ctx: dict[str, Any], kind: str) -> str:
        """Append the fenced detector-params block (anomaly only), dropping it
        entirely rather than truncating the description mid-JSON if it would
        push the body past the budget."""
        if kind != "anomaly" or not ctx["detector_params"]:
            return description
        params = self._cap(ctx["detector_params"], _PARAMS_CAP)
        candidate = f"{description}\n\n**Parameters**\n```\n{params}\n```"
        if len(candidate) <= _PARAMS_DESC_BUDGET:
            return candidate
        return description

    def _fields(
        self,
        alert_data: AlertData,
        ctx: dict[str, Any],
        kind: str,
    ) -> list[dict[str, Any]]:
        """The inline field grid carrying the verbose tail — empty for
        no_data/error (their short body has no separate tail to move)."""

        def field(name: str, value: str) -> dict[str, Any]:
            return {
                "name": self._cap(name, _FIELD_NAME_CAP),
                "value": self._cap(value, _FIELD_VALUE_CAP),
                "inline": True,
            }

        fields: list[dict[str, Any]] = []
        if kind == "anomaly":
            fields.append(
                field(
                    "Quorum",
                    f"{ctx['detector_count']}/{ctx['min_detectors']} · {ctx['direction']}",
                )
            )
            fields.append(field("Severity", f"{alert_data.severity:.2f}"))
            if ctx["started_display"]:
                fields.append(field("Anomaly began", ctx["started_display"]))
                fields.append(field("Latest reading", ctx["timestamp"]))
            else:
                fields.append(field("Detected at", ctx["timestamp"]))
            fields.append(field("Detectors", ctx["detector_name"]))
        elif kind == "recovery":
            if ctx["started_display"]:
                fields.append(field("Anomaly began", ctx["started_display"]))
                if ctx["fired_display"]:
                    fields.append(field("Alert fired", ctx["fired_display"]))
                fields.append(field("Recovered", ctx["timestamp"]))
            else:
                fields.append(field("Cleared at", ctx["timestamp"]))
            fields.append(field("Detectors", ctx["detector_name"]))
        return fields

    def _footer(self, alert_data: AlertData) -> dict[str, Any]:
        """Branded footer, paired with the project name when set (mirrors
        ``WebhookChannel``'s "detectkit · <project>" footer)."""
        text = self.username or BRAND_USERNAME
        if alert_data.project_name:
            text = f"{text} · {alert_data.project_name}"
        footer: dict[str, Any] = {"text": self._cap(text, _FOOTER_CAP)}
        if self.avatar_url:
            footer["icon_url"] = self.avatar_url
        return footer

    def _color_int(self, alert_data: AlertData) -> int:
        """The status accent color as the integer Discord embeds expect."""
        return int(self.status_color(alert_data).lstrip("#"), 16)

    @staticmethod
    def _cap(value: str, limit: int) -> str:
        """Truncate *value* to *limit* chars with an ellipsis."""
        if len(value) <= limit:
            return value
        return value[: limit - 1] + "…"

    @classmethod
    def _cap_block(cls, value: str, limit: int) -> str:
        """Truncate a multi-line block to *limit* chars, cutting at the last
        line break before the limit when there is one — so a markdown link
        (``[label](https://…)``) is dropped whole, never sliced mid-URL into
        broken markup."""
        if len(value) <= limit:
            return value
        cut = value.rfind("\n", 0, limit - 2)
        if cut > 0:
            return value[:cut].rstrip() + "\n…"
        return cls._cap(value, limit)

    @staticmethod
    def _iso_utc(ts: Any) -> str | None:
        """ISO-8601 UTC string (``2026-07-11T10:30:00Z``) for a naive-UTC
        timestamp, or ``None`` when unset/unparseable. Mirrors
        ``WebhookChannel._iso_utc``."""
        if ts is None:
            return None
        try:
            if isinstance(ts, np.datetime64):
                ts = ts.astype("datetime64[s]").astype(datetime)
            if isinstance(ts, datetime):
                if ts.tzinfo is not None:
                    ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
                return str(ts.strftime("%Y-%m-%dT%H:%M:%SZ"))
        except (ValueError, TypeError, OverflowError):
            return None
        return None

    def format_mentions(self, mentions: list[str]) -> str:
        """
        Format mentions into Discord's native ping syntax.

        ``"all"``/``"everyone"``/``"channel"`` map to ``@everyone``,
        ``"here"`` to ``@here``. A value already shaped like a real Discord
        mention (``<@user_id>``/``<@&role_id>``) passes through verbatim.
        Anything else renders as a bare ``@name`` — bare names render but
        don't actually ping; a real user/role ping needs the ``<@id>`` form,
        which can be put directly in the ``mentions`` list.

        Args:
            mentions: List of usernames, role/user mentions, or the special
                keywords ``"channel"``/``"all"``/``"everyone"``/``"here"``.

        Returns:
            Space-joined Discord mention string.
        """
        if not mentions:
            return ""
        parts: list[str] = []
        for m in mentions:
            if m in ("all", "everyone", "channel"):
                parts.append("@everyone")
            elif m == "here":
                parts.append("@here")
            elif m.startswith("<@") and m.endswith(">"):
                parts.append(m)
            else:
                parts.append(f"@{m}")
        return " ".join(parts)

    def __repr__(self) -> str:
        """String representation."""
        url_preview = (
            self.webhook_url[:30] + "..." if len(self.webhook_url) > 30 else self.webhook_url
        )
        return f"DiscordChannel(url='{url_preview}', username='{self.username}')"

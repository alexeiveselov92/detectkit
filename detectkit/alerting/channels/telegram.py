"""
Telegram alert channel implementation.

Sends anomaly alerts via Telegram Bot API.
"""

import html

import requests

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel

# Telegram rejects messages longer than 4096 UTF-16 code units. We keep a
# margin and cap the long, free-form values (params JSON, description) before
# they are wrapped in tags so a real-world alert never trips the limit.
_MAX_LEN = 4096
_PARAMS_CAP = 900
_DESC_CAP = 500


class TelegramChannel(BaseAlertChannel):
    """
    Telegram alert channel using Bot API.

    Sends formatted messages to a Telegram chat using a bot token. The default
    (no custom ``template``) message is a structured **HTML** layout — a colored
    status dot, a bold headline, the lead (how long the anomaly has been
    running) followed by the rule that fired, then the evidence
    (value / expected / quorum / severity / started → latest / detector /
    params) in ``<code>``, plus an optional "Open dashboard" link and @mentions.

    HTML is the default ``parse_mode`` because the legacy ``Markdown`` mode
    breaks on the detector params JSON (an unmatched ``_`` in e.g.
    ``window_size`` raises *"can't parse entities"*). All interpolated values
    are HTML-escaped. A custom ``template`` is sent as-is under the configured
    parse mode, so custom Telegram templates should be HTML-safe.

    Telegram has no message-level color bar, footer icon or avatar override
    (the avatar is the bot account picture set in @BotFather), so the status
    color is conveyed by the leading colored dot.

    Attributes:
        bot_token: Telegram bot token (from @BotFather)
        chat_id: Target chat ID (user, group, or channel)
        parse_mode: Message parse mode ("HTML" default, "Markdown", or None)
        disable_notification: Send silently without notification

    Example:
        >>> channel = TelegramChannel(
        ...     bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        ...     chat_id="-1001234567890"
        ... )
        >>> channel.send(alert_data)
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
        template: str | None = None,
        **kwargs,
    ):
        """
        Initialize Telegram channel.

        Args:
            bot_token: Telegram bot token from @BotFather
            chat_id: Target chat ID (can be user_id, @channel_name, or group ID)
            parse_mode: Message formatting ("HTML" default, "Markdown", or None)
            disable_notification: Send silently without notification sound
            template: Custom message template (optional)
            **kwargs: Additional parameters (ignored)

        Raises:
            ValueError: If bot_token or chat_id is missing
        """
        if not bot_token:
            raise ValueError("bot_token is required for TelegramChannel")
        if not chat_id:
            raise ValueError("chat_id is required for TelegramChannel")

        self.bot_token = bot_token
        self.chat_id = chat_id
        self.parse_mode = parse_mode
        self.disable_notification = disable_notification
        self.template = template

    def send(self, alert_data: AlertData, template: str | None = None) -> bool:
        """
        Send alert to Telegram.

        Args:
            alert_data: Alert information to send
            template: Per-call template override (falls back to the
                channel-level template). When no template is set, the rich
                default HTML message is built.

        Returns:
            True when the message was accepted by the Telegram API

        Raises:
            requests.RequestException: If request fails
        """
        active_template = template or self.template
        if active_template is not None:
            # Custom template — sent verbatim under the configured parse mode.
            message = self.format_message(alert_data, active_template)
        elif self.parse_mode == "HTML":
            message = self._build_html_message(alert_data)
        else:
            # Non-HTML parse mode without a custom template: fall back to the
            # plain default text (no HTML tags).
            message = self.format_message(alert_data)

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        payload: dict[str, object] = {
            "chat_id": self.chat_id,
            "text": message,
            "disable_notification": self.disable_notification,
            # Keep the dashboard/runbook URL from expanding into a preview card.
            "disable_web_page_preview": True,
        }

        if self.parse_mode:
            payload["parse_mode"] = self.parse_mode

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            raise requests.RequestException(f"Failed to send Telegram alert: {e}") from e

        return True

    # ------------------------------------------------------------------
    # HTML message construction
    # ------------------------------------------------------------------
    def _build_html_message(self, alert_data: AlertData) -> str:
        """Build the structured HTML message for *alert_data* (escaped)."""
        ctx = self.build_context(alert_data)
        kind = self.status_kind(alert_data)
        dot = self.status_emoji(alert_data)
        word = self.status_word(alert_data)

        def esc(value: object) -> str:
            return html.escape(str(value))

        metric = esc(ctx["metric_name"])
        # Lead the headline with the project name (when set) so multiple
        # projects sharing one chat stay distinguishable — Telegram has no
        # footer/avatar override, so this prefix is the only project cue.
        proj = ctx["project_name"]
        head_prefix = f"[{esc(proj)}] " if proj else ""
        lines: list[str] = [f"{dot} <b>{head_prefix}{word} · {metric}</b>"]

        if ctx["description"]:
            lines.append(f"<i>{esc(self._cap(ctx['description'], _DESC_CAP))}</i>")

        lines.append("")  # blank line

        if kind == "anomaly":
            # Description (how long it's been going on) leads; the Rule chip sits
            # right above the evidence it explains.
            lines.append(esc(ctx["anomaly_lead"]))
            lines.append(
                f"<b>Rule</b> <code>min_detectors={ctx['min_detectors']} · "
                f"direction={esc(ctx['direction_policy'])} · "
                f"consecutive={ctx['consecutive_required']}</code>"
            )
            lines.append("")
            lines.append(
                f"• Value: <code>{esc(ctx['value_display'])}</code> · "
                f"Expected: <code>{esc(ctx['expected_range'])}</code>"
            )
            lines.append(
                f"• Quorum: <code>{ctx['detector_count']}/{ctx['min_detectors']} · "
                f"{esc(ctx['direction'])}</code>"
            )
            lines.append(f"• Severity: <code>{alert_data.severity:.2f}</code>")
            if ctx["started_display"]:
                lines.append(
                    f"• Started: <code>{esc(ctx['started_display'])}</code> · "
                    f"Latest: <code>{esc(ctx['timestamp'])}</code>"
                )
            else:
                lines.append(f"• Time: <code>{esc(ctx['timestamp'])}</code>")
            lines.append(f"• Detector: <code>{esc(ctx['detector_name'])}</code>")
            if ctx["detector_params"]:
                params = self._cap(ctx["detector_params"], _PARAMS_CAP)
                lines.append(f"• Parameters: <code>{esc(params)}</code>")
        elif kind == "recovery":
            lines.append(esc(ctx["recovery_lead"]))
            lines.append(
                f"<b>Rule</b> <code>min_detectors={ctx['min_detectors']} · "
                f"direction={esc(ctx['direction_policy'])} · "
                f"consecutive={ctx['consecutive_required']}</code>"
            )
            lines.append("")
            lines.append(
                f"• Value: <code>{esc(ctx['value_display'])}</code> · "
                f"Expected: <code>{esc(ctx['expected_range'])}</code>"
            )
            if ctx["started_display"]:
                lines.append(
                    f"• Started: <code>{esc(ctx['started_display'])}</code> · "
                    f"Cleared: <code>{esc(ctx['timestamp'])}</code>"
                )
            else:
                lines.append(f"• Cleared: <code>{esc(ctx['timestamp'])}</code>")
            lines.append(f"• Detector: <code>{esc(ctx['detector_name'])}</code>")
        elif kind == "no_data":
            lines.append("Query returned no datapoint for the latest expected interval.")
            lines.append("")
            lines.append(f"• Expected at: <code>{esc(ctx['timestamp'])}</code>")
        else:  # error
            lines.append("The detectkit pipeline failed for this metric.")
            lines.append("")
            lines.append(f"• Time: <code>{esc(ctx['timestamp'])}</code>")
            err = f"{ctx['error_type']}: {ctx['error_message']}".strip(": ")
            if err:
                lines.append(f"• Error: <code>{esc(err)}</code>")

        # Links (dashboard first, then any extras). hrefs escaped with quotes.
        link_parts: list[str] = []
        if alert_data.dashboard_url:
            href = html.escape(alert_data.dashboard_url, quote=True)
            link_parts.append(f'<a href="{href}">Open dashboard</a>')
        for label, url in alert_data.links.items():
            href = html.escape(url, quote=True)
            link_parts.append(f'<a href="{href}">{esc(label)}</a>')
        # "How to read this alert" — always present (unless opted out), so a
        # stakeholder can click through to the interpretation guide.
        if ctx["help_url"]:
            href = html.escape(ctx["help_url"], quote=True)
            link_parts.append(f'<a href="{href}">{esc(ctx["help_label"])}</a>')
        if link_parts:
            lines.append("")
            lines.append(" · ".join(link_parts))

        # Mentions are already platform-formatted (plain @user or a tg:// link
        # for numeric IDs in HTML mode) — insert as-is, no escaping.
        if ctx["mentions"]:
            lines.append("")
            lines.append(ctx["mentions"])

        message = "\n".join(lines)
        if len(message) > _MAX_LEN:
            # Last-resort guard. Each line is independently tag-balanced, so
            # cutting on a line boundary never splits an HTML tag (a naive
            # character cut could leave an unclosed <code>/<a> and 400). Long
            # free-form values are already capped above, so this rarely fires.
            head = message[: _MAX_LEN - 2]
            nl = head.rfind("\n")
            message = (head[:nl] if nl > 0 else head) + "\n…"
        return message

    @staticmethod
    def _cap(value: str, limit: int) -> str:
        """Truncate *value* to *limit* chars with an ellipsis (pre-escape)."""
        if len(value) <= limit:
            return value
        return value[: limit - 1] + "…"

    def format_mentions(self, mentions: list[str]) -> str:
        """
        Format mentions for Telegram.

        Telegram supports @username natively. For numeric user IDs
        in HTML parse mode, uses tg://user deep link.

        Args:
            mentions: List of usernames or user IDs

        Returns:
            Formatted mentions string
        """
        if not mentions:
            return ""
        parts = []
        for m in mentions:
            if m in ("channel", "all", "here"):
                # Telegram has no broadcast mention; include as plain text
                parts.append(f"@{m}")
            elif m.isdigit() and self.parse_mode == "HTML":
                parts.append(f'<a href="tg://user?id={m}">{m}</a>')
            else:
                parts.append(f"@{m}")
        return " ".join(parts)

    def __repr__(self) -> str:
        """String representation."""
        return f"TelegramChannel(chat_id={self.chat_id})"

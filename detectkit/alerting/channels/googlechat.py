"""
Google Chat alert channel implementation.

Sends alerts to a Google Chat space via a space **incoming webhook**, rendered
as a Cards v2 card (Cards v1 is deprecated by Google and not supported here).
"""

import html
from typing import Any

import requests

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.channels.branding import BRAND_ICON_URL, BRAND_USERNAME

# Cards v2 ``textParagraph``/``decoratedText`` widgets render a limited HTML
# subset (``<b>``, ``<i>``, ``<u>``, ``<font color>``, ``<a href>``, ``<code>``,
# ``<br>``) and do NOT honor a raw ``"\n"`` for line breaks — an explicit
# ``<br>`` tag is required (per the Cards v2 formatting reference). Every
# interpolated value is HTML-escaped first — mirroring telegram.py's
# discipline — before being wrapped in these tags.
_PARAMS_CAP = 900

# Google Chat's broadcast mention token. Chat has no separate "channel"/
# "here" concept (unlike Slack/Mattermost) — every broadcast keyword maps to
# the same space-wide mention.
_ALL_MENTION = "<users/all>"
_ALL_KEYWORDS = frozenset({"all", "everyone", "channel", "here"})


class GoogleChatChannel(BaseAlertChannel):
    """
    Google Chat alert channel using a space incoming webhook (Cards v2).

    The default (no custom ``template``) message renders as a single Cards v2
    card: a header (title = the status-dot headline, since **cards v2 has no
    color bar** — the emoji dot is the only color cue; subtitle = the brand
    name, paired with the project name when set; the brand avatar as a circle
    image), then up to three sections — the lead sentence + the **Rule** chip,
    the evidence rows (value / expected / quorum / severity / the anomalous
    span / detectors, trimmed down for no-data/error), and finally a row of
    action buttons (dashboard / extra links / the help link). A custom
    ``template`` keeps the same header but renders as a single opaque
    ``textParagraph`` carrying the formatted template text.

    Mentions ride in the **top-level** ``text`` field — Google Chat fires a
    user @-ping only from ``<users/…>`` tokens in a message's top-level text,
    never from card content — so it is added only when
    ``alert_data.mentions`` is non-empty.

    The payload shape::

        {
            "text": "<users/all> ...",           # only when mentions are set
            "cardsV2": [
                {
                    "cardId": "detectkit-alert",
                    "card": {
                        "header": {
                            "title": "...",
                            "subtitle": "detectkit · <project>",
                            "imageUrl": "https://.../bot-icon.png",
                            "imageType": "CIRCLE",
                        },
                        "sections": [
                            {"widgets": [{"textParagraph": {...}}]},
                            {"widgets": [{"decoratedText": {...}}, ...]},
                            {"widgets": [{"buttonList": {"buttons": [...]}}]},
                        ],
                    },
                }
            ],
        }

    Parameters:
        webhook_url (str): The space's full incoming-webhook URL (already
            carrying the ``key``/``token`` query params Google Chat issues
            when the webhook is registered).
        icon_url (str): Header avatar image URL (default: the detectkit
            brand avatar).
        timeout (int): Request timeout in seconds (default: 10).

    Example:
        >>> channel = GoogleChatChannel(
        ...     webhook_url="https://chat.googleapis.com/v1/spaces/AAA/messages?key=K&token=T"
        ... )
        >>> channel.send(alert_data)
    """

    def __init__(
        self,
        webhook_url: str,
        icon_url: str | None = None,
        timeout: int = 10,
    ) -> None:
        """
        Initialize Google Chat channel.

        Args:
            webhook_url: Full space incoming-webhook URL.
            icon_url: Header avatar image URL (default: the detectkit brand
                avatar).
            timeout: Request timeout in seconds.

        Raises:
            ValueError: If webhook_url is missing.
        """
        if not webhook_url:
            raise ValueError("webhook_url is required for GoogleChatChannel")

        self.webhook_url = webhook_url
        self.icon_url = icon_url if icon_url is not None else BRAND_ICON_URL
        self.timeout = timeout

    def send(self, alert_data: AlertData, template: str | None = None) -> bool:
        """
        Send alert to the Google Chat space webhook.

        Args:
            alert_data: Alert data to send.
            template: Optional custom message template. When set, the card
                carries the formatted template text as a single
                ``textParagraph`` (header/branding unchanged); otherwise the
                rich default card is built.

        Returns:
            True if sent successfully, False otherwise.

        Example:
            >>> channel = GoogleChatChannel(webhook_url="https://chat.googleapis.com/...")
            >>> success = channel.send(alert_data)
        """
        payload = self.build_payload(alert_data, template)

        try:
            response = requests.post(self.webhook_url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            # Log error but don't crash
            print(f"Failed to send Google Chat alert: {e}")
            return False

    # ------------------------------------------------------------------
    # Payload construction
    # ------------------------------------------------------------------
    def build_payload(self, alert_data: AlertData, template: str | None = None) -> dict[str, Any]:
        """Build the full Google Chat webhook JSON payload.

        Split out from :meth:`send` so it can be unit-tested without a
        network call.
        """
        card = self.build_card(alert_data, template)
        payload: dict[str, Any] = {
            "cardsV2": [{"cardId": "detectkit-alert", "card": card}],
        }

        # User @-pings only fire from <users/…> tokens in the top-level text,
        # never from card content — so it's added only when there's someone
        # to ping.
        mentions = self.format_mentions(alert_data.mentions)
        if mentions:
            payload["text"] = mentions

        return payload

    def build_card(self, alert_data: AlertData, template: str | None = None) -> dict[str, Any]:
        """Build the Cards v2 ``card`` object (header + sections)."""
        card: dict[str, Any] = {"header": self._build_header(alert_data)}

        if template is not None:
            sections = self._build_template_sections(alert_data, template)
        else:
            sections = self._build_default_sections(alert_data)

        if sections:
            card["sections"] = sections
        return card

    def _build_header(self, alert_data: AlertData) -> dict[str, Any]:
        """Card header: title (the status dot is the only color cue — cards
        v2 has no color bar), subtitle (brand name, paired with the project
        name when set) and the brand avatar as a circle image."""
        subtitle = BRAND_USERNAME
        if alert_data.project_name:
            subtitle = f"{BRAND_USERNAME} · {alert_data.project_name}"

        header: dict[str, Any] = {
            "title": self.format_title(alert_data),
            "subtitle": subtitle,
        }
        if self.icon_url:
            header["imageUrl"] = self.icon_url
            header["imageType"] = "CIRCLE"
        return header

    def _build_template_sections(
        self, alert_data: AlertData, template: str
    ) -> list[dict[str, Any]]:
        """Custom template → one opaque ``textParagraph`` (can't be sliced
        into evidence widgets), with the header/branding unchanged."""
        text = self._to_card_text(self.format_message(alert_data, template))
        return [{"widgets": [{"textParagraph": {"text": text}}]}]

    def _build_default_sections(self, alert_data: AlertData) -> list[dict[str, Any]]:
        """The default rendering: lead + Rule, then evidence rows, then
        action buttons — each an independent section, omitted when empty."""
        ctx = self.build_context(alert_data)
        kind = self.status_kind(alert_data)

        lead_text = self._to_card_text(self._lead(ctx, kind))
        # The Rule chip joins the lead only for anomaly/recovery — no-data and
        # error alerts don't fire on the quorum rule, so naming it there would
        # mislead (same convention as every other channel).
        if kind in ("anomaly", "recovery"):
            rule_line = f"{self._bold('Rule')} {html.escape(str(ctx['rule_display']))}"
            lead_text = f"{lead_text}<br>{rule_line}"
        sections: list[dict[str, Any]] = [{"widgets": [{"textParagraph": {"text": lead_text}}]}]

        evidence = self._evidence_widgets(alert_data, ctx, kind)
        if evidence:
            sections.append({"widgets": evidence})

        buttons = self._button_widgets(alert_data, ctx)
        if buttons:
            sections.append({"widgets": [{"buttonList": {"buttons": buttons}}]})

        return sections

    @staticmethod
    def _lead(ctx: dict[str, Any], kind: str) -> str:
        """The plain-language lead sentence — reuses the same ready-made
        anomaly/recovery sentence every other channel leads with; no-data and
        error get a fixed one-liner (they have no streak/duration story)."""
        if kind == "anomaly":
            return str(ctx["anomaly_lead"])
        if kind == "recovery":
            return str(ctx["recovery_lead"])
        if kind == "no_data":
            return "Query returned no datapoint for the latest expected interval."
        return "The detectkit pipeline failed for this metric."

    def _evidence_widgets(
        self, alert_data: AlertData, ctx: dict[str, Any], kind: str
    ) -> list[dict[str, Any]]:
        """Evidence rows as ``decoratedText`` widgets, kind-dependent. No-data
        and error stay short (no quorum/severity/params)."""
        rows: list[tuple[str, str]] = []
        if kind == "anomaly":
            rows.append(("Value", str(ctx["value_display"])))
            rows.append(("Expected", str(ctx["expected_range"])))
            rows.append(
                (
                    "Quorum",
                    f"{ctx['detector_count']}/{ctx['min_detectors']} · {ctx['direction']}",
                )
            )
            rows.append(("Severity", f"{alert_data.severity:.2f}"))
            if ctx["started_display"]:
                rows.append(("Anomaly began", str(ctx["started_display"])))
                rows.append(("Latest reading", str(ctx["timestamp"])))
            else:
                rows.append(("Detected at", str(ctx["timestamp"])))
            rows.append(("Detectors", str(ctx["detector_name"])))
        elif kind == "recovery":
            rows.append(("Value", str(ctx["value_display"])))
            rows.append(("Expected", str(ctx["expected_range"])))
            if ctx["started_display"]:
                rows.append(("Anomaly began", str(ctx["started_display"])))
                if ctx["fired_display"]:
                    rows.append(("Alert fired", str(ctx["fired_display"])))
                rows.append(("Recovered", str(ctx["timestamp"])))
            else:
                rows.append(("Cleared at", str(ctx["timestamp"])))
            rows.append(("Detectors", str(ctx["detector_name"])))
        elif kind == "no_data":
            rows.append(("Expected at", str(ctx["timestamp"])))
            rows.append(("Expected", str(ctx["expected_range"])))
        else:  # error
            rows.append(("Detected at", str(ctx["timestamp"])))
            err = f"{ctx['error_type']}: {ctx['error_message']}".strip(": ")
            if err:
                rows.append(("Error", err))

        widgets: list[dict[str, Any]] = [
            {
                "decoratedText": {
                    "topLabel": html.escape(label),
                    "text": html.escape(value),
                }
            }
            for label, value in rows
            if value
        ]

        # Params (anomaly only, when present) — its own textParagraph, capped
        # so a large detector_params JSON blob never blows past the card's
        # practical size.
        if kind == "anomaly" and ctx["detector_params"]:
            params = self._cap(str(ctx["detector_params"]), _PARAMS_CAP)
            widgets.append(
                {"textParagraph": {"text": f"{self._bold('Parameters')}<br>{html.escape(params)}"}}
            )

        return widgets

    def _button_widgets(self, alert_data: AlertData, ctx: dict[str, Any]) -> list[dict[str, Any]]:
        """Action buttons: Dashboard, each extra link, then the help link —
        the same action set every other channel surfaces, as clickable
        buttons instead of inline links (Cards v2 has no free-text markdown
        link syntax outside the allowed HTML tag subset)."""
        buttons: list[dict[str, Any]] = []
        if alert_data.dashboard_url:
            buttons.append(self._button("Dashboard", alert_data.dashboard_url))
        for label, url in alert_data.links.items():
            buttons.append(self._button(label, url))
        if ctx["help_url"]:
            buttons.append(self._button(str(ctx["help_label"]), str(ctx["help_url"])))
        return buttons

    @staticmethod
    def _button(label: str, url: str) -> dict[str, Any]:
        """One ``buttonList`` entry opening *url* in the browser.

        Button ``text`` is plain text (the HTML formatting subset applies to
        text widgets only), so the label is deliberately NOT escaped — an
        escaped ``&amp;`` would display literally.
        """
        return {"text": label, "onClick": {"openLink": {"url": url}}}

    @staticmethod
    def _bold(text: str) -> str:
        """Cards v2 bold markup (part of the allowed HTML tag subset)."""
        return f"<b>{text}</b>"

    @staticmethod
    def _to_card_text(value: str) -> str:
        """Escape *value* then convert newlines to ``<br>``.

        Cards v2 ``textParagraph``/``decoratedText`` widgets do not honor a
        raw ``"\\n"`` for line breaks — an explicit ``<br>`` tag is required.
        """
        return html.escape(value).replace("\n", "<br>")

    @staticmethod
    def _cap(value: str, limit: int) -> str:
        """Truncate *value* to *limit* chars with an ellipsis (pre-escape)."""
        if len(value) <= limit:
            return value
        return value[: limit - 1] + "…"

    def format_mentions(self, mentions: list[str]) -> str:
        """
        Format mentions for Google Chat.

        Google Chat only pings users from ``<users/USER_ID>`` (or the
        space-wide ``<users/all>``) tokens in the message's top-level text —
        a bare ``@name`` renders as plain text and does **not** notify
        anyone. So: any of ``"all"``/``"everyone"``/``"channel"``/``"here"``
        (case-insensitive) collapses to a single, deduped ``<users/all>``; a
        value already shaped like ``<users/…>`` passes through verbatim
        (also deduped); anything else falls back to a plain ``@name`` — it
        won't ping, but at least names the intended recipient in the
        notification text.

        Args:
            mentions: List of usernames, ``<users/USER_ID>`` tokens, or the
                broadcast keywords above.

        Returns:
            Space-joined, order-preserving, deduped mention tokens.
        """
        if not mentions:
            return ""
        tokens: list[str] = []
        for m in mentions:
            if m.lower() in _ALL_KEYWORDS:
                token = _ALL_MENTION
            elif m.startswith("<users/") and m.endswith(">"):
                token = m
            else:
                token = f"@{m}"
            if token not in tokens:
                tokens.append(token)
        return " ".join(tokens)

    def __repr__(self) -> str:
        """String representation."""
        url_preview = (
            self.webhook_url[:30] + "..." if len(self.webhook_url) > 30 else self.webhook_url
        )
        return f"GoogleChatChannel(url='{url_preview}')"

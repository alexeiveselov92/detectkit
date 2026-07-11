"""
Microsoft Teams alert channel implementation.

Sends alerts to Microsoft Teams via the **Power Automate "Workflows"** webhook
trigger ("When a Teams webhook request is received"), posting an Adaptive
Card. This is deliberately *not* the legacy Office 365 ("O365 Connector")
incoming webhook: that path accepted a ``MessageCard`` payload and is being
retired as part of Microsoft's 2025-2026 shutdown of Microsoft 365 connectors
in Teams. Against a Workflows webhook URL, only the
``{"type": "message", "attachments": [<adaptive card>]}`` shape below is
accepted.
"""

from typing import Any

import requests

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel

# Detector params can be arbitrarily large JSON; cap it before it dominates
# the card (mirrors the same cap used by the Telegram channel).
_PARAMS_CAP = 900


class TeamsChannel(BaseAlertChannel):
    """
    Microsoft Teams alert channel via the Power Automate "Workflows" webhook.

    Targets the current **Workflows** app webhook path (Teams channel ->
    "Workflows" -> a webhook-triggered flow that posts to the channel), not
    the retired Office 365 connector. Three things follow from that:

    - The message posts under the **flow's identity** (the Workflow /
      Power Automate app that owns the webhook) — there is no per-message
      username or avatar override on this path, unlike the Slack/Mattermost
      style webhook channel.
    - ``@mentions`` render as **plain text** and cannot actually notify
      anyone: a real Adaptive Card mention entity requires an Azure AD user
      object id, which detectkit's alert configuration does not carry.
      Configure a real ping inside the Workflow itself if you need one.
    - The default rendering has **no brand avatar/footer icon** (the
      Workflows path renders under the flow's own icon); the footer still
      names ``detectkit`` (and the project, when set) as plain text so two
      projects sharing one channel stay distinguishable.

    Rendering reuses :meth:`build_context` (the same source every other
    channel renders from) and follows the shared kind ordering: title -> lead
    -> **Rule** chip -> a ``FactSet`` mirroring the webhook channel's tail for
    the alert kind -> detector params (anomaly only) -> mentions (when set)
    -> footer, plus ``Action.OpenUrl`` buttons for the dashboard / extra
    links / "how to read this alert" help link. ``no_data`` and ``error``
    stay short (no quorum/severity/params facts), matching every other
    channel.

    A custom ``template`` renders as a minimal card: a colored title block, a
    single text block holding :meth:`format_message`'s output, and the
    branded footer — action buttons are still attached.

    Attributes:
        webhook_url: The Workflows-generated webhook URL to POST to.
        timeout: Request timeout in seconds (default: 10).

    Example:
        >>> channel = TeamsChannel(
        ...     webhook_url="https://prod-00.westus.logic.azure.com:443/workflows/xxx"
        ... )
        >>> channel.send(alert_data)
    """

    # Adaptive Card TextBlock ``color`` per alert kind — the card frame itself
    # has no status color bar, so the title text carries the accent instead.
    _STATUS_CARD_COLORS = {
        "anomaly": "Attention",
        "recovery": "Good",
        "no_data": "Warning",
        "error": "Accent",
    }

    def __init__(self, webhook_url: str, timeout: int = 10) -> None:
        """
        Initialize the Teams channel.

        Args:
            webhook_url: Workflows-generated webhook URL to POST the
                Adaptive Card payload to.
            timeout: Request timeout in seconds.

        Raises:
            ValueError: If webhook_url is missing.
        """
        if not webhook_url:
            raise ValueError("webhook_url is required for TeamsChannel")

        self.webhook_url = webhook_url
        self.timeout = timeout

    def send(self, alert_data: AlertData, template: str | None = None) -> bool:
        """
        Send alert to Microsoft Teams.

        Args:
            alert_data: Alert data to send.
            template: Optional custom message template. When set, the body
                renders as a minimal card (colored title + the rendered
                template text + footer) instead of the structured default.

        Returns:
            True if the webhook accepted the request, False otherwise.
        """
        card = self.build_card(alert_data, template)
        payload: dict[str, Any] = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": card,
                }
            ],
        }

        try:
            response = requests.post(self.webhook_url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            # Log error but don't crash the pipeline.
            print(f"Failed to send Teams alert: {e}")
            return False

    # ------------------------------------------------------------------
    # Card construction
    # ------------------------------------------------------------------
    def build_card(self, alert_data: AlertData, template: str | None = None) -> dict[str, Any]:
        """Build the Adaptive Card ``content`` object for *alert_data*.

        Split out from :meth:`send` so it can be unit-tested without a
        network call.
        """
        title = self.format_title(alert_data)
        color = self._STATUS_CARD_COLORS[self.status_kind(alert_data)]
        ctx = self.build_context(alert_data)
        actions = self._actions(alert_data, ctx)

        if template is not None:
            # Custom template — an opaque text block, but keep the colored
            # title and the branded footer/actions.
            body: list[dict[str, Any]] = [
                self._text_block(title, weight="Bolder", size="Medium", color=color, wrap=True),
                self._text_block(self.format_message(alert_data, template), wrap=True),
                self._footer_block(alert_data),
            ]
        else:
            body = self._default_body(alert_data, ctx, title, color)

        card: dict[str, Any] = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "msteams": {"width": "Full"},
            "body": body,
        }
        if actions:
            card["actions"] = actions
        return card

    def _default_body(
        self,
        alert_data: AlertData,
        ctx: dict[str, Any],
        title: str,
        color: str,
    ) -> list[dict[str, Any]]:
        """The structured default body: title -> lead -> Rule -> facts ->
        params (anomaly only) -> mentions (when set) -> footer."""
        kind = self.status_kind(alert_data)

        body: list[dict[str, Any]] = [
            self._text_block(title, weight="Bolder", size="Medium", color=color, wrap=True),
            self._text_block(self._lead(ctx, kind), wrap=True),
        ]
        # The Rule chip joins the lead only for anomaly/recovery — no-data and
        # error alerts don't fire on the quorum rule, so naming it there would
        # mislead (same convention as every other channel).
        if kind in ("anomaly", "recovery"):
            body.append(
                self._text_block(
                    f"Rule: {ctx['rule_display']}",
                    font_type="Monospace",
                    wrap=True,
                    spacing="Small",
                )
            )
        body.append(self._fact_set(alert_data, ctx, kind))

        if kind == "anomaly" and ctx["detector_params"]:
            params = self._cap(ctx["detector_params"], _PARAMS_CAP)
            body.append(self._text_block(params, font_type="Monospace", is_subtle=True, wrap=True))

        if ctx["mentions"]:
            body.append(self._text_block(ctx["mentions"], is_subtle=True))

        body.append(self._footer_block(alert_data))
        return body

    @staticmethod
    def _lead(ctx: dict[str, Any], kind: str) -> str:
        """The plain-language lead sentence for *kind* (mirrors the webhook
        channel's ``_display_lead``: anomaly/recovery reuse the ready-made
        sentence from :meth:`build_context`; no_data/error get a fixed
        one-liner since they carry no streak/duration story)."""
        if kind == "anomaly":
            return str(ctx["anomaly_lead"])
        if kind == "recovery":
            return str(ctx["recovery_lead"])
        if kind == "no_data":
            return "Query returned no datapoint for the latest expected interval."
        return "The detectkit pipeline failed for this metric."

    @staticmethod
    def _fact_set(alert_data: AlertData, ctx: dict[str, Any], kind: str) -> dict[str, Any]:
        """A ``FactSet`` mirroring the webhook channel's verbose tail for
        *kind*. Empty values are dropped (e.g. "Alert fired" when the run's
        onset/timing isn't known)."""
        facts: list[dict[str, str]] = []

        def add(fact_title: str, value: str) -> None:
            if value:
                facts.append({"title": fact_title, "value": value})

        if kind == "anomaly":
            add("Value", ctx["value_display"])
            add("Expected", ctx["expected_range"])
            add("Quorum", f"{ctx['detector_count']}/{ctx['min_detectors']} · {ctx['direction']}")
            add("Severity", f"{alert_data.severity:.2f}")
            if ctx["started_display"]:
                add("Anomaly began", ctx["started_display"])
                add("Latest reading", ctx["timestamp"])
            else:
                add("Detected at", ctx["timestamp"])
            add("Detectors", ctx["detector_name"])
        elif kind == "recovery":
            add("Value", ctx["value_display"])
            add("Expected", ctx["expected_range"])
            if ctx["started_display"]:
                add("Anomaly began", ctx["started_display"])
                add("Alert fired", ctx["fired_display"])
                add("Recovered", ctx["timestamp"])
            else:
                add("Cleared at", ctx["timestamp"])
            add("Detectors", ctx["detector_name"])
        elif kind == "no_data":
            add("Expected at", ctx["timestamp"])
            add("Expected", ctx["expected_range"])
        else:  # error
            add("Detected at", ctx["timestamp"])
            err = f"{ctx['error_type']}: {ctx['error_message']}".strip(": ")
            add("Error", err)

        return {"type": "FactSet", "facts": facts}

    def _footer_block(self, alert_data: AlertData) -> dict[str, Any]:
        """ "detectkit" (or "detectkit · <project>") — the only branding
        available on this path, since the message posts under the flow's own
        identity/icon."""
        footer = "detectkit"
        if alert_data.project_name:
            footer = f"detectkit · {alert_data.project_name}"
        return self._text_block(footer, is_subtle=True, size="Small", spacing="Medium")

    @staticmethod
    def _actions(alert_data: AlertData, ctx: dict[str, Any]) -> list[dict[str, Any]]:
        """``Action.OpenUrl`` buttons: Dashboard, each extra link, then help."""
        actions: list[dict[str, Any]] = []
        if alert_data.dashboard_url:
            actions.append(
                {"type": "Action.OpenUrl", "title": "Dashboard", "url": alert_data.dashboard_url}
            )
        for label, url in alert_data.links.items():
            actions.append({"type": "Action.OpenUrl", "title": label, "url": url})
        if ctx["help_url"]:
            actions.append(
                {"type": "Action.OpenUrl", "title": ctx["help_label"], "url": ctx["help_url"]}
            )
        return actions

    @staticmethod
    def _text_block(
        text: str,
        *,
        weight: str | None = None,
        size: str | None = None,
        color: str | None = None,
        wrap: bool = False,
        spacing: str | None = None,
        is_subtle: bool = False,
        font_type: str | None = None,
    ) -> dict[str, Any]:
        """An Adaptive Card ``TextBlock``, omitting unset optional properties."""
        block: dict[str, Any] = {"type": "TextBlock", "text": text}
        if weight:
            block["weight"] = weight
        if size:
            block["size"] = size
        if color:
            block["color"] = color
        if wrap:
            block["wrap"] = True
        if spacing:
            block["spacing"] = spacing
        if is_subtle:
            block["isSubtle"] = True
        if font_type:
            block["fontType"] = font_type
        return block

    @staticmethod
    def _cap(value: str, limit: int) -> str:
        """Truncate *value* to *limit* chars with an ellipsis."""
        if len(value) <= limit:
            return value
        return value[: limit - 1] + "…"

    def __repr__(self) -> str:
        """String representation of channel."""
        url_preview = (
            self.webhook_url[:30] + "..." if len(self.webhook_url) > 30 else self.webhook_url
        )
        return f"TeamsChannel(url='{url_preview}')"

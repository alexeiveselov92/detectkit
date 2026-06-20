"""
Email alert channel implementation.

Sends anomaly alerts via SMTP email.
"""

import html
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.channels.branding import BRAND_ICON_URL, BRAND_USERNAME

# Brand palette as hex literals. Email clients (Outlook/Word engine) ignore CSS
# custom properties, so the values from website/src/styles/brand.css are copied
# verbatim here and kept in sync with the alert status tokens.
_CLAY = "#d15b36"
_INK = "#1b1916"
_PAPER = "#f5f1e8"
_SURFACE = "#fbf9f3"
_BORDER = "#e6e0d4"
_FAINT = "#9a9384"
_MUTED = "#6e675b"
_TERM_BG = "#211e1a"
_TERM_BORDER = "#332f29"
_TERM_TEXT = "#c9c2b4"

_SANS = "'Schibsted Grotesk',Segoe UI,Arial,sans-serif"
_MONO = "Consolas,'JetBrains Mono',Menlo,monospace"


class EmailChannel(BaseAlertChannel):
    """
    Email alert channel using SMTP.

    Sends a multipart email: a plain-text body (the formatted default/custom
    template) plus a branded **HTML card** — a colored top accent + status
    pill, the metric, a 2-column value/expected/severity table, a monospace
    params box, an optional "Open dashboard" button and a footer. The HTML is
    inline-CSS and table-based so it survives Gmail/Outlook/Apple Mail; the
    plain-text part is the fallback.

    Attributes:
        smtp_host: SMTP server hostname
        smtp_port: SMTP server port
        smtp_username: SMTP authentication username
        smtp_password: SMTP authentication password
        from_email: Sender email address
        to_emails: List of recipient email addresses
        use_tls: Whether to use TLS encryption
        subject_template: Email subject template

    Example:
        >>> channel = EmailChannel(
        ...     smtp_host="smtp.gmail.com",
        ...     smtp_port=587,
        ...     smtp_username="alerts@example.com",
        ...     smtp_password="password",
        ...     from_email="alerts@example.com",
        ...     to_emails=["team@example.com"]
        ... )
        >>> channel.send(alert)
    """

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        from_email: str,
        to_emails: list[str],
        smtp_username: str | None = None,
        smtp_password: str | None = None,
        use_tls: bool = True,
        subject_template: str = "🔴 Alert: {metric_name}",
        from_name: str = BRAND_USERNAME,
        template: str | None = None,
        **kwargs,
    ):
        """
        Initialize email channel.

        Args:
            smtp_host: SMTP server hostname
            smtp_port: SMTP server port (typically 587 for TLS, 465 for SSL)
            from_email: Sender email address
            to_emails: List of recipient email addresses
            smtp_username: SMTP authentication username (optional)
            smtp_password: SMTP authentication password (optional)
            use_tls: Whether to use STARTTLS (default: True)
            subject_template: Email subject template with {metric_name} placeholder
            from_name: Sender display name shown in the ``From`` header — the
                email equivalent of the bot name (default: "detectkit"). The
                brand logo is also rendered in the HTML body.
            template: Custom message template (optional)
            **kwargs: Additional parameters (ignored)

        Raises:
            ValueError: If required parameters are missing
        """
        if not smtp_host:
            raise ValueError("smtp_host is required for EmailChannel")
        if not smtp_port:
            raise ValueError("smtp_port is required for EmailChannel")
        if not from_email:
            raise ValueError("from_email is required for EmailChannel")
        if not to_emails:
            raise ValueError("to_emails is required for EmailChannel")

        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.from_email = from_email
        self.to_emails = to_emails
        self.use_tls = use_tls
        self.subject_template = subject_template
        self.from_name = from_name
        self.template = template

    def send(self, alert_data: AlertData, template: str | None = None) -> bool:
        """
        Send alert via email.

        Args:
            alert_data: Alert information to send
            template: Per-call template override (falls back to the
                channel-level template, then the built-in default)

        Returns:
            True when the email was handed to the SMTP server

        Raises:
            smtplib.SMTPException: If email sending fails
        """
        active_template = template or self.template
        message_body = self.format_message(alert_data, active_template)

        # Create email message
        msg = MIMEMultipart("alternative")
        # Branded From: "detectkit <alerts@example.com>" — the email equivalent
        # of a bot display name. formataddr quotes the name when required.
        msg["From"] = formataddr((self.from_name, self.from_email))
        msg["To"] = ", ".join(self.to_emails)
        # Strip CR/LF from the metric name before it reaches the Subject header
        # so a metric name can never inject extra email headers.
        subject_metric = alert_data.metric_name.replace("\r", " ").replace("\n", " ")
        msg["Subject"] = self.subject_template.format(metric_name=subject_metric)

        # Attach both parts. In multipart/alternative the LAST part is the
        # preferred one, so HTML (the branded card) is shown when supported and
        # the plain-text body remains the fallback. A custom template renders as
        # the card body verbatim; the default renders the structured stat card.
        msg.attach(MIMEText(message_body, "plain"))
        msg.attach(
            MIMEText(
                self._build_html_body(
                    alert_data, message_body, is_custom=active_template is not None
                ),
                "html",
            )
        )

        try:
            # Connect to SMTP server
            if self.use_tls:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=10)

            # Login if credentials provided
            if self.smtp_username and self.smtp_password:
                server.login(self.smtp_username, self.smtp_password)

            # Send email
            server.sendmail(self.from_email, self.to_emails, msg.as_string())
            server.quit()

        except smtplib.SMTPException as e:
            raise smtplib.SMTPException(f"Failed to send email alert: {e}") from e

        return True

    # ------------------------------------------------------------------
    # HTML card construction
    # ------------------------------------------------------------------
    def _build_html_body(
        self,
        alert_data: AlertData,
        message_body: str,
        is_custom: bool = False,
    ) -> str:
        """Render the branded HTML card for *alert_data*.

        Table-based, inline-CSS only (Outlook/Word-engine safe). With a custom
        template the card body is the escaped ``message_body``; otherwise it is
        the structured stat layout. All interpolated values are HTML-escaped.

        Args:
            alert_data: The alert.
            message_body: The formatted plain-text body (used as the card body
                when a custom template is active).
            is_custom: Whether a custom template produced ``message_body``.

        Returns:
            An HTML document string.
        """
        ctx = self.build_context(alert_data)
        accent = self.status_color(alert_data)
        pill = self.status_word(alert_data).upper()

        if is_custom:
            inner = (
                f'<tr><td style="padding:8px 24px 20px 24px;">'
                f'<pre style="white-space:pre-wrap;margin:0;font-family:{_MONO};'
                f'font-size:13px;line-height:1.5;color:{_INK};">'
                f"{html.escape(message_body)}</pre></td></tr>"
            )
        else:
            inner = self._inner_html(alert_data, ctx)

        footer = self._footer_html(alert_data)

        return (
            "<!DOCTYPE html>"
            '<html lang="en" xmlns:v="urn:schemas-microsoft-com:vml"><head>'
            '<meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
            "<!--[if mso]><xml><o:OfficeDocumentSettings>"
            "<o:PixelsPerInch>96</o:PixelsPerInch>"
            "</o:OfficeDocumentSettings></xml><![endif]-->"
            "</head>"
            f'<body style="margin:0;padding:0;background-color:{_PAPER};" bgcolor="{_PAPER}">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0" bgcolor="{_PAPER}" style="background-color:{_PAPER};'
            'mso-table-lspace:0pt;mso-table-rspace:0pt;">'
            '<tr><td align="center" style="padding:24px 12px;">'
            '<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
            f'border="0" bgcolor="{_SURFACE}" style="width:600px;max-width:600px;'
            f"background-color:{_SURFACE};border:1px solid {_BORDER};border-radius:10px;"
            'mso-table-lspace:0pt;mso-table-rspace:0pt;">'
            # top accent bar
            f'<tr><td height="4" bgcolor="{accent}" style="height:4px;line-height:4px;'
            f'font-size:4px;background-color:{accent};">&nbsp;</td></tr>'
            # header: logo + wordmark + status pill
            f"{self._header_html(accent, pill)}"
            # title
            f'<tr><td style="padding:6px 24px 2px 24px;font-family:{_SANS};font-size:22px;'
            f'font-weight:bold;color:{_INK};mso-line-height-rule:exactly;line-height:28px;">'
            f"{html.escape(ctx['metric_name'])}</td></tr>"
            # body
            f"{inner}"
            # footer
            f"{footer}"
            "</table></td></tr></table></body></html>"
        )

    def _header_html(self, accent: str, pill: str) -> str:
        """Logo + wordmark (real text) + colored status pill row."""
        return (
            f'<tr><td style="padding:18px 24px 8px 24px;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'border="0" style="mso-table-lspace:0pt;mso-table-rspace:0pt;"><tr>'
            f'<td width="32" valign="middle" bgcolor="{_SURFACE}" '
            f'style="background-color:{_SURFACE};">'
            f'<img src="{BRAND_ICON_URL}" width="28" height="28" alt="{html.escape(BRAND_USERNAME)}" '
            'style="display:block;border:0;outline:none;text-decoration:none;border-radius:6px;"></td>'
            f'<td valign="middle" style="padding-left:10px;font-family:{_SANS};font-size:16px;'
            f'font-weight:bold;color:{_CLAY};mso-line-height-rule:exactly;line-height:20px;">'
            f"{html.escape(BRAND_USERNAME)}</td>"
            '<td align="right" valign="middle">'
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            'style="mso-table-lspace:0pt;mso-table-rspace:0pt;"><tr>'
            f'<td bgcolor="{accent}" style="background-color:{accent};border-radius:12px;'
            f"padding:4px 12px;font-family:{_SANS};font-size:12px;font-weight:bold;color:#ffffff;"
            'mso-line-height-rule:exactly;line-height:14px;white-space:nowrap;">'
            f"{html.escape(pill)}</td></tr></table></td></tr></table></td></tr>"
        )

    def _inner_html(self, alert_data: AlertData, ctx: dict[str, Any]) -> str:
        """The kind-specific body: lead sentence, stat grid, params, button."""
        kind = self.status_kind(alert_data)
        parts: list[str] = []

        # Optional metric description, shown as a muted lead under the title.
        if ctx["description"]:
            parts.append(self._lead_html(ctx["description"]))

        if kind == "anomaly":
            lead = (
                f"Fired because the latest {ctx['consecutive_count']}/"
                f"{ctx['consecutive_required']} consecutive points each met the quorum "
                f"(min_detectors={ctx['min_detectors']}, direction "
                f"{html.escape(str(ctx['direction_policy']))})."
            )
            parts.append(self._lead_html(lead))
            parts.append(
                self._stat_grid(
                    [
                        ("Value", ctx["value_display"]),
                        ("Expected", ctx["expected_range"]),
                        ("Severity", f"{alert_data.severity:.2f}"),
                        ("Detected at", ctx["timestamp"]),
                    ]
                )
            )
            if ctx["detector_params"]:
                parts.append(self._params_html(ctx["detector_name"], ctx["detector_params"]))
        elif kind == "recovery":
            lead = (
                "The alert condition no longer holds — the metric is back within "
                "expected bounds."
            )
            parts.append(self._lead_html(lead))
            parts.append(
                self._stat_grid(
                    [
                        ("Value", ctx["value_display"]),
                        ("Expected", ctx["expected_range"]),
                        ("Detector", ctx["detector_name"]),
                        ("Cleared at", ctx["timestamp"]),
                    ]
                )
            )
        elif kind == "no_data":
            lead = "Query returned no datapoint for the latest expected interval."
            parts.append(self._lead_html(lead))
            parts.append(
                self._stat_grid(
                    [
                        ("Value", "—"),
                        ("Expected at", ctx["timestamp"]),
                    ]
                )
            )
        else:  # error
            parts.append(self._lead_html("The detectkit pipeline failed for this metric."))
            err = f"{ctx['error_type']}: {ctx['error_message']}".strip(": ")
            parts.append(self._params_html("Error", err))
            parts.append(self._stat_grid([("Detected at", ctx["timestamp"])]))

        button = self._links_html(alert_data)
        if button:
            parts.append(button)

        return "".join(parts)

    def _lead_html(self, text: str) -> str:
        return (
            f'<tr><td style="padding:4px 24px 16px 24px;font-family:{_SANS};font-size:14px;'
            f'color:{_MUTED};mso-line-height-rule:exactly;line-height:20px;">'
            f"{html.escape(text)}</td></tr>"
        )

    def _stat_grid(self, pairs: list[tuple[str, str]]) -> str:
        """A 2-column grid of (label, value) cells (table-based)."""
        cells = ""
        for i in range(0, len(pairs), 2):
            row = pairs[i : i + 2]
            tds = ""
            for label, value in row:
                tds += (
                    f'<td width="50%" bgcolor="{_PAPER}" style="width:50%;'
                    f"background-color:{_PAPER};border:1px solid {_BORDER};padding:10px 12px;"
                    f'font-family:{_SANS};mso-line-height-rule:exactly;line-height:16px;">'
                    f'<span style="font-size:11px;color:{_FAINT};text-transform:uppercase;">'
                    f"{html.escape(label)}</span><br>"
                    f'<span style="font-size:15px;font-weight:bold;color:{_INK};">'
                    f"{html.escape(value)}</span></td>"
                )
            if len(row) == 1:
                tds += '<td width="50%" style="width:50%;"></td>'
            cells += f"<tr>{tds}</tr>"
        return (
            '<tr><td style="padding:0 24px 16px 24px;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="border-collapse:collapse;mso-table-lspace:0pt;mso-table-rspace:0pt;">'
            f"{cells}</table></td></tr>"
        )

    def _params_html(self, label: str, value: str) -> str:
        """A labeled dark monospace box (detector params / error message)."""
        return (
            f'<tr><td style="padding:0 24px 6px 24px;font-family:{_SANS};font-size:11px;'
            f'color:{_FAINT};text-transform:uppercase;mso-line-height-rule:exactly;line-height:14px;">'
            f"{html.escape(label)}</td></tr>"
            '<tr><td style="padding:0 24px 20px 24px;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'bgcolor="{_TERM_BG}" style="background-color:{_TERM_BG};border:1px solid {_TERM_BORDER};'
            'border-radius:6px;mso-table-lspace:0pt;mso-table-rspace:0pt;"><tr>'
            f'<td style="padding:12px 14px;font-family:{_MONO};font-size:12px;color:{_TERM_TEXT};'
            'mso-line-height-rule:exactly;line-height:18px;word-break:break-all;">'
            f"{html.escape(value)}</td></tr></table></td></tr>"
        )

    def _links_html(self, alert_data: AlertData) -> str:
        """Dashboard button (clay) + any extra text links."""
        if not alert_data.dashboard_url and not alert_data.links:
            return ""
        rows = ""
        if alert_data.dashboard_url:
            href = html.escape(alert_data.dashboard_url, quote=True)
            rows += (
                '<tr><td style="padding:0 24px 16px 24px;">'
                '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
                'style="mso-table-lspace:0pt;mso-table-rspace:0pt;"><tr>'
                f'<td bgcolor="{_CLAY}" style="background-color:{_CLAY};border-radius:6px;">'
                f'<a href="{href}" style="display:inline-block;padding:10px 18px;'
                f"font-family:{_SANS};font-size:14px;font-weight:bold;color:#ffffff;"
                'text-decoration:none;">Open dashboard &rarr;</a>'
                "</td></tr></table></td></tr>"
            )
        if alert_data.links:
            link_parts = []
            for label, url in alert_data.links.items():
                href = html.escape(url, quote=True)
                link_parts.append(
                    f'<a href="{href}" style="color:{_CLAY};text-decoration:underline;">'
                    f"{html.escape(label)}</a>"
                )
            rows += (
                f'<tr><td style="padding:0 24px 16px 24px;font-family:{_SANS};font-size:13px;'
                f'color:{_MUTED};mso-line-height-rule:exactly;line-height:20px;">'
                + " &middot; ".join(link_parts)
                + "</td></tr>"
            )
        return rows

    def _footer_html(self, alert_data: AlertData) -> str:
        cc = self.format_mentions(alert_data.mentions)
        cc_html = f" &middot; {html.escape(cc)}" if cc else ""
        return (
            f'<tr><td bgcolor="{_SURFACE}" style="background-color:{_SURFACE};'
            f"border-top:1px solid {_BORDER};padding:14px 24px;font-family:{_SANS};"
            f'font-size:12px;color:{_FAINT};mso-line-height-rule:exactly;line-height:16px;">'
            f"Sent by detectkit{cc_html}</td></tr>"
        )

    def format_mentions(self, mentions: list[str]) -> str:
        """
        Format mentions for email.

        Email has no mention syntax. Renders usernames as plain text,
        filtering out broadcast keywords that are meaningless for email.

        Args:
            mentions: List of usernames

        Returns:
            Formatted string like "CC: user1, user2" or empty string
        """
        if not mentions:
            return ""
        user_mentions = [m for m in mentions if m not in ("channel", "all", "here")]
        if not user_mentions:
            return ""
        return "CC: " + ", ".join(user_mentions)

    def __repr__(self) -> str:
        """String representation."""
        return f"EmailChannel(to={self.to_emails})"

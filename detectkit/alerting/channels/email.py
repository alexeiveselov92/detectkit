"""
Email alert channel implementation.

Sends anomaly alerts via SMTP email.
"""

import html
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.channels.branding import BRAND_ICON_URL, BRAND_USERNAME


class EmailChannel(BaseAlertChannel):
    """
    Email alert channel using SMTP.

    Sends formatted emails via SMTP server.

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
        >>> alert = AlertData(
        ...     metric_name="cpu_usage",
        ...     timestamp=np.datetime64("2024-01-01T10:00:00"),
        ...     value=95.0,
        ...     is_anomaly=True
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
        subject_template: str = "⚠ Alert: {metric_name}",
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

        Example:
            >>> channel.send(alert_data)
        """
        message_body = self.format_message(alert_data, template or self.template)

        # Create email message
        msg = MIMEMultipart("alternative")
        # Branded From: "detectkit <alerts@example.com>" — the email equivalent
        # of a bot display name. formataddr quotes the name when required.
        msg["From"] = formataddr((self.from_name, self.from_email))
        msg["To"] = ", ".join(self.to_emails)
        msg["Subject"] = self.subject_template.format(metric_name=alert_data.metric_name)

        # Attach both parts. In multipart/alternative the LAST part is the
        # preferred one, so HTML (with the brand logo) is shown when supported
        # and the plain-text body remains the fallback.
        msg.attach(MIMEText(message_body, "plain"))
        msg.attach(MIMEText(self._build_html_body(message_body), "html"))

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

    def _build_html_body(self, message_body: str) -> str:
        """Wrap the plain-text body in a branded HTML layout.

        Renders a small header with the detectkit brand logo and name above the
        message (kept in a ``<pre>`` so the alert-centric text layout carries
        over verbatim). The logo is referenced by URL; clients that block remote
        images simply fall back to the alt text and the plain-text part.

        Args:
            message_body: The formatted plain-text alert body.

        Returns:
            An HTML document string.
        """
        safe_body = html.escape(message_body)
        return (
            '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,'
            'Arial,sans-serif;color:#1b1916;max-width:640px">'
            '<div style="margin-bottom:12px">'
            f'<img src="{BRAND_ICON_URL}" width="28" height="28" '
            f'alt="{html.escape(BRAND_USERNAME)}" '
            'style="border-radius:6px;vertical-align:middle">'
            '<span style="font-weight:600;font-size:16px;color:#d15b36;'
            f'vertical-align:middle;margin-left:8px">{html.escape(BRAND_USERNAME)}</span>'
            "</div>"
            '<pre style="white-space:pre-wrap;font-family:JetBrains Mono,'
            "ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;"
            f'line-height:1.5;margin:0">{safe_body}</pre>'
            "</div>"
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

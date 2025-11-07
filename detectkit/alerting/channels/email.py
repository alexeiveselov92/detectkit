"""
Email alert channel implementation.

Sends anomaly alerts via SMTP email.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel


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
        to_emails: List[str],
        smtp_username: Optional[str] = None,
        smtp_password: Optional[str] = None,
        use_tls: bool = True,
        subject_template: str = "Anomaly Alert: {metric_name}",
        template: Optional[str] = None,
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
        self.template = template

    def send(self, alert_data: AlertData) -> None:
        """
        Send alert via email.

        Args:
            alert_data: Alert information to send

        Raises:
            smtplib.SMTPException: If email sending fails

        Example:
            >>> channel.send(alert_data)
        """
        message_body = self.format_message(alert_data, self.template)

        # Create email message
        msg = MIMEMultipart("alternative")
        msg["From"] = self.from_email
        msg["To"] = ", ".join(self.to_emails)
        msg["Subject"] = self.subject_template.format(
            metric_name=alert_data.metric_name
        )

        # Attach plain text body
        msg.attach(MIMEText(message_body, "plain"))

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
            raise smtplib.SMTPException(f"Failed to send email alert: {e}")

    def __repr__(self) -> str:
        """String representation."""
        return f"EmailChannel(to={self.to_emails})"

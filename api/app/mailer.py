"""Outbound email over SMTP (Mailpit in development, Amazon SES in production)."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .config import get_settings

log = logging.getLogger("kathachepta.mail")
sent_messages: list[EmailMessage] = []  # captured in tests


def send_email(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if settings.environment == "test":
        sent_messages.append(message)
        return
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_username:
                smtp.starttls()
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except OSError as error:
        log.error("Email to %s failed via %s:%s: %s", to, settings.smtp_host, settings.smtp_port, error)
        raise

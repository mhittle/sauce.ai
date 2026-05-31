"""Shared SMTP send helper used by ``jobs/send_digest.py`` and
``jobs/breaking_alerts.py``.

Extracted so the two senders share one ``MIMEMultipart('alternative')``
build + RFC 8058 ``List-Unsubscribe`` / ``List-Unsubscribe-Post`` block.
Stdlib only — no Flask, no Anthropic, no requests.
"""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr


def build_message(
    *,
    subject: str,
    from_addr: str,
    from_name: str,
    to_addr: str,
    html: str,
    text: str,
    list_unsubscribe_url: str | None = None,
) -> MIMEMultipart:
    """Build a multipart/alternative message.

    When ``list_unsubscribe_url`` is set, attach the RFC 8058 one-click
    ``List-Unsubscribe`` / ``List-Unsubscribe-Post`` headers so Gmail /
    Outlook show the native one-click unsubscribe affordance.
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_addr))
    msg["To"] = to_addr
    if list_unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{list_unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg


def smtp_send(cfg, from_addr: str, to_addr: str, msg) -> None:
    """Open an SMTP connection per send. Plain on port 25; STARTTLS optional.

    ``cfg`` must expose ``SMTP_HOST`` / ``SMTP_PORT`` / ``SMTP_USE_TLS`` /
    ``SMTP_USER`` / ``SMTP_PASSWORD``. The connection lifecycle (ehlo,
    starttls, login, sendmail, quit) is closed defensively so a failed
    quit can't mask a successful send.
    """
    smtp = smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=30)
    try:
        smtp.ehlo()
        if cfg.SMTP_USE_TLS:
            smtp.starttls()
            smtp.ehlo()
        if cfg.SMTP_USER:
            smtp.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
        smtp.sendmail(from_addr, [to_addr], msg.as_string())
    finally:
        try:
            smtp.quit()
        except Exception:
            pass

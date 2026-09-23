"""Report email over SMTP (stdlib). No SMTP configured -> skipped; the report
stays available at its URL."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from .config import Settings

log = logging.getLogger("redteam")


def _pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def build_message(settings: Settings, to: str, run_id: str, html: str, summary: dict) -> EmailMessage:
    adv = summary.get("adversarial") or {}
    url = f"{settings.public_base_url.rstrip('/')}/runs/{run_id}"
    msg = EmailMessage()
    msg["Subject"] = f"sauce.ai/redteam report {run_id}: {_pct((adv.get('conversation_risk') or {}).get('value'))} of conversations reached a harmful reply"
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.set_content(
        f"Your clinical red-team run {run_id} is complete.\n\n"
        f"Conversations with >=1 harmful reply: {adv.get('trials_with_harm')} / {adv.get('trials')}\n"
        f"Harmful replies: {adv.get('harmful_responses')} / {adv.get('responses')}\n\n"
        f"Full report (also attached): {url}\n")
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(html.encode("utf-8"), maintype="text", subtype="html",
                       filename=f"redteam-report-{run_id}.html")
    return msg


def send_report(settings: Settings, to: str, run_id: str, html: str, summary: dict) -> bool:
    if not settings.smtp_host:
        log.info("SMTP not configured; report %s not emailed", run_id)
        return False
    msg = build_message(settings, to, run_id, html, summary)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            if settings.smtp_starttls:
                s.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_pass or "")
            s.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        log.error("emailing report %s failed: %s", run_id, exc)
        return False

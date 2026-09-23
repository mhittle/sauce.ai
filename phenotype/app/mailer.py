"""Report email over SMTP (stdlib). No SMTP configured -> skipped; the report
stays available at its URL."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from .config import Settings

log = logging.getLogger("phenotype")


def build_message(settings: Settings, to: str, job_id: str, html: str, result: dict) -> EmailMessage:
    url = f"{settings.public_base_url.rstrip('/')}/jobs/{job_id}"
    cands = result.get("candidates") or []
    top = cands[0] if cands else None
    msg = EmailMessage()
    msg["Subject"] = (f"sauce.ai/phenotype {job_id}: {len(cands)} validated algorithm(s) for "
                      f"{result.get('condition', 'your condition')}")
    msg["From"] = settings.smtp_from
    msg["To"] = to
    lines = [f"Your phenotyping-algorithm review {job_id} is complete.", ""]
    if top:
        lines.append(f"Top-ranked: {top['algorithm']['name']} (evidence grade: {top['grade']['label']})")
    lines += [f"Studies included: {(result.get('flow') or {}).get('extracted', 0)}", "",
              f"Full report (also attached): {url}"]
    msg.set_content("\n".join(lines) + "\n")
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(html.encode("utf-8"), maintype="text", subtype="html",
                       filename=f"phenotype-report-{job_id}.html")
    return msg


def send_report(settings: Settings, to: str, job_id: str, html: str, result: dict) -> bool:
    if not settings.smtp_host or not to:
        log.info("SMTP not configured or no email; report %s not emailed", job_id)
        return False
    msg = build_message(settings, to, job_id, html, result)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            if settings.smtp_starttls:
                s.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_pass or "")
            s.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        log.error("emailing report %s failed: %s", job_id, exc)
        return False

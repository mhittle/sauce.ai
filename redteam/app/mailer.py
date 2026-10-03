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


NOT_CONFIGURED = "email is not configured on this server (SMTP_HOST unset); the report stays at its URL"


def mail_enabled(settings: Settings) -> bool:
    return bool(settings.smtp_host)


def deliver(settings: Settings, msg: EmailMessage) -> tuple[bool, str | None]:
    """Send one message. Returns (ok, error): the error is a short, user-safe
    reason (host/port, STARTTLS, login, or server reply) so a run can record
    why its report never arrived instead of failing silently."""
    if not settings.smtp_host:
        return False, NOT_CONFIGURED
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            if settings.smtp_starttls:
                s.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_pass or "")
            s.send_message(msg)
        return True, None
    except smtplib.SMTPAuthenticationError as exc:
        return False, f"SMTP login rejected by {settings.smtp_host} ({exc.smtp_code}): check SMTP_USER / SMTP_PASS"
    except smtplib.SMTPRecipientsRefused as exc:
        return False, f"recipient refused by {settings.smtp_host}: {exc.recipients}"
    except smtplib.SMTPException as exc:
        return False, f"SMTP error from {settings.smtp_host}:{settings.smtp_port}: {exc}"
    except OSError as exc:
        return False, f"could not reach {settings.smtp_host}:{settings.smtp_port}: {exc}"


def send_report_detailed(settings: Settings, to: str, run_id: str, html: str, summary: dict) -> tuple[bool, str | None]:
    ok, err = deliver(settings, build_message(settings, to, run_id, html, summary)) if settings.smtp_host else (False, NOT_CONFIGURED)
    if ok:
        log.info("report %s emailed to %s", run_id, to)
    else:
        log.error("report %s not emailed: %s", run_id, err)
    return ok, err


def send_report(settings: Settings, to: str, run_id: str, html: str, summary: dict) -> bool:
    return send_report_detailed(settings, to, run_id, html, summary)[0]


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    """``python -m app.mailer you@lab.edu`` sends a test message with the
    server's SMTP_* settings and prints exactly why it failed, if it did."""
    import sys
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1 or "@" not in args[0]:
        print("usage: python -m app.mailer <recipient@example.org>")
        return 2
    settings = settings or Settings()
    print(f"SMTP_HOST={settings.smtp_host or '(unset)'} SMTP_PORT={settings.smtp_port} "
          f"SMTP_USER={settings.smtp_user or '(unset)'} SMTP_STARTTLS={settings.smtp_starttls} SMTP_FROM={settings.smtp_from}")
    msg = EmailMessage()
    msg["Subject"] = "sauce.ai/redteam test message"
    msg["From"] = settings.smtp_from
    msg["To"] = args[0]
    msg.set_content("If you can read this, report email from sauce.ai/redteam works.\n")
    ok, err = deliver(settings, msg)
    print("sent" if ok else f"FAILED: {err}")
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

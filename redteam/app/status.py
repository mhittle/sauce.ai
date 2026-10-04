"""Live status: every run in flight on this worker, at a glance.

``GET /status`` (HTML, refreshes itself) and ``GET /status.json`` show the
queue depth, the runs executing right now with their trial progress, pace and
projected finish, the runs that finished in the last day with their outcome,
and the worker's configuration (threads, providers with keys, email). It
reads only the light run records, so it stays cheap while a batch writes.
No secrets: emails are masked and target credentials never leave memory.
"""
from __future__ import annotations

import datetime as dt
import time
from html import escape

from . import field as field_mod
from .catalog import SPECIALTIES

RECENT_WINDOW_S = 24 * 3600


def _mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "—"
    user, dom = email.split("@", 1)
    return f"{user[:2]}***@{dom}"


def _spec_label(slug: str | None) -> str:
    s = SPECIALTIES.get(slug or "")
    return s["label"] if isinstance(s, dict) and s.get("label") else (slug or "").replace("_", " ")


def _row(r: dict, now: float) -> dict:
    cfg = r.get("config") or {}
    tgt = r.get("target") or {}
    label = tgt.get("model") or f"{tgt.get('kind', '?')}"
    started = r.get("started_at")
    done, n = r.get("completed_trials") or 0, r.get("n_trials") or 0
    elapsed = (now - started) if started else None
    rate = (done / elapsed * 60.0) if (elapsed and elapsed > 0 and done) else None   # trials per minute
    eta = ((n - done) / rate * 60.0) if (rate and n > done) else None                # seconds
    return {
        "run_id": r["id"], "status": r["status"],
        "model": label, "display": field_mod._MODEL_DISPLAY.get(label, label),
        "specialty": cfg.get("specialty"), "specialty_label": _spec_label(cfg.get("specialty")),
        "condition": cfg.get("condition") or "", "email": _mask(r.get("email")),
        "n_trials": n, "completed_trials": done, "pct": int(100 * done / n) if n else 0,
        "created_at": r.get("created_at"), "started_at": started, "finished_at": r.get("finished_at"),
        "elapsed_s": elapsed, "trials_per_min": rate, "eta_s": eta,
        "super_run_id": cfg.get("super_run_id") or "", "field_scan_id": cfg.get("field_scan_id") or "",
        "error": r.get("error"),
    }


def snapshot(store, settings, now: float | None = None) -> dict:
    now = now or time.time()
    rows = [_row(r, now) for r in store.recent_runs(limit=2000)]
    running = [x for x in rows if x["status"] == "running"]
    queued = [x for x in rows if x["status"] == "queued"]
    recent = [x for x in rows if x["status"] in ("complete", "failed")
              and (x["finished_at"] or x["created_at"] or 0) >= now - RECENT_WINDOW_S]
    running.sort(key=lambda x: x["started_at"] or 0)
    queued.sort(key=lambda x: x["created_at"] or 0)
    recent.sort(key=lambda x: -(x["finished_at"] or x["created_at"] or 0))
    in_flight_trials = sum(x["completed_trials"] for x in running)
    total_trials = sum(x["n_trials"] for x in running)
    rates = [x["trials_per_min"] for x in running if x["trials_per_min"]]
    agg_rate = sum(rates) if rates else None
    remaining = sum(x["n_trials"] - x["completed_trials"] for x in running) + sum(x["n_trials"] for x in queued)
    from .providers import available_providers
    return {
        "now": now, "generated": dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "worker": {
            "worker_threads": settings.worker_threads, "trial_concurrency": settings.trial_concurrency,
            "providers": available_providers(settings), "email_enabled": bool(settings.smtp_host),
            "super_run_enabled": bool(settings.super_token),
        },
        "counts": {"running": len(running), "queued": len(queued),
                   "complete_24h": sum(1 for x in recent if x["status"] == "complete"),
                   "failed_24h": sum(1 for x in recent if x["status"] == "failed")},
        "in_flight": {"trials_done": in_flight_trials, "trials_total": total_trials,
                      "trials_per_min": agg_rate, "trials_remaining": remaining,
                      "eta_s": (remaining / agg_rate * 60.0) if agg_rate else None},
        "running": running, "queued": queued, "recent": recent,
    }


# -- rendering ----------------------------------------------------------------

def _dur(s: float | None) -> str:
    if s is None:
        return "—"
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def _pace(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f}"


def _when(t: float | None) -> str:
    return "—" if not t else dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%H:%M:%S")


def _run_cell(x: dict) -> str:
    batch = (f" &middot; <a class='small' href='/super/{escape(x['super_run_id'])}'>batch {escape(x['super_run_id'])}</a>"
             if x["super_run_id"] else
             (f" &middot; <a class='small' href='/field?field={escape(x['field_scan_id'])}'>field scan</a>" if x["field_scan_id"] else ""))
    return (f"<td><b>{escape(x['display'])}</b> <span class='muted small'>{escape(x['specialty_label'])}"
            f"{' / ' + escape(x['condition']) if x['condition'] else ''}</span><br>"
            f"<a class='small' href='/runs/{escape(x['run_id'])}'>{escape(x['run_id'])}</a>{batch}"
            f" <span class='muted small'>{escape(x['email'])}</span></td>")


def render_html(snap: dict) -> str:
    from .report import CSS, NAV
    w, c, f = snap["worker"], snap["counts"], snap["in_flight"]
    running_rows = "".join(
        f"<tr>{_run_cell(x)}"
        f"<td class='n'>{x['completed_trials']}/{x['n_trials']}"
        f"<div style='height:5px;background:var(--card-2);margin-top:4px'><div style='height:100%;width:{x['pct']}%;background:var(--accent)'></div></div></td>"
        f"<td class='n'>{_when(x['started_at'])}</td><td class='n'>{_dur(x['elapsed_s'])}</td>"
        f"<td class='n'>{_pace(x['trials_per_min'])}</td>"
        f"<td class='n'>{_dur(x['eta_s'])}</td></tr>"
        for x in snap["running"]) or "<tr><td colspan='6' class='muted small' style='text-align:center;padding:16px'>nothing running</td></tr>"
    queued_rows = "".join(
        f"<tr>{_run_cell(x)}<td class='n'>{x['n_trials']}</td><td class='n'>{_when(x['created_at'])}</td></tr>"
        for x in snap["queued"]) or "<tr><td colspan='3' class='muted small' style='text-align:center;padding:16px'>queue empty</td></tr>"
    recent_rows = "".join(
        f"<tr>{_run_cell(x)}<td class='n'>{escape(x['status'])}</td><td class='n'>{x['completed_trials']}/{x['n_trials']}</td>"
        f"<td class='n'>{_when(x['finished_at'])}</td><td class='small'>{escape((x['error'] or '')[:140])}</td></tr>"
        for x in snap["recent"][:60]) or "<tr><td colspan='5' class='muted small' style='text-align:center;padding:16px'>none in the last 24 h</td></tr>"
    rate = "—" if f["trials_per_min"] is None else f"{f['trials_per_min']:.1f}/min"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="15"><meta name="robots" content="noindex">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Status — sauce.ai/redteam</title>
<style>{CSS}</style></head><body>{NAV}<div class="wrap">
<div class="muted small">sauce.ai/redteam &middot; worker status &middot; {escape(snap['generated'])} &middot; refreshes every 15 s &middot;
<a href="/status.json">JSON</a></div>
<h1>Runs in flight</h1>
<div class="tiles">
  <div class="tile"><div class="v">{c['running']}</div><div class="l">running <span class="muted">of {w['worker_threads']} slots</span></div></div>
  <div class="tile"><div class="v">{c['queued']}</div><div class="l">queued</div></div>
  <div class="tile"><div class="v">{f['trials_done']}/{f['trials_total']}</div><div class="l">trials in running runs</div></div>
  <div class="tile"><div class="v">{rate}</div><div class="l">aggregate pace &middot; ETA for everything {_dur(f['eta_s'])}</div></div>
</div>
<p class="small muted">Worker: {w['worker_threads']} runs at a time &times; {w['trial_concurrency']} conversations each &middot;
providers with keys: {escape(', '.join(w['providers']) or 'none')} &middot; email {'on' if w['email_enabled'] else 'off'} &middot;
Super Run launcher {'enabled' if w['super_run_enabled'] else 'disabled'} &middot;
last 24 h: {c['complete_24h']} complete, {c['failed_24h']} failed</p>
<h2>Running</h2>
<table><tr><th>Run</th><th>Trials</th><th>Started</th><th>Elapsed</th><th>Pace (trials/min)</th><th>ETA</th></tr>{running_rows}</table>
<h2>Queued</h2>
<table><tr><th>Run</th><th>Trials</th><th>Submitted</th></tr>{queued_rows}</table>
<h2>Finished in the last 24 h</h2>
<table><tr><th>Run</th><th>Outcome</th><th>Trials</th><th>Finished</th><th>Error</th></tr>{recent_rows}</table>
<p class="small muted">Times are UTC. Pace is each run's completed trials over its elapsed time; ETA assumes it holds.
A service restart fails in-flight runs (partial results are kept) — see INSTALL.md.</p>
</div></body></html>"""

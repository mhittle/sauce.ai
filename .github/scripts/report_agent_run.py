#!/usr/bin/env python3
"""Append one row to the `agent_runs` table via the HMAC
/agent-ops/report-run endpoint, from a workflow's post-step.

Reads everything from env vars so it can be invoked uniformly from
every agent workflow:

  AGENT_OPS_SECRET  HMAC key. Empty => skip silently (e.g. PR from a
                    fork can't see the repo secret; not a fleet event
                    worth recording).
  SITE_URL          e.g. https://sauce.ai/news  (default)
  WORKFLOW          short workflow name (e.g. dev-agent, qa-code)
  JOB               job name within the workflow (e.g. implement)
  RUN_ID            github.run_id
  CONCLUSION        success | failure | cancelled | skipped
  EST_COST_USD      best-effort cost estimate (budget cap if unknown)
  STARTED_AT        epoch seconds when the agent step began
                    (workflow exports this via GITHUB_ENV before the
                    agent runs). Empty => duration_seconds=0.
  PR_NUMBER         optional, 0 if not a PR context
  NOTES             optional short note (e.g. "budget-cap" if cost is
                    a cap rather than measured)

NEVER fails the workflow. Any error (DNS, 5xx, missing secret) is
logged and the script exits 0. The fleet-observability page is a
nice-to-have; a broken reporting step must not break the actual
agent workflow.
"""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default) or default


def main() -> int:
    secret = _env("AGENT_OPS_SECRET")
    if not secret:
        print("report_agent_run: AGENT_OPS_SECRET unset; skipping report", file=sys.stderr)
        return 0

    site = _env("SITE_URL", "https://sauce.ai/news").rstrip("/")
    url = f"{site}/agent-ops/report-run"

    started_at = _env("STARTED_AT")
    duration = 0
    if started_at:
        try:
            duration = max(0, int(time.time()) - int(started_at))
        except (TypeError, ValueError):
            duration = 0

    try:
        est_cost = float(_env("EST_COST_USD", "0"))
    except (TypeError, ValueError):
        est_cost = 0.0

    try:
        pr_number = int(_env("PR_NUMBER", "0"))
    except (TypeError, ValueError):
        pr_number = 0
    try:
        run_id = int(_env("RUN_ID", "0"))
    except (TypeError, ValueError):
        run_id = 0

    payload = {
        "workflow": _env("WORKFLOW", "")[:64],
        "job": _env("JOB", "")[:64],
        "run_id": run_id,
        "conclusion": _env("CONCLUSION", "")[:32],
        "duration_seconds": duration,
        "est_cost_usd": est_cost,
        "pr_number": pr_number,
        "notes": _env("NOTES", "")[:255],
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    ts = str(int(time.time()))
    sig = hmac.new(
        secret.encode("utf-8"),
        ts.encode("utf-8") + b"." + body,
        hashlib.sha256,
    ).hexdigest()

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Agent-Timestamp": ts,
            "X-Agent-Signature": sig,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"report_agent_run: {resp.status} {resp.read(200)!r}")
    except urllib.error.HTTPError as exc:
        print(f"report_agent_run: HTTP {exc.code} from {url}: {exc.read(200)!r}", file=sys.stderr)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"report_agent_run: network error: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

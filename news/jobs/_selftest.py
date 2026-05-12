#!/usr/bin/env python3
"""Diagnostic: prints Python info, env-var visibility, and DB connectivity.

Run from a cron-equivalent shell to check whether a cron job would work:

    /home/USER/virtualenv/.../bin/python /home/USER/.../news/jobs/_selftest.py

Prints PASS/FAIL lines that are grep-friendly. Exits non-zero on any FAIL.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failed = []


def check(label, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    if not ok:
        failed.append(label)
    print(f"{tag}  {label}{(': ' + detail) if detail else ''}")


print(f"python   {sys.executable}")
print(f"version  {sys.version.split()[0]}")
print(f"cwd      {os.getcwd()}")
print(f"sys.path[0]  {sys.path[0]}")
print("---")

try:
    from _bootstrap import Config, get_conn  # noqa: E402
    check("_bootstrap importable", True)
except Exception as e:
    check("_bootstrap importable", False, repr(e))
    print("\n".join(failed))
    sys.exit(1)

required_env = ["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"]
for name in required_env:
    val = os.environ.get(name, "")
    check(f"env {name}", bool(val), ("set" if val else "MISSING — cron will fail"))

check("Config.DB_USER not empty", bool(Config.DB_USER), Config.DB_USER or "(empty)")
check("Config.DB_NAME not empty", bool(Config.DB_NAME), Config.DB_NAME or "(empty)")

try:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()
    conn.close()
    check("MySQL connect", True)
except Exception as e:
    check("MySQL connect", False, repr(e))

api_key = os.environ.get("ANTHROPIC_API_KEY", "")
check(
    "env ANTHROPIC_API_KEY",
    bool(api_key),
    f"len={len(api_key)}" if api_key else "MISSING (rules-only mode)",
)

print("---")
if failed:
    print(f"{len(failed)} check(s) failed: {', '.join(failed)}")
    sys.exit(1)
print("all checks passed")

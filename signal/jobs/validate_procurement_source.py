"""Dry-run a procurement source and print what it extracted — the live tuning
loop for selectors/field paths (no DB writes).

    python jobs/validate_procurement_source.py --slug ga-gpr [--limit 10]

Run this against the real page while tuning seed/procurement_sources.json:
it shows the normalized rows + which canonical fields came back empty, so you
fix the config and re-run until it's clean (same idea as validating permit
field maps on first pull).
"""
from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse

from app.adapters.solicitations.config_source import (build_config_adapter,
                                                      get_source, load_sources)

FIELDS = ("source_id", "title", "agency", "state", "due_date", "source_url")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=False)
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    if not args.slug:
        print("sources:", [s["slug"] for s in load_sources()])
        return
    src = get_source(args.slug)
    if not src:
        raise SystemExit(f"no source {args.slug!r} in procurement_sources.json")

    adapter = build_config_adapter(src)
    empty = {f: 0 for f in FIELDS}
    n = 0
    for norm in adapter.pull():
        n += 1
        for f in FIELDS:
            if not getattr(norm, f, None):
                empty[f] += 1
        if n <= args.limit:
            print(f"- {norm.due_date or '?':<12} {norm.state or '--'} "
                  f"{(norm.title or '')[:60]!r} docs={len(norm.documents)} "
                  f"{norm.source_url or ''}")
    print(f"\n{n} rows. empty-field counts: "
          + ", ".join(f"{f}={c}" for f, c in empty.items() if c))
    if n == 0:
        print("0 rows — check row_selector / records_path against the live page.")


if __name__ == "__main__":
    main()

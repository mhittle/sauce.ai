"""Discover CivicPlus municipalities from the CISA .gov domain list and emit
verified, compact `civicplus` source entries (PRD PlanHub track, scale-out).

CivicPlus runs the identical `Bids.aspx` module on thousands of city/county
sites, so one config pattern generalizes. This probes each candidate's open-
bids page for the CivicPlus marker and seeds only the ones that currently
return open bids (immediately useful, active sources).

    python jobs/discover_civicplus.py --target 200 --limit 2500 [--dry-run]

Source list: CISA cisagov/dotgov-data current-full.csv (City + County).
Respectful: one GET per domain, modest concurrency, short timeout.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import concurrent.futures as cf
import csv
import io
import json
import pathlib
import re

import requests

from app.adapters.solicitations.config_source import civicplus_list_url

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCES = ROOT / "seed" / "procurement_sources.json"
DOTGOV_URL = "https://raw.githubusercontent.com/cisagov/dotgov-data/main/current-full.csv"
UA = {"User-Agent": "Mozilla/5.0 sauce.ai-signal-discovery"}


def slugify(domain: str) -> str:
    return re.sub(r"\.gov$", "", domain.strip().lower()).replace(".", "-")


def load_candidates(csv_path: str | None) -> list[dict]:
    text = (pathlib.Path(csv_path).read_text() if csv_path
            else requests.get(DOTGOV_URL, timeout=30, headers=UA).text)
    return [r for r in csv.DictReader(io.StringIO(text))
            if r["Domain type"] in ("City", "County")]


def probe(row: dict) -> dict | None:
    domain = row["Domain name"].strip().lower()
    try:
        resp = requests.get(civicplus_list_url(domain), timeout=8,
                            allow_redirects=True, headers=UA)
    except requests.RequestException:
        return None
    if "listItemsRow" not in resp.text:        # CivicPlus marker + has open bids
        return None
    open_rows = len(re.findall(r"listItemsRow[^\"']*\bbid\b", resp.text))
    return {
        "slug": slugify(domain),
        "name": (row.get("Organization name") or domain).strip(),
        "level": "county" if row["Domain type"] == "County" else "local",
        "state": row.get("State") or None,
        "platform": "civicplus",
        "domain": domain,
        "active": True,
        "_open_rows": open_rows,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="local dotgov CSV (else download)")
    ap.add_argument("--target", type=int, default=200, help="stop after N hits")
    ap.add_argument("--limit", type=int, default=2500, help="max domains to probe")
    ap.add_argument("--max-workers", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import random
    cands = load_candidates(args.csv)
    random.seed(args.seed); random.shuffle(cands)
    cands = cands[:args.limit]

    existing = json.loads(SOURCES.read_text()) if SOURCES.exists() else []
    have = {s["slug"] for s in existing}

    def reg(d: str) -> str:
        return re.sub(r"^www\.", "", (d or "").strip().lower())
    have_domains = set()
    for s in existing:
        dom = s.get("domain")
        if not dom and s.get("list_url"):
            from urllib.parse import urlparse
            dom = urlparse(s["list_url"]).netloc
        if dom:
            have_domains.add(reg(dom))

    hits: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=args.max_workers) as ex:
        futs = [ex.submit(probe, r) for r in cands]
        for fut in cf.as_completed(futs):
            res = fut.result()
            if res and res["slug"] not in have and reg(res["domain"]) not in have_domains:
                have.add(res["slug"]); have_domains.add(reg(res["domain"]))
                hits.append(res)
                print(f"  + {res['domain']:<32} [{res['state']}] "
                      f"open={res['_open_rows']}")
                if len(hits) >= args.target:
                    break
        ex.shutdown(wait=False, cancel_futures=True)

    for h in hits:
        h.pop("_open_rows", None)
    print(f"\ndiscovered {len(hits)} new CivicPlus sources "
          f"(existing {len(existing)}).")
    if args.dry_run:
        return
    SOURCES.write_text(json.dumps(existing + hits, indent=2) + "\n")
    print(f"wrote {SOURCES.relative_to(ROOT)} "
          f"({len(existing) + len(hits)} total sources).")


if __name__ == "__main__":
    main()

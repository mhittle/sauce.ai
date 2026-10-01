"""Command-line entry point for the confirmatory analysis.

    python -m analysis.cli --input tidy.csv --out results/
    python -m analysis.cli --simulate --out results/     # runnable demo, no export

Reads the tidy per-turn export, runs the pre-registered SAP, and writes
``results.json`` + ``results.md``.
"""
from __future__ import annotations

import argparse
import json
import os

from . import io, sap, simulate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="sauce.ai/redteam confirmatory analysis")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="tidy export file (.csv or .json)")
    src.add_argument("--simulate", action="store_true",
                     help="run on a synthetic dataset instead of a real export")
    ap.add_argument("--out", default="results", help="output directory")
    ap.add_argument("--seed", type=int, default=7, help="seed for --simulate")
    args = ap.parse_args(argv)

    if args.simulate:
        rows = simulate.generate(seed=args.seed)
    elif args.input.endswith(".json"):
        rows = io.load_json(args.input)
    else:
        rows = io.load_csv(args.input)

    results = sap.run_all(rows)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    with open(os.path.join(args.out, "results.md"), "w", encoding="utf-8") as fh:
        fh.write(sap.to_markdown(results))
    print(f"wrote {args.out}/results.json and results.md  (status={results.get('status')})")
    return 0 if results.get("status") == "ok" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

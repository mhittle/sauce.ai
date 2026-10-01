"""Statistical analysis plan runner — fits the pre-registered family and
collects results (PREREGISTRATION.md §5).

`run_all` takes tidy rows (from `io`), validates, builds the frame, fits every
model, and applies Benjamini–Hochberg across the target contrasts. Heavy imports
happen inside `models`, so importing `sap` is cheap; `run_all` raises a clear
RuntimeError only if the scientific stack is missing when a fit is attempted.
"""
from __future__ import annotations

import datetime as dt

from . import io, models, schema, stats_utils


def run_all(rows: list[dict]) -> dict:
    problems = schema.validate(rows)
    if problems:
        return {"status": "invalid", "problems": problems}
    df = io.to_frame(rows)

    primary = models.primary_logistic(df)
    results = {
        "status": "ok",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "n_rows": len(rows),
        "n_targets": int(df["target_label"].nunique()),
        "primary_logistic": primary,
        "time_to_harm_km": models.km_logrank(df),
        "discrete_time_hazard": models.discrete_time_hazard(df),
        "competing_risks": models.competing_risks(df),
    }

    # FDR across the target fixed-effect contrasts in the primary GEE
    coef = (((primary.get("gee") or {}).get("coef")) or {})
    contrasts = {k: v for k, v in coef.items() if k.startswith("C(target_label)")}
    pvals = [v.get("p") for v in contrasts.values()]
    bh = stats_utils.benjamini_hochberg(pvals)
    results["fdr_target_contrasts"] = {
        "terms": list(contrasts.keys()),
        "p": pvals,
        "q": bh["q"],
        "n_rejected": len(bh["rejected"]),
        "alpha": 0.05,
    }
    return results


def to_markdown(results: dict) -> str:
    if results.get("status") == "invalid":
        return "# Analysis — INVALID INPUT\n\n" + "\n".join(f"- {p}" for p in results["problems"])
    lines = ["# Confirmatory analysis — sauce.ai/redteam",
             "", f"_Generated {results['generated_at']} · {results['n_rows']} rows · "
             f"{results['n_targets']} targets_", ""]

    km = results["time_to_harm_km"]
    lines += ["## RQ2 — time to first harmful reply (Kaplan–Meier)", ""]
    if km.get("status") == "ok":
        for t, m in sorted(km["medians"].items()):
            lines.append(f"- **{t}**: median {'not reached' if m is None else m} prompts")
        lr = km["logrank"]
        lines += ["", f"Log-rank across targets: χ²={lr['chi2']:.2f}, df={lr['df']}, p={lr['p']:.4g}", ""]
    else:
        lines += [f"_{km.get('reason', km.get('status'))}_", ""]

    pl = results["primary_logistic"]
    lines += ["## RQ1 — harm by target (GEE logistic, conversation-clustered)", ""]
    gee = pl.get("gee") or {}
    if gee.get("status") == "ok":
        lines += ["| term | OR | 95% CI | p |", "| --- | --- | --- | --- |"]
        for name, r in gee["coef"].items():
            if not name.startswith("C(target_label)"):
                continue
            ci = (f"{r.get('or_lo', float('nan')):.2f}–{r.get('or_hi', float('nan')):.2f}"
                  if "or_lo" in r else "—")
            lines.append(f"| {name} | {r['or']:.2f} | {ci} | {r.get('p', float('nan')):.4g} |")
        fdr = results["fdr_target_contrasts"]
        lines += ["", f"Benjamini–Hochberg across {len(fdr['terms'])} target contrasts: "
                  f"{fdr['n_rejected']} significant at q≤{fdr['alpha']}.", ""]
    else:
        lines += [f"_{gee.get('status')}: {gee.get('reason', gee.get('error', ''))}_", ""]

    cr = results["competing_risks"]
    if cr.get("status") == "ok":
        lines += ["## Competing risks — harmful cumulative incidence", ""]
        for t, r in sorted(cr["targets"].items()):
            if "harmful_cif_final" in r:
                lines.append(f"- **{t}**: {r['harmful_cif_final']:.3f}")
        lines.append("")
    return "\n".join(lines)

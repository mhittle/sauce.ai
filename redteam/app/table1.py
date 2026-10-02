"""Table 1 — the descriptive case-mix table (STROBE item 14), pure stdlib.

One column per run (agent / arm), one row per persona covariate level with
n (%), plus the **standardized mean difference** of each run against the
referent (first run, or `ref=`) — the balance diagnostic used for Table 1 in
observational studies. On the instrument's paired design (same seed, specialty,
condition, n) every agent meets the same personas, so SMDs are ~0; a non-zero
SMD means the runs do not share a case-mix and the contrast is not paired.
"""
from __future__ import annotations

import datetime as dt
import math
from html import escape

from .dataset import target_label
from .epi import COVARIATES
from .field import _MODEL_DISPLAY

ROWS = [
    ("age_band", "Age band"), ("sex", "Sex"), ("speaker", "Speaker"), ("health_literacy", "Health literacy"),
    ("affect", "Affect"), ("access", "Care access"),
]


def _meds_band(p: dict) -> str:
    n = len(p.get("current_meds") or [])
    return "0" if n == 0 else "1" if n == 1 else "2" if n == 2 else "3+"


EXTRA = {"meds": ("Current high-risk medications", _meds_band),
         "red_flag": ("Latent red flag present", lambda p: "yes" if p.get("red_flag") else "no")}


def _levels(convs: list[dict], f) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in convs:
        k = f(c["persona"])
        out[k] = out.get(k, 0) + 1
    return out


def smd_categorical(a: dict[str, int], b: dict[str, int]) -> float | None:
    """Standardized mean difference for a multi-level categorical covariate
    (Yang & Dalton 2012): sqrt(T'S⁻¹T) with S the pooled covariance of the
    level indicators; reduces to the usual binary SMD for two levels. Uses the
    diagonal approximation when S is singular."""
    na, nb = sum(a.values()), sum(b.values())
    if na == 0 or nb == 0:
        return None
    levels = sorted(set(a) | set(b))[1:]  # drop one level (reference)
    if not levels:
        return 0.0
    pa = [a.get(l, 0) / na for l in levels]
    pb = [b.get(l, 0) / nb for l in levels]
    t = [x - y for x, y in zip(pa, pb)]
    k = len(levels)
    s = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(k):
            va = (pa[i] * (1 - pa[i]) if i == j else -pa[i] * pa[j])
            vb = (pb[i] * (1 - pb[i]) if i == j else -pb[i] * pb[j])
            s[i][j] = (va + vb) / 2
    # solve S x = t by Gauss-Jordan; fall back to diagonal if singular
    m = [row[:] + [t[i]] for i, row in enumerate(s)]
    try:
        for c in range(k):
            piv = max(range(c, k), key=lambda r: abs(m[r][c]))
            if abs(m[piv][c]) < 1e-12:
                raise ZeroDivisionError
            m[c], m[piv] = m[piv], m[c]
            pv = m[c][c]
            m[c] = [v / pv for v in m[c]]
            for r in range(k):
                if r != c and m[r][c]:
                    f = m[r][c]
                    m[r] = [rv - f * cv for rv, cv in zip(m[r], m[c])]
        x = [m[i][k] for i in range(k)]
        q = sum(ti * xi for ti, xi in zip(t, x))
    except ZeroDivisionError:
        q = sum((ti * ti) / s[i][i] for i, ti in enumerate(t) if s[i][i] > 1e-12)
    return math.sqrt(max(q, 0.0))


def _convs(store, run_id: str) -> list[dict]:
    return [{"persona": t["persona"], "arm": t.get("arm")} for t in store.trials_for_run(run_id, with_turns=False)
            if t["status"] in ("complete", "harm")]


def table1(store, run_ids: list[str], ref: str | None = None) -> dict:
    cols = []
    for rid in run_ids:
        run = store.get_run(rid)
        if not run:
            continue
        convs = _convs(store, rid)
        if not convs:
            continue
        cfg = run.get("config") or {}
        lab = target_label(run)
        cols.append({"run_id": rid, "label": _MODEL_DISPLAY.get(lab, lab), "n": len(convs), "convs": convs,
                     "key": (cfg.get("seed"), cfg.get("specialty"), cfg.get("condition"), cfg.get("n_trials")),
                     "arms": sorted({c["arm"] for c in convs if c["arm"]})})
    if not cols:
        return {"n_runs": 0, "columns": [], "rows": []}
    ref_i = next((i for i, c in enumerate(cols) if c["run_id"] == ref), 0)
    fs = [(k, lab, COVARIATES[k]) for k, lab in ROWS] + [(k, lab, f) for k, (lab, f) in EXTRA.items()]
    rows, max_smd = [], 0.0
    for key, label, f in fs:
        per = [_levels(c["convs"], f) for c in cols]
        levels = sorted(set().union(*per))
        smds = [None if i == ref_i else smd_categorical(per[i], per[ref_i]) for i in range(len(cols))]
        max_smd = max([max_smd] + [s for s in smds if s is not None])
        rows.append({"covariate": key, "label": label,
                     "levels": [{"level": lv, "cells": [{"n": p.get(lv, 0), "pct": p.get(lv, 0) / c["n"]}
                                                         for p, c in zip(per, cols)]} for lv in levels],
                     "smd": smds})
    return {"n_runs": len(cols), "referent": {"run_id": cols[ref_i]["run_id"], "label": cols[ref_i]["label"]},
            "columns": [{k: c[k] for k in ("run_id", "label", "n", "arms")} for c in cols],
            "rows": rows, "shared_case_mix": len({c["key"] for c in cols}) == 1,
            "max_smd": max_smd, "balanced": max_smd < 0.10,
            "n_conversations": sum(c["n"] for c in cols)}


def render_html(res: dict) -> str:
    from .report import CSS, NAV, FOOTER
    when = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not res["columns"]:
        return (f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{NAV}"
                "<div class='wrap'><h1>Table 1</h1><p class='muted'>No completed conversations in the chosen runs.</p></div></body></html>")
    cols = res["columns"]
    head = "".join(f"<th class='n'>{escape(c['label'])}<br><span class='muted'>n = {c['n']}</span></th>" for c in cols)
    smd_head = "".join(f"<th class='n'>SMD vs ref</th>" if c["run_id"] != res["referent"]["run_id"] else "<th class='n'>ref</th>" for c in cols)
    body = []
    for r in res["rows"]:
        body.append(f"<tr><td colspan='{1 + 2 * len(cols)}' style='background:var(--card-2)'><b>{escape(r['label'])}</b></td></tr>")
        for i, lv in enumerate(r["levels"]):
            cells = "".join(f"<td class='n'>{c['n']} ({c['pct'] * 100:.0f}%)</td>" for c in lv["cells"])
            smds = "".join((f"<td class='n'>{s:.2f}</td>" if s is not None else "<td class='n muted'>—</td>")
                           for s in r["smd"]) if i == 0 else "<td></td>" * len(cols)
            body.append(f"<tr><td style='padding-left:22px'>{escape(lv['level'])}</td>{cells}{smds}</tr>")
    bal = ("Balanced: every standardized mean difference is below 0.10 — the agents met the same case-mix."
           if res["balanced"] else
           f"<b>Not balanced:</b> max standardized mean difference {res['max_smd']:.2f} ≥ 0.10 — these runs do not share a "
           "case-mix; contrasts between them are not paired.")
    mix = ("Runs share one seeded case-mix (same seed, specialty, condition, n)." if res["shared_case_mix"]
           else "Runs were configured with different seeds / specialties / conditions / n.")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Table 1 — case-mix — sauce.ai/redteam</title>
<style>{CSS}</style></head><body>{NAV}<div class="wrap">
<div class="muted small">sauce.ai/redteam · table 1 · {res['n_runs']} run(s) · {res['n_conversations']} conversations · {when}</div>
<h1>Table 1 — synthetic case-mix by agent</h1>
<div class="muted small">Referent: {escape(res['referent']['label'])} · {mix}</div>
<div class="{'note' if res['balanced'] else 'warn'}">{bal}</div>
<h2>Persona covariates</h2>
<div class="table-wrap"><table><tr><th>Covariate · level</th>{head}{smd_head}</tr>{''.join(body)}</table></div>
<p class="small muted">n (%) of completed adversarial conversations per level. SMD: standardized mean difference of the run
against the referent (Yang &amp; Dalton multi-level form; the usual binary SMD for two levels); &lt; 0.10 is the conventional
balance threshold. Personas are synthetic — this table describes the library's case-mix, not a patient population.
Numbers: <code>/table1.json</code> with the same query.</p>
</div>{FOOTER}</body></html>"""

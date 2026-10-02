"""Shareable model safety card, eval card, and dataset datasheet.

Turns a completed run into a single, legible, link-and-screenshot-friendly
artifact: one **model safety card** per target (headline safety score + rank,
attack success, critical failures, time-to-harm curve, top harm categories,
provenance), plus a 1200×630 **share image** (SVG) with Open Graph tags, a
**methods/eval card** describing how the eval works, and a
**datasheet-for-datasets** for the generated conversation data.

Reuses the existing report house style and metrics — no new scoring. Pure given
a store; all rendering is stdlib string building.
"""
from __future__ import annotations

import datetime as dt
from html import escape

from . import leaderboard, report
from .field import _MODEL_DISPLAY
from .compare import PALETTE
from .dataset import target_label


def safety_card(store, run_id: str) -> dict | None:
    run = store.get_run(run_id)
    if not run or run.get("status") != "complete" or not run.get("summary"):
        return None
    adv = (run["summary"].get("adversarial")) or {}
    if not adv.get("trials"):
        return None
    cfg = run.get("config") or {}
    orch = cfg.get("orchestration") or {}
    specialty = cfg.get("specialty") or "unknown"

    # leaderboard standing for this target in its specialty
    rank = n_targets = None
    try:
        bd = leaderboard.board(store, specialty)
        n_targets = bd["n_targets"]
        label = target_label(run)
        for e in bd["entries"]:
            if e["target_label"] == label:
                rank = e["rank"]
                break
    except Exception:  # pragma: no cover - standing is a nice-to-have
        pass

    cats = sorted((adv.get("category_counts") or {}).items(), key=lambda kv: -kv[1])[:4]
    return {
        "run_id": run_id, "target_label": _MODEL_DISPLAY.get(target_label(run), target_label(run)), "specialty": specialty,
        "created_at": run.get("created_at"), "trials": adv["trials"],
        "safety_score": leaderboard.safety_score(adv),
        "critical_count": leaderboard.critical_count(adv),
        "attack_success": adv["conversation_risk"],
        "response_risk": adv["response_risk"],
        "median_prompts_to_harm": adv["prompts_until_harm"]["km"].get("median"),
        "km": adv["prompts_until_harm"]["km"],
        "qalys_per_1000": adv["expected_qalys_lost_per_1000_conversations"].get("mean"),
        "escalation_sensitivity": (adv.get("escalation_sensitivity") or {}).get("value"),
        "top_categories": cats,
        "rank": rank, "n_targets": n_targets,
        "provenance": {
            "attackers": orch.get("attackers", []), "judges": cfg.get("judges", []),
            "harm_threshold": cfg.get("harm_threshold"), "seed": cfg.get("seed"),
        },
    }


def _score_color(score: float | None) -> str:
    if score is None:
        return "#52514e"
    return f"hsl({int(120 * score)},60%,38%)"


def _score_str(score: float | None) -> str:
    return "—" if score is None else f"{score * 100:.0f}"


# -- share image (Open Graph, 1200x630) --------------------------------------

def render_card_svg(card: dict) -> str:
    W, H = 1200, 630
    score = card["safety_score"]
    col = _score_color(score)
    tiles = [
        ("Attack success", report._pct((card["attack_success"] or {}).get("value"))),
        ("Critical failures", str(card["critical_count"])),
        ("Median prompts→harm",
         "—" if card["median_prompts_to_harm"] is None else str(card["median_prompts_to_harm"])),
        ("Conversations", str(card["trials"])),
    ]
    tx = [60, 345, 630, 915]
    tile_svg = "".join(
        f'<text x="{x}" y="430" font-size="22" fill="#52514e">{escape(lbl)}</text>'
        f'<text x="{x}" y="478" font-size="40" font-weight="700" fill="#0b0b0b">{escape(val)}</text>'
        for (lbl, val), x in zip(tiles, tx))
    rank = (f'rank {card["rank"]}/{card["n_targets"]} in {escape(_spec(card["specialty"]))}'
            if card["rank"] else escape(_spec(card["specialty"])))
    return f"""<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">
<rect width="{W}" height="{H}" fill="#fcfcfb"/>
<rect x="0" y="0" width="{W}" height="12" fill="{col}"/>
<text x="60" y="90" font-size="26" fill="#52514e" font-family="system-ui,Arial">sauce.ai/redteam · clinical AI safety card</text>
<text x="60" y="165" font-size="62" font-weight="800" fill="#0b0b0b" font-family="system-ui,Arial">{escape(card['target_label'][:28])}</text>
<text x="60" y="210" font-size="26" fill="#52514e" font-family="system-ui,Arial">{rank}</text>
<text x="60" y="330" font-size="150" font-weight="800" fill="{col}" font-family="system-ui,Arial">{_score_str(score)}</text>
<text x="330" y="330" font-size="34" fill="#52514e" font-family="system-ui,Arial">/ 100</text>
<text x="330" y="285" font-size="28" fill="#0b0b0b" font-family="system-ui,Arial">safety score</text>
<text x="330" y="300" font-size="18" fill="#9a9893" font-family="system-ui,Arial"> </text>
<g font-family="system-ui,Arial">{tile_svg}</g>
<line x1="60" y1="520" x2="{W - 60}" y2="520" stroke="#eeede8"/>
<text x="60" y="565" font-size="20" fill="#9a9893" font-family="system-ui,Arial">Adversarial elicitation · LLM-judge screening (audited) · higher score = safer</text>
</svg>"""


def _spec(slug: str) -> str:
    from .catalog import SPECIALTIES
    s = SPECIALTIES.get(slug)
    return s["label"] if isinstance(s, dict) and s.get("label") else slug.replace("_", " ")


# -- full card page -----------------------------------------------------------

def _cat_bars(cats: list[tuple[str, int]]) -> str:
    if not cats:
        return '<p class="small muted">no harm categories recorded</p>'
    top = max(n for _, n in cats) or 1
    rows = "".join(
        f'<div style="display:flex;align-items:center;gap:8px;margin:3px 0">'
        f'<span style="width:180px;font-size:13px">{escape(c.replace("_", " "))}</span>'
        f'<span style="height:14px;width:{int(220 * n / top)}px;background:{PALETTE[i % len(PALETTE)]};'
        f'border-radius:3px"></span><span class="small muted">{n}</span></div>'
        for i, (c, n) in enumerate(cats))
    return rows


def render_card_html(card: dict) -> str:
    when = dt.datetime.fromtimestamp(card["created_at"] or 0, dt.timezone.utc).strftime("%Y-%m-%d")
    score = card["safety_score"]
    km_series = [(card["target_label"], _score_color(score), card["km"])] if card["km"].get("curve") else []
    rank = f'Rank {card["rank"]} of {card["n_targets"]}' if card["rank"] else "Unranked"
    prov = card["provenance"]
    og_img = f"/card/{card['run_id']}/image.svg"
    desc = (f"Safety score {_score_str(score)}/100 · attack success "
            f"{report._pct((card['attack_success'] or {}).get('value'))} · "
            f"{card['critical_count']} critical failures over {card['trials']} conversations.")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Safety card — {escape(card['target_label'])}</title>
<meta property="og:title" content="Clinical AI safety card — {escape(card['target_label'])}">
<meta property="og:description" content="{escape(desc)}">
<meta property="og:image" content="{og_img}">
<meta name="twitter:card" content="summary_large_image">
<style>{report.CSS}
.hero {{ display:flex; gap:24px; align-items:center; flex-wrap:wrap; margin:14px 0 }}
.bigscore {{ font-size:72px; font-weight:800; line-height:1 }}
</style></head><body>{report.NAV}<div class="wrap">
<div class="muted small">sauce.ai/redteam &middot; clinical AI safety card &middot; {when}</div>
<h1>{escape(card['target_label'])}</h1>
<div class="muted small">{escape(_spec(card['specialty']))} &middot; {rank} &middot; {card['trials']} conversations</div>
<div class="hero">
  <div><div class="bigscore" style="color:{_score_color(score)}">{_score_str(score)}<span style="font-size:24px;color:#9a9893"> / 100</span></div>
  <div class="small muted">safety score (severity-weighted safe rate)</div></div>
</div>
<div class="tiles">
  {report._tile(report._pct((card['attack_success'] or {}).get('value')), 'Attack success')}
  {report._tile(str(card['critical_count']), 'Critical failures')}
  {report._tile('not reached' if card['median_prompts_to_harm'] is None else str(card['median_prompts_to_harm']), 'Median prompts&rarr;harm')}
  {report._tile(report._num(card['qalys_per_1000'], 2), 'QALYs / 1,000')}
</div>
<h2>Time to first harmful reply</h2>
{report.km_svg(km_series) if km_series else '<p class="small muted">no time-to-harm curve</p>'}
<h2>Top harm categories</h2>
{_cat_bars(card['top_categories'])}
<h2>Provenance</h2>
<p class="small">Attackers: {escape(', '.join(prov['attackers']) or '—')} &middot;
Judges: {escape(', '.join(prov['judges']) or '—')} &middot;
Harm threshold: {prov['harm_threshold']} &middot; Seed: {prov['seed']} &middot;
Run: <a href="/runs/{escape(card['run_id'])}">{escape(card['run_id'])}</a></p>
<div class="warn">LLM-judge screening signals (the judge is itself audited — see the grader audit), not clinical
determinations. Share image: <a href="{og_img}">{og_img}</a>. See the <a href="/eval-card">eval card</a> and
<a href="/datasheet">dataset datasheet</a>.</div>
</div></body></html>"""


# -- eval card (model card for the eval) -------------------------------------

def render_eval_card() -> str:
    rows = [
        ("What it measures", "The rate and severity of unsafe clinical advice a chatbot gives under adaptive "
         "adversarial pressure, expressed as interpretable epidemiological risk (attack success, number "
         "needed to harm, time-to-harm, a severity-weighted safety score, and a design-based Critical Harm Rate)."),
        ("Intended use", "Pre-deployment and ongoing safety evaluation of clinical/health chatbots by their "
         "owners, and comparative benchmarking. Authorized testing only."),
        ("Out of scope", "Not a medical device assessment, not a clinical determination, not a guarantee of "
         "safety. Results are screening signals requiring clinician review."),
        ("Elicitation", "A synthetic patient converses with the target; an orchestrator (tactic bandit + "
         "multi-model propose/refine/arbiter/consensus) steers toward unsafe states. Each component's marginal "
         "value is quantified by the ablation harness."),
        ("Grader", "An LLM harm-judge panel scores P(follow)×P(harm|follow), severity, categories, and "
         "escalation. The grader is validated two ways: against clinician adjudication (agreement, "
         "sensitivity/specificity, calibration) and by a bias/robustness audit (verbosity, authority, "
         "disclaimer, paraphrase, self-preference)."),
        ("Metrics", "Wilson/Newcombe intervals, Kaplan–Meier + log-rank time-to-harm, NNH, expected QALY/DALY "
         "loss, Horvitz–Thompson Critical Harm Rate with exact and bootstrap CIs. Confirmatory models "
         "(mixed-effects logistic, frailty survival, competing risks) run in a separate analysis package."),
        ("Reproducibility", "Fixed seeds, pinned prompt and model snapshots, a tidy per-turn export, and a "
         "pre-registered protocol with a power analysis."),
        ("Limitations", "Synthetic-persona realism; LLM-judge validity (mitigated, not eliminated); model "
         "drift; generalization from the target panel to the deployed ecosystem."),
        ("Standards", "Maps to NIST AI RMF (MAP/MEASURE), UK AISI evaluation guidance, and TRIPOD-LLM / "
         "datasheet-for-datasets reporting."),
    ]
    body = "".join(f"<h2>{escape(h)}</h2><p>{escape(t)}</p>" for h, t in rows)
    return _doc("Eval card — sauce.ai/redteam", "Eval card", body)


def render_datasheet() -> str:
    rows = [
        ("Motivation", "To measure how often, how fast, and how severely deployed clinical chatbots give "
         "unsafe advice under adversarial pressure, with clinician-interpretable risk metrics."),
        ("Composition", "Synthetic multi-turn conversations between a generated patient persona and a target "
         "chatbot, each turn annotated by an LLM judge panel (P(harm), severity, categories, escalation). No "
         "real patient data; no PHI."),
        ("Collection", "Conversations are generated on demand against researcher-supplied endpoints the "
         "researcher is authorized to test. Target credentials are held in memory for the run only and never "
         "persisted."),
        ("Preprocessing / labeling", "Harm labels are LLM-judge screening signals; a stratified sample is "
         "adjudicated by clinicians for validation. The judge is audited for bias and calibration."),
        ("Uses", "Safety benchmarking, methods research, and (with clinician review) vendor disclosure. Not for "
         "clinical decision-making."),
        ("Distribution", "A de-identified conversation + annotation export (tidy CSV/JSON) accompanies "
         "publications; the most operational jailbreak strings are withheld under responsible disclosure."),
        ("Maintenance", "Suite/judge/prompt versions and model snapshots are recorded; changes are versioned "
         "and never mixed across versions in a comparison."),
    ]
    body = "".join(f"<h2>{escape(h)}</h2><p>{escape(t)}</p>" for h, t in rows)
    return _doc("Dataset datasheet — sauce.ai/redteam", "Datasheet for the conversation dataset", body)


def _doc(title: str, h1: str, body: str) -> str:
    when = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>
<style>{report.CSS}</style></head><body>{report.NAV}<div class="wrap">
<div class="muted small">sauce.ai/redteam &middot; {when}</div><h1>{escape(h1)}</h1>{body}
<p class="small muted">Standards-neutral reporting (NIST AI RMF, UK AISI, TRIPOD-LLM, datasheet-for-datasets).</p>
</div></body></html>"""

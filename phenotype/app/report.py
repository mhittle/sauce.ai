"""Self-contained HTML report (inline CSS, no scripts): renders the same in a
browser, as an email body, and as an attachment."""
from __future__ import annotations

import datetime as dt
from html import escape

from . import catalog as C
from .config import Settings
from .literature import europepmc_query, pubmed_query

CSS = """
body{margin:0;background:#fcfcfb;color:#0b0b0b;font:15px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:24px 16px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 8px;border-bottom:1px solid #e4e3de;padding-bottom:4px}
h3{font-size:15px;margin:16px 0 6px}
a{color:#2a78d6}.muted{color:#52514e}.small{font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}
.tile{border:1px solid #e4e3de;border-radius:8px;padding:12px;background:#fff}
.tile .v{font-size:24px;font-weight:600}.tile .l{font-size:13px;color:#52514e}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #eeede8;vertical-align:top}
th{color:#52514e;font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.warn{background:#fff6e5;border:1px solid #f0d9a8;border-radius:8px;padding:10px 12px;font-size:13px}
details{border:1px solid #e4e3de;border-radius:8px;margin:10px 0;background:#fff}
summary{cursor:pointer;padding:10px 12px;font-size:15px}
.body{padding:4px 14px 14px}
pre{background:#f6f6f3;border:1px solid #eeede8;border-radius:6px;padding:10px;overflow-x:auto;font-size:12.5px;white-space:pre-wrap;overflow-wrap:anywhere}
code{overflow-wrap:anywhere}
.g{display:inline-block;min-width:22px;text-align:center;border-radius:4px;padding:0 6px;font-weight:600;color:#fff}
.g4{background:#1a7f4b}.g3{background:#2a78d6}.g2{background:#b7791f}.g1{background:#9b1c1b}
.tag{display:inline-block;font-size:12px;border:1px solid #d9d8d2;border-radius:10px;padding:0 8px;margin:2px 4px 2px 0}
.ok{color:#1a7f4b}.bad{color:#9b1c1b}
q{font-style:italic;color:#52514e}
"""


def _pct(x, d=1) -> str:
    return "&ndash;" if x is None else f"{100 * x:.{d}f}%"


def _ci(p: dict | None) -> str:
    if not p:
        return "&ndash;"
    return f"{_pct(p['value'])} <span class=muted>({_pct(p['lo'])}&ndash;{_pct(p['hi'])})</span>"


def _grade(g: dict) -> str:
    return f'<span class="g g{g["level"]}">{g["letter"]}</span> {escape(g["label"])}'


def _tile(v, label: str) -> str:
    return f'<div class="tile"><div class="v">{v}</div><div class="l">{escape(label)}</div></div>'


def _risk(r: dict) -> str:
    cls = {"low": "ok", "high": "bad"}.get(r["overall"], "muted")
    doms = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in r["domains"].items())
    return f'<span class="{cls}" title="{escape(doms)}">{escape(r["overall"])}</span>'


def _codes_table(alg: dict) -> str:
    rows = []
    for i, r in enumerate(alg["rules"], 1):
        for c in r["components"]:
            codes = ", ".join(escape(x) for x in c["codes"]) or '<span class=bad>not reported</span>'
            src = ' <span class="tag">inferred</span>' if c["codes"] and c.get("codes_source") == "inferred" else ""
            rows.append(f"<tr><td>Rule {i}</td><td>{escape(c['label'])}</td><td>{escape(c['domain'])}</td>"
                        f"<td>{escape(c['code_system'])}</td><td>{escape(c['care_setting'])}</td><td>{codes}{src}"
                        f"{(' ' + escape(c['lab_threshold'])) if c.get('lab_threshold') else ''}</td></tr>")
    for c in alg["exclusions"]:
        rows.append(f"<tr><td>Exclude</td><td>{escape(c['label'])}</td><td>{escape(c['domain'])}</td>"
                    f"<td>{escape(c['code_system'])}</td><td>{escape(c['care_setting'])}</td>"
                    f"<td>{', '.join(escape(x) for x in c['codes'])}</td></tr>")
    return ('<div class=scroll><table><tr><th></th><th>Component</th><th>Domain</th><th>Code system</th>'
            '<th>Setting</th><th>Codes</th></tr>' + "".join(rows) + "</table></div>")


def _pooled_table(c: dict) -> str:
    rows = []
    for m in C.METRICS:
        p = c["pooled"].get(m)
        if not p:
            rows.append(f"<tr><td>{C.METRIC_LABELS[m]}</td><td colspan=5 class=muted>not estimated</td></tr>")
            continue
        ver = '<span class=ok>verified</span>' if p.get("verified") else '<span class=bad>unverified</span>'
        if p.get("assumed_n"):
            ver += ' <span class="tag">n assumed</span>'
        i2 = f"{100 * p['i2']:.0f}%" if p["k"] > 1 else "&ndash;"
        rows.append(f"<tr><td>{C.METRIC_LABELS[m]}</td><td class=n>{_ci(p)}</td><td class=n>{p['k']}</td>"
                    f"<td class=n>{p['n']:,}</td><td class=n>{i2}</td><td>{ver}</td></tr>")
    return ('<div class=scroll><table><tr><th>Metric</th><th>Pooled (95% CI)</th><th>k</th><th>n (eff.)</th>'
            '<th>I&sup2;</th><th>Quotes</th></tr>' + "".join(rows) + "</table></div>")


def _validation_rows(c: dict) -> str:
    rows = []
    for v in c["validations"]:
        mets = []
        for m in C.METRICS:
            mv = v["metrics"].get(m)
            if not mv:
                continue
            mark = '<span class=ok>&#10003;</span>' if mv["verified"] else '<span class=bad title="quote not found verbatim">?</span>'
            ci = f" ({_pct(mv['lo'])}&ndash;{_pct(mv['hi'])})" if mv["lo"] is not None and mv["hi"] is not None else ""
            cnt = f" [{mv['x']}/{mv['n']}]" if mv["x"] is not None and mv["n"] else ""
            quote = f'<br><q>{escape(mv["quote"][:240])}</q>' if mv["quote"] else ""
            mets.append(f"<b>{C.METRIC_LABELS[m]}</b> {_pct(mv['value'])}{ci}{cnt} {mark}{quote}")
        ref = C.REFERENCE_STANDARDS[v["reference_standard"]]["label"]
        samp = C.SAMPLING[v["sampling"]]["label"]
        ext = ' <span class="tag">external</span>' if v["external"] else ""
        rows.append(
            f"<tr><td><a href=\"{escape(v['url'])}\">{escape(v['citation'][:160])}</a>{ext}</td>"
            f"<td>{escape(v['dataset'])}<br><span class=muted>{escape(v['country'])} {escape(v['years'])} "
            f"{escape(v['data_type'])}</span></td><td class=n>{v['n_validated'] or '&ndash;'}</td>"
            f"<td>{escape(ref)}{('<br><span class=muted>' + escape(v['reference_detail']) + '</span>') if v['reference_detail'] else ''}"
            f"<br><span class=muted>{escape(samp)}</span></td><td>{_risk(v['risk'])}</td>"
            f"<td>{'<br>'.join(mets)}</td></tr>")
    return ('<div class=scroll><table><tr><th>Reference</th><th>Dataset</th><th>n</th><th>Reference standard / sampling</th>'
            '<th>Risk of bias</th><th>Reported accuracy</th></tr>' + "".join(rows) + "</table></div>")


def _candidate(c: dict, open_: bool) -> str:
    a = c["algorithm"]
    comp = c["components"]
    notes = "".join(f"<li>{escape(n)}</li>" for n in c["grade"]["reasons"]) or "<li>No downgrades.</li>"
    appl = "".join(f"<li>{escape(n)}</li>" for n in c["applicability_notes"])
    prev = ""
    if c.get("at_prevalence"):
        ap = c["at_prevalence"]
        prev = (f"<h3>At your expected prevalence ({_pct(ap['prevalence'], 2)})</h3><p class=small>"
                f"Expected PPV {_pct(ap['ppv'])}, NPV {_pct(ap['npv'], 2)}. The algorithm would flag "
                f"{_pct(ap['apparent_prevalence'], 2)} of the population; correct a crude prevalence with "
                f"Rogan&ndash;Gladen: p = (apparent + Sp &minus; 1) / (Se + Sp &minus; 1).</p>")
    return f"""<details{' open' if open_ else ''}><summary><b>#{c['rank']} {escape(a['name'])}</b> &nbsp; {_grade(c['grade'])}
 &nbsp;<span class=muted>score {comp_score(c)}</span></summary><div class=body>
<p>{escape(a['summary'])}</p>
<h3>Algorithm, spelled out</h3><pre>{escape(c['pseudocode'])}</pre>
{_codes_table(a)}
{('<p class=small><b>Notes:</b> ' + escape(a['notes']) + '</p>') if a['notes'] else ''}
<h3>Validity</h3>{_pooled_table(c)}
{prev}
<h3>Evidence grade: {_grade(c['grade'])}</h3><ul class=small>{notes}</ul>
<p class=small>Score {comp_score(c)} = accuracy {comp['accuracy']:.3f} &times; quality {comp['quality']:.3f}
 &times; applicability {comp['applicability']:.3f} &times; replication {comp['replication']:.3f}</p>
{('<p class=small><b>Applicability to your setting:</b></p><ul class=small>' + appl + '</ul>') if appl else ''}
<h3>Validation studies</h3>{_validation_rows(c)}
<details><summary class=small>OMOP CDM SQL (PostgreSQL)</summary><div class=body><pre>{escape(c['omop_sql'])}</pre></div></details>
</div></details>"""


def comp_score(c: dict) -> str:
    return f"{c['composite']:.3f}"


def render_report(job: dict, result: dict, settings: Settings) -> str:
    spec = result["spec"]
    flow = result["flow"]
    cands = result["candidates"]
    use = C.INTENDED_USES[spec["intended_use"]]
    when = dt.datetime.fromtimestamp(job["created_at"]).strftime("%Y-%m-%d")
    idn = flow["identified"]
    n_ident = sum(v for v in idn.values() if isinstance(v, int))
    rank_rows = "".join(
        f"<tr><td class=n>{c['rank']}</td><td>{escape(c['algorithm']['name'])}</td><td>{_grade(c['grade'])}</td>"
        f"<td class=n>{comp_score(c)}</td>"
        + "".join(f"<td class=n>{_ci(c['pooled'].get(m))}</td>" for m in ("sensitivity", "specificity", "ppv"))
        + f"<td class=n>{len(c['validations'])}</td></tr>" for c in cands)
    studies = "".join(
        f"<li><a href=\"{escape(s['url'])}\">{escape(s['citation'])}</a> <span class=muted small>"
        f"({escape(s['text_basis'])}{', cited by ' + str(s['cited_by']) if s['cited_by'] else ''}"
        f"{', ' + str(s['n_algorithms']) + ' algorithm(s)' if s['n_algorithms'] else ', no extractable accuracy data'})</span></li>"
        for s in result["studies"])
    excluded = "".join(f"<tr><td><a href=\"{escape(x['url'])}\">{escape(x['citation'][:180])}</a></td>"
                       f"<td>{escape(x['label'])}</td><td>{escape(x['reason'])}</td></tr>" for x in result["excluded"])
    weights = ", ".join(f"{C.METRIC_LABELS[m]} {w:.2f}" for m, w in use["weights"].items() if w)
    body_cands = "".join(_candidate(c, i < 3) for i, c in enumerate(cands)) or \
        "<p>No algorithm with extractable validation results was found. Try synonyms, a broader data setting, or more papers.</p>"
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Phenotype algorithms: {escape(result['condition'])}</title><style>{CSS}</style></head><body><div class=wrap>
<p class="muted small">sauce.ai/phenotype &middot; job {escape(job['id'])} &middot; {when}</p>
<h1>Validated phenotyping algorithms for {escape(result['condition'])}</h1>
<p class=muted>Ranked for <b>{escape(use['label'])}</b> in {escape(', '.join(C.DATA_TYPES[d] for d in spec['data_types']))}
({escape(C.CODING_ERAS[spec['coding_era']])}{', ' + escape(spec['country']) if spec['country'] else ''}).</p>
<div class=tiles>{_tile(n_ident, 'records identified')}{_tile(flow['screened'], 'screened')}
{_tile(flow['included'], 'validation studies')}{_tile(flow['extracted'], 'with extractable accuracy')}
{_tile(len(cands), 'distinct algorithms')}</div>
<p class=warn>Machine-assisted evidence review. Algorithms, code lists and accuracy figures were extracted by a
language model from abstracts or open-access full text; figures marked <span class=bad>?</span> could not be matched
to a verbatim quote. Check the source paper (and its supplement for full code lists) before using an algorithm.
PPV and NPV depend on prevalence and do not transport directly between populations.</p>
<h2>Ranking</h2><div class=scroll><table><tr><th>#</th><th>Algorithm</th><th>Evidence</th><th>Score</th>
<th>Sensitivity</th><th>Specificity</th><th>PPV</th><th>Validations</th></tr>{rank_rows}</table></div>
<h2>Algorithms</h2>{body_cands}
<h2>Studies read</h2><ol class=small>{studies}</ol>
<details><summary class=small>Screened out ({len(result['excluded'])})</summary><div class="body scroll"><table>
<tr><th>Record</th><th>Label</th><th>Reason</th></tr>{excluded}</table></div></details>
<h2>Methods</h2><div class=small>
<p><b>Search.</b> PubMed: <code>{escape(pubmed_query(result['condition'], spec['synonyms']))}</code>.
Europe PMC: <code>{escape(europepmc_query(result['condition'], spec['synonyms']))}</code>. Known papers suggested
by the model were kept only if their title resolved to a PubMed record. One-hop citation snowballing through
the Europe PMC citation graph (papers citing, and cited by, included studies and reviews). Identified: {escape(str(idn))};
{flow['deduplicated']} after de-duplication.</p>
<p><b>Screening and extraction.</b> Titles and abstracts screened by {escape(settings.screen_model)}; included
papers read by {escape(settings.extract_model)} (open-access full text when available, otherwise the abstract).
Each accuracy figure must come with a verbatim quote containing the number; unmatched figures are flagged.</p>
<p><b>Pooling.</b> Sensitivity, specificity, PPV and NPV pooled on the logit scale (DerSimonian&ndash;Laird random
effects) across validations of the same algorithm; algorithms are the same when their code categories (ICD to 3
characters) and counting logic match. Study variances come from 2&times;2 counts, else the reported 95% CI, else
p and its denominator (when only the number of records verified is reported, half of it, capped at
{C.ASSUMED_N_CAP}; marked &ldquo;n assumed&rdquo;). Verified figures are pooled in preference to unverified ones.</p>
<p><b>Score.</b> accuracy &times; quality &times; applicability &times; replication. Accuracy = weighted sum of pooled
<i>lower</i> 95% confidence limits ({weights}; an unestimated metric counts as {C.MISSING_METRIC_VALUE}).
Quality = 0.6 + 0.4 &times; mean QUADAS-2-style domain score (reference standard, patient selection, blinding;
low 1, unclear 0.5, high 0). Applicability multiplies penalties for data type, coding era, NLP dependence and
country (floor 0.5). Replication = min(1, 0.85 + 0.05 &times; independent datasets).</p>
<p><b>Evidence grade</b> (GRADE-style, start High): downgrade for primary metric(s) not estimated, risk of bias,
inconsistency (I&sup2; &gt; {int(100 * C.INCONSISTENT_I2)}%), imprecision (95% CI wider than
{int(100 * C.IMPRECISE_CI_WIDTH)} points or &lt; {C.MIN_TOTAL_N} records verified), indirectness (applicability &lt;
0.8), a single validation without external replication, and unverified extraction.</p>
<p><b>SQL.</b> Generated deterministically from the structured algorithm for OMOP CDM v5.4 source concepts;
drug components expand RxNorm ingredients through <code>concept_ancestor</code>. Review before use.</p>
<p class=muted>Model usage: {escape(str(result['usage']))}; literature API calls: {result['literature_calls']}.</p>
</div></div></body></html>"""

"""Causal diagrams for "AI advice as an exposure" (pure stdlib).

A small DAG toolkit — d-separation by the ancestral-moral-graph test, the
backdoor criterion, and enumeration of **minimal sufficient adjustment sets**
over observed nodes — plus two reference DAGs for the instrument:

* ``observational`` — real-world use: which agent a person consults depends
  on health literacy, care access, clinical severity and an unmeasured
  "trust in medicine"; those also affect harm. The exposure→outcome effect
  is confounded, and U is not blockable from observed covariates.
* ``trial`` — the red-team design: personas are drawn from a seeded case-mix
  and **every persona is assigned to every agent**, so no persona covariate
  causes exposure. The empty set is a sufficient adjustment set; what remains
  are the measurement path (judge) and the adaptive-pressure mediator.

The DAGs are explicit, editable assumptions (pass extra edges/nodes); they are
not learned from data.
"""
from __future__ import annotations

from html import escape
from itertools import combinations

# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


class DAG:
    def __init__(self, nodes: dict[str, dict], edges: list[tuple[str, str]]):
        """nodes: id → {label, kind} with kind in exposure|outcome|covariate|
        unobserved|mediator|measurement. edges: (parent, child)."""
        self.nodes = dict(nodes)
        self.edges = []
        for p, c in edges:
            if p not in self.nodes or c not in self.nodes:
                raise ValueError(f"edge {p}->{c} references unknown node")
            if (p, c) not in self.edges:
                self.edges.append((p, c))
        self._assert_acyclic()

    # -- structure ---------------------------------------------------------
    def parents(self, n: str) -> set[str]:
        return {p for p, c in self.edges if c == n}

    def children(self, n: str) -> set[str]:
        return {c for p, c in self.edges if p == n}

    def ancestors(self, nodes: set[str]) -> set[str]:
        seen, stack = set(), list(nodes)
        while stack:
            n = stack.pop()
            for p in self.parents(n):
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        return seen

    def descendants(self, n: str) -> set[str]:
        seen, stack = set(), [n]
        while stack:
            x = stack.pop()
            for c in self.children(x):
                if c not in seen:
                    seen.add(c)
                    stack.append(c)
        return seen

    def _assert_acyclic(self) -> None:
        for n in self.nodes:
            if n in self.descendants(n):
                raise ValueError(f"cycle through {n}")

    def without_edges_out_of(self, n: str) -> "DAG":
        return DAG(self.nodes, [(p, c) for p, c in self.edges if p != n])

    # -- d-separation ------------------------------------------------------
    def d_separated(self, x: str, y: str, z: set[str]) -> bool:
        """Ancestral moral graph test: restrict to An({x,y}∪Z), moralise
        (marry co-parents, drop directions), delete Z, test connectivity."""
        keep = {x, y} | set(z) | self.ancestors({x, y} | set(z))
        und: dict[str, set[str]] = {n: set() for n in keep}
        for p, c in self.edges:
            if p in keep and c in keep:
                und[p].add(c)
                und[c].add(p)
        for n in keep:  # moralise
            ps = [p for p in self.parents(n) if p in keep]
            for a, b in combinations(ps, 2):
                und[a].add(b)
                und[b].add(a)
        for n in z:
            und.pop(n, None)
            for s in und.values():
                s.discard(n)
        seen, stack = {x}, [x]
        while stack:
            n = stack.pop()
            for m in und.get(n, ()):
                if m == y:
                    return False
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        return True

    # -- backdoor adjustment -------------------------------------------------
    def backdoor_valid(self, x: str, y: str, z: set[str]) -> bool:
        """Z satisfies the backdoor criterion for X→Y: no node in Z is a
        descendant of X and Z blocks every path from X to Y in the graph with
        X's outgoing edges removed."""
        if z & (self.descendants(x) | {x, y}):
            return False
        return self.without_edges_out_of(x).d_separated(x, y, z)

    def observed(self) -> list[str]:
        return [n for n, d in self.nodes.items() if d.get("kind") != "unobserved"]

    def minimal_adjustment_sets(self, x: str, y: str, max_size: int = 6) -> list[list[str]]:
        """All minimal sufficient adjustment sets drawn from observed,
        non-descendant nodes (ascending size). Empty list ⇒ the effect is not
        identifiable by covariate adjustment from observed nodes."""
        cands = [n for n in self.observed() if n not in (x, y) and n not in self.descendants(x)]
        found: list[set[str]] = []
        for k in range(0, min(max_size, len(cands)) + 1):
            for combo in combinations(cands, k):
                z = set(combo)
                if any(f <= z for f in found):
                    continue
                if self.backdoor_valid(x, y, z):
                    found.append(z)
        return [sorted(z) for z in found]

    def open_backdoor_paths(self, x: str, y: str, z: set[str] | None = None, limit: int = 12) -> list[list[str]]:
        """Enumerate X ← … Y paths (first edge into X) that are open given Z —
        for explanation, not inference. Simple paths; small graphs only."""
        z = set(z or ())
        out: list[list[str]] = []
        und = {n: set() for n in self.nodes}
        for p, c in self.edges:
            und[p].add(c)
            und[c].add(p)

        def is_open(path: list[str]) -> bool:
            for i in range(1, len(path) - 1):
                a, m, b = path[i - 1], path[i], path[i + 1]
                into_m = (a, m) in self.edges and (b, m) in self.edges  # collider
                if into_m:
                    if not ({m} | self.descendants(m)) & z:
                        return False
                elif m in z:
                    return False
            return True

        def walk(path: list[str]):
            if len(out) >= limit:
                return
            last = path[-1]
            if last == y and len(path) > 2:
                if is_open(path):
                    out.append(list(path))
                return
            for nxt in und[last]:
                if nxt in path:
                    continue
                if len(path) == 1 and (x, nxt) in self.edges:
                    continue  # must start with an edge INTO x
                walk(path + [nxt])

        walk([x])
        return out


# ---------------------------------------------------------------------------
# Reference DAGs
# ---------------------------------------------------------------------------

_NODES = {
    "A": {"label": "AI agent consulted", "kind": "exposure"},
    "Y": {"label": "Unsafe advice / harm", "kind": "outcome"},
    "Age": {"label": "Age", "kind": "covariate"},
    "Lit": {"label": "Health literacy", "kind": "covariate"},
    "Sev": {"label": "Clinical severity (red flag)", "kind": "covariate"},
    "Acc": {"label": "Care access", "kind": "covariate"},
    "U": {"label": "Trust in medicine (unmeasured)", "kind": "unobserved"},
    "P": {"label": "Adversarial pressure (prompts)", "kind": "mediator"},
    "J": {"label": "Judge style bias", "kind": "measurement"},
    "Ystar": {"label": "Judge-labelled harm (Y*)", "kind": "measurement"},
}

_COMMON = [("Age", "Y"), ("Lit", "Y"), ("Sev", "Y"), ("Acc", "Y"), ("U", "Y"),
           ("A", "P"), ("P", "Y"), ("A", "Y"),
           ("Y", "Ystar"), ("J", "Ystar"), ("A", "J")]
_OBS_ONLY = [("Lit", "A"), ("Acc", "A"), ("Sev", "A"), ("Age", "A"), ("U", "A")]


def reference_dag(design: str = "observational", extra_edges: list[tuple[str, str]] | None = None) -> DAG:
    if design not in ("observational", "trial"):
        raise ValueError("design must be 'observational' or 'trial'")
    edges = list(_COMMON) + (list(_OBS_ONLY) if design == "observational" else [])
    return DAG(_NODES, edges + list(extra_edges or []))


def analyze(design: str = "observational", extra_edges: list[tuple[str, str]] | None = None) -> dict:
    g = reference_dag(design, extra_edges)
    sets = g.minimal_adjustment_sets("A", "Y")
    open_paths = g.open_backdoor_paths("A", "Y", set())
    # does the unmeasured node sit on an open backdoor path even after the best observed set?
    best = set(sets[0]) if sets else set()
    unblockable = [p for p in g.open_backdoor_paths("A", "Y", best) if "U" in p]
    # measurement path: A → J → Y* (judge self-preference) — not a confounder of A→Y but of A→Y*
    meas = ("A", "J") in g.edges and ("J", "Ystar") in g.edges
    return {
        "design": design,
        "nodes": [{"id": k, **v} for k, v in g.nodes.items()],
        "edges": [{"from": p, "to": c} for p, c in g.edges],
        "exposure": "A", "outcome": "Y",
        "minimal_adjustment_sets": sets,
        "identifiable_by_adjustment": bool(sets),
        "open_backdoor_paths_unadjusted": open_paths,
        "unblockable_paths_after_adjustment": unblockable,
        "measurement_bias_path": ["A", "J", "Ystar"] if meas else None,
        "mediator": "P",
        "notes": _notes(design, sets, unblockable),
    }


def _notes(design: str, sets: list[list[str]], unblockable: list[list[str]]) -> list[str]:
    n = []
    if design == "trial":
        n.append("Exposure is assigned by design (every persona meets every agent on the same seeded case-mix), "
                 "so no persona covariate causes exposure: the empty set is sufficient and the crude contrast is "
                 "unconfounded for the total effect of agent on harm.")
        n.append("Adversarial pressure (P) is a mediator of A→Y, not a confounder — adjusting for it would estimate "
                 "a direct effect, not the total effect the leaderboard reports.")
    else:
        if sets:
            n.append(f"Observed covariates {sets[0]} block the measured backdoor paths; the unmeasured trust node "
                     "is the residual threat, quantified by the E-value on the /epi page.")
        else:
            n.append("No observed set blocks every backdoor path (the unmeasured trust node opens one): the "
                     "effect is not identifiable by covariate adjustment from real-world use data — which is why the "
                     "instrument assigns exposure by design instead.")
    n.append("Y* (the judge label) is a mis-measured Y; the A→J→Y* path is differential measurement error "
             "(judge self-preference / style bias), audited by the grader audit and corrected in the /epi QBA.")
    return n


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------

_POS = {  # fixed layered layout (x, y) in a 760×400 frame
    "Age": (90, 70), "Lit": (250, 70), "Sev": (410, 70), "Acc": (570, 70),
    "U": (330, 150),
    "A": (120, 250), "P": (330, 250), "Y": (560, 250),
    "J": (330, 340), "Ystar": (560, 340),
}
_TOP_ROW = {"Age", "Lit", "Sev", "Acc"}
_KIND_FILL = {"exposure": "#8e2a1f", "outcome": "#d1261a", "covariate": "#fcfcfb", "unobserved": "#fcfcfb",
              "mediator": "#fcfcfb", "measurement": "#fcfcfb"}
_INK, _INK2, _MUTED = "#0b0b0b", "#52514e", "#9a9893"


def dag_svg(res: dict, width: int = 760, height: int = 400) -> str:
    nodes = {n["id"]: n for n in res["nodes"]}
    adj = set(res["minimal_adjustment_sets"][0]) if res["minimal_adjustment_sets"] else set()
    r = 22
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" '
             f'style="max-width:{width}px" font-family="system-ui,Arial" role="img" '
             f'aria-label="Causal diagram: AI agent consulted and unsafe advice, {escape(res["design"])} design">',
             '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
             f'<path d="M0,0 L10,5 L0,10 z" fill="{_INK2}"/></marker>'
             '<marker id="arrm" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
             f'<path d="M0,0 L10,5 L0,10 z" fill="{_MUTED}"/></marker></defs>',
             f'<rect width="{width}" height="{height}" fill="#fcfcfb"/>',
             f'<text x="16" y="22" font-size="14" font-weight="700" fill="{_INK}">'
             f'{"Real-world use (observational)" if res["design"] == "observational" else "Red-team design (exposure assigned)"}'
             f' — AI agent → unsafe advice</text>']
    for e in res["edges"]:
        (x1, y1), (x2, y2) = _POS[e["from"]], _POS[e["to"]]
        dx, dy = x2 - x1, y2 - y1
        d = (dx * dx + dy * dy) ** 0.5 or 1
        sx, sy = x1 + dx / d * (r + 2), y1 + dy / d * (r + 2)
        ex, ey = x2 - dx / d * (r + 4), y2 - dy / d * (r + 4)
        meas = nodes[e["to"]]["kind"] == "measurement" or nodes[e["from"]]["kind"] == "measurement"
        unobs = nodes[e["from"]]["kind"] == "unobserved"
        stroke = _MUTED if (meas or unobs) else _INK2
        dash = ' stroke-dasharray="5,4"' if (meas or unobs) else ""
        parts.append(f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="{stroke}" '
                     f'stroke-width="1.6"{dash} marker-end="url(#{"arrm" if stroke == _MUTED else "arr"})"/>')
    for nid, (x, y) in _POS.items():
        if nid not in nodes:
            continue
        n = nodes[nid]
        fill = _KIND_FILL.get(n["kind"], "#fcfcfb")
        stroke = "#b8860b" if nid in adj else (_MUTED if n["kind"] == "unobserved" else _INK2)
        sw = 3 if nid in adj else 1.5
        dash = ' stroke-dasharray="4,3"' if n["kind"] == "unobserved" else ""
        txt = "#fcfcfb" if n["kind"] in ("exposure", "outcome") else _INK
        parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{dash}/>'
                     f'<text x="{x}" y="{y + 5}" font-size="13" font-weight="700" text-anchor="middle" fill="{txt}">'
                     f'{escape("Y*" if nid == "Ystar" else nid)}</text>')
        lab = n["label"]
        if nid in _TOP_ROW:      # label above: the downward edges leave from below
            lx, ly, anchor = x, y - r - 8, "middle"
        elif nid == "U":         # label beside: edges fan out below and above
            lx, ly, anchor = x + r + 6, y + 4, "start"
        else:
            lx, ly, anchor = x, y + r + 14, "middle"
        parts.append(f'<text x="{lx}" y="{ly}" font-size="10.5" text-anchor="{anchor}" fill="{_INK2}">{escape(lab)}</text>')
    legend = ('<tspan fill="#b8860b">◯</tspan> minimal adjustment set  · dashed: unmeasured / measurement path'
              if adj else 'dashed: unmeasured / measurement path · no observed adjustment set suffices'
              if res["design"] == "observational" else
              'dashed: unmeasured / measurement path · empty adjustment set suffices (exposure assigned by design)')
    parts.append(f'<text x="16" y="{height - 6}" font-size="10.5" fill="{_INK2}">{legend}</text>')
    parts.append("</svg>")
    return "".join(parts)

import type { TextFragment } from "./schedule.js";

// ---------------------------------------------------------------------------
// Dimension skeleton (DIM_SKELETON gate) — deterministic geometry from the
// sheet's own text layer.
// ---------------------------------------------------------------------------
// Cabinet drawings print their answer: every run is subdivided by a CHAIN of
// dimension strings (`6 | 27 | 24 | 24 | 27 | 6` under a `124"` overall IS the
// island's cabinet split), and the text layer gives each string's exact
// position — localization the VLM cannot produce on its own (the bbox spike
// failed). Cluster the dim strings into collinear chains and hand them to the
// vision prompt as authoritative structure: vision assigns segments to
// cabinets/openings instead of freestyle-counting, and two views showing the
// same chain are the same cabinets (dedup by dimension signature, not labels).
// Pure + IO-free; callers supply pageTextFragments output.

export interface DimToken {
  x: number;
  y: number;
  raw: string;
  inches: number;
}

export interface DimChain {
  axis: "h" | "v";
  // Position of the chain along the cross axis (y for horizontal chains).
  at: number;
  tokens: DimToken[]; // ordered along the chain's axis
}

export interface DimSkeleton {
  chains: DimChain[];
  labels: { x: number; y: number; text: string }[];
}

// Parse a printed dimension to decimal inches: `24"`, `27`, `34 1/2`, `1'-6"`,
// `6' - 0"`, `124"`. Plain integers are accepted (shop drawings omit the quote
// mark); prose/codes return null.
export function parseDimInches(text: string): number | null {
  const s = text
    .trim()
    .replace(/[”“]/g, '"')
    .replace(/[’‘]/g, "'");
  // feet-inches: 1'-6", 6' - 0", 3'-2 1/2"
  let m = /^(\d{1,2})'\s*-?\s*(\d{1,2})?(?:\s+(\d+)\/(\d+))?"?$/.exec(s);
  if (m) {
    const ft = Number(m[1]);
    const inch = m[2] ? Number(m[2]) : 0;
    const frac = m[3] ? Number(m[3]) / Number(m[4]) : 0;
    return ft * 12 + inch + frac;
  }
  // inches: 24, 24", 34 1/2, 34 1/2", 25.625, 1 1/2"
  m = /^(\d{1,3})(?:\s+(\d+)\/(\d+))?(?:\.(\d+))?"?$/.exec(s);
  if (m) {
    let v = Number(m[1]);
    if (m[2]) v += Number(m[2]) / Number(m[3]);
    else if (m[4]) v = Number(`${m[1]}.${m[4]}`);
    return v;
  }
  // bare fraction: 1/2"
  m = /^(\d+)\/(\d+)"?$/.exec(s);
  if (m) return Number(m[1]) / Number(m[2]);
  return null;
}

// Room/fixture words that anchor the skeleton semantically.
const LABEL_RE =
  /\b(kitchen|pantry|island|vanity|bath|laundry|mud|closet|linen|sink|range|stove|cooktop|oven|micro(?:wave)?|fridge|refrigerator|dish\s?washer|dw|ref|hood|washer|dryer|bar|desk)\b/i;

// A chain whose values are consecutive small integers is the sheet's grid
// ruler (1 2 3 … 35 across the border), not dimensions.
function isGridRuler(tokens: DimToken[]): boolean {
  if (tokens.length < 5) return false;
  let consecutive = 0;
  for (let i = 1; i < tokens.length; i++) {
    if (tokens[i].inches - tokens[i - 1].inches === 1) consecutive++;
  }
  return consecutive >= tokens.length - 2;
}

function cluster(
  tokens: DimToken[],
  key: (t: DimToken) => number,
  order: (t: DimToken) => number,
  axis: "h" | "v",
  tol: number
): DimChain[] {
  const groups: { at: number; tokens: DimToken[] }[] = [];
  for (const t of [...tokens].sort((a, b) => key(a) - key(b))) {
    const g = groups.find((g) => Math.abs(g.at - key(t)) <= tol);
    if (g) g.tokens.push(t);
    else groups.push({ at: key(t), tokens: [t] });
  }
  return groups
    .map((g) => ({
      axis,
      at: Math.round(g.at),
      tokens: g.tokens.sort((a, b) => order(a) - order(b)),
    }))
    .filter((g) => g.tokens.length >= 2 && !isGridRuler(g.tokens));
}

// Extract the dimension skeleton of one page. `tol` is the collinearity
// tolerance in PDF points.
export function extractDimSkeleton(
  fragments: TextFragment[],
  tol = 8
): DimSkeleton {
  const tokens: DimToken[] = [];
  const labels: DimSkeleton["labels"] = [];
  for (const f of fragments) {
    const t = f.text.trim();
    if (!t) continue;
    const inches = parseDimInches(t);
    // Dimensions on drawings are 0.5..300 inches; single digits ≤ 3 are usually
    // fillers/reveals — keep them (they matter for run math).
    if (inches != null && inches > 0 && inches <= 300) {
      tokens.push({ x: Math.round(f.x), y: Math.round(f.y), raw: t, inches });
    } else if (LABEL_RE.test(t) && t.length <= 40) {
      labels.push({ x: Math.round(f.x), y: Math.round(f.y), text: t });
    }
  }
  const horizontal = cluster(tokens, (t) => t.y, (t) => t.x, "h", tol);
  const vertical = cluster(tokens, (t) => t.x, (t) => t.y, "v", tol);
  // Vertical chains repeat every horizontal token that shares an x with
  // something; keep only vertical chains with ≥3 tokens to cut that noise.
  return {
    chains: [...horizontal, ...vertical.filter((c) => c.tokens.length >= 3)],
    labels,
  };
}

const fmtIn = (v: number) => (v % 1 === 0 ? String(v) : v.toFixed(3).replace(/0+$/, "").replace(/\.$/, ""));

// Render the skeleton as the grounding block appended to the vision prompt
// (extractPage opts.grounding). Returns undefined when the sheet has no
// usable printed structure (caller falls back to ungrounded reading).
export function formatDimGrounding(skel: DimSkeleton): string | undefined {
  if (skel.chains.length === 0) return undefined;
  const chainLines = skel.chains
    .slice(0, 40)
    .map(
      (c) =>
        `  [${c.axis === "h" ? "y" : "x"}≈${c.at}] ${c.tokens.map((t) => fmtIn(t.inches)).join(" | ")}`
    );
  const labelLine =
    skel.labels.length > 0
      ? `FIXTURE/ROOM LABELS (x,y): ${skel.labels
          .slice(0, 30)
          .map((l) => `${l.text}(${l.x},${l.y})`)
          .join(", ")}\n`
      : "";
  return (
    "PRINTED DIMENSION CHAINS ON THIS SHEET (extracted from the drawing's own text). " +
    "Each chain is a run of printed dimensions along one line of the drawing; a chain of " +
    "cabinet-sized values subdividing a larger overall dimension IS that run's cabinet " +
    "layout. Rules:\n" +
    "- When a drawn cabinet clearly aligns with a printed value, use that EXACT value " +
    "for its size. If you cannot confidently match a drawn cabinet to a chain, still " +
    "emit it with your best visual estimate — NEVER drop or re-size a clearly drawn " +
    "cabinet just because its dimension isn't identifiable in the chains.\n" +
    "- Assign each segment to a cabinet OR an opening (sink/range/cooktop/DW/fridge " +
    "gaps are NOT cabinets; 1-3\" segments are fillers, not cabinets).\n" +
    "- The SAME value sequence appearing more than once (plan + elevation, or repeated " +
    "views) is the SAME cabinets — count them ONCE.\n" +
    "- Equal ADJACENT segments are often the DOORS of one wider cabinet (two 18\" doors " +
    "= one 36\" pair-door cabinet; two 23\" doors = one 46\" pantry). Count CARCASSES " +
    "from the drawn cabinet outlines/dividers, not from door divisions — emit one line " +
    "per carcass at the full carcass width.\n" +
    "- HEIGHTS are printed too (vertical chains, stacked section dims): a door-over-door " +
    "stack drawn as one outline (e.g. 19.5 over 34.5) is ONE cabinet at the FULL stacked " +
    "height (~54\"). Use the printed height for every wall/tall unit; never default a " +
    "height when the chains provide one.\n" +
    chainLines.join("\n") +
    "\n" +
    labelLine
  );
}

// One-call convenience for callers holding raw fragments.
export function buildDimGrounding(fragments: TextFragment[]): string | undefined {
  return formatDimGrounding(extractDimSkeleton(fragments));
}

// Printed dimension values near a page-point rectangle (fragment anchors are
// top-left points in the same upright page space). Used to give the measure
// pass a per-cabinet shortlist — the dims that size a cabinet sit just
// outside its box (dimension bands above/below/beside), hence the slack.
// Returns the deduped raw strings nearest-first, or [] when none qualify.
export function dimsNearRect(
  fragments: TextFragment[],
  rect: { x0: number; y0: number; x1: number; y1: number },
  slackPt: number,
  max = 12
): string[] {
  const cx = (rect.x0 + rect.x1) / 2;
  const cy = (rect.y0 + rect.y1) / 2;
  const near: { raw: string; d: number }[] = [];
  for (const f of fragments) {
    const t = f.text.trim();
    const inches = parseDimInches(t);
    if (inches == null || inches <= 0 || inches > 300) continue;
    if (
      f.x < rect.x0 - slackPt ||
      f.x > rect.x1 + slackPt ||
      f.y < rect.y0 - slackPt ||
      f.y > rect.y1 + slackPt
    )
      continue;
    near.push({ raw: t, d: Math.hypot(f.x - cx, f.y - cy) });
  }
  near.sort((a, b) => a.d - b.d);
  const seen = new Set<string>();
  const out: string[] = [];
  for (const n of near) {
    if (seen.has(n.raw)) continue;
    seen.add(n.raw);
    out.push(n.raw);
    if (out.length >= max) break;
  }
  return out;
}

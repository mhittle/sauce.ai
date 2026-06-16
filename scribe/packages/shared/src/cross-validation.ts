import type { CabinetLineItem } from "./schemas.js";

// Cross-validation comparator (pure, IO-free). Anthropic remains the source of
// truth; this diffs a secondary extraction (OpenAI) against it and lowers the
// confidence of primary lines the secondary disagrees with or fails to find,
// so they drop below the review threshold. Lines the secondary found but the
// primary missed are reported as flags (never injected — never silently add).

const DIM_TOLERANCE_IN = 0.51;
// Both below LOW_CONFIDENCE_THRESHOLD (0.8) so flagged lines reach human review.
const DISAGREE_CONFIDENCE = 0.6;
const MISSING_CONFIDENCE = 0.7;

function normTag(tag: string | null): string | null {
  if (!tag) return null;
  return tag.toUpperCase().replace(/[\s-]/g, "");
}

function dimsClose(a: number | null, b: number | null): boolean {
  if (a == null && b == null) return true;
  if (a == null || b == null) return false;
  return Math.abs(a - b) <= DIM_TOLERANCE_IN;
}

function sameLine(a: CabinetLineItem, b: CabinetLineItem): boolean {
  const aTag = normTag(a.tag);
  const bTag = normTag(b.tag);
  if (aTag && bTag) return aTag === bTag && a.category === b.category;
  return (
    a.category === b.category &&
    dimsClose(a.width_in, b.width_in) &&
    dimsClose(a.height_in, b.height_in)
  );
}

// Reasons a matched pair disagrees (qty/dims). Empty array = agreement.
function disagreements(p: CabinetLineItem, s: CabinetLineItem): string[] {
  const out: string[] = [];
  if (p.qty !== s.qty) out.push(`qty ${p.qty}≠${s.qty}`);
  if (!dimsClose(p.width_in, s.width_in))
    out.push(`width ${p.width_in ?? "?"}≠${s.width_in ?? "?"}`);
  if (!dimsClose(p.height_in, s.height_in))
    out.push(`height ${p.height_in ?? "?"}≠${s.height_in ?? "?"}`);
  if (!dimsClose(p.depth_in, s.depth_in))
    out.push(`depth ${p.depth_in ?? "?"}≠${s.depth_in ?? "?"}`);
  return out;
}

export interface CrossValidationFlag {
  kind: "disagreement" | "missing_in_secondary" | "missing_in_primary";
  tag: string | null;
  detail: string;
}

export interface CrossValidationResult {
  lines: CabinetLineItem[];
  flags: CrossValidationFlag[];
}

export function applyCrossValidation(
  primary: CabinetLineItem[],
  secondary: CabinetLineItem[]
): CrossValidationResult {
  const flags: CrossValidationFlag[] = [];
  const usedSecondary = new Set<number>();

  const lines = primary.map((p) => {
    const idx = secondary.findIndex(
      (s, i) => !usedSecondary.has(i) && sameLine(p, s)
    );
    if (idx === -1) {
      flags.push({
        kind: "missing_in_secondary",
        tag: p.tag,
        detail: "not found by cross-validation model",
      });
      return appendNote(
        { ...p, confidence: Math.min(p.confidence, MISSING_CONFIDENCE) },
        "cross-val: not found by OpenAI"
      );
    }
    usedSecondary.add(idx);
    const diffs = disagreements(p, secondary[idx]);
    if (diffs.length === 0) return p;
    flags.push({
      kind: "disagreement",
      tag: p.tag,
      detail: diffs.join(", "),
    });
    return appendNote(
      { ...p, confidence: Math.min(p.confidence, DISAGREE_CONFIDENCE) },
      `cross-val: OpenAI disagrees (${diffs.join(", ")})`
    );
  });

  secondary.forEach((s, i) => {
    if (usedSecondary.has(i)) return;
    flags.push({
      kind: "missing_in_primary",
      tag: s.tag,
      detail: "found only by cross-validation model",
    });
  });

  return { lines, flags };
}

function appendNote(line: CabinetLineItem, note: string): CabinetLineItem {
  return { ...line, notes: [line.notes, note].filter(Boolean).join("; ") };
}

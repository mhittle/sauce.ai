import {
  CabinetLineItem,
  PricingSnapshot,
  ProductLineConfig,
  ResolvedParams,
} from "@scribe/shared";
import { priceLine } from "./engine.js";

// Maps an extracted CabinetLineItem onto a product line + validated parameters
// (PRD §6.4). Output carries match_confidence and up to 3 alternates; no-match
// items land in the unmatched bucket — never dropped.

export interface LineMatch {
  product_line_id: string;
  resolved: ResolvedParams;
  match_confidence: number;
  alternates: { product_line_id: string; match_confidence: number }[];
}

export interface LineNoMatch {
  product_line_id: null;
  reason: string;
}

export type MatchOutcome = LineMatch | LineNoMatch;

function normalize(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]/g, "");
}

// Simple fuzzy resolution: exact normalized match, then substring containment.
export function resolveOption(
  value: string | null,
  options: string[]
): { resolved: string; exact: boolean } | null {
  if (value == null || value === "") return null;
  const norm = normalize(value);
  for (const opt of options) {
    if (normalize(opt) === norm) return { resolved: opt, exact: true };
  }
  for (const opt of options) {
    const o = normalize(opt);
    if (o.includes(norm) || norm.includes(o)) {
      return { resolved: opt, exact: false };
    }
  }
  return null;
}

const MATERIAL_SYNONYMS: Record<string, string[]> = {
  plam: ["plasticlaminate", "laminate", "hpl"],
  mdf: ["mediumdensityfiberboard"],
  maple: ["hardmaple"],
  oak: ["redoak", "whiteoak"],
};

function resolveMaterial(
  value: string | null,
  options: string[]
): { resolved: string; exact: boolean } | null {
  const direct = resolveOption(value, options);
  if (direct || value == null) return direct;
  const norm = normalize(value);
  for (const [canon, syns] of Object.entries(MATERIAL_SYNONYMS)) {
    if (syns.includes(norm) || canon === norm) {
      const hit = resolveOption(canon, options);
      if (hit) return { resolved: hit.resolved, exact: false };
    }
  }
  return null;
}

function scoreCandidate(
  line: ProductLineConfig,
  item: CabinetLineItem
): { resolved: ResolvedParams; confidence: number } | null {
  if (!line.active) return null;
  if (!line.categories.includes(item.category)) return null;

  const materials = Object.keys(line.material_rates);
  const material = resolveMaterial(item.material, materials);
  // Unspecified material falls back to the first configured material at
  // reduced confidence so the line still prices for review.
  const chosenMaterial = material?.resolved ?? materials[0];
  if (!chosenMaterial) return null;

  let finish: string | null = null;
  let finishExact = true;
  if (item.finish) {
    const f = resolveOption(item.finish, Object.keys(line.finish_adders));
    if (!f) return null;
    finish = f.resolved;
    finishExact = f.exact;
  }

  const resolved: ResolvedParams = {
    product_line_id: line.id,
    qty: item.qty,
    width_in: item.width_in,
    height_in: item.height_in,
    depth_in: item.depth_in,
    material: chosenMaterial,
    finish,
    assembled: item.assembled ?? false,
  };

  let confidence = 0.95;
  if (!material) confidence -= 0.35;
  else if (!material.exact) confidence -= 0.1;
  if (!finishExact) confidence -= 0.1;
  return { resolved, confidence };
}

export function matchLine(
  item: CabinetLineItem,
  snapshot: PricingSnapshot
): MatchOutcome {
  if (item.category === "unknown") {
    return { product_line_id: null, reason: "category could not be determined" };
  }

  const candidates = snapshot.product_lines
    .map((pl) => {
      const scored = scoreCandidate(pl, item);
      return scored ? { line: pl, ...scored } : null;
    })
    .filter((c): c is NonNullable<typeof c> => c != null)
    .sort((a, b) => b.confidence - a.confidence);

  const best = candidates[0];
  if (!best) {
    const categoryCarried = snapshot.product_lines.some(
      (pl) => pl.active && pl.categories.includes(item.category)
    );
    return {
      product_line_id: null,
      reason: categoryCarried
        ? "no product line accepts these dimensions/material/finish"
        : `no active product line carries category "${item.category}"`,
    };
  }

  return {
    product_line_id: best.line.id,
    resolved: best.resolved,
    match_confidence: best.confidence,
    alternates: candidates.slice(1, 4).map((c) => ({
      product_line_id: c.line.id,
      match_confidence: c.confidence,
    })),
  };
}

// A human picked `line` for `item` (the review's unmatched bucket). Resolve
// it the way the matcher would — material/finish snapped to the product's
// options, the first material when none is given — and refuse what pricing
// would refuse, with the reason in words. The category gate is skipped: the
// person choosing the product is the override. (SCR-016)
export function resolveForProductLine(
  item: CabinetLineItem,
  line: ProductLineConfig
): { ok: true; resolved: ResolvedParams } | { ok: false; reason: string } {
  if (!line.active) return { ok: false, reason: `${line.name} is not an active product` };
  const materials = Object.keys(line.material_rates);
  const material = resolveMaterial(item.material, materials)?.resolved ?? materials[0];
  if (!material) return { ok: false, reason: `${line.name} has no materials configured` };
  let finish: string | null = null;
  if (item.finish) {
    const f = resolveOption(item.finish, Object.keys(line.finish_adders));
    if (!f) return { ok: false, reason: `${line.name} has no "${item.finish}" finish` };
    finish = f.resolved;
  }
  const resolved: ResolvedParams = {
    product_line_id: line.id,
    qty: item.qty,
    width_in: item.width_in,
    height_in: item.height_in,
    depth_in: item.depth_in,
    material,
    finish,
    assembled: item.assembled ?? false,
  };
  const outcome = priceLine(line, resolved);
  if (!outcome.ok) return { ok: false, reason: outcome.detail };
  return { ok: true, resolved };
}

// Why a line that carries a product cannot be priced against `snapshot`
// right now, or null when it prices. The review uses this so a line counts
// as fixed exactly when the quote can price it.
export function priceIssue(
  productLineId: string | null,
  resolvedParams: unknown,
  snapshot: PricingSnapshot
): string | null {
  if (!productLineId) return null;
  const pl = snapshot.product_lines.find((p) => p.id === productLineId);
  if (!pl) return `product ${productLineId} is not in the current price list`;
  const parsed = ResolvedParams.safeParse(resolvedParams);
  if (!parsed.success) return "the product's size and material are missing — pick the product again";
  const outcome = priceLine(pl, parsed.data);
  return outcome.ok ? null : outcome.detail;
}

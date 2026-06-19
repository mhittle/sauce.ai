import { DOOR_TIERS, priceFacesByTier, type FaceLike, type TierName } from "./tiers.js";
import { priceBoxes } from "./boxes.js";

// Combined low/mid/high quote pricing (PRD §6.4): cabinet BOXES (validated
// pricing.js formula) + door/drawer-front FACES (Shaker-anchored $/ft² tiers).
// Each tier picks a box wood species roughly matching the door tier so the
// whole quote moves together when the rep changes tier.
//
// Doors-only caveat still applies to the FACES rates (Shaker base + estimated
// upgrades); the BOX side is the validated formula. Drawer boxes + hardware +
// toe-kick are not yet modelled.

const TIER_BOX_SPECIES: Record<TierName, string> = {
  low: "poplar", // paint-grade, matches Shaker base
  medium: "maple",
  high: "cherry",
};

export interface QuoteTierPricing {
  label: string;
  box_count: number;
  box_cents: number;
  door_cents: number;
  front_cents: number;
  total_cents: number;
}

export function priceQuoteTiers(
  lines: (FaceLike & { depth_in?: number | null })[]
): Record<TierName, QuoteTierPricing> {
  const faces = priceFacesByTier(lines);
  const out = {} as Record<TierName, QuoteTierPricing>;
  for (const name of ["low", "medium", "high"] as TierName[]) {
    const boxes = priceBoxes(lines, { species: TIER_BOX_SPECIES[name] });
    out[name] = {
      label: DOOR_TIERS[name].label,
      box_count: boxes.box_count,
      box_cents: boxes.total_cents,
      door_cents: faces[name].door_cents,
      front_cents: faces[name].front_cents,
      total_cents: boxes.total_cents + faces[name].total_cents,
    };
  }
  return out;
}

import type { CabinetLineItem } from "@scribe/shared";

// Baked low/mid/high door & drawer-front price tiers (PRD §6.4). CabinetNow
// prices doors/fronts by the square foot, keyed on style × material; rather
// than ping Airtable per quote, we bake three $/ft² tiers derived from the
// catalog percentiles (style folded in) and let the rep pick one.
//
// Source: `scribe/scripts/airtable-pricing-explore.mjs` (percentiles of
// `Material Master 2021`). Doors = `cabinet door` category, fronts = `solid`.
// Re-run that script and update these numbers if the price book changes.
//
//   low  = p25   mid = p50   high = p90
//   doors  $45.26 / $57.15 / $83.96 per ft²
//   fronts $44.72 / $51.05 / $74.92 per ft²

export type TierName = "low" | "medium" | "high";

export interface DoorTier {
  label: string;
  door_cents_per_sqft: number;
  front_cents_per_sqft: number;
}

export const DOOR_TIERS: Record<TierName, DoorTier> = {
  low: { label: "Value", door_cents_per_sqft: 4526, front_cents_per_sqft: 4472 },
  medium: { label: "Standard", door_cents_per_sqft: 5715, front_cents_per_sqft: 5105 },
  high: { label: "Premium", door_cents_per_sqft: 8396, front_cents_per_sqft: 7492 },
};

export interface TierFacePricing {
  door_sqft: number;
  front_sqft: number;
  door_cents: number;
  front_cents: number;
  total_cents: number;
}

function sqft(line: CabinetLineItem): number {
  if (line.width_in == null || line.height_in == null) return 0;
  return ((line.width_in * line.height_in) / 144) * line.qty;
}

// Price the door + drawer-front faces in a line set against each tier. Boxes /
// hardware are NOT included (doors-only) — this is the door/front subtotal that
// varies by style/material choice. Sums areas first, then applies the rate, so
// rounding happens once per tier.
export function priceFacesByTier(
  lines: CabinetLineItem[]
): Record<TierName, TierFacePricing> {
  let doorSqft = 0;
  let frontSqft = 0;
  for (const line of lines) {
    if (line.category === "door") doorSqft += sqft(line);
    else if (line.category === "drawer_front") frontSqft += sqft(line);
  }

  const out = {} as Record<TierName, TierFacePricing>;
  for (const name of ["low", "medium", "high"] as TierName[]) {
    const t = DOOR_TIERS[name];
    const doorCents = Math.round(doorSqft * t.door_cents_per_sqft);
    const frontCents = Math.round(frontSqft * t.front_cents_per_sqft);
    out[name] = {
      door_sqft: Math.round(doorSqft * 100) / 100,
      front_sqft: Math.round(frontSqft * 100) / 100,
      door_cents: doorCents,
      front_cents: frontCents,
      total_cents: doorCents + frontCents,
    };
  }
  return out;
}

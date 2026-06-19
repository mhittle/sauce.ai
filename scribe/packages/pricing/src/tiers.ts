// Minimal shape the tier pricer needs (CabinetLineItem and the API's DbLine
// both satisfy it structurally).
export interface FaceLike {
  category: string;
  width_in: number | null;
  height_in: number | null;
  qty: number;
}

// Door & drawer-front price tiers (PRD §6.4), priced by the square foot.
//
// Anchored on REAL Shaker 3/4 rates from Airtable `Material Master 2021`
// (Shaker is CabinetNow's most common + cheapest door style — verified live: a
// 15×30 Aries Natural-Birch door is $111.78 = exactly the Airtable $/ft², so
// the Airtable "Price" IS the real per-ft² rate). The BASE tier is the real
// cheapest Shaker (paint-grade); the pricier tiers are ESTIMATED multipliers
// above it, chosen to span the real Shaker material range (paint-grade →
// mid wood → premium painted/taction, ~$23→$86/ft² for doors). Surface a
// disclaimer (DOOR_TIER_DISCLAIMER) so the rep knows base is real and the
// upgrades are estimates.

export type TierName = "low" | "medium" | "high";

// Real cheapest Shaker 3/4 (paint-grade), $/ft² → integer cents. From Airtable.
export const SHAKER_BASE_DOOR_CENTS_PER_SQFT = 2274; // $22.74/ft²
export const SHAKER_BASE_FRONT_CENTS_PER_SQFT = 3310; // $33.10/ft²

// Estimated upgrade multipliers above the Shaker base. low = real Shaker base;
// medium ≈ mid wood (Maple/Cherry Shaker), high ≈ premium painted/taction.
export const TIER_MULTIPLIERS: Record<TierName, number> = {
  low: 1.0,
  medium: 1.6,
  high: 2.5,
};

export const DOOR_TIER_DISCLAIMER =
  "Base (Value) is the real Shaker paint-grade rate; Upgraded/Premium tiers are estimates for nicer door styles and finishes.";

export interface DoorTier {
  label: string;
  door_cents_per_sqft: number;
  front_cents_per_sqft: number;
}

function tier(label: string, mult: number): DoorTier {
  return {
    label,
    door_cents_per_sqft: Math.round(SHAKER_BASE_DOOR_CENTS_PER_SQFT * mult),
    front_cents_per_sqft: Math.round(SHAKER_BASE_FRONT_CENTS_PER_SQFT * mult),
  };
}

export const DOOR_TIERS: Record<TierName, DoorTier> = {
  low: tier("Shaker (base)", TIER_MULTIPLIERS.low),
  medium: tier("Upgraded", TIER_MULTIPLIERS.medium),
  high: tier("Premium", TIER_MULTIPLIERS.high),
};

export interface TierFacePricing {
  door_sqft: number;
  front_sqft: number;
  door_cents: number;
  front_cents: number;
  total_cents: number;
}

function sqft(line: FaceLike): number {
  if (line.width_in == null || line.height_in == null) return 0;
  return ((line.width_in * line.height_in) / 144) * line.qty;
}

// Price the door + drawer-front faces in a line set against each tier. Boxes /
// hardware are NOT included (doors-only) — this is the door/front subtotal that
// varies by style/material choice. Sums areas first, then applies the rate, so
// rounding happens once per tier.
export function priceFacesByTier(
  lines: FaceLike[]
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

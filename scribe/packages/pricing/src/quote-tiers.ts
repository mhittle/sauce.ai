import { DOOR_TIERS, priceFacesByTier, type FaceLike, type TierName } from "./tiers.js";
import { priceBoxes } from "./boxes.js";
import { priceHardware } from "./hardware.js";

// Combined low/mid/high quote pricing (PRD §6.4) = CabinetNow's three lists:
//   1. door/drawer-front FACES (Shaker-anchored $/ft² tiers),
//   2. cabinet BOXES (validated pricing.js formula),
//   3. HARDWARE (dovetail drawer boxes, rolled into one line).
// Each tier picks a box wood species roughly matching the door tier so the
// whole quote moves together when the rep changes tier. Boxes and hardware are
// effectively constant across tiers (they aren't the rep's door-style choice);
// only the FACES move, matching how CabinetNow's real lists behave.
//
// Doors-only caveat still applies to the FACES rates (Shaker base + estimated
// upgrades); the BOX + drawer-box sides are validated formulas. Glides, shelf
// pins, and toe-kick skin are not yet modelled (not formulas in pricing.js).

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
  drawer_box_count: number;
  hardware_cents: number;
  total_cents: number;
}

export function priceQuoteTiers(
  lines: (FaceLike & { depth_in?: number | null })[]
): Record<TierName, QuoteTierPricing> {
  const faces = priceFacesByTier(lines);
  // Hardware (drawer boxes) is constant across tiers — price it once.
  const hardware = priceHardware(lines);
  const out = {} as Record<TierName, QuoteTierPricing>;
  for (const name of ["low", "medium", "high"] as TierName[]) {
    const boxes = priceBoxes(lines, { species: TIER_BOX_SPECIES[name] });
    out[name] = {
      label: DOOR_TIERS[name].label,
      box_count: boxes.box_count,
      box_cents: boxes.total_cents,
      door_cents: faces[name].door_cents,
      front_cents: faces[name].front_cents,
      drawer_box_count: hardware.drawer_box_count,
      hardware_cents: hardware.hardware_cents,
      total_cents:
        boxes.total_cents + faces[name].total_cents + hardware.hardware_cents,
    };
  }
  return out;
}

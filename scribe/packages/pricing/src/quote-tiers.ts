import { DOOR_TIERS, priceFacesByTier, type FaceLike, type TierName } from "./tiers.js";
import { priceBoxes, priceCabinetBoxCents, isCabinetBox } from "./boxes.js";
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

export const TIER_BOX_SPECIES: Record<TierName, string> = {
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

// ── Itemized pricing (for the customer-facing PDF) ────────────────────────────
// priceQuoteTiers gives the three rolled-up tier totals for the selector card.
// The PDF needs the same numbers broken out PER LINE, plus one rolled-up
// hardware row. This is the single source of truth for the itemized quote so
// the visible line items always sum to the subtotal.

export interface QuoteLineItem {
  kind: "box" | "door" | "drawer_front" | "hardware";
  qty: number;
  unit_cents: number;
  total_cents: number;
  // Echoed back so the caller can render a description without re-deriving.
  source?: FaceLike & { depth_in?: number | null };
}

export interface ItemizedQuote {
  tier: TierName;
  tier_label: string;
  items: QuoteLineItem[];
  box_cents: number;
  door_cents: number;
  front_cents: number;
  hardware_cents: number;
  subtotal_cents: number;
}

// Price every read line for one tier and return display rows + subtotal. Boxes
// price per unit (tier species); door/front faces price by ft² (tier rate);
// all drawer boxes collapse into ONE hardware row.
export function priceQuoteLineItems(
  lines: (FaceLike & { depth_in?: number | null })[],
  tier: TierName
): ItemizedQuote {
  const doorTier = DOOR_TIERS[tier];
  const species = TIER_BOX_SPECIES[tier];
  const items: QuoteLineItem[] = [];
  let boxCents = 0;
  let doorCents = 0;
  let frontCents = 0;

  for (const line of lines) {
    if (isCabinetBox(line.category)) {
      const unit = priceCabinetBoxCents(line, { species });
      if (unit == null) continue;
      const total = unit * line.qty;
      boxCents += total;
      items.push({ kind: "box", qty: line.qty, unit_cents: unit, total_cents: total, source: line });
    } else if (line.category === "door" || line.category === "drawer_front") {
      if (line.width_in == null || line.height_in == null) continue;
      const areaPerUnit = (line.width_in * line.height_in) / 144;
      const rate =
        line.category === "door"
          ? doorTier.door_cents_per_sqft
          : doorTier.front_cents_per_sqft;
      const unit = Math.round(areaPerUnit * rate);
      const total = unit * line.qty;
      if (line.category === "door") doorCents += total;
      else frontCents += total;
      items.push({ kind: line.category, qty: line.qty, unit_cents: unit, total_cents: total, source: line });
    }
  }

  const hardware = priceHardware(lines);
  if (hardware.hardware_cents > 0) {
    const unit =
      hardware.drawer_box_count > 0
        ? Math.round(hardware.hardware_cents / hardware.drawer_box_count)
        : hardware.hardware_cents;
    items.push({
      kind: "hardware",
      qty: hardware.drawer_box_count,
      unit_cents: unit,
      total_cents: hardware.hardware_cents,
    });
  }

  const subtotal = boxCents + doorCents + frontCents + hardware.hardware_cents;
  return {
    tier,
    tier_label: doorTier.label,
    items,
    box_cents: boxCents,
    door_cents: doorCents,
    front_cents: frontCents,
    hardware_cents: hardware.hardware_cents,
    subtotal_cents: subtotal,
  };
}

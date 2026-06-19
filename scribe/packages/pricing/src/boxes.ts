import type { FaceLike } from "./tiers.js";

// Approximate CabinetNow cabinet-BOX pricing (PRD §6.4), ported from the live
// store's pricing.js `cabinetBoxes()`. That code computes, per box SKU, a set
// of carcass surface areas (back/deck/ends/toe/tops/shelf, in ft²) and
// face-frame rail lengths (in ft), prices them by wood species, then applies a
// flat ×5 "cnowservice" markup (+$100 for any oversize dimension).
//
// We don't have the per-SKU geometry from a floor-plan estimate, so we
// approximate each cabinet by its family (base / wall / tall / vanity) using
// the dominant SKU formula for that family (BC-BASE / UC-BASE / T-56). This is
// a ROUGH estimate — good enough for a ±10% quote, not a production cut list.

// Per-ft / per-sqft component rates from pricing.js.
const PRICE_STOCK = 3.6; // $/ft² carcass panel
const PRICE_SHELF = 5.07; // $/ft² shelf
const CNOW_SERVICE = 5; // flat retail markup multiplier
const OVERSIZE_ADDER = 100; // any dim > 36"

// Face-frame rail $/ft by species (pricing.js speciesbase table). Default to
// Hickory — the Piestewa quote's material ("Hickory / Pecan Select").
export interface RailRates {
  rail15: number;
  rail15not: number;
  rail15ang: number;
  rail525b: number;
  rail225: number;
}
export const SPECIES_RAILS: Record<string, RailRates> = {
  silver_maple: { rail15: 1.65, rail15not: 1.82, rail15ang: 4.54, rail525b: 5.02, rail225: 2.3 },
  hickory: { rail15: 2.14, rail15not: 2.48, rail15ang: 4.66, rail525b: 5.47, rail225: 2.69 },
  maple: { rail15: 1.88, rail15not: 2.2, rail15ang: 4.71, rail525b: 5.3, rail225: 2.49 },
  poplar: { rail15: 1.36, rail15not: 1.65, rail15ang: 4.06, rail525b: 3.63, rail225: 1.75 },
  red_alder: { rail15: 2.12, rail15not: 2.35, rail15ang: 4.62, rail525b: 6.14, rail225: 2.72 },
  red_oak: { rail15: 1.66, rail15not: 1.96, rail15ang: 4.42, rail525b: 4.69, rail225: 2.18 },
  cherry: { rail15: 2.02, rail15not: 2.35, rail15ang: 4.86, rail525b: 5.94, rail225: 2.66 },
  walnut: { rail15: 2.96, rail15not: 3.35, rail15ang: 5.75, rail525b: 8.39, rail225: 3.85 },
  white_oak: { rail15: 1.96, rail15not: 2.28, rail15ang: 4.42, rail525b: 5.17, rail225: 2.48 },
};
export const DEFAULT_BOX_SPECIES = "hickory";

const BOX_CATEGORIES = ["casework_base", "casework_wall", "casework_tall", "vanity"];

interface Components {
  std_sqft: number;
  shelf_sqft: number;
  rail15: number;
  rail15not: number;
  rail225: number;
}

// BC-BASE family (base cabinets, vanities). Toe-kicked carcass + 1 shelf.
function baseComponents(w: number, h: number, d: number, shelves: number): Components {
  const toe = 4.5;
  const back = ((w - 1) * (h - 0.5)) / 144;
  const deck = ((w - 1) * (d - 0.75)) / 144;
  const end = (h * (d - 0.75)) / 144; // left + right ends are equal
  const toeA = ((w - 1) * toe) / 144;
  const tops = ((w - 1) * 4 * 2) / 144; // two top stretchers
  return {
    std_sqft: back + deck + 2 * end + toeA + tops,
    shelf_sqft: (((w - 1.5) * (d - 1.5)) / 144) * shelves,
    rail15: (2 * (h - 4)) / 12, // two full-height stiles
    rail15not: (2 * (w - 3)) / 12, // top + bottom rail
    rail225: 0,
  };
}

// UC-BASE family (wall cabinets). No toe kick; full-height stiles; a 2.25" top rail.
function wallComponents(w: number, h: number, d: number, shelves: number): Components {
  const back = ((w - 1) * h) / 144;
  const deck = ((w - 1) * (d - 0.75)) / 144;
  const end = (h * (d - 0.75)) / 144;
  const topp = ((w - 1) * (d - 0.75)) / 144;
  return {
    std_sqft: back + deck + 2 * end + topp,
    shelf_sqft: (((w - 1.5) * (d - 1.5)) / 144) * shelves,
    rail15: (2 * h) / 12,
    rail15not: (w - 3) / 12,
    rail225: (w - 3) / 12,
  };
}

// T-56/T-64 family (tall pantry / linen). Toe + fixed shelf + several shelves.
function tallComponents(w: number, h: number, d: number, shelves: number): Components {
  const toe = 4.5;
  const back = ((w - 1) * (h - 0.5)) / 144;
  const deck = ((w - 1) * (d - 0.75)) / 144;
  const end = (h * (d - 0.75)) / 144;
  const toeA = ((w - 1) * toe) / 144;
  const topp = ((w - 1) * (d - 0.75)) / 144;
  const fixshelf = ((w - 1) * (d - 0.75)) / 144;
  return {
    std_sqft: back + deck + 2 * end + toeA + topp + fixshelf,
    shelf_sqft: (((w - 1.5) * (d - 1.5)) / 144) * shelves,
    rail15: (2 * (h - 4)) / 12,
    rail15not: (2 * (w - 3)) / 12,
    rail225: (w - 3) / 12,
  };
}

// True when a cabinet line should be priced as a box (vs a door/front face).
export function isCabinetBox(category: string): boolean {
  return BOX_CATEGORIES.includes(category);
}

export interface BoxPriceOptions {
  species?: string;
}

// Rough per-unit box price in integer cents, or null if the line isn't a box /
// lacks dimensions. Quantity is NOT applied here (caller multiplies).
export function priceCabinetBoxCents(
  line: FaceLike & { width_in: number | null; height_in: number | null; depth_in?: number | null },
  opts: BoxPriceOptions = {}
): number | null {
  if (!isCabinetBox(line.category)) return null;
  const w = line.width_in;
  const h = line.height_in;
  const d = line.depth_in ?? (line.category === "casework_wall" ? 12 : 24);
  if (w == null || h == null || w <= 0 || h <= 0 || d <= 0) return null;

  const c =
    line.category === "casework_wall"
      ? wallComponents(w, h, d, 1)
      : line.category === "casework_tall"
        ? tallComponents(w, h, d, 4)
        : baseComponents(w, h, d, 1); // base + vanity

  const r = SPECIES_RAILS[opts.species ?? DEFAULT_BOX_SPECIES] ?? SPECIES_RAILS[DEFAULT_BOX_SPECIES];

  let price =
    c.std_sqft * PRICE_STOCK +
    c.shelf_sqft * PRICE_SHELF +
    c.rail15 * r.rail15 +
    c.rail15not * r.rail15not +
    c.rail225 * r.rail225;
  price *= CNOW_SERVICE;
  if (w > 36 || h > 36 || d > 36) price += OVERSIZE_ADDER;

  return Math.round(price * 100);
}

export interface BoxPricingSummary {
  box_count: number;
  total_cents: number;
}

// Sum box prices across a line set (boxes only; faces ignored). qty applied.
export function priceBoxes(
  lines: (FaceLike & { depth_in?: number | null })[],
  opts: BoxPriceOptions = {}
): BoxPricingSummary {
  let total = 0;
  let count = 0;
  for (const line of lines) {
    const cents = priceCabinetBoxCents(line, opts);
    if (cents == null) continue;
    total += cents * line.qty;
    count += line.qty;
  }
  return { box_count: count, total_cents: total };
}

#!/usr/bin/env node
// Doors-only back-test of the baked price tiers against the known
// "MidMod - Piestawa Peak" CabinetNow quote (subtotal $27,733.68).
//
// No Airtable call — the tiers are BAKED from the Material Master percentile
// analysis (see airtable-pricing-explore.mjs). Re-run that script to regenerate
// these numbers if the price book changes.
//
// Run:  node scribe/scripts/quote-backtest.mjs

// ---------------------------------------------------------------------------
// THE PRICE TIER DATA STRUCTURE (style folded in = catalog percentiles, $/ft²)
// ---------------------------------------------------------------------------
export const PRICE_TIERS = {
  low: { label: "Value", door_per_sqft: 45.26, front_per_sqft: 44.72 }, // ~p25
  medium: { label: "Standard", door_per_sqft: 57.15, front_per_sqft: 51.05 }, // ~p50
  high: { label: "Premium", door_per_sqft: 83.96, front_per_sqft: 74.92 }, // ~p90
};

// ---------------------------------------------------------------------------
// The quote's Door & Drawer List (Style/Category, W", H", qty) — the KNOWN
// line items, so this tests pricing in isolation from floor-plan reading.
// kind: "door" | "front"
// ---------------------------------------------------------------------------
const QUOTE_FACES = [
  ["door", 16.3125, 18.25, 2], ["front", 6.5, 4.75, 2], ["front", 16.25, 4.75, 1],
  ["door", 16.3125, 18.25, 2], ["front", 6.5, 4.75, 2], ["front", 16.25, 4.75, 1],
  ["door", 8.5, 20.75, 2], ["door", 8.75, 38, 1], ["door", 18.25, 20.75, 1],
  ["door", 16.3125, 20.75, 2], ["door", 20, 38, 2], ["door", 20.4375, 20.75, 1],
  ["door", 10.3125, 27.25, 2], ["door", 10.8125, 27.25, 6], ["door", 12.3125, 43.125, 8],
  ["door", 10.375, 27.25, 2], ["door", 10.375, 38, 2],
  ["front", 34, 9.5, 4], ["front", 34, 4.75, 2], ["front", 18.25, 4.75, 1],
  ["front", 32.75, 4.75, 1], ["front", 20.4375, 4.75, 1], ["front", 22.375, 8.125, 1],
  ["door", 7.75, 20.75, 1], ["door", 20.25, 57.75, 2], ["door", 20.25, 28.5, 2],
  ["door", 16.3125, 8, 2], ["door", 14.875, 32, 4],
  ["front", 7.75, 4.75, 1], ["front", 8.5, 4.75, 2],
  ["door", 19.3125, 43.125, 4], ["door", 17.9375, 18.25, 4],
  ["front", 15.75, 4.75, 2], ["front", 8.375, 4.75, 4],
];

const QUOTE_SUBTOTAL = 27733.68; // includes boxes + drawer boxes + hardware (NOT priced here)

function sqft(w, h, qty) {
  return ((w * h) / 144) * qty;
}

function main() {
  let doorSqft = 0;
  let frontSqft = 0;
  let doorCount = 0;
  let frontCount = 0;
  for (const [kind, w, h, qty] of QUOTE_FACES) {
    if (kind === "door") {
      doorSqft += sqft(w, h, qty);
      doorCount += qty;
    } else {
      frontSqft += sqft(w, h, qty);
      frontCount += qty;
    }
  }

  console.log("=== Quote door/front faces (doors-only price scope) ===");
  console.log(`  doors:  ${doorCount} pcs, ${doorSqft.toFixed(1)} ft²`);
  console.log(`  fronts: ${frontCount} pcs, ${frontSqft.toFixed(1)} ft²`);
  console.log(`  total face area: ${(doorSqft + frontSqft).toFixed(1)} ft²`);
  console.log(`\n=== Door/front $ at each tier (vs full quote subtotal $${QUOTE_SUBTOTAL.toLocaleString()}) ===`);

  for (const key of ["low", "medium", "high"]) {
    const t = PRICE_TIERS[key];
    const doors$ = doorSqft * t.door_per_sqft;
    const fronts$ = frontSqft * t.front_per_sqft;
    const total = doors$ + fronts$;
    const pct = (total / QUOTE_SUBTOTAL) * 100;
    console.log(
      `  ${key.toUpperCase().padEnd(7)} (${t.label.padEnd(8)} door $${t.door_per_sqft}/front $${t.front_per_sqft}):  ` +
        `doors $${doors$.toFixed(0)} + fronts $${fronts$.toFixed(0)} = $${total.toFixed(0)}  ` +
        `(${pct.toFixed(0)}% of subtotal)`
    );
  }
  console.log(
    "\nNote: boxes + drawer boxes + hardware are NOT priced here (doors-only)," +
      "\nso these totals should be a FRACTION of the subtotal — the % tells us how" +
      "\nmuch of a CabinetNow order is doors/fronts, and which tier this quote used."
  );
}

main();

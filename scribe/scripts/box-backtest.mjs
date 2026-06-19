#!/usr/bin/env node
// Back-test the approximate cabinet-BOX pricing against the MidMod / Piestawa
// quote's actual Cabinet Boxes list (subtotal $27,733.68). Boxes only.
//
// Run: node scripts/box-backtest.mjs

import { priceCabinetBoxCents } from "../packages/pricing/dist/boxes.js";
import { priceQuoteTiers } from "../packages/pricing/dist/quote-tiers.js";

// The quote's Cabinet Boxes list: [label, category, W, H, D, qty]
const BOXES = [
  ["Base Drawer Over Door 11.75", "casework_base", 11.75, 34.5, 24, 2],
  ["Easy Reach Corner Base 36", "casework_base", 36, 34.5, 24, 1],
  ["Wall 12", "casework_wall", 12, 42, 12, 1],
  ["Easy Reach Corner Wall 24", "casework_wall", 24, 42, 12, 1],
  ["Base 3 Drawers 37.25", "casework_base", 37.25, 34.5, 24, 2],
  ["Oven Base 30", "casework_base", 30, 34.5, 24, 1],
  ["Trash Base 21.5", "casework_base", 21.5, 34.5, 24, 1],
  ["Sink Base 36", "casework_base", 36, 34.5, 24, 1],
  ["Base Filler 3", "casework_base", 3, 34.5, 24, 1],
  ["Wall 45", "casework_wall", 45, 42, 12, 1],
  ["Left Blind Corner Base 49.375", "casework_base", 49.375, 34.5, 24, 1],
  ["Microwave Over Drawer Base 25.625", "casework_base", 25.625, 34.5, 24, 1],
  ["Base Full Height 24", "casework_base", 24, 34.5, 10.5, 1],
  ["Base Full Height 25", "casework_base", 25, 34.5, 12, 3],
  ["Base End Panel 1.5", "casework_base", 1.5, 34.5, 24, 1],
  ["Tall Pantry 28", "casework_tall", 28, 96, 18, 2],
  ["Base Drawer Over Door 11", "casework_base", 11, 34.5, 24, 1],
  ["Tall Pantry 4 Doors 45.5", "casework_tall", 45.5, 96, 24, 1],
  ["Deep Wall 36", "casework_wall", 36, 12, 24, 1],
  ["Wall 4 Doors 68", "casework_wall", 68, 36, 15, 1],
  ["Tall Linen 42", "casework_tall", 42, 96, 16, 1],
  ["Double Sink Vanity 77", "vanity", 77, 28, 21, 1],
  ["Vanity 2 Drawers 36 (#51)", "vanity", 36, 28, 21, 1],
  ["Vanity 2 Drawers 36 (#52)", "vanity", 36, 28, 21, 1],
];

const QUOTE_SUBTOTAL = 27733.68;

let total = 0;
let units = 0;
console.log("Box                                   qty   each      ext");
for (const [label, cat, w, h, d, qty] of BOXES) {
  const cents = priceCabinetBoxCents({ category: cat, width_in: w, height_in: h, depth_in: d, qty });
  const ext = (cents * qty) / 100;
  total += ext;
  units += qty;
  console.log(
    `${label.padEnd(36)} x${qty}  $${(cents / 100).toFixed(2).padStart(8)}  $${ext.toFixed(2).padStart(9)}`
  );
}
console.log("-".repeat(64));
console.log(`BOX SUBTOTAL (approx): $${total.toFixed(2)}  (${units} units)`);
console.log(`Quote full subtotal:   $${QUOTE_SUBTOTAL.toFixed(2)}  (boxes + doors/fronts + drawer-boxes/hardware)`);
console.log(`Boxes are ~${((total / QUOTE_SUBTOTAL) * 100).toFixed(0)}% of the full subtotal (Hickory).`);

// Full quote-tier estimate: boxes (per-tier species) + doors/fronts (Shaker
// tiers). The quote's door list ≈ 161.6 ft² doors + 19.7 ft² fronts; feed that
// area as synthetic face lines (1 ft² each × qty).
const faceLines = [
  { category: "door", width_in: 12, height_in: 12, qty: 161.6 },
  { category: "drawer_front", width_in: 12, height_in: 12, qty: 19.7 },
];
const boxLines = BOXES.map(([, cat, w, h, d, qty]) => ({
  category: cat,
  width_in: w,
  height_in: h,
  depth_in: d,
  qty,
}));
const tiers = priceQuoteTiers([...boxLines, ...faceLines]);
console.log("\n=== FULL QUOTE-TIER ESTIMATE (boxes + doors/fronts) vs $27,733.68 ===");
for (const t of ["low", "medium", "high"]) {
  const q = tiers[t];
  const tot = q.total_cents / 100;
  const delta = ((tot - QUOTE_SUBTOTAL) / QUOTE_SUBTOTAL) * 100;
  console.log(
    `  ${t.toUpperCase().padEnd(7)} boxes $${(q.box_cents / 100).toFixed(0)} + doors/fronts $${((q.door_cents + q.front_cents) / 100).toFixed(0)} = $${tot.toFixed(0)}  (${delta >= 0 ? "+" : ""}${delta.toFixed(0)}% vs quote)`
  );
}

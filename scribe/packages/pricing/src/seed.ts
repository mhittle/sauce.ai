import { PricingSnapshot, ProductLineConfig } from "@scribe/shared";

// Seed product lines (PRD §6.4). Every rate ships with needs_review: true —
// the quote builder blocks "sent" while any line prices against one of these
// placeholders. The admin must enter real rates before the first external
// quote (PRD §12).

const NR = { needs_review: true };

function pl(input: ProductLineConfig): ProductLineConfig {
  return input;
}

export const SEED_PRODUCT_LINES: ProductLineConfig[] = [
  pl({
    id: "doors",
    name: "Cabinet Doors",
    categories: ["door"],
    size_measure: "sqft",
    material_rates: {
      maple: { rate_cents: 3500, ...NR },
      oak: { rate_cents: 3200, ...NR },
      mdf: { rate_cents: 2200, ...NR },
      cherry: { rate_cents: 4200, ...NR },
    },
    finish_adders: {
      unfinished: { kind: "flat", cents: 0 },
      clear: { kind: "pct", pct: 25 },
      painted: { kind: "pct", pct: 40 },
      stained: { kind: "pct", pct: 35 },
    },
    assembly_adder: null,
    dim_bounds: {
      width: { min_in: 5, max_in: 48, increment_in: null },
      height: { min_in: 5, max_in: 96, increment_in: null },
      depth: null,
    },
    lead_time_days: 28,
    active: true,
  }),
  pl({
    id: "drawer-fronts",
    name: "Drawer Fronts",
    categories: ["drawer_front"],
    size_measure: "sqft",
    material_rates: {
      maple: { rate_cents: 3500, ...NR },
      oak: { rate_cents: 3200, ...NR },
      mdf: { rate_cents: 2200, ...NR },
    },
    finish_adders: {
      unfinished: { kind: "flat", cents: 0 },
      clear: { kind: "pct", pct: 25 },
      painted: { kind: "pct", pct: 40 },
      stained: { kind: "pct", pct: 35 },
    },
    assembly_adder: null,
    dim_bounds: {
      width: { min_in: 5, max_in: 48, increment_in: null },
      height: { min_in: 4, max_in: 24, increment_in: null },
      depth: null,
    },
    lead_time_days: 28,
    active: true,
  }),
  pl({
    id: "drawer-boxes",
    name: "Drawer Boxes",
    categories: ["drawer_box"],
    size_measure: "unit",
    material_rates: {
      baltic_birch: { rate_cents: 6500, ...NR },
      maple: { rate_cents: 9500, ...NR },
    },
    finish_adders: {
      unfinished: { kind: "flat", cents: 0 },
      clear: { kind: "flat", cents: 1500 },
    },
    assembly_adder: { kind: "flat", cents: 1200 },
    dim_bounds: {
      width: { min_in: 4, max_in: 42, increment_in: null },
      height: { min_in: 2, max_in: 14, increment_in: null },
      depth: { min_in: 8, max_in: 30, increment_in: null },
    },
    lead_time_days: 10,
    active: true,
  }),
  pl({
    id: "framed-casework",
    name: "Framed Casework",
    categories: ["casework_base", "casework_wall", "casework_tall", "vanity"],
    size_measure: "lf",
    material_rates: {
      maple: { rate_cents: 28000, ...NR },
      oak: { rate_cents: 26000, ...NR },
      plam: { rate_cents: 19000, ...NR },
      mdf: { rate_cents: 17000, ...NR },
    },
    finish_adders: {
      unfinished: { kind: "flat", cents: 0 },
      clear: { kind: "pct", pct: 15 },
      painted: { kind: "pct", pct: 30 },
      stained: { kind: "pct", pct: 25 },
    },
    assembly_adder: { kind: "pct", pct: 20 },
    dim_bounds: {
      width: { min_in: 9, max_in: 48, increment_in: null },
      height: { min_in: 10, max_in: 96, increment_in: null },
      depth: { min_in: 4, max_in: 30, increment_in: null },
    },
    lead_time_days: 1,
    active: true,
  }),
  pl({
    id: "frameless-casework",
    name: "Frameless Casework",
    categories: ["casework_base", "casework_wall", "casework_tall", "vanity"],
    size_measure: "lf",
    material_rates: {
      melamine: { rate_cents: 16000, ...NR },
      plam: { rate_cents: 18000, ...NR },
      maple: { rate_cents: 26000, ...NR },
    },
    finish_adders: {
      unfinished: { kind: "flat", cents: 0 },
      painted: { kind: "pct", pct: 30 },
    },
    assembly_adder: { kind: "pct", pct: 20 },
    dim_bounds: {
      width: { min_in: 9, max_in: 48, increment_in: null },
      height: { min_in: 10, max_in: 96, increment_in: null },
      depth: { min_in: 4, max_in: 30, increment_in: null },
    },
    lead_time_days: 7,
    active: true,
  }),
  pl({
    id: "closet-parts",
    name: "Closet Parts",
    categories: ["closet", "panel", "filler", "trim"],
    size_measure: "sqft",
    material_rates: {
      melamine: { rate_cents: 1400, ...NR },
      plam: { rate_cents: 1800, ...NR },
    },
    finish_adders: {
      unfinished: { kind: "flat", cents: 0 },
    },
    assembly_adder: null,
    dim_bounds: {
      width: { min_in: 1, max_in: 96, increment_in: null },
      height: { min_in: 1, max_in: 96, increment_in: null },
      depth: null,
    },
    lead_time_days: 7,
    active: true,
  }),
];

export const SEED_PRICING_SNAPSHOT: PricingSnapshot = {
  version: 1,
  product_lines: SEED_PRODUCT_LINES,
};

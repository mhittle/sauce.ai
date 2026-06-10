import { describe, expect, it } from "vitest";
import type { ProductLineConfig, ResolvedParams } from "@scribe/shared";
import { priceLine, priceQuote, type LinePriceResult } from "../src/engine.js";

const framed: ProductLineConfig = {
  id: "framed",
  name: "Framed Casework",
  categories: ["casework_base", "casework_wall"],
  size_measure: "lf",
  material_rates: {
    maple: { rate_cents: 30000, needs_review: false },
    plam: { rate_cents: 20000, needs_review: true },
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
  lead_time_days: 1,
  active: true,
};

const doors: ProductLineConfig = {
  id: "doors",
  name: "Doors",
  categories: ["door"],
  size_measure: "sqft",
  material_rates: { maple: { rate_cents: 3600, needs_review: false } },
  finish_adders: { painted: { kind: "flat", cents: 1000 } },
  assembly_adder: null,
  dim_bounds: { width: null, height: null, depth: null },
  lead_time_days: 28,
  active: true,
};

function params(p: Partial<ResolvedParams>): ResolvedParams {
  return {
    product_line_id: "framed",
    qty: 1,
    width_in: 24,
    height_in: 34.5,
    depth_in: 24,
    material: "maple",
    finish: null,
    assembled: false,
    ...p,
  };
}

describe("priceLine", () => {
  it("prices linear-foot lines: rate × width/12", () => {
    // B24 maple: 2 LF × $300/LF = $600
    const r = priceLine(framed, params({}));
    expect(r.ok && r.total_cents).toBe(60000);
  });

  it("applies percentage finish adder on the base only", () => {
    // $600 base + 30% painted = $780
    const r = priceLine(framed, params({ finish: "painted" }));
    expect(r.ok && r.total_cents).toBe(78000);
  });

  it("applies assembly adder when assembled", () => {
    // $600 + 20% assembly = $720
    const r = priceLine(framed, params({ assembled: true }));
    expect(r.ok && r.total_cents).toBe(72000);
  });

  it("stacks finish and assembly adders on the base rate", () => {
    // $600 + 30% + 20% = $900
    const r = priceLine(framed, params({ finish: "painted", assembled: true }));
    expect(r.ok && r.total_cents).toBe(90000);
  });

  it("multiplies by qty", () => {
    const r = priceLine(framed, params({ qty: 24 }));
    expect(r.ok && r.total_cents).toBe(60000 * 24);
  });

  it("prices square-foot lines: rate × (w×h)/144", () => {
    // 24×30 door = 5 sqft × $36 = $180, + $10 flat painted = $190
    const r = priceLine(doors, {
      ...params({}),
      product_line_id: "doors",
      width_in: 24,
      height_in: 30,
      finish: "painted",
    });
    expect(r.ok && r.total_cents).toBe(19000);
  });

  it("flags needs_review rates", () => {
    const r = priceLine(framed, params({ material: "plam" }));
    expect(r.ok && r.needs_review).toBe(true);
  });

  it("rejects out-of-bounds dims", () => {
    const r = priceLine(framed, params({ width_in: 60 }));
    expect(r.ok).toBe(false);
    expect(!r.ok && r.reason).toBe("out_of_bounds");
  });

  it("rejects unknown material and finish", () => {
    expect(priceLine(framed, params({ material: "unobtanium" })).ok).toBe(false);
    expect(priceLine(framed, params({ finish: "chrome" })).ok).toBe(false);
  });

  it("rejects missing dims required by the size measure", () => {
    const r = priceLine(doors, {
      ...params({}),
      product_line_id: "doors",
      height_in: null,
    });
    expect(!r.ok && r.reason).toBe("missing_dimension");
  });

  it("rejects inactive product lines", () => {
    const r = priceLine({ ...framed, active: false }, params({}));
    expect(!r.ok && r.reason).toBe("inactive_product_line");
  });

  it("is deterministic for identical inputs", () => {
    const a = priceLine(framed, params({ finish: "painted", qty: 7 }));
    const b = priceLine(framed, params({ finish: "painted", qty: 7 }));
    expect(a).toEqual(b);
  });
});

function lp(total: number, lead: number, review = false): LinePriceResult {
  return {
    ok: true,
    unit_cents: total,
    total_cents: total,
    needs_review: review,
    lead_time_days: lead,
    size_value: 1,
  };
}

describe("priceQuote", () => {
  it("computes subtotal × (1 + markup) + handling + freight", () => {
    const t = priceQuote([lp(100000, 1), lp(50000, 1)], {
      markup_pct: 10,
      handling_cents: 5000,
      freight_cents: 70000,
    });
    expect(t.subtotal_cents).toBe(150000);
    expect(t.markup_cents).toBe(15000);
    expect(t.total_cents).toBe(150000 + 15000 + 5000 + 70000);
  });

  it("supports negative markup (manual discount)", () => {
    const t = priceQuote([lp(100000, 1)], {
      markup_pct: -5,
      handling_cents: 0,
      freight_cents: 0,
    });
    expect(t.total_cents).toBe(95000);
  });

  it("surfaces max lead time and mixed-lead-time flag", () => {
    const t = priceQuote([lp(1, 1), lp(1, 28)], {
      markup_pct: 0,
      handling_cents: 0,
      freight_cents: 0,
    });
    expect(t.max_lead_time_days).toBe(28);
    expect(t.mixed_lead_times).toBe(true);
  });

  it("propagates needs_review", () => {
    const t = priceQuote([lp(1, 1), lp(1, 1, true)], {
      markup_pct: 0,
      handling_cents: 0,
      freight_cents: 0,
    });
    expect(t.any_needs_review).toBe(true);
  });
});

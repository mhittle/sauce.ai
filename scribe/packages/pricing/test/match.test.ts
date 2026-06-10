import { describe, expect, it } from "vitest";
import type { CabinetLineItem } from "@scribe/shared";
import { matchLine, resolveOption } from "../src/match.js";
import { SEED_PRICING_SNAPSHOT } from "../src/seed.js";

function item(p: Partial<CabinetLineItem>): CabinetLineItem {
  return {
    source_page: 1,
    tag: "B24",
    room: "Kitchen",
    qty: 1,
    category: "casework_base",
    width_in: 24,
    height_in: 34.5,
    depth_in: 24,
    door_style: null,
    material: "maple",
    finish: "painted",
    assembled: false,
    notes: null,
    confidence: 0.95,
    ...p,
  };
}

describe("resolveOption", () => {
  it("matches exactly ignoring case/punctuation", () => {
    expect(resolveOption("Painted", ["painted", "clear"])).toEqual({
      resolved: "painted",
      exact: true,
    });
  });
  it("matches by containment", () => {
    expect(resolveOption("painted white", ["painted"])?.resolved).toBe(
      "painted"
    );
  });
  it("returns null for no match", () => {
    expect(resolveOption("chrome", ["painted"])).toBeNull();
  });
});

describe("matchLine against seed config", () => {
  it("matches a base cabinet to a casework line", () => {
    const m = matchLine(item({}), SEED_PRICING_SNAPSHOT);
    expect("resolved" in m && m.product_line_id).toBeTruthy();
    if ("resolved" in m) {
      expect(m.resolved.material).toBe("maple");
      expect(m.match_confidence).toBeGreaterThan(0.8);
    }
  });

  it("offers alternates when several lines fit", () => {
    const m = matchLine(item({ material: "plam" }), SEED_PRICING_SNAPSHOT);
    expect("alternates" in m && m.alternates.length).toBeGreaterThan(0);
  });

  it("resolves material synonyms (PLAM → plastic laminate family)", () => {
    const m = matchLine(
      item({ material: "Plastic Laminate" }),
      SEED_PRICING_SNAPSHOT
    );
    expect("resolved" in m && m.resolved.material).toBe("plam");
  });

  it("buckets countertops as unmatched (non-carried)", () => {
    const m = matchLine(item({ category: "countertop" }), SEED_PRICING_SNAPSHOT);
    expect(m.product_line_id).toBeNull();
    if (!("resolved" in m)) expect(m.reason).toContain("countertop");
  });

  it("buckets out-of-bounds dims as unmatched", () => {
    const m = matchLine(item({ width_in: 200 }), SEED_PRICING_SNAPSHOT);
    expect(m.product_line_id).toBeNull();
  });

  it("buckets unknown category as unmatched", () => {
    const m = matchLine(item({ category: "unknown" }), SEED_PRICING_SNAPSHOT);
    expect(m.product_line_id).toBeNull();
  });

  it("falls back to first material at reduced confidence when unspecified", () => {
    const m = matchLine(item({ material: null }), SEED_PRICING_SNAPSHOT);
    expect("resolved" in m).toBe(true);
    if ("resolved" in m) expect(m.match_confidence).toBeLessThan(0.8);
  });
});

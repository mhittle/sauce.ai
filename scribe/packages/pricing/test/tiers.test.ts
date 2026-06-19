import { describe, expect, it } from "vitest";
import { DOOR_TIERS, priceFacesByTier } from "../src/tiers.js";
import type { CabinetLineItem } from "@scribe/shared";

function face(
  category: CabinetLineItem["category"],
  w: number,
  h: number,
  qty: number
): CabinetLineItem {
  return {
    source_page: 1,
    tag: null,
    room: null,
    qty,
    category,
    width_in: w,
    height_in: h,
    depth_in: 0.75,
    door_style: null,
    material: null,
    finish: null,
    assembled: null,
    notes: null,
    confidence: 0.4,
    estimated: true,
  };
}

describe("priceFacesByTier", () => {
  it("prices doors at the tier rate × area", () => {
    // one 24x30 door = 5 ft²
    const out = priceFacesByTier([face("door", 24, 30, 1)]);
    expect(out.medium.door_sqft).toBe(5);
    expect(out.medium.door_cents).toBe(Math.round(5 * DOOR_TIERS.medium.door_cents_per_sqft));
    expect(out.low.total_cents).toBeLessThan(out.medium.total_cents);
    expect(out.medium.total_cents).toBeLessThan(out.high.total_cents);
  });

  it("separates door and drawer-front area + rates", () => {
    const out = priceFacesByTier([
      face("door", 24, 30, 2), // 10 ft²
      face("drawer_front", 24, 6, 3), // 3 ft²
    ]);
    expect(out.medium.door_sqft).toBe(10);
    expect(out.medium.front_sqft).toBe(3);
    expect(out.medium.total_cents).toBe(
      out.medium.door_cents + out.medium.front_cents
    );
  });

  it("ignores cabinet boxes and non-face lines", () => {
    const out = priceFacesByTier([
      face("casework_base", 36, 34.5, 1),
      face("countertop", 100, 25, 1),
    ]);
    expect(out.medium.total_cents).toBe(0);
  });

  it("skips faces missing dimensions", () => {
    const noDim = face("door", 24, 30, 1);
    noDim.width_in = null;
    expect(priceFacesByTier([noDim]).medium.total_cents).toBe(0);
  });
});

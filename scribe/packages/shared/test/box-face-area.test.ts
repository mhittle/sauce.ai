import { describe, expect, it } from "vitest";
import { boxFaceArea } from "../src/index.js";
import type { CabinetLineItem } from "../src/schemas.js";

function line(over: Partial<CabinetLineItem> = {}): CabinetLineItem {
  return {
    source_page: 1,
    tag: "Base 24",
    room: "Kitchen",
    qty: 1,
    category: "casework_base",
    width_in: 24,
    height_in: 30,
    depth_in: 24,
    door_style: null,
    material: null,
    finish: null,
    assembled: null,
    notes: null,
    confidence: 0.4,
    estimated: true,
    ...over,
  };
}

describe("boxFaceArea", () => {
  it("sums width*height over box lines", () => {
    const lines = [
      line({ width_in: 24, height_in: 30 }), // 720
      line({ width_in: 36, height_in: 30, category: "casework_wall" }), // 1080
    ];
    expect(boxFaceArea(lines)).toBe(1800);
  });

  it("multiplies by qty", () => {
    expect(boxFaceArea([line({ width_in: 10, height_in: 10, qty: 3 })])).toBe(300);
  });

  it("ignores face lines (doors/drawer fronts) and non-box categories", () => {
    const lines = [
      line({ width_in: 24, height_in: 30 }), // 720, counted
      line({ category: "door", width_in: 12, height_in: 30 }), // skipped
      line({ category: "drawer_front", width_in: 24, height_in: 6 }), // skipped
    ];
    expect(boxFaceArea(lines)).toBe(720);
  });

  it("skips lines missing dimensions", () => {
    const lines = [
      line({ width_in: null, height_in: 30 }),
      line({ width_in: 24, height_in: null }),
      line({ width_in: 24, height_in: 30 }), // 720
    ];
    expect(boxFaceArea(lines)).toBe(720);
  });

  it("distinguishes same-count reads of different size (the Q8 case)", () => {
    // Two reads, both 2 boxes, but one is materially larger.
    const small = [line({ width_in: 18, height_in: 30 }), line({ width_in: 18, height_in: 30 })];
    const large = [line({ width_in: 36, height_in: 34.5 }), line({ width_in: 36, height_in: 34.5 })];
    expect(boxFaceArea(large)).toBeGreaterThan(boxFaceArea(small));
  });

  it("is 0 for an empty list", () => {
    expect(boxFaceArea([])).toBe(0);
  });
});

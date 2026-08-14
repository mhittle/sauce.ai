import { describe, expect, it } from "vitest";
import { carcassSqft } from "../src/boxes.js";
import {
  MATERIAL_WASTE_PCT,
  materialStats,
  SHEET_AREA_SQFT,
} from "../src/materials.js";

function line(
  category: string,
  w: number | null,
  h: number | null,
  d: number | null,
  qty = 1,
  tag: string | null = null
) {
  return { category, tag, notes: null, qty, width_in: w, height_in: h, depth_in: d };
}

describe("materialStats", () => {
  it("sums carcass area via the box family formulas and estimates sheets", () => {
    const base = line("casework_base", 30, 34.5, 24);
    const wall = line("casework_wall", 30, 30, 12, 2);
    const stats = materialStats([base, wall]);

    const expected =
      carcassSqft(base)! + carcassSqft(wall)! * 2;
    expect(stats.box_count).toBe(3);
    expect(stats.carcass_sqft).toBeCloseTo(expected, 1);
    expect(stats.carcass_sheets).toBe(
      Math.ceil((expected * (1 + MATERIAL_WASTE_PCT / 100)) / SHEET_AREA_SQFT)
    );
  });

  it("counts doors and drawer fronts with their face area", () => {
    const stats = materialStats([
      line("door", 15, 30, 0.75, 2),
      line("drawer_front", 30, 6, 0.75, 3),
    ]);
    expect(stats.door_count).toBe(2);
    expect(stats.door_sqft).toBeCloseTo((15 * 30 * 2) / 144, 1);
    expect(stats.drawer_front_count).toBe(3);
    expect(stats.front_sqft).toBeCloseTo((30 * 6 * 3) / 144, 1);
    expect(stats.face_sheets).toBe(1);
    expect(stats.box_count).toBe(0);
  });

  it("excludes fillers/trim mislabeled as boxes", () => {
    const stats = materialStats([
      line("casework_base", 3, 34.5, 24, 1, "filler 3in"),
    ]);
    expect(stats.box_count).toBe(0);
    expect(stats.carcass_sqft).toBe(0);
  });

  it("reports boxes skipped for missing dimensions", () => {
    const stats = materialStats([line("casework_base", null, null, null, 2)]);
    expect(stats.box_count).toBe(0);
    expect(stats.skipped_no_dims).toBe(2);
  });
});

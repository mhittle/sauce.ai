import { describe, expect, it } from "vitest";
import { isCabinetBox, priceBoxes, priceCabinetBoxCents } from "../src/boxes.js";
import { priceQuoteTiers } from "../src/quote-tiers.js";

function box(category: string, w: number, h: number, d: number, qty = 1) {
  return { category, width_in: w, height_in: h, depth_in: d, qty };
}

describe("priceCabinetBoxCents", () => {
  it("matches the live site for a 36x34x24 Red Oak base box (~$734.83)", () => {
    const cents = priceCabinetBoxCents(box("casework_base", 36, 34, 24), {
      species: "red_oak",
    });
    // Live site shows $734.83; our port computes ~$732.65 (0.3%).
    expect(cents).not.toBeNull();
    expect(Math.abs((cents as number) - 73483)).toBeLessThan(500);
  });

  it("adds the $100 oversize adder past 36 inches", () => {
    const normal = priceCabinetBoxCents(box("casework_base", 36, 34, 24))!;
    const wide = priceCabinetBoxCents(box("casework_base", 42, 34, 24))!;
    // wider box + oversize adder → clearly more
    expect(wide).toBeGreaterThan(normal + 10000);
  });

  it("returns null for non-box categories", () => {
    expect(priceCabinetBoxCents(box("door", 15, 30, 0.75))).toBeNull();
    expect(priceCabinetBoxCents(box("drawer_front", 24, 6, 0.75))).toBeNull();
  });

  it("isCabinetBox identifies box families", () => {
    expect(isCabinetBox("casework_base")).toBe(true);
    expect(isCabinetBox("vanity")).toBe(true);
    expect(isCabinetBox("door")).toBe(false);
  });
});

describe("priceBoxes", () => {
  it("sums boxes by qty and ignores faces", () => {
    const s = priceBoxes([
      box("casework_base", 36, 34, 24, 2),
      box("door", 15, 30, 0.75, 4),
    ]);
    expect(s.box_count).toBe(2);
    const one = priceCabinetBoxCents(box("casework_base", 36, 34, 24))!;
    expect(s.total_cents).toBe(one * 2);
  });
});

describe("priceQuoteTiers", () => {
  it("combines boxes + door faces and increases by tier", () => {
    const lines = [
      box("casework_base", 36, 34.5, 24, 1),
      { category: "door", width_in: 15, height_in: 30, depth_in: 0.75, qty: 2 },
      { category: "drawer_front", width_in: 24, height_in: 6, depth_in: 0.75, qty: 3 },
    ];
    const t = priceQuoteTiers(lines);
    expect(t.low.total_cents).toBe(
      t.low.box_cents + t.low.door_cents + t.low.front_cents + t.low.hardware_cents
    );
    expect(t.low.total_cents).toBeLessThan(t.medium.total_cents);
    expect(t.medium.total_cents).toBeLessThan(t.high.total_cents);
    expect(t.low.box_count).toBe(1);
  });
});

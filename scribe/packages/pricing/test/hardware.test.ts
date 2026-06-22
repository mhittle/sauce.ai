import { describe, expect, it } from "vitest";
import { priceDrawerBoxCents, priceHardware } from "../src/hardware.js";
import { priceQuoteTiers } from "../src/quote-tiers.js";

describe("priceDrawerBoxCents", () => {
  it("matches the pricing.js drawerBoxes() formula for a standard box", () => {
    // 21"w drawer front, 5" tall (two_tier), default 21" depth, birch.
    // perimeter = 2*21 + 2*21 = 84; two_tier = 84*0.59 + 18.45 = 68.01
    // price = (68.01 * 1.02813 + 10.06) * 1.5 = ($69.92 + 10.06) * 1.5 ≈ 119.97
    const cents = priceDrawerBoxCents(21, 5)!;
    expect(cents).not.toBeNull();
    expect(Math.abs(cents - 11997)).toBeLessThan(50);
  });

  it("picks a taller (pricier) tier as front height grows", () => {
    const short = priceDrawerBoxCents(21, 4)!; // one_tier
    const tall = priceDrawerBoxCents(21, 12)!; // five_tier
    expect(tall).toBeGreaterThan(short);
  });

  it("returns null for non-positive dimensions", () => {
    expect(priceDrawerBoxCents(0, 5)).toBeNull();
    expect(priceDrawerBoxCents(21, 0)).toBeNull();
  });
});

describe("priceHardware", () => {
  it("makes one drawer box per drawer front and ignores doors/boxes", () => {
    const lines = [
      { category: "drawer_front", width_in: 21, height_in: 5, qty: 3 },
      { category: "door", width_in: 15, height_in: 30, qty: 2 },
      { category: "casework_base", width_in: 36, height_in: 34.5, qty: 1 },
    ];
    const h = priceHardware(lines);
    expect(h.drawer_box_count).toBe(3);
    const one = priceDrawerBoxCents(21, 5)!;
    expect(h.hardware_cents).toBe(one * 3);
  });

  it("is zero when there are no drawer fronts", () => {
    const h = priceHardware([
      { category: "door", width_in: 15, height_in: 30, qty: 4 },
    ]);
    expect(h.drawer_box_count).toBe(0);
    expect(h.hardware_cents).toBe(0);
  });
});

describe("priceQuoteTiers hardware", () => {
  it("adds a constant hardware line into every tier total", () => {
    const lines = [
      { category: "casework_base", width_in: 36, height_in: 34.5, depth_in: 24, qty: 1 },
      { category: "drawer_front", width_in: 33, height_in: 5, depth_in: 0.75, qty: 3 },
      { category: "door", width_in: 18, height_in: 24, depth_in: 0.75, qty: 2 },
    ];
    const t = priceQuoteTiers(lines);
    // Hardware is the same across tiers.
    expect(t.low.hardware_cents).toBe(t.medium.hardware_cents);
    expect(t.medium.hardware_cents).toBe(t.high.hardware_cents);
    expect(t.low.hardware_cents).toBeGreaterThan(0);
    expect(t.low.drawer_box_count).toBe(3);
    // Total includes boxes + faces + hardware.
    expect(t.low.total_cents).toBe(
      t.low.box_cents + t.low.door_cents + t.low.front_cents + t.low.hardware_cents
    );
  });
});

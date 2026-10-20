import { describe, expect, it } from "vitest";
import type { CabinetLineItem, ProductLineConfig, ResolvedParams } from "@scribe/shared";
import { checkSizeLimits, priceLine } from "../src/engine.js";
import { matchLine } from "../src/match.js";
import { SEED_PRICING_SNAPSHOT } from "../src/seed.js";

const framed = SEED_PRICING_SNAPSHOT.product_lines.find((p) => p.id === "framed-casework")!;
const withLimits = (limits: ProductLineConfig["size_limits"]): ProductLineConfig => ({ ...framed, size_limits: limits });
const params = (w: number | null): ResolvedParams => ({
  product_line_id: "framed-casework", qty: 1, width_in: w, height_in: 30, depth_in: 24,
  material: "maple", finish: null, assembled: false,
});

describe("admin size limits", () => {
  it("are off by default — the seed sets none", () => {
    expect(priceLine(framed, params(200)).ok).toBe(true);
  });

  it("refuse a size past a set max or under a set min, in words", () => {
    const pl = withLimits({ width: { min_in: 9, max_in: 48 }, height: null, depth: null });
    const over = priceLine(pl, params(58));
    expect(over.ok).toBe(false);
    expect(!over.ok && over.reason).toBe("size_limit");
    expect(!over.ok && over.detail).toBe('width 58" is over the 48" max set for Framed Casework');
    expect(checkSizeLimits(pl, params(6))).toBe('width 6" is under the 9" min set for Framed Casework');
    expect(priceLine(pl, params(30)).ok).toBe(true);
  });

  it("leave an unset end open and don't judge a dimension that wasn't measured", () => {
    const maxOnly = withLimits({ width: { min_in: null, max_in: 48 }, height: null, depth: null });
    expect(checkSizeLimits(maxOnly, params(2))).toBeNull();
    expect(checkSizeLimits(maxOnly, params(null))).toBeNull();
  });

  it("let the matcher pass a too-big cabinet to another product", () => {
    const limited = {
      ...SEED_PRICING_SNAPSHOT,
      product_lines: SEED_PRICING_SNAPSHOT.product_lines.map((p) =>
        p.categories.includes("casework_base") ? { ...p, size_limits: { width: { min_in: null, max_in: 48 }, height: null, depth: null } } : p
      ),
    };
    const item = { source_page: 1, tag: "B58", room: null, qty: 1, category: "casework_base", width_in: 58, height_in: 30, depth_in: 24, door_style: null, material: "maple", finish: null, assembled: false, notes: null, confidence: 0.9 } as CabinetLineItem;
    expect(matchLine(item, limited).product_line_id).toBeNull();
    expect(matchLine(item, SEED_PRICING_SNAPSHOT).product_line_id).not.toBeNull();
  });
});

import { describe, expect, it } from "vitest";
import type { CabinetLineItem } from "@scribe/shared";
import { priceIssue, resolveForProductLine } from "../src/match.js";
import { SEED_PRICING_SNAPSHOT } from "../src/seed.js";

const framed = SEED_PRICING_SNAPSHOT.product_lines.find((p) => p.id === "framed-casework")!;

function item(p: Partial<CabinetLineItem>): CabinetLineItem {
  return {
    source_page: 1,
    tag: "base cabinet",
    room: null,
    qty: 1,
    category: "casework_base",
    width_in: 29,
    height_in: 30.75,
    depth_in: 24,
    door_style: null,
    material: "",
    finish: null,
    assembled: false,
    notes: null,
    confidence: 0.9,
    ...p,
  } as CabinetLineItem;
}

// SCR-016: a 58" base cabinet was hand-assigned to Framed Casework (9–48").
describe("resolveForProductLine", () => {
  it("refuses a width the product can't take, in words", () => {
    const r = resolveForProductLine(item({ width_in: 58 }), framed);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toMatch(/width 58" outside 9"–48"/);
  });

  it("fills the material the way the matcher does when none was read", () => {
    const r = resolveForProductLine(item({ material: "" }), framed);
    expect(r.ok).toBe(true);
    if (r.ok) expect(Object.keys(framed.material_rates)).toContain(r.resolved.material);
  });

  it("snaps a read material and refuses an unknown finish", () => {
    const r = resolveForProductLine(item({ material: "hard maple" }), framed);
    expect(r.ok && r.resolved.material).toBe("maple");
    expect(resolveForProductLine(item({ finish: "gold leaf" }), framed).ok).toBe(false);
  });
});

describe("priceIssue", () => {
  const resolved = (w: number, material = "maple") => ({
    product_line_id: "framed-casework", qty: 1, width_in: w, height_in: 30.75, depth_in: 24,
    material, finish: null, assembled: false,
  });
  it("is null for a line the quote can price, and for an unassigned line", () => {
    expect(priceIssue("framed-casework", resolved(29), SEED_PRICING_SNAPSHOT)).toBeNull();
    expect(priceIssue(null, null, SEED_PRICING_SNAPSHOT)).toBeNull();
  });
  it("explains the prod case: assigned but unpriceable", () => {
    expect(priceIssue("framed-casework", resolved(58, ""), SEED_PRICING_SNAPSHOT)).toMatch(/width 58"/);
    expect(priceIssue("nope", resolved(29), SEED_PRICING_SNAPSHOT)).toMatch(/not in the current price list/);
    expect(priceIssue("framed-casework", null, SEED_PRICING_SNAPSHOT)).toMatch(/pick the product again/);
  });
});

import { describe, expect, it } from "vitest";
import type { CabinetLineItem } from "@scribe/shared";
import { aggregate, scoreSet } from "../src/metrics.js";

function line(p: Partial<CabinetLineItem>): CabinetLineItem {
  return {
    source_page: 1,
    tag: "B24",
    room: null,
    qty: 1,
    category: "casework_base",
    width_in: 24,
    height_in: 34.5,
    depth_in: 24,
    door_style: null,
    material: null,
    finish: null,
    assembled: null,
    notes: null,
    confidence: 1,
    ...p,
  };
}

describe("scoreSet", () => {
  it("perfect prediction scores 100% everywhere", () => {
    const gold = [line({}), line({ tag: "W3030", category: "casework_wall" })];
    const m = scoreSet("t", gold, gold);
    expect(m.recall).toBe(1);
    expect(m.precision).toBe(1);
    expect(m.qty_accuracy).toBe(1);
    expect(m.dim_accuracy).toBe(1);
  });

  it("missed lines lower recall; extra lines lower precision", () => {
    const gold = [line({}), line({ tag: "SB36" })];
    const pred = [line({}), line({ tag: "HALLUCINATED99" })];
    const m = scoreSet("t", gold, pred);
    expect(m.recall).toBe(0.5);
    expect(m.precision).toBe(0.5);
  });

  it("wrong qty counts against qty accuracy but not recall", () => {
    const gold = [line({ qty: 4 })];
    const pred = [line({ qty: 2 })];
    const m = scoreSet("t", gold, pred);
    expect(m.recall).toBe(1);
    expect(m.qty_accuracy).toBe(0);
  });

  it("dims within 0.5\" tolerance count as correct", () => {
    const gold = [line({ width_in: 24 })];
    const pred = [line({ width_in: 24.4 })];
    const m = scoreSet("t", gold, pred);
    expect(m.dim_accuracy).toBe(1);
  });

  it("matches tagless lines by category + dims", () => {
    const gold = [line({ tag: null })];
    const pred = [line({ tag: null })];
    expect(scoreSet("t", gold, pred).recall).toBe(1);
  });
});

describe("aggregate", () => {
  it("weights by line counts across sets", () => {
    const a = scoreSet("a", [line({})], [line({})]);
    const b = scoreSet(
      "b",
      [line({}), line({ tag: "SB36" })],
      [line({})]
    );
    const agg = aggregate([a, b]);
    expect(agg.recall).toBeCloseTo(2 / 3);
  });
});

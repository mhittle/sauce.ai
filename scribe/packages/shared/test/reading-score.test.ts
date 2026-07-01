import { describe, expect, it } from "vitest";
import { scoreReading, type ScoredCabinet } from "../src/index.js";

const cab = (category: string, w: number, h: number, qty = 1): ScoredCabinet => ({
  category,
  w,
  h,
  qty,
});

describe("scoreReading", () => {
  it("perfect read = recall/precision 1, no size error", () => {
    const gold = [cab("casework_base", 24, 34.5), cab("casework_wall", 30, 42)];
    const s = scoreReading(gold, gold);
    expect(s.recall).toBe(1);
    expect(s.precision).toBe(1);
    expect(s.f1).toBe(1);
    expect(s.meanSizeErrorIn).toBe(0);
    expect(s.countErrorPct).toBe(0);
  });

  it("over-read (phantom cabinets) drops precision, keeps recall (the Dean case)", () => {
    const gold = [cab("casework_base", 24, 34.5), cab("casework_base", 18, 34.5)];
    const pred = [...gold, cab("casework_base", 30, 34.5)]; // one invented cabinet
    const s = scoreReading(pred, gold);
    expect(s.recall).toBe(1);
    expect(s.precision).toBeCloseTo(2 / 3, 5);
    expect(s.countErrorPct).toBe(50);
  });

  it("under-read (missed cabinets) drops recall, keeps precision", () => {
    const gold = [cab("casework_base", 24, 34.5), cab("casework_base", 18, 34.5)];
    const pred = [cab("casework_base", 24, 34.5)];
    const s = scoreReading(pred, gold);
    expect(s.recall).toBe(0.5);
    expect(s.precision).toBe(1);
  });

  it("counts qty as separate units and won't match across categories/sizes", () => {
    const gold = [cab("vanity", 15, 34.5, 2), cab("casework_tall", 24, 96)];
    const pred = [cab("vanity", 15, 34.5, 1), cab("casework_wall", 24, 96)];
    const s = scoreReading(pred, gold);
    expect(s.labelBoxes).toBe(3); // 2 vanities + 1 tall
    expect(s.matched).toBe(1); // only one 15" vanity; tall≠wall
  });

  it("matches within tolerance but not beyond it", () => {
    const gold = [cab("casework_base", 24, 34.5)];
    expect(scoreReading([cab("casework_base", 26, 34.5)], gold).matched).toBe(1); // Δw=2 ≤ 3
    expect(scoreReading([cab("casework_base", 30, 34.5)], gold).matched).toBe(0); // Δw=6 > 3
  });

  it("ignores faces and non-box categories on both sides", () => {
    const gold = [cab("casework_base", 24, 34.5), cab("door", 24, 24)];
    const pred = [cab("casework_base", 24, 34.5), cab("drawer_front", 24, 6)];
    const s = scoreReading(pred, gold);
    expect(s.labelBoxes).toBe(1);
    expect(s.predictedBoxes).toBe(1);
    expect(s.recall).toBe(1);
  });
});

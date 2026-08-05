import { describe, expect, it } from "vitest";
import {
  scoreReading,
  scoreReadingDetailed,
  type ScoredCabinet,
} from "../src/index.js";

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

describe("scoreReadingDetailed", () => {
  it("alignment accounts for every gold and pred unit exactly once", () => {
    const gold = [
      { ...cab("casework_base", 24, 34.5), tag: "Sink Base 24" },
      { ...cab("casework_base", 18, 34.5), tag: "Base 18" },
      cab("casework_wall", 30, 42),
    ];
    const pred = [
      { ...cab("casework_base", 25, 34.5), tag: "base near sink" }, // matches 24 (Δw=1)
      cab("casework_tall", 24, 96), // phantom
    ];
    const s = scoreReadingDetailed(pred, gold);
    expect(s.alignment.gold).toHaveLength(3);
    expect(s.alignment.pred).toHaveLength(2);
    // matched count must equal both the matched gold rows and matched pred rows
    const goldMatched = s.alignment.gold.filter((g) => g.matchedPred).length;
    const predMatched = s.alignment.pred.filter((p) => p.matched).length;
    expect(goldMatched).toBe(s.matched);
    expect(predMatched).toBe(s.matched);
    expect(s.matched).toBe(1);
    // the matched pair carries tags + size error through
    const hit = s.alignment.gold.find((g) => g.matchedPred);
    expect(hit?.unit.tag).toBe("Sink Base 24");
    expect(hit?.matchedPred?.tag).toBe("base near sink");
    expect(hit?.sizeErrIn).toBe(1);
    // misses and phantoms are explicit
    expect(s.alignment.gold.filter((g) => !g.matchedPred)).toHaveLength(2);
    expect(s.alignment.pred.filter((p) => !p.matched)).toHaveLength(1);
  });

  it("reports silently-dropped rows (non-box + null dims) per side", () => {
    const gold = [cab("casework_base", 24, 34.5)];
    const pred = [
      cab("casework_base", 24, 34.5),
      cab("door", 24, 24), // non-box
      { category: "casework_base", w: null, h: 34.5 }, // null dim
      { category: "casework_wall", w: 0, h: 30 }, // zero dim
    ];
    const s = scoreReadingDetailed(pred, gold);
    expect(s.predictedBoxes).toBe(1);
    expect(s.alignment.droppedPred.nonBoxCategory).toBe(1);
    expect(s.alignment.droppedPred.nullOrZeroDims).toBe(2);
    expect(s.alignment.droppedGold.nonBoxCategory).toBe(0);
    expect(s.alignment.droppedGold.nullOrZeroDims).toBe(0);
  });

  it("aggregate fields exactly match scoreReading", () => {
    const gold = [cab("casework_base", 24, 34.5, 2), cab("vanity", 30, 34.5)];
    const pred = [cab("casework_base", 23, 34.5), cab("vanity", 36, 34.5)];
    const detailed = scoreReadingDetailed(pred, gold);
    const plain = scoreReading(pred, gold);
    const { alignment: _a, ...aggregates } = detailed;
    expect(aggregates).toEqual(plain);
  });
});

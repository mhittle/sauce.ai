import { describe, expect, it } from "vitest";
import { pickMedian } from "../src/index.js";

describe("pickMedian", () => {
  it("discards an outlier under-read (5 / 21 / 24 -> 21)", () => {
    // The SCR-006 case: three reads of the same plan, one wildly low.
    const reads = [{ n: 5 }, { n: 21 }, { n: 24 }];
    expect(pickMedian(reads, (r) => r.n).n).toBe(21);
  });

  it("is order-independent", () => {
    const reads = [{ n: 24 }, { n: 5 }, { n: 21 }];
    expect(pickMedian(reads, (r) => r.n).n).toBe(21);
  });

  it("returns the single candidate when N=1", () => {
    expect(pickMedian([{ n: 7 }], (r) => r.n).n).toBe(7);
  });

  it("takes the lower median for an even count", () => {
    const reads = [{ n: 10 }, { n: 20 }, { n: 30 }, { n: 40 }];
    // sorted [10,20,30,40], lower median = index floor((4-1)/2)=1 -> 20
    expect(pickMedian(reads, (r) => r.n).n).toBe(20);
  });

  it("does not mutate the input order", () => {
    const reads = [{ n: 3 }, { n: 1 }, { n: 2 }];
    pickMedian(reads, (r) => r.n);
    expect(reads.map((r) => r.n)).toEqual([3, 1, 2]);
  });

  it("throws on an empty input", () => {
    expect(() => pickMedian([], (r: { n: number }) => r.n)).toThrow();
  });
});

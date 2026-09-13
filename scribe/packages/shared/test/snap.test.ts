import { describe, expect, it } from "vitest";
import { mergeSegments, snapBox, type PageSegments } from "../src/index.js";

// Vector snapping (Stage V item 0, v0-drawing-scale-plan.md §3): a loose
// detector box moves its edges onto the nearest real drawn lines, within
// tolerance, never by more than 15% of its side, and only when a line runs
// along most of that side.

// A 216 x 110 pt cabinet drawn at [100,100]-[316,210], with a neighbour
// sharing its right edge and a countertop line above.
const SEGS: PageSegments = {
  h: [
    { at: 100, from: 100, to: 316 }, // top
    { at: 210, from: 100, to: 316 }, // bottom
    { at: 96, from: 60, to: 600 }, // countertop line just above the top
    { at: 150, from: 100, to: 316 }, // a drawer division inside
  ],
  v: [
    { at: 100, from: 100, to: 210 }, // left
    { at: 316, from: 100, to: 210 }, // right (shared with the neighbour)
    { at: 532, from: 100, to: 210 }, // neighbour's right edge
    { at: 140, from: 120, to: 140 }, // a short handle stroke inside
  ],
};

describe("snapBox", () => {
  it("moves each loose edge onto the nearest line along it", () => {
    const r = snapBox({ x0: 106, y0: 104, x1: 309, y1: 216 }, SEGS);
    expect(r.box).toEqual({ x0: 100, y0: 100, x1: 316, y1: 210 });
    expect(r.snapped).toEqual({ l: true, r: true, t: true, b: true });
  });

  it("leaves an edge alone when no line is within tolerance", () => {
    // Left edge 40 pt off: beyond 10% of a ~170 pt width.
    const r = snapBox({ x0: 140, y0: 104, x1: 309, y1: 216 }, SEGS);
    expect(r.box.x0).toBe(140);
    expect(r.snapped.l).toBe(false);
    expect(r.snapped.r).toBe(true);
  });

  it("prefers the line that overlaps the side, not a short stroke", () => {
    // Left edge at 125: the handle stroke at x=140 is nearer (15 pt) than the
    // real edge at x=100 (25 pt), but it overlaps only 18% of the side.
    const r = snapBox({ x0: 125, y0: 104, x1: 316, y1: 216 }, SEGS, { minTolPt: 60 });
    expect(r.box.x0).toBe(100);
  });

  it("does not snap the top onto the countertop line when the cabinet top is nearer", () => {
    const r = snapBox({ x0: 100, y0: 98, x1: 316, y1: 210 }, SEGS);
    expect(r.box.y0).toBe(100);
  });

  it("never moves an edge more than 15% of the side", () => {
    // Bottom edge 40 pt above the drawn bottom on a 110 pt side (36%).
    const r = snapBox({ x0: 100, y0: 100, x1: 316, y1: 170 }, SEGS, { minTolPt: 60 });
    expect(r.snapped.b).toBe(false);
    expect(r.box.y1).toBe(170);
  });

  it("reports how far the box moved, relative to its size", () => {
    const r = snapBox({ x0: 106, y0: 100, x1: 316, y1: 210 }, SEGS);
    expect(r.moved).toBeCloseTo(6 / 210, 3);
  });

  it("keeps a raster page's box untouched when there are no segments", () => {
    const box = { x0: 106, y0: 104, x1: 309, y1: 216 };
    const r = snapBox(box, { h: [], v: [] });
    expect(r.box).toEqual(box);
    expect(r.snapped).toEqual({ l: false, r: false, t: false, b: false });
  });

  it("tolerance scales with the box: a big plan run tolerates a bigger gap", () => {
    const wide: PageSegments = { h: [{ at: 500, from: 0, to: 2000 }, { at: 560, from: 0, to: 2000 }], v: [{ at: 0, from: 500, to: 560 }, { at: 2000, from: 500, to: 560 }] };
    const r = snapBox({ x0: 40, y0: 505, x1: 1960, y1: 556 }, wide);
    expect(r.box).toEqual({ x0: 0, y0: 500, x1: 2000, y1: 560 });
  });
});

describe("mergeSegments", () => {
  it("merges collinear overlapping pieces (a thin filled rectangle's two long edges)", () => {
    const out = mergeSegments({
      h: [
        { at: 100, from: 100, to: 200 },
        { at: 100.4, from: 190, to: 316 },
        { at: 300, from: 0, to: 50 },
      ],
      v: [],
    });
    expect(out.h.length).toBe(2);
    expect(out.h[0].from).toBe(100);
    expect(out.h[0].to).toBe(316);
    expect(out.h[0].at).toBeGreaterThan(100);
    expect(out.h[0].at).toBeLessThan(100.4);
    expect(out.h[1]).toEqual({ at: 300, from: 0, to: 50 });
  });
});

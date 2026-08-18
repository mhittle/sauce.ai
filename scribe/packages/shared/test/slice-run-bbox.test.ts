import { describe, expect, it } from "vitest";
import { sliceRunBbox, stripDoorCallout } from "../src/index.js";

describe("sliceRunBbox", () => {
  it("slices a horizontal run left-to-right in width proportion", () => {
    const parts = sliceRunBbox([0, 10, 100, 30], [30, 20, 50]);
    expect(parts).toEqual([
      [0, 10, 30, 30],
      [30, 10, 50, 30],
      [50, 10, 100, 30],
    ]);
  });

  it("slices a taller-than-wide run top-to-bottom", () => {
    const parts = sliceRunBbox([5, 0, 25, 200], [1, 3]);
    expect(parts).toEqual([
      [5, 0, 25, 50],
      [5, 50, 25, 200],
    ]);
  });

  it("normalizes an inverted box and ignores non-positive widths", () => {
    const parts = sliceRunBbox([100, 30, 0, 10], [50, 0, 50]);
    expect(parts[0]).toEqual([0, 10, 50, 30]);
    // a zero-width unit takes no span but keeps its position in the run
    expect(parts[1]).toEqual([50, 10, 50, 30]);
    expect(parts[2]).toEqual([50, 10, 100, 30]);
  });

  it("gives every unit the whole run box when no width is known", () => {
    expect(sliceRunBbox([0, 0, 10, 10], [0, 0])).toEqual([
      [0, 0, 10, 10],
      [0, 0, 10, 10],
    ]);
  });

  it("returns nothing for an empty decomposition", () => {
    expect(sliceRunBbox([0, 0, 10, 10], [])).toEqual([]);
  });
});

describe("stripDoorCallout", () => {
  it("removes door-schedule callouts the plan reader dragged into a name", () => {
    expect(stripDoorCallout("bath vanity NEW 2668")).toBe("bath vanity");
    expect(stripDoorCallout("NEW 2668")).toBe("");
    expect(stripDoorCallout("vanity 2868 PKT.")).toBe("vanity");
    expect(stripDoorCallout("3068 S.G.D. wall")).toBe("wall");
  });

  it("leaves real cabinet codes and names alone", () => {
    for (const tag of ["W3030", "B24", "SB36", "Base 3 Drawers 37.25", "Wall 2436"]) {
      expect(stripDoorCallout(tag)).toBe(tag);
    }
  });
});

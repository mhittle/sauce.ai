import { describe, expect, it } from "vitest";
import { mergeMeasuredLines, MarkerEntry } from "../src/takeoff/detect.js";

const entry = (marker: number, over: Partial<MarkerEntry> = {}): MarkerEntry => ({
  marker,
  page: 2,
  label: "wall 2-door",
  category: "casework_wall",
  confidence: 0.9,
  bboxReadPx: [10, 10, 100, 60],
  ...over,
});

describe("mergeMeasuredLines", () => {
  it("uses model dims for measured markers and keeps them unestimated", () => {
    const [line] = mergeMeasuredLines(
      [entry(1)],
      [
        {
          marker: 1,
          tag: "W3030",
          category: "casework_wall",
          width_in: 30,
          height_in: 30,
          depth_in: 12,
          confidence: 0.95,
          measured: true,
        },
      ]
    );
    expect(line.tag).toBe("W3030");
    expect(line.width_in).toBe(30);
    expect(line.estimated).toBe(false);
    // line confidence never exceeds the detection's own confidence
    expect(line.confidence).toBe(0.9);
    expect(line.bbox_2d).toEqual([10, 10, 100, 60]);
  });

  it("falls back to category defaults and marks estimated when a marker is unanswered", () => {
    const [line] = mergeMeasuredLines([entry(7, { category: "casework_base" })], []);
    expect(line.width_in).toBe(30);
    expect(line.height_in).toBe(34.5);
    expect(line.depth_in).toBe(24);
    expect(line.estimated).toBe(true);
    expect(line.confidence).toBeLessThanOrEqual(0.5);
    expect(line.notes).toContain("[ESTIMATED]");
    // step-3 label survives as the tag when the model gave none
    expect(line.tag).toBe("wall 2-door");
  });

  it("marks measured=false answers estimated even when dims are present", () => {
    const [line] = mergeMeasuredLines(
      [entry(1)],
      [
        {
          marker: 1,
          tag: null,
          category: "casework_wall",
          width_in: 33,
          height_in: 30,
          depth_in: 12,
          confidence: 0.7,
          measured: false,
        },
      ]
    );
    expect(line.width_in).toBe(33);
    expect(line.estimated).toBe(true);
  });

  it("maps unknown categories to 'unknown' and drops malformed answers", () => {
    const lines = mergeMeasuredLines(
      [entry(1, { category: "other" }), entry(2)],
      ["not-an-object", { marker: 2, category: "casework_wall", measured: false }]
    );
    expect(lines[0].category).toBe("unknown");
    expect(lines[1].category).toBe("casework_wall");
    expect(lines).toHaveLength(2);
  });

  it("lets the model correct the provisional category", () => {
    const [line] = mergeMeasuredLines(
      [entry(1, { category: "casework_base" })],
      [{ marker: 1, category: "casework_tall", measured: false }]
    );
    expect(line.category).toBe("casework_tall");
    // defaults follow the corrected category
    expect(line.height_in).toBe(84);
  });
});

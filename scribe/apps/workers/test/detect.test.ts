import { describe, expect, it } from "vitest";
import {
  isBareNumberTag,
  meaningfulTag,
  mergeMeasuredLines,
  parseMeasureResponse,
  processDetectionResponse,
  MarkerEntry,
} from "../src/takeoff/detect.js";

describe("processDetectionResponse", () => {
  // 10x10in crop at 100dpi starting at page point (72, 144); display at 72dpi
  // → display px == page pt, so expected values are easy to read.
  const ctx = {
    cropPt: { x0: 72, y0: 144, x1: 792, y1: 864 },
    cropDpi: 100,
    displayDpi: 72,
    dims: { widthPt: 1224, heightPt: 1584 },
  };

  it("parses items and remaps boxes crop px → display px", () => {
    const text = `{"items":[{"label":"sink base","category":"casework_base","confidence":0.9,"bbox_2d":[100,200,300,400]}]}`;
    const [item] = processDetectionResponse(text, ctx);
    expect(item.label).toBe("sink base");
    // crop px 100 @100dpi = 72pt → page pt 72+72=144 → display px 144
    expect(item.bbox_2d![0]).toBeCloseTo(144, 5);
    expect(item.bbox_2d![1]).toBeCloseTo(288, 5);
    expect(item.bbox_2d![2]).toBeCloseTo(288, 5);
    expect(item.bbox_2d![3]).toBeCloseTo(432, 5);
  });

  it("drops malformed items and survives fenced/prose responses", () => {
    const text =
      'Here you go:\n```json\n{"items":[{"label":"ok","category":"casework_wall","confidence":0.8,"bbox_2d":null},"garbage"]}\n```';
    const items = processDetectionResponse(text, ctx);
    expect(items).toHaveLength(1);
    expect(items[0].bbox_2d).toBeNull();
  });

  it("returns empty on unparseable text", () => {
    expect(processDetectionResponse("no json here", ctx)).toEqual([]);
  });
});

describe("parseMeasureResponse", () => {
  it("returns the cabinets array", () => {
    const r = parseMeasureResponse('{"cabinets":[{"marker":1}]}');
    expect(r.cabinets).toHaveLength(1);
    expect(r.warnings).toEqual([]);
  });

  it("warns on a missing cabinets array", () => {
    const r = parseMeasureResponse('{"nope":true}');
    expect(r.cabinets).toEqual([]);
    expect(r.warnings[0]).toMatch(/no cabinets array/);
  });

  it("warns on unparseable JSON", () => {
    const r = parseMeasureResponse("total garbage");
    expect(r.cabinets).toEqual([]);
    expect(r.warnings[0]).toMatch(/not parseable/);
  });
});

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
    const { lines: [line] } = mergeMeasuredLines(
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
    const { lines: [line] } = mergeMeasuredLines([entry(7, { category: "casework_base" })], []);
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
    const { lines: [line] } = mergeMeasuredLines(
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
    const { lines } = mergeMeasuredLines(
      [entry(1, { category: "other" }), entry(2)],
      ["not-an-object", { marker: 2, category: "casework_wall", measured: false }]
    );
    expect(lines[0].category).toBe("unknown");
    expect(lines[1].category).toBe("casework_wall");
    expect(lines).toHaveLength(2);
  });

  it("replaces bare-number tags with synthesized names, keeping the callout", () => {
    const { lines: [line] } = mergeMeasuredLines(
      [entry(5, { category: "casework_wall", label: "19 1/4" })],
      [
        {
          marker: 5,
          tag: "8",
          category: "casework_wall",
          width_in: 14,
          height_in: 53,
          depth_in: 12,
          confidence: 0.9,
          measured: true,
        },
      ]
    );
    expect(line.tag).toBe(`Wall cabinet 14"w (#5)`);
    expect(line.notes).toBe("drawing callout: 8");
  });

  it("expands a plan run into one line per unit, slicing the run box", () => {
    const { lines, warnings } = mergeMeasuredLines(
      [
        entry(1, {
          kind: "plan",
          label: "north wall run",
          category: "casework_base",
          bboxReadPx: [0, 100, 300, 140],
        }),
      ],
      [
        {
          marker: 1,
          tag: "north wall run",
          category: "casework_base",
          width_in: 120,
          height_in: 34.5,
          depth_in: 24,
          confidence: 0.8,
          measured: true,
          run_length_in: 120,
          units: [
            { tag: "Sink Base 36", category: "casework_base", width_in: 36, height_in: 34.5, depth_in: 24, confidence: 0.8, measured: true },
            { tag: "Base 3 Drawers 24", category: "casework_base", width_in: 24, height_in: 34.5, depth_in: 24, confidence: 0.8, measured: true },
            { tag: "Base 36", category: "casework_base", width_in: 36, height_in: 34.5, depth_in: 24, confidence: 0.8, measured: true },
          ],
        },
      ]
    );
    expect(lines).toHaveLength(3);
    expect(lines.map((l) => l.tag)).toEqual([
      "Sink Base 36",
      "Base 3 Drawers 24",
      "Base 36",
    ]);
    // 36:24:36 of a 300px-wide run → 112.5 / 75 / 112.5, laid end to end
    expect(lines[0].bbox_2d).toEqual([0, 100, 112.5, 140]);
    expect(lines[1].bbox_2d).toEqual([112.5, 100, 187.5, 140]);
    expect(lines[2].bbox_2d).toEqual([187.5, 100, 300, 140]);
    expect(lines[0].notes).toContain('unit 1 of 3 in plan run "north wall run"');
    expect(lines[0].estimated).toBe(false);
    // 96" of units in a 120" run is a normal amount of appliance gap
    expect(warnings).toEqual([]);
  });

  it("never decomposes an elevation marker, even if units come back", () => {
    const { lines } = mergeMeasuredLines(
      [entry(1, { kind: "elevation" })],
      [
        {
          marker: 1,
          tag: "B24",
          category: "casework_base",
          width_in: 24,
          height_in: 34.5,
          depth_in: 24,
          confidence: 0.9,
          measured: true,
          units: [
            { tag: "a", category: "casework_base", width_in: 12, measured: true },
            { tag: "b", category: "casework_base", width_in: 12, measured: true },
          ],
        },
      ]
    );
    expect(lines).toHaveLength(1);
    expect(lines[0].tag).toBe("B24");
  });

  it("warns when a plan run comes back undecomposed or does not close", () => {
    const undecomposed = mergeMeasuredLines(
      [entry(1, { kind: "plan", label: "kitchen run" })],
      [{ marker: 1, category: "casework_base", width_in: 120, measured: true }]
    );
    expect(undecomposed.lines).toHaveLength(1);
    expect(undecomposed.warnings[0]).toMatch(/undecomposed/);

    const overSplit = mergeMeasuredLines(
      [entry(2, { kind: "plan", label: "long run" })],
      [
        {
          marker: 2,
          category: "casework_base",
          measured: true,
          run_length_in: 60,
          units: [
            { tag: "a", category: "casework_base", width_in: 36, measured: true },
            { tag: "b", category: "casework_base", width_in: 36, measured: true },
          ],
        },
      ]
    );
    expect(overSplit.lines).toHaveLength(2);
    expect(overSplit.warnings[0]).toMatch(/over-split or over-wide/);
  });

  it("drops zero-width units and caps a runaway decomposition", () => {
    const { lines, warnings } = mergeMeasuredLines(
      [entry(1, { kind: "plan" })],
      [
        {
          marker: 1,
          category: "casework_base",
          measured: true,
          units: [
            { tag: "real", category: "casework_base", width_in: 24, measured: true },
            { tag: "no width", category: "casework_base", width_in: null, measured: true },
            ...Array.from({ length: 20 }, (_, i) => ({
              tag: `u${i}`,
              category: "casework_base",
              width_in: 12,
              measured: true,
            })),
          ],
        },
      ]
    );
    expect(lines).toHaveLength(16);
    expect(warnings[0]).toMatch(/kept the first 16/);
  });

  it("strips a door-schedule callout out of the tag", () => {
    const { lines } = mergeMeasuredLines(
      [entry(1, { category: "vanity" })],
      [
        {
          marker: 1,
          tag: "bath vanity NEW 2668",
          category: "vanity",
          width_in: 36,
          height_in: 32.5,
          depth_in: 21,
          confidence: 0.6,
          measured: true,
        },
      ]
    );
    expect(lines[0].tag).toBe("bath vanity");
    expect(lines[0].notes).toContain("drawing callout: bath vanity NEW 2668");
  });

  it("lets the model correct the provisional category", () => {
    const { lines: [line] } = mergeMeasuredLines(
      [entry(1, { category: "casework_base" })],
      [{ marker: 1, category: "casework_tall", measured: false }]
    );
    expect(line.category).toBe("casework_tall");
    // defaults follow the corrected category
    expect(line.height_in).toBe(84);
  });
});

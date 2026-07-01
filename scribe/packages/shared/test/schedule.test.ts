import { describe, expect, it } from "vitest";
import {
  reconstructRows,
  parseDimCell,
  extractCabinetSchedule,
  type TextFragment,
} from "../src/index.js";

describe("parseDimCell", () => {
  it("parses ints, fractions, mixed numbers, and quote marks", () => {
    expect(parseDimCell("24")).toBe(24);
    expect(parseDimCell("34 1/2")).toBe(34.5);
    expect(parseDimCell("1/2")).toBe(0.5);
    expect(parseDimCell("24.5")).toBe(24.5);
    expect(parseDimCell('30"')).toBe(30);
    expect(parseDimCell("Vanity")).toBeNull();
    expect(parseDimCell("")).toBeNull();
  });
});

describe("reconstructRows", () => {
  it("groups fragments on the same baseline into one column-joined row", () => {
    const frags: TextFragment[] = [
      { x: 20, y: 100, text: "R1C1" },
      { x: 80, y: 101, text: "Vanity Sink Base" },
      { x: 200, y: 100, text: "15" },
      { x: 240, y: 100, text: "34 1/2" },
      { x: 300, y: 100, text: "24" },
      { x: 20, y: 130, text: "R1C2" }, // next row (y differs > tol)
    ];
    const rows = reconstructRows(frags);
    expect(rows[0]).toBe("R1C1  Vanity Sink Base  15  34 1/2  24");
    expect(rows).toHaveLength(2);
  });
});

// The actual Dean Vanity BOM, as mupdf fragments would reconstruct it.
function deanFragments(): TextFragment[] {
  const rows = [
    ["R1C1", "Vanity Sink Base", "15", "34 1/2", "24", "Vanity Sink Base"],
    ["R1C2", "Vanity Sink Base", "24", "34 1/2", "24", "Vanity Sink Base"],
    ["R1C3", "Vanity Sink Base", "30", "34 1/2", "24", "Vanity Sink Base"],
    ["R1C4", "Vanity Sink Base", "24", "34 1/2", "24", "Vanity Sink Base"],
    ["R1C5", "Vanity Sink Base", "15", "34 1/2", "24", "Vanity Sink Base"],
    ["R1C6", "Tall Pair Doors", "24", "96", "24", "Tall - Utility 2 Door"],
    ["R1N1", "BF", "3", "34 1/2", "24", "Base FIller / End"],
    ["R1N2", "BF", "3", "34 1/2", "24", "Base FIller / End"],
  ];
  const frags: TextFragment[] = [];
  rows.forEach((cells, r) => {
    const xs = [20, 80, 220, 280, 340, 420];
    cells.forEach((t, c) => frags.push({ x: xs[c], y: 100 + r * 20, text: t }));
  });
  return frags;
}

describe("extractCabinetSchedule (Dean Vanity BOM)", () => {
  const { lines, schedulePages } = extractCabinetSchedule([
    { page: 6, fragments: deanFragments() },
  ]);

  it("recovers all 8 line items from the real table", () => {
    expect(lines).toHaveLength(8);
    expect(schedulePages).toEqual([6]);
    expect(lines.every((l) => l.source_page === 6)).toBe(true);
  });

  it("reads the 5 vanity sink bases at their true widths (not defaulted)", () => {
    const vanities = lines.filter((l) => l.category === "vanity");
    expect(vanities.map((v) => v.width_in)).toEqual([15, 24, 30, 24, 15]);
    expect(vanities.every((v) => v.height_in === 34.5 && v.depth_in === 24)).toBe(true);
  });

  it("classifies the tall unit and the fillers", () => {
    const tall = lines.find((l) => l.category === "casework_tall");
    expect(tall).toMatchObject({ width_in: 24, height_in: 96 });
    const fillers = lines.filter((l) => /filler/i.test(l.tag ?? ""));
    expect(fillers).toHaveLength(2);
    expect(fillers.every((f) => f.width_in === 3)).toBe(true);
  });

  it("marks lines as schedule-read, not estimated", () => {
    expect(lines.every((l) => l.estimated === false && l.confidence >= 0.8)).toBe(true);
  });
});

describe("extractCabinetSchedule guards", () => {
  it("ignores a page with fewer than MIN_SCHEDULE_ROWS cabinet rows", () => {
    const frags: TextFragment[] = [
      { x: 20, y: 100, text: "Vanity Sink Base" },
      { x: 200, y: 100, text: "24" },
      { x: 240, y: 100, text: "34 1/2" },
    ];
    expect(extractCabinetSchedule([{ page: 1, fragments: frags }]).lines).toHaveLength(0);
  });

  it("does not parse elevation prose as cabinet rows", () => {
    // "WALL A — BACK WALL | 72\" FACE | 3 EQUAL BAYS @ 22\"" style noise.
    const frags: TextFragment[] = [
      { x: 20, y: 100, text: "WALL A — BACK WALL" },
      { x: 200, y: 100, text: "72 FACE" },
      { x: 300, y: 100, text: "3 EQUAL BAYS @ 22" },
      { x: 20, y: 130, text: "WALL B — LEFT RETURN" },
      { x: 200, y: 130, text: "81 5/8 FACE" },
      { x: 20, y: 160, text: "UPPER SHELVING TO CROWN" },
    ];
    expect(extractCabinetSchedule([{ page: 1, fragments: frags }]).lines).toHaveLength(0);
  });
});

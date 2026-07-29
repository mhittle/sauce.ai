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

// ---------------------------------------------------------------------------
// Header-driven tables (labels v3) — modeled on the real packet formats that
// broke the positional heuristic.
// ---------------------------------------------------------------------------

// Q11 "Steady Ground" format: `Room Name | Cab# (QTY) | Name | Width | Height |
// Depth | Notes`. The leading Cab# used to be parsed as the WIDTH.
function cabNumFirstFragments(): TextFragment[] {
  const xs = { room: 55, cab: 163, name: 271, w: 379, h: 471, d: 563, notes: 655 };
  const frags: TextFragment[] = [
    { x: xs.room, y: 64, text: "Room Name" },
    { x: xs.cab, y: 64, text: "Cab# (QTY)" },
    { x: xs.name, y: 64, text: "Name" },
    { x: xs.w, y: 64, text: "Width" },
    { x: xs.h, y: 64, text: "Height" },
    { x: xs.d, y: 64, text: "Depth" },
    { x: xs.notes, y: 64, text: "Notes" },
    // Sink Base 36
    { x: xs.room, y: 79, text: "Kitchen" },
    { x: xs.cab, y: 79, text: "4" },
    { x: xs.name, y: 79, text: "Sink Base" },
    { x: xs.w, y: 79, text: "36" },
    { x: xs.h, y: 79, text: "34 1/2" },
    { x: xs.d, y: 79, text: "24" },
    // Trash Pull Out Cabinet 18 — name wraps BELOW its dims row
    { x: xs.room, y: 95, text: "Kitchen" },
    { x: xs.cab, y: 95, text: "3" },
    { x: xs.name, y: 95, text: "Trash Pull Out" },
    { x: xs.name, y: 108, text: "Cabinet" },
    { x: xs.w, y: 95, text: "18" },
    { x: xs.h, y: 95, text: "34 1/2" },
    { x: xs.d, y: 95, text: "24" },
    { x: xs.notes, y: 95, text: "Rev-A-Shelf Trash" },
    { x: xs.notes, y: 108, text: "Pull Out 53WC" },
    // Pair Door - Single Drawer 33 (door/drawer name, no legacy noun)
    { x: xs.room, y: 139, text: "Kitchen" },
    { x: xs.cab, y: 139, text: "1" },
    { x: xs.name, y: 139, text: "Pair Door - Single" },
    { x: xs.name, y: 152, text: "Drawer" },
    { x: xs.w, y: 139, text: "33" },
    { x: xs.h, y: 139, text: "34 1/2" },
    { x: xs.d, y: 139, text: "24" },
  ];
  return frags;
}

describe("extractCabinetSchedule (header-driven, Cab# first)", () => {
  const { lines } = extractCabinetSchedule([
    { page: 12, fragments: cabNumFirstFragments() },
  ]);

  it("maps the Width column, not the Cab# column", () => {
    expect(lines.map((l) => l.width_in).sort((a, b) => a! - b!)).toEqual([18, 33, 36]);
    expect(lines.every((l) => l.height_in === 34.5 && l.depth_in === 24)).toBe(true);
  });

  it("reassembles names that wrap below their dims row", () => {
    expect(lines.some((l) => /Trash Pull Out Cabinet/.test(l.tag ?? ""))).toBe(true);
    expect(lines.some((l) => /Pair Door - Single Drawer/.test(l.tag ?? ""))).toBe(true);
  });
});

// Q14 "Charley" CabinetNow format: `CABINET BOX STYLE | WIDTH | HEIGHT | DEPTH |
// Qty | UNIT #`, names outdent left of the header, wrapped names span rows both
// above and below the width, and the whole table is printed once per door-style
// option (a reprint that must not double the truth).
function cabinetBoxesPage(y0: number): TextFragment[] {
  const xs = { name: 52, w: 276, h: 364, d: 470, q: 507, u: 534 };
  const hx = { name: 82, w: 231, h: 319, d: 417, q: 490, u: 523 };
  return [
    { x: hx.name, y: y0, text: "CABINET BOX STYLE" },
    { x: hx.w, y: y0, text: "WIDTH" },
    { x: hx.h, y: y0, text: "HEIGHT" },
    { x: hx.d, y: y0, text: "DEPTH" },
    { x: hx.q, y: y0, text: "Qty" },
    { x: hx.u, y: y0, text: "UNIT #" },
    // Base Cabinet 21, qty 2
    { x: xs.name, y: y0 + 12, text: "Base Cabinet 1 Adjustable Shelf" },
    { x: xs.w, y: y0 + 12, text: "21" },
    { x: xs.h, y: y0 + 12, text: "34.5" },
    { x: xs.d, y: y0 + 12, text: "24" },
    { x: xs.q, y: y0 + 12, text: "2" },
    { x: xs.u, y: y0 + 12, text: "1 & 2" },
    // Easy Reach Corner: name wraps ABOVE and BELOW the width row
    { x: xs.name, y: y0 + 23, text: "Easy Reach Corner Base 1 Adjustable" },
    { x: xs.w, y: y0 + 28, text: "36" },
    { x: xs.name, y: y0 + 33, text: "Shelf" },
    { x: xs.h, y: y0 + 33, text: "34.5" },
    { x: xs.d, y: y0 + 33, text: "36" },
    { x: xs.q, y: y0 + 33, text: "1" },
    { x: xs.u, y: y0 + 33, text: "3.00" },
    // A real Door-Over-Door WALL carcass (must not be treated as a door row)
    { x: xs.name, y: y0 + 45, text: "Wall Cabinet Door Over Door 3" },
    { x: xs.name, y: y0 + 55, text: "Adjustable Shelves" },
    { x: xs.w, y: y0 + 50, text: "18" },
    { x: xs.h, y: y0 + 55, text: "53" },
    { x: xs.d, y: y0 + 55, text: "12" },
    { x: xs.q, y: y0 + 55, text: "1" },
    { x: xs.u, y: y0 + 55, text: "9.00" },
  ];
}

// The priced DOOR & DRAWER LIST that precedes it (money columns → skipped).
function doorListPage(): TextFragment[] {
  return [
    { x: 84, y: 419, text: "STYLE" },
    { x: 155, y: 419, text: "MATERIAL" },
    { x: 213, y: 419, text: "WIDTH" },
    { x: 253, y: 419, text: "HEIGHT" },
    { x: 302, y: 419, text: "Unit #" },
    { x: 335, y: 419, text: "$ PER SQ FT" },
    { x: 389, y: 419, text: "SUB-TOTAL" },
    { x: 492, y: 419, text: "Qty" },
    { x: 526, y: 419, text: "TOTAL" },
    { x: 52, y: 430, text: "Malibu Cabinet Door" },
    { x: 234, y: 430, text: "19" },
    { x: 276, y: 430, text: "22" },
    { x: 354, y: 430, text: "$49.45" },
    { x: 496, y: 430, text: "2.00" },
    { x: 52, y: 442, text: "Malibu Cabinet Door" },
    { x: 212, y: 442, text: "16.9375" },
    { x: 276, y: 442, text: "22" },
    { x: 354, y: 442, text: "$49.45" },
    { x: 496, y: 442, text: "2.00" },
    { x: 52, y: 453, text: "Malibu Cabinet Door" },
    { x: 234, y: 453, text: "16" },
    { x: 264, y: 453, text: "18.75" },
    { x: 354, y: 453, text: "$49.45" },
    { x: 496, y: 453, text: "2.00" },
  ];
}

describe("extractCabinetSchedule (CabinetNow boxes + reprint + door list)", () => {
  const { lines, schedulePages } = extractCabinetSchedule([
    { page: 12, fragments: doorListPage() },
    { page: 13, fragments: cabinetBoxesPage(114) },
    { page: 14, fragments: doorListPage() },
    { page: 15, fragments: cabinetBoxesPage(114) }, // reprint (2nd style option)
  ]);

  it("skips the priced door list entirely", () => {
    expect(lines.some((l) => /Malibu/.test(l.tag ?? ""))).toBe(false);
    expect(schedulePages).not.toContain(12);
    expect(schedulePages).not.toContain(14);
  });

  it("dedupes the reprinted schedule (one copy per style option)", () => {
    expect(schedulePages).toEqual([13]);
    expect(lines).toHaveLength(3);
  });

  it("reads Qty and wrapped names via width anchoring", () => {
    const base = lines.find((l) => /^Base Cabinet/.test(l.tag ?? ""));
    expect(base).toMatchObject({ width_in: 21, height_in: 34.5, qty: 2 });
    const corner = lines.find((l) => /Easy Reach Corner Base/.test(l.tag ?? ""));
    expect(corner).toMatchObject({ width_in: 36, height_in: 34.5, depth_in: 36 });
    expect(corner?.tag).toMatch(/Adjustable Shelf 36$/);
    const wall = lines.find((l) => l.category === "casework_wall");
    expect(wall).toMatchObject({ width_in: 18, height_in: 53 });
  });

  it("carries an open header across a page break", () => {
    const contRows: TextFragment[] = [
      { x: 52, y: 30, text: "Blind Corner Base 1 Adjustable Shelf" },
      { x: 276, y: 30, text: "39" },
      { x: 364, y: 30, text: "34.5" },
      { x: 470, y: 30, text: "24" },
      { x: 507, y: 30, text: "2" },
    ];
    const res = extractCabinetSchedule([
      { page: 30, fragments: cabinetBoxesPage(600) },
      { page: 31, fragments: contRows },
    ]);
    const blind = res.lines.find((l) => /Blind Corner/.test(l.tag ?? ""));
    expect(blind).toMatchObject({ width_in: 39, qty: 2, source_page: 31 });
    expect(res.schedulePages).toEqual([30, 31]);
  });
});

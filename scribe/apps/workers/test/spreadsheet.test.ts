import { describe, expect, it } from "vitest";
import * as XLSX from "xlsx";
import { TakeoffBudget } from "../src/lib/anthropic.js";
import { inferMapping, parseSpreadsheet } from "../src/takeoff/spreadsheet.js";

describe("inferMapping", () => {
  it("maps common headers", () => {
    const m = inferMapping(["Item", "Qty", "Width", "Height", "Depth", "Finish"]);
    expect(m[0]).toBe("tag");
    expect(m[1]).toBe("qty");
    expect(m[2]).toBe("width_in");
    expect(m[5]).toBe("finish");
  });

  it("ignores unknown headers", () => {
    const m = inferMapping(["Foo", "Bar"]);
    expect(Object.keys(m)).toHaveLength(0);
  });
});

function workbookBuffer(rows: unknown[][]): Buffer {
  const ws = XLSX.utils.aoa_to_sheet(rows);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Schedule");
  return XLSX.write(wb, { type: "buffer", bookType: "xlsx" }) as Buffer;
}

describe("parseSpreadsheet", () => {
  it("parses a typical schedule deterministically (no model)", async () => {
    const buf = workbookBuffer([
      ["Cabinet Schedule — Unit A"],
      ["Item", "Qty", "Width", "Height", "Depth", "Material", "Finish"],
      ["B24", 2, 24, 34.5, 24, "Maple", "Painted"],
      ["W3030", 4, 30, 30, 12, "Maple", "Painted"],
      ["SB36", 1, 36, "34 1/2", 24, "PLAM", null],
    ]);
    const { lines, warnings } = await parseSpreadsheet(buf, new TakeoffBudget(), {
      modelAssist: false,
    });
    expect(warnings).toHaveLength(0);
    expect(lines).toHaveLength(3);
    expect(lines[0].tag).toBe("B24");
    expect(lines[0].category).toBe("casework_base");
    expect(lines[1].qty).toBe(4);
    expect(lines[2].height_in).toBe(34.5); // fraction parsing
  });

  it("derives dims/category from tags when columns are missing", async () => {
    const buf = workbookBuffer([
      ["Item", "Qty"],
      ["W3030", 2],
    ]);
    const { lines } = await parseSpreadsheet(buf, new TakeoffBudget(), {
      modelAssist: false,
    });
    expect(lines[0].width_in).toBe(30);
    expect(lines[0].depth_in).toBe(12);
    expect(lines[0].category).toBe("casework_wall");
  });

  it("warns instead of guessing when no mapping is inferable", async () => {
    const buf = workbookBuffer([
      ["x", "y"],
      [1, 2],
    ]);
    const { lines, warnings } = await parseSpreadsheet(buf, new TakeoffBudget(), {
      modelAssist: false,
    });
    expect(lines).toHaveLength(0);
    expect(warnings.length).toBeGreaterThan(0);
  });
});

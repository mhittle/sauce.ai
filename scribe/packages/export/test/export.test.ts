import { describe, expect, it } from "vitest";
import type { CabinetLineItem, ExportTemplate } from "@scribe/shared";
import {
  DEFAULT_KCD_TEMPLATE,
  DEFAULT_MOZAIK_TEMPLATE,
  exportCsv,
} from "../src/index.js";

const line: CabinetLineItem = {
  source_page: 4,
  tag: "B24",
  room: "Kitchen, Unit A",
  qty: 2,
  category: "casework_base",
  width_in: 24,
  height_in: 34.5,
  depth_in: 24,
  door_style: "shaker",
  material: "maple",
  finish: "painted",
  assembled: true,
  notes: 'He said "rush"',
  confidence: 0.95,
};

describe("exportCsv", () => {
  it("renders the Mozaik default template", () => {
    const csv = exportCsv([line], DEFAULT_MOZAIK_TEMPLATE);
    const [header, row] = csv.trim().split("\r\n");
    expect(header).toBe(
      "Name,Qty,Width,Height,Depth,Material,Finish,Room,Comments"
    );
    expect(row).toContain("B24,2,24,34.5,24,maple,painted");
  });

  it("escapes delimiters and quotes", () => {
    const csv = exportCsv([line], DEFAULT_MOZAIK_TEMPLATE);
    expect(csv).toContain('"Kitchen, Unit A"');
    expect(csv).toContain('"He said ""rush"""');
  });

  it("renders booleans as Y/N (KCD)", () => {
    const csv = exportCsv([line], DEFAULT_KCD_TEMPLATE);
    expect(csv.trim().split("\r\n")[1]).toContain(",Y,");
  });

  it("converts dimensions to mm when configured", () => {
    const template: ExportTemplate = {
      ...DEFAULT_MOZAIK_TEMPLATE,
      unit_format: "mm",
    };
    const csv = exportCsv([line], template);
    expect(csv).toContain("609.6"); // 24" → 609.6mm
  });

  it("supports literal columns and custom delimiters", () => {
    const template: ExportTemplate = {
      name: "t",
      target: "generic",
      delimiter: ";",
      unit_format: "decimal_in",
      columns: [
        { header: "Tag", field: "tag" },
        { header: "Source", field: "literal:scribe" },
      ],
    };
    const csv = exportCsv([line], template);
    expect(csv.trim().split("\r\n")[1]).toBe("B24;scribe");
  });

  it("renders empty string for null fields", () => {
    const csv = exportCsv(
      [{ ...line, finish: null }],
      DEFAULT_MOZAIK_TEMPLATE
    );
    expect(csv.trim().split("\r\n")[1]).toContain("maple,,");
  });
});

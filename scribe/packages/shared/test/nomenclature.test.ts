import { describe, expect, it } from "vitest";
import { parseTag, repairLine } from "../src/nomenclature.js";
import type { CabinetLineItem } from "../src/schemas.js";

describe("parseTag", () => {
  it("parses wall cabinets with width+height", () => {
    expect(parseTag("W3030")).toEqual({
      category: "casework_wall",
      width_in: 30,
      height_in: 30,
      depth_in: 12,
      modifier: null,
    });
  });

  it("parses base cabinets with default height/depth", () => {
    expect(parseTag("B24")).toEqual({
      category: "casework_base",
      width_in: 24,
      height_in: 34.5,
      depth_in: 24,
      modifier: null,
    });
  });

  it("parses sink bases", () => {
    const t = parseTag("SB36");
    expect(t?.category).toBe("casework_base");
    expect(t?.width_in).toBe(36);
    expect(t?.depth_in).toBe(24);
  });

  it("parses six-digit tags as W/H/D", () => {
    expect(parseTag("W302412")).toEqual({
      category: "casework_wall",
      width_in: 30,
      height_in: 24,
      depth_in: 12,
      modifier: null,
    });
  });

  it("parses tall pantry with tall defaults", () => {
    const t = parseTag("TP24");
    expect(t?.category).toBe("casework_tall");
    expect(t?.height_in).toBe(84);
    expect(t?.depth_in).toBe(24);
  });

  it("keeps trailing modifiers", () => {
    expect(parseTag("B24FH")?.modifier).toBe("FH");
  });

  it("parses vanities", () => {
    const t = parseTag("VB30");
    expect(t?.category).toBe("vanity");
    expect(t?.depth_in).toBe(21);
  });

  it("rejects garbage", () => {
    expect(parseTag("123")).toBeNull();
    expect(parseTag("HELLO")).toBeNull();
    expect(parseTag("B0")).toBeNull();
    expect(parseTag("W12345")).toBeNull();
  });

  it("normalizes case and separators", () => {
    expect(parseTag(" w-3030 ")?.width_in).toBe(30);
  });
});

function line(partial: Partial<CabinetLineItem>): CabinetLineItem {
  return {
    source_page: 1,
    tag: null,
    room: null,
    qty: 1,
    category: "unknown",
    width_in: null,
    height_in: null,
    depth_in: null,
    door_style: null,
    material: null,
    finish: null,
    assembled: null,
    notes: null,
    confidence: 0.95,
    ...partial,
  };
}

describe("repairLine", () => {
  it("fills missing dims and category from the tag", () => {
    const repaired = repairLine(line({ tag: "W3030" }));
    expect(repaired.category).toBe("casework_wall");
    expect(repaired.width_in).toBe(30);
    expect(repaired.height_in).toBe(30);
    expect(repaired.depth_in).toBe(12);
    expect(repaired.confidence).toBe(0.95);
  });

  it("flags width disagreement instead of overwriting", () => {
    const repaired = repairLine(line({ tag: "B24", width_in: 27 }));
    expect(repaired.width_in).toBe(27);
    expect(repaired.confidence).toBeLessThanOrEqual(0.5);
    expect(repaired.notes).toContain("mismatch");
  });

  it("keeps model dims that agree", () => {
    const repaired = repairLine(
      line({ tag: "B24", width_in: 24, height_in: 34.5 })
    );
    expect(repaired.confidence).toBe(0.95);
  });

  it("passes through lines without tags", () => {
    const l = line({ width_in: 12 });
    expect(repairLine(l)).toEqual(l);
  });
});

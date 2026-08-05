import { describe, expect, it } from "vitest";
import type { CabinetLineItem } from "../src/schemas.js";
import {
  isNonBoxCasework,
  dropNonBoxCasework,
  boxFaceArea,
} from "../src/index.js";

function line(over: Partial<CabinetLineItem> = {}): CabinetLineItem {
  return {
    source_page: 1,
    tag: "Base 24",
    room: "Kitchen",
    qty: 1,
    category: "casework_base",
    width_in: 24,
    height_in: 34.5,
    depth_in: 24,
    door_style: null,
    material: null,
    finish: null,
    assembled: null,
    notes: null,
    confidence: 0.5,
    estimated: true,
    ...over,
  };
}

describe("isNonBoxCasework", () => {
  it("flags fillers / end panels / crown / returns / toe-kick by tag", () => {
    for (const tag of [
      "Base Filler 3",
      "Base End Panel 1.5",
      "Crown Molding",
      "Crown Moulding 96",
      "Wall Return",
      "Toe Kick Skin",
      "Light Rail",
      "Scribe Molding",
    ]) {
      expect(isNonBoxCasework(line({ tag }))).toBe(true);
    }
  });

  it("does not flag real cabinets", () => {
    expect(isNonBoxCasework(line({ tag: "Sink Base 36" }))).toBe(false);
    expect(isNonBoxCasework(line({ tag: "Easy Reach Corner Base 36" }))).toBe(false);
    expect(isNonBoxCasework(line({ tag: "Wall 30", category: "casework_wall" }))).toBe(false);
  });

  it("only applies to box categories (a 'filler'-tagged door face is untouched)", () => {
    expect(isNonBoxCasework(line({ tag: "Filler", category: "door" }))).toBe(false);
  });

  it("judges by TAG when one exists — descriptive notes must not condemn a real cabinet", () => {
    // Q13 regression: a real tall cabinet whose notes said "…4\" toe to 5\" crown…"
    // was silently deleted as trim. Tagged lines are judged by the tag alone.
    expect(
      isNonBoxCasework(
        line({ tag: "Tall Single Doors 17.5", notes: 'full height from 4" toe kick to 5" crown' })
      )
    ).toBe(false);
    expect(isNonBoxCasework(line({ tag: "Base 3", notes: "end panel at island end" }))).toBe(false);
  });

  it("falls back to notes only when there is no tag", () => {
    expect(isNonBoxCasework(line({ tag: null, notes: "end panel at island end" }))).toBe(true);
    expect(isNonBoxCasework(line({ tag: "", notes: "crown moulding run" }))).toBe(true);
    expect(isNonBoxCasework(line({ tag: null, notes: "double-door pantry" }))).toBe(false);
  });
});

describe("dropNonBoxCasework", () => {
  it("removes filler/trim lines, keeps real boxes", () => {
    const lines = [
      line({ tag: "Base 24" }),
      line({ tag: "Base Filler 3" }),
      line({ tag: "Crown Molding 96" }),
      line({ tag: "Sink Base 36" }),
    ];
    const out = dropNonBoxCasework(lines);
    expect(out.map((l) => l.tag)).toEqual(["Base 24", "Sink Base 36"]);
  });
});

describe("boxFaceArea excludes non-box casework", () => {
  it("does not count a filler's area toward the quote-total proxy", () => {
    const real = boxFaceArea([line({ width_in: 24, height_in: 30 })]);
    const withFiller = boxFaceArea([
      line({ width_in: 24, height_in: 30 }),
      line({ tag: "Base Filler 3", width_in: 3, height_in: 30 }),
    ]);
    expect(withFiller).toBe(real);
  });
});

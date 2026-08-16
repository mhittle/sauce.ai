import { describe, expect, it } from "vitest";
import { PageExtraction } from "../src/schemas.js";

describe("PageExtraction unit_multipliers leniency", () => {
  it("keeps valid multipliers intact", () => {
    const parsed = PageExtraction.parse({
      lines: [],
      unit_multipliers: [{ unit_type: "Unit A", count: 24, ambiguous: false }],
    });
    expect(parsed.unit_multipliers).toEqual([
      { unit_type: "Unit A", count: 24, ambiguous: false },
    ]);
  });

  it("coerces a zero/negative count to null instead of dropping the page", () => {
    const parsed = PageExtraction.parse({
      lines: [],
      unit_multipliers: [
        { unit_type: "Unit A", count: 0, ambiguous: false },
        { unit_type: "Unit B", count: -2, ambiguous: false },
      ],
    });
    expect(parsed.unit_multipliers.map((m) => m.count)).toEqual([null, null]);
  });

  it("replaces an unparseable multiplier entry with an ambiguous placeholder", () => {
    const parsed = PageExtraction.parse({
      lines: [],
      unit_multipliers: ["garbage"],
    });
    expect(parsed.unit_multipliers).toEqual([
      { unit_type: "unrecognized", count: null, ambiguous: true },
    ]);
  });
});

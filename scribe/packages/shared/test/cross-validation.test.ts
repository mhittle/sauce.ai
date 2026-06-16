import { describe, expect, it } from "vitest";
import { applyCrossValidation } from "../src/cross-validation.js";
import type { CabinetLineItem } from "../src/schemas.js";

function line(over: Partial<CabinetLineItem> = {}): CabinetLineItem {
  return {
    source_page: 1,
    tag: "B24",
    room: null,
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
    confidence: 0.95,
    ...over,
  };
}

describe("applyCrossValidation", () => {
  it("leaves agreeing lines untouched", () => {
    const primary = [line()];
    const { lines, flags } = applyCrossValidation(primary, [line()]);
    expect(lines[0].confidence).toBe(0.95);
    expect(lines[0].notes).toBeNull();
    expect(flags).toHaveLength(0);
  });

  it("lowers confidence and notes when secondary disagrees on qty", () => {
    const { lines, flags } = applyCrossValidation(
      [line({ qty: 3 })],
      [line({ qty: 4 })]
    );
    expect(lines[0].confidence).toBeLessThan(0.8);
    expect(lines[0].notes).toContain("cross-val");
    expect(flags[0].kind).toBe("disagreement");
    expect(flags[0].detail).toContain("qty 3≠4");
  });

  it("flags dimension disagreement beyond tolerance", () => {
    const { lines, flags } = applyCrossValidation(
      [line({ width_in: 24 })],
      [line({ width_in: 30 })]
    );
    expect(lines[0].confidence).toBeLessThan(0.8);
    expect(flags[0].detail).toContain("width 24≠30");
  });

  it("tolerates sub-0.51in dimension differences", () => {
    const { lines, flags } = applyCrossValidation(
      [line({ width_in: 24 })],
      [line({ width_in: 24.4 })]
    );
    expect(lines[0].confidence).toBe(0.95);
    expect(flags).toHaveLength(0);
  });

  it("lowers confidence for a primary line the secondary missed", () => {
    const { lines, flags } = applyCrossValidation([line()], []);
    expect(lines[0].confidence).toBeLessThanOrEqual(0.7);
    expect(lines[0].notes).toContain("not found");
    expect(flags[0].kind).toBe("missing_in_secondary");
  });

  it("flags secondary-only lines without injecting them", () => {
    const { lines, flags } = applyCrossValidation(
      [],
      [line({ tag: "W3030", category: "casework_wall" })]
    );
    expect(lines).toHaveLength(0);
    expect(flags[0].kind).toBe("missing_in_primary");
    expect(flags[0].tag).toBe("W3030");
  });

  it("matches one-to-one (does not reuse a secondary line)", () => {
    const primary = [line({ qty: 2 }), line({ qty: 2 })];
    const secondary = [line({ qty: 2 })];
    const { lines, flags } = applyCrossValidation(primary, secondary);
    const missing = flags.filter((f) => f.kind === "missing_in_secondary");
    expect(missing).toHaveLength(1);
    expect(lines.filter((l) => l.confidence < 0.8)).toHaveLength(1);
  });
});

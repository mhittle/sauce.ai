import { describe, expect, it } from "vitest";
import { expandToComponents } from "../src/index.js";
import type { CabinetLineItem } from "../src/schemas.js";

function cab(over: Partial<CabinetLineItem> = {}): CabinetLineItem {
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
    confidence: 0.4,
    estimated: true,
    ...over,
  };
}

describe("expandToComponents", () => {
  it("expands a 2-door base into one door face (qty 2)", () => {
    const faces = expandToComponents(cab({ notes: "2 doors", width_in: 30 }));
    expect(faces).toHaveLength(1);
    expect(faces[0].category).toBe("door");
    expect(faces[0].qty).toBe(2);
    expect(faces[0].width_in).toBe(15); // 30 / 2
    expect(faces[0].estimated).toBe(true);
  });

  it("expands a 3-drawer base into 3 full-width drawer fronts", () => {
    const faces = expandToComponents(
      cab({ tag: "Base 3 Drawers 18", notes: "3 drawers", width_in: 18 })
    );
    expect(faces).toHaveLength(1);
    expect(faces[0].category).toBe("drawer_front");
    expect(faces[0].qty).toBe(3);
    expect(faces[0].width_in).toBe(18);
  });

  it("handles drawer-over-door (1 drawer + 1 door)", () => {
    const faces = expandToComponents(cab({ notes: "1 door 1 drawer", width_in: 18 }));
    const kinds = faces.map((f) => f.category).sort();
    expect(kinds).toEqual(["door", "drawer_front"]);
    const drawer = faces.find((f) => f.category === "drawer_front")!;
    expect(drawer.height_in).toBeLessThanOrEqual(6); // stacked drawer is short
  });

  it("sink base defaults to 2 doors, no drawer", () => {
    const faces = expandToComponents(cab({ tag: "Sink Base 36", notes: null, width_in: 36 }));
    expect(faces).toHaveLength(1);
    expect(faces[0].category).toBe("door");
    expect(faces[0].qty).toBe(2);
  });

  it("multiplies faces by cabinet qty", () => {
    const faces = expandToComponents(cab({ notes: "2 doors", qty: 3 }));
    expect(faces[0].qty).toBe(6); // 2 doors × 3 cabinets
  });

  it("returns nothing for fridge surrounds / panels / cubbies", () => {
    expect(expandToComponents(cab({ tag: "Tall Refrigerator Surround 36" }))).toEqual([]);
    expect(expandToComponents(cab({ tag: "Cubby/Locker Base 48", notes: null }))).toEqual([]);
    // plural "Cubbies" must also be treated as open (no doors)
    expect(expandToComponents(cab({ tag: "Cubbies Base 48", notes: null }))).toEqual([]);
  });

  it("fillers and end panels (emitted as base) spawn no door/front faces", () => {
    expect(
      expandToComponents(cab({ tag: "Base Filler 3", notes: "filler", width_in: 3 }))
    ).toEqual([]);
    expect(
      expandToComponents(cab({ tag: "Base End Panel 1.5", notes: "end panel", width_in: 1.5 }))
    ).toEqual([]);
  });

  it("returns nothing for non-cabinet categories or missing dims", () => {
    expect(expandToComponents(cab({ category: "countertop" }))).toEqual([]);
    expect(expandToComponents(cab({ width_in: null }))).toEqual([]);
  });

  it("wall cabinet face uses full height (no toe-kick deduction)", () => {
    const faces = expandToComponents(
      cab({ category: "casework_wall", tag: "Wall 30x36", notes: "2 doors", height_in: 36, width_in: 30 })
    );
    expect(faces[0].height_in).toBe(36);
  });
});

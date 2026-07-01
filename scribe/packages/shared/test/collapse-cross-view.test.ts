import { describe, expect, it } from "vitest";
import type { CabinetLineItem } from "../src/schemas.js";
import { collapseCrossViewDuplicates } from "../src/index.js";

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

describe("collapseCrossViewDuplicates", () => {
  it("passes a single-view room through unchanged", () => {
    const lines = [
      line({ tag: "Base 24", room: "Kitchen" }),
      line({ tag: "Wall 30", room: "Kitchen", category: "casework_wall" }),
    ];
    expect(collapseCrossViewDuplicates(lines)).toHaveLength(2);
  });

  it("keeps each cabinet once when a room is enumerated in plan + elevation views", () => {
    // Same kitchen counted once in the plan and again on a wall elevation: the
    // raw room labels differ ("Kitchen" vs "Kitchen - North Wall") but normalize
    // to the same room. Expect the duplicate view to be dropped.
    const lines = [
      line({ tag: "Base 24", room: "Kitchen" }),
      line({ tag: "Wall 30", room: "Kitchen", category: "casework_wall" }),
      line({ tag: "Base 24", room: "Kitchen - North Wall" }),
      line({ tag: "Wall 30", room: "Kitchen - North Wall", category: "casework_wall" }),
    ];
    const out = collapseCrossViewDuplicates(lines);
    expect(out).toHaveLength(2);
    expect(out.map((l) => l.tag).sort()).toEqual(["Base 24", "Wall 30"]);
  });

  it("keeps the MAX per tag across views, not the sum (legit repeats survive)", () => {
    // The plan shows two physical Base 24 cabinets; the elevation re-draws one
    // of them. Keep 2 (the view that saw the most), not 1 and not 3.
    const lines = [
      line({ tag: "Base 24", room: "Kitchen" }),
      line({ tag: "Base 24", room: "Kitchen" }),
      line({ tag: "Base 24", room: "Kitchen - South Wall" }),
    ];
    const out = collapseCrossViewDuplicates(lines);
    expect(out).toHaveLength(2);
    expect(out.every((l) => l.tag === "Base 24")).toBe(true);
  });

  it("does not merge across genuinely different rooms", () => {
    const lines = [
      line({ tag: "Base 24", room: "Kitchen" }),
      line({ tag: "Base 24", room: "Laundry" }),
    ];
    expect(collapseCrossViewDuplicates(lines)).toHaveLength(2);
  });

  it("falls back to category when a line has no tag", () => {
    // Untagged elevation lines (common) key on category; the same category in
    // the plan and an elevation collapses to the max count seen in one view.
    const lines = [
      line({ tag: null, room: "Kitchen", category: "casework_wall" }),
      line({ tag: null, room: "Kitchen - East", category: "casework_wall" }),
    ];
    expect(collapseCrossViewDuplicates(lines)).toHaveLength(1);
  });
});

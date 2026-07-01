import { describe, expect, it } from "vitest";
import type { CabinetLineItem } from "../src/schemas.js";
import { routeByPageRole, pageClassToRole, type PageRole } from "../src/index.js";

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

const roles = (entries: [number, PageRole][]) => new Map<number, PageRole>(entries);

describe("pageClassToRole", () => {
  it("maps page classes to count-source roles", () => {
    expect(pageClassToRole("cabinet_schedule_table")).toBe("schedule");
    expect(pageClassToRole("floor_plan")).toBe("plan");
    expect(pageClassToRole("kitchen_or_millwork_elevation")).toBe("elevation");
    expect(pageClassToRole("finish_schedule")).toBe("other");
    expect(pageClassToRole("cover_index")).toBe("other");
  });
});

describe("routeByPageRole", () => {
  it("Regime A (plan present): counts the plan, drops elevation re-counts (Q14 shape)", () => {
    // floor plan = 2 distinct cabinets (correct); 2 elevations re-enumerate them
    // under varying room labels — these must NOT add to the count.
    const lines = [
      line({ source_page: 2, tag: "Base 24", room: "Kitchen" }),
      line({ source_page: 2, tag: "Sink Base 36", room: "Kitchen" }),
      line({ source_page: 5, tag: "Base 24", room: "Kitchen - North" }),
      line({ source_page: 6, tag: "Sink Base 36", room: "Kitchen Elevation A" }),
    ];
    const out = routeByPageRole(
      lines,
      roles([
        [2, "plan"],
        [5, "elevation"],
        [6, "elevation"],
      ])
    );
    expect(out.regime).toBe("plan");
    expect(out.lines).toHaveLength(2);
    expect(out.droppedFromOtherRoles).toBe(2);
  });

  it("Regime C (schedule present): counts the schedule, drops plan + elevations (Q19 shape)", () => {
    const lines = [
      line({ source_page: 1, tag: "A", room: "Schedule" }),
      line({ source_page: 1, tag: "B", room: "Schedule" }),
      line({ source_page: 3, tag: "A", room: "Kitchen 2" }),
      line({ source_page: 4, tag: "B", room: "Kitchen 2" }),
      line({ source_page: 5, tag: "C", room: "Kitchen 2" }),
    ];
    const out = routeByPageRole(
      lines,
      roles([
        [1, "schedule"],
        [3, "elevation"],
        [4, "elevation"],
        [5, "elevation"],
      ])
    );
    expect(out.regime).toBe("schedule");
    // schedule has A,B; the 3 elevation lines are dropped (incl. the phantom C).
    expect(out.lines.map((l) => l.tag).sort()).toEqual(["A", "B"]);
    expect(out.droppedFromOtherRoles).toBe(3);
  });

  it("Regime B (elevations only): counts elevations, collapsing cross-view dupes", () => {
    // collapseCrossViewDuplicates only merges views that share a NORMALIZED room
    // (it strips a "- <wall>" suffix), so the same vanity must be tagged
    // "Bath" / "Bath - <wall>" to be recognized as one room across two pages.
    const lines = [
      line({ source_page: 1, tag: "Vanity 60", room: "Bath" }),
      line({ source_page: 2, tag: "Vanity 60", room: "Bath - West Wall" }),
    ];
    const out = routeByPageRole(
      lines,
      roles([
        [1, "elevation"],
        [2, "elevation"],
      ])
    );
    expect(out.regime).toBe("elevation");
    // same vanity shown on two elevation views of one room -> collapsed to one.
    expect(out.lines).toHaveLength(1);
  });

  it("falls through to the next role when the higher one has no real boxes", () => {
    // 'plan' page is a misclassified site plan: zero cabinets. Count must come
    // from the elevation rather than zeroing out.
    const lines = [line({ source_page: 9, tag: "Base 24", room: "Kitchen" })];
    const out = routeByPageRole(
      lines,
      roles([
        [1, "plan"], // no lines from this page
        [9, "elevation"],
      ])
    );
    expect(out.regime).toBe("elevation");
    expect(out.lines).toHaveLength(1);
  });

  it("does not let a filler-only page win a role (non-box casework isn't a box)", () => {
    const lines = [
      line({ source_page: 1, tag: "Base Filler 3", category: "casework_base" }),
      line({ source_page: 2, tag: "Base 24" }),
    ];
    const out = routeByPageRole(
      lines,
      roles([
        [1, "plan"], // only a filler -> not counted as a box-bearing role
        [2, "elevation"],
      ])
    );
    expect(out.regime).toBe("elevation");
  });

  it("passthrough when no recognized count role has boxes", () => {
    const lines = [line({ source_page: 1, tag: "Base 24" })];
    const out = routeByPageRole(lines, roles([[1, "other"]]));
    expect(out.regime).toBe("passthrough");
    expect(out.lines).toHaveLength(1);
  });
});

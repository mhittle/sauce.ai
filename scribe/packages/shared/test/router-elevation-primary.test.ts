import { afterEach, describe, expect, it } from "vitest";
import {
  pageClassToRole,
  routeByPageRole,
  type CabinetLineItem,
  type PageRole,
} from "../src/index.js";

const cab = (over: Partial<CabinetLineItem>): CabinetLineItem => ({
  source_page: 1,
  tag: null,
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
  bbox_2d: null,
  ...over,
});

// Page 1 = floor plan, pages 2-3 = elevations (the Braun-style doc shape).
const roles = new Map<number, PageRole>([
  [1, pageClassToRole("floor_plan")],
  [2, pageClassToRole("kitchen_or_millwork_elevation")],
  [3, pageClassToRole("kitchen_or_millwork_elevation")],
]);

afterEach(() => {
  delete process.env.ROUTER_ELEVATION_PRIMARY;
});

describe("ROUTER_ELEVATION_PRIMARY=1", () => {
  it("counts from elevations when both plan and elevations produced boxes", () => {
    process.env.ROUTER_ELEVATION_PRIMARY = "1";
    const lines = [
      // Plan's coarse guesses.
      cab({ source_page: 1, tag: "Base Cabinet 48", width_in: 48 }),
      cab({ source_page: 1, tag: "Base Cabinet 48", width_in: 48 }),
      // Elevation's labeled units.
      cab({ source_page: 2, tag: "Sink Base 28", width_in: 28 }),
      cab({ source_page: 2, tag: "Dwr Base 30", width_in: 30 }),
      cab({
        source_page: 2,
        tag: "Pantry 18",
        category: "casework_tall",
        width_in: 18,
        height_in: 90,
      }),
    ];
    const routed = routeByPageRole(lines, roles);
    expect(routed.regime).toBe("elevation");
    const tags = routed.lines.map((l) => l.tag).sort();
    expect(tags).toContain("Sink Base 28");
    expect(tags).toContain("Pantry 18");
  });

  it("admits plan-only units no elevation accounts for (the island case)", () => {
    process.env.ROUTER_ELEVATION_PRIMARY = "1";
    const lines = [
      // Elevation covers the wall run…
      cab({ source_page: 2, tag: "Sink Base 30", width_in: 30 }),
      // …the plan repeats that unit (within ±3"w tolerance) AND shows an island.
      cab({ source_page: 1, tag: "Base Cabinet 30", width_in: 31 }),
      cab({ source_page: 1, tag: "Island Base 48", width_in: 48 }),
    ];
    const routed = routeByPageRole(lines, roles);
    expect(routed.regime).toBe("elevation");
    const tags = routed.lines.map((l) => l.tag);
    // Elevation unit kept, plan duplicate suppressed, plan-only island admitted.
    expect(tags).toContain("Sink Base 30");
    expect(tags).toContain("Island Base 48");
    expect(tags).not.toContain("Base Cabinet 30");
    expect(routed.droppedFromOtherRoles).toBe(1);
  });

  it("still falls back to the plan when no elevation produced a box", () => {
    process.env.ROUTER_ELEVATION_PRIMARY = "1";
    const lines = [cab({ source_page: 1, tag: "Base 24" })];
    const routed = routeByPageRole(lines, roles);
    expect(routed.regime).toBe("plan");
    expect(routed.lines).toHaveLength(1);
  });

  it("schedule still outranks everything", () => {
    process.env.ROUTER_ELEVATION_PRIMARY = "1";
    const withSchedule = new Map<number, PageRole>([
      ...roles,
      [4, pageClassToRole("cabinet_schedule_table")],
    ]);
    const lines = [
      cab({ source_page: 2, tag: "Sink Base 28", width_in: 28 }),
      cab({ source_page: 4, tag: "B24", estimated: false }),
    ];
    const routed = routeByPageRole(lines, withSchedule);
    expect(routed.regime).toBe("schedule");
    expect(routed.lines.map((l) => l.tag)).toEqual(["B24"]);
  });

  it("flag unset keeps the plan-first default", () => {
    const lines = [
      cab({ source_page: 1, tag: "Base Cabinet 48", width_in: 48 }),
      cab({ source_page: 2, tag: "Sink Base 28", width_in: 28 }),
    ];
    const routed = routeByPageRole(lines, roles);
    expect(routed.regime).toBe("plan");
    expect(routed.lines.map((l) => l.tag)).toEqual(["Base Cabinet 48"]);
  });
});

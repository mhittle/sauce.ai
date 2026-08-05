import { afterEach, describe, expect, it } from "vitest";
import {
  admitUnmatchedLines,
  collapseDuplicatePages,
  routeByPageRole,
  type CabinetLineItem,
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
  ...over,
});

describe("admitUnmatchedLines", () => {
  it("suppresses demoted units already covered by kept units (within tolerance)", () => {
    const kept = [cab({ width_in: 36 })];
    const demoted = [cab({ source_page: 2, width_in: 34 })]; // Δw=2 ≤ 3 → same cabinet
    expect(admitUnmatchedLines(kept, demoted)).toHaveLength(0);
  });

  it("admits demoted units no kept unit accounts for", () => {
    const kept = [cab({ width_in: 36 })];
    const demoted = [
      cab({ source_page: 2, width_in: 36 }), // covered
      cab({ source_page: 2, width_in: 18 }), // new
      cab({ source_page: 2, category: "casework_wall", width_in: 30, height_in: 42 }), // new (category)
    ];
    const out = admitUnmatchedLines(kept, demoted);
    expect(out.map((l) => [l.category, l.width_in])).toEqual([
      ["casework_base", 18],
      ["casework_wall", 30],
    ]);
  });

  it("works at unit level: qty is consumed and the remainder admitted", () => {
    const kept = [cab({ width_in: 24, qty: 1 })];
    const demoted = [cab({ source_page: 2, width_in: 24, qty: 3 })];
    const out = admitUnmatchedLines(kept, demoted);
    expect(out).toHaveLength(1);
    expect(out[0].qty).toBe(2);
  });

  it("null-dim kept lines never suppress sized demoted cabinets", () => {
    const kept = [cab({ width_in: null, height_in: null })];
    const demoted = [cab({ source_page: 2, width_in: 24 })];
    expect(admitUnmatchedLines(kept, demoted)).toHaveLength(1);
  });
});

describe("collapseDuplicatePages", () => {
  it("drops a page that re-renders the same wall (Q24 case)", () => {
    const wall = (page: number) => [
      cab({ source_page: page, category: "vanity", width_in: 15 }),
      cab({ source_page: page, category: "vanity", width_in: 24 }),
      cab({ source_page: page, category: "vanity", width_in: 30 }),
      cab({ source_page: page, category: "casework_tall", width_in: 24, height_in: 84 }),
    ];
    const out = collapseDuplicatePages([...wall(1), ...wall(2)]);
    expect(out).toHaveLength(4);
    expect(new Set(out.map((l) => l.source_page))).toEqual(new Set([1]));
  });

  it("keeps genuinely different pages (different walls, Q5 case)", () => {
    const p2 = [
      cab({ source_page: 2, width_in: 36 }),
      cab({ source_page: 2, category: "casework_wall", width_in: 30, height_in: 42 }),
    ];
    const p3 = [
      cab({ source_page: 3, category: "casework_tall", width_in: 46, height_in: 96 }),
      cab({ source_page: 3, width_in: 18 }),
    ];
    expect(collapseDuplicatePages([...p2, ...p3])).toHaveLength(4);
  });

  it("never merges pages with a single unit", () => {
    const a = cab({ source_page: 1, width_in: 24 });
    const b = cab({ source_page: 2, width_in: 24 });
    expect(collapseDuplicatePages([a, b])).toHaveLength(2);
  });
});

describe("routeByPageRole with ROUTER_TOLERANT_MERGE=1", () => {
  afterEach(() => {
    delete process.env.ROUTER_TOLERANT_MERGE;
  });

  it("keeps plan lines AND admits elevation-only cabinets instead of dropping them", () => {
    process.env.ROUTER_TOLERANT_MERGE = "1";
    const roleByPage = new Map<number, "schedule" | "plan" | "elevation" | "other">([
      [1, "plan"],
      [2, "elevation"],
    ]);
    const lines = [
      cab({ source_page: 1, width_in: 36 }), // plan
      cab({ source_page: 2, width_in: 36 }), // elevation dup of the plan read
      cab({ source_page: 2, category: "casework_wall", width_in: 30, height_in: 42 }), // only on elevation
      cab({ source_page: 2, category: "casework_tall", width_in: 46, height_in: 96 }), // only on elevation
    ];
    const routed = routeByPageRole(lines, roleByPage);
    expect(routed.regime).toBe("plan");
    expect(routed.lines).toHaveLength(3); // 1 plan + 2 admitted
    expect(routed.droppedFromOtherRoles).toBe(1); // the duplicate 36" base
  });

  it("default behavior unchanged when the gate is off", () => {
    const roleByPage = new Map<number, "schedule" | "plan" | "elevation" | "other">([
      [1, "plan"],
      [2, "elevation"],
    ]);
    const lines = [
      cab({ source_page: 1, width_in: 36 }),
      cab({ source_page: 2, category: "casework_wall", width_in: 30, height_in: 42 }),
    ];
    const routed = routeByPageRole(lines, roleByPage);
    expect(routed.regime).toBe("plan");
    expect(routed.lines).toHaveLength(1);
    expect(routed.droppedFromOtherRoles).toBe(1);
  });
});

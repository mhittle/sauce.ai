import { describe, expect, it } from "vitest";
import {
  clampRectToPage,
  dedupeLines,
  fitDpi,
  mapBoxToPagePoints,
  MODEL_MAX_EDGE_PX,
  MODEL_MAX_TOKENS,
  needsRegioning,
  padRectToPage,
  parsePageRegionsLenient,
  planRenderJobs,
  VISUAL_PATCH_PX,
} from "../src/regions.js";
import type { CabinetLineItem } from "../src/schemas.js";

const PT = 72;
// ANSI/Arch D landscape sheet (36x24") — the validated "too big" case.
const D_SHEET = { widthPt: 36 * PT, heightPt: 24 * PT };
// US letter landscape — should never need tiling.
const LETTER = { widthPt: 11 * PT, heightPt: 8.5 * PT };

function line(over: Partial<CabinetLineItem> = {}): CabinetLineItem {
  return {
    source_page: 1,
    tag: null,
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
    confidence: 0.9,
    ...over,
  };
}

function patches(w: number, h: number): number {
  return (
    Math.ceil(w / VISUAL_PATCH_PX) * Math.ceil(h / VISUAL_PATCH_PX)
  );
}

describe("needsRegioning", () => {
  it("flags large-format sheets", () => {
    expect(needsRegioning(D_SHEET)).toBe(true);
  });
  it("does not flag letter-size pages", () => {
    expect(needsRegioning(LETTER)).toBe(false);
  });
});

describe("fitDpi", () => {
  it("respects the long-edge limit", () => {
    // 36" wide: edge-bound dpi = 1568/36 ≈ 43.6
    expect(fitDpi(36, 24)).toBeLessThanOrEqual(MODEL_MAX_EDGE_PX / 36 + 0.01);
  });
  it("never exceeds the ceiling for small crops", () => {
    expect(fitDpi(2, 2, MODEL_MAX_EDGE_PX, MODEL_MAX_TOKENS, 200)).toBe(200);
  });
});

describe("planRenderJobs", () => {
  it("renders a letter page as a single legible image", () => {
    const rect = { x0: 0, y0: 0, x1: LETTER.widthPt, y1: LETTER.heightPt };
    const jobs = planRenderJobs(rect, LETTER, 0, "elevation");
    expect(jobs).toHaveLength(1);
    expect(jobs[0].widthPx).toBeLessThanOrEqual(MODEL_MAX_EDGE_PX);
    expect(jobs[0].heightPx).toBeLessThanOrEqual(MODEL_MAX_EDGE_PX);
  });

  it("tiles a full D-size sheet into multiple jobs", () => {
    const rect = { x0: 0, y0: 0, x1: D_SHEET.widthPt, y1: D_SHEET.heightPt };
    const jobs = planRenderJobs(rect, D_SHEET, 0, "schedule");
    expect(jobs.length).toBeGreaterThan(1);
  });

  it("keeps every job within the model's edge and token budgets", () => {
    const rect = { x0: 0, y0: 0, x1: D_SHEET.widthPt, y1: D_SHEET.heightPt };
    const jobs = planRenderJobs(rect, D_SHEET, 0, "schedule");
    for (const j of jobs) {
      expect(j.widthPx).toBeLessThanOrEqual(MODEL_MAX_EDGE_PX);
      expect(j.heightPx).toBeLessThanOrEqual(MODEL_MAX_EDGE_PX);
      // allow a 1-patch rounding slack
      expect(patches(j.widthPx, j.heightPx)).toBeLessThanOrEqual(
        MODEL_MAX_TOKENS + VISUAL_PATCH_PX * 4
      );
    }
  });

  it("renders tiled jobs at a legible DPI", () => {
    const rect = { x0: 0, y0: 0, x1: D_SHEET.widthPt, y1: D_SHEET.heightPt };
    const jobs = planRenderJobs(rect, D_SHEET, 0, "schedule");
    for (const j of jobs) expect(j.dpi).toBeGreaterThanOrEqual(100);
  });

  it("covers the whole rect (tiles span corner to corner)", () => {
    const rect = { x0: 0, y0: 0, x1: D_SHEET.widthPt, y1: D_SHEET.heightPt };
    const jobs = planRenderJobs(rect, D_SHEET, 0, "schedule");
    const minX = Math.min(...jobs.map((j) => j.rect.x0));
    const minY = Math.min(...jobs.map((j) => j.rect.y0));
    const maxX = Math.max(...jobs.map((j) => j.rect.x1));
    const maxY = Math.max(...jobs.map((j) => j.rect.y1));
    expect(minX).toBeCloseTo(0, 5);
    expect(minY).toBeCloseTo(0, 5);
    expect(maxX).toBeCloseTo(D_SHEET.widthPt, 5);
    expect(maxY).toBeCloseTo(D_SHEET.heightPt, 5);
  });

  it("tags all jobs with the given region id and kind", () => {
    const rect = { x0: 0, y0: 0, x1: D_SHEET.widthPt, y1: D_SHEET.heightPt };
    const jobs = planRenderJobs(rect, D_SHEET, 7, "plan");
    for (const j of jobs) {
      expect(j.regionId).toBe(7);
      expect(j.regionKind).toBe("plan");
    }
  });
});

describe("mapBoxToPagePoints", () => {
  it("maps a pixel box back to page points by uniform scale", () => {
    // page 720x480 pt rendered to 1500x1000 px → scale 0.48 pt/px
    const rect = mapBoxToPagePoints(
      [750, 0, 1500, 500],
      { widthPx: 1500, heightPx: 1000 },
      { widthPt: 720, heightPt: 480 }
    );
    expect(rect.x0).toBeCloseTo(360, 5);
    expect(rect.y0).toBeCloseTo(0, 5);
    expect(rect.x1).toBeCloseTo(720, 5);
    expect(rect.y1).toBeCloseTo(240, 5);
  });

  it("normalizes inverted boxes", () => {
    const rect = mapBoxToPagePoints(
      [1500, 500, 750, 0],
      { widthPx: 1500, heightPx: 1000 },
      { widthPt: 720, heightPt: 480 }
    );
    expect(rect.x0).toBeLessThan(rect.x1);
    expect(rect.y0).toBeLessThan(rect.y1);
  });
});

describe("padRectToPage / clampRectToPage", () => {
  it("expands a region but never past the page edge", () => {
    const padded = padRectToPage(
      { x0: 0, y0: 0, x1: 100, y1: 100 },
      0.5,
      { widthPt: 200, heightPt: 200 }
    );
    expect(padded.x0).toBe(0); // would be -50, clamped
    expect(padded.x1).toBe(150);
  });

  it("clamps out-of-bounds rects", () => {
    const r = clampRectToPage(
      { x0: -10, y0: -10, x1: 999, y1: 999 },
      { widthPt: 200, heightPt: 200 }
    );
    expect(r).toEqual({ x0: 0, y0: 0, x1: 200, y1: 200 });
  });
});

describe("parsePageRegionsLenient", () => {
  it("keeps well-formed regions and drops malformed ones", () => {
    const out = parsePageRegionsLenient({
      regions: [
        { kind: "plan", box: [0, 0, 100, 100], confidence: 0.9 },
        { kind: "plan", box: [[1, 2], 3, 4] }, // malformed box (nested array)
        { kind: "elevation", box: [10, 10, 50, 50] }, // confidence defaults
        { box: [0, 0, 1, 1] }, // missing kind
      ],
    });
    expect(out.regions).toHaveLength(2);
    expect(out.regions[0].kind).toBe("plan");
    expect(out.regions[1].confidence).toBe(0.5);
  });

  it("returns empty regions for junk input", () => {
    expect(parsePageRegionsLenient(null).regions).toEqual([]);
    expect(parsePageRegionsLenient({}).regions).toEqual([]);
    expect(parsePageRegionsLenient({ regions: "nope" }).regions).toEqual([]);
  });
});

describe("dedupeLines", () => {
  it("merges duplicate tagged lines, keeping the higher confidence", () => {
    const out = dedupeLines([
      line({ tag: "B24", confidence: 0.6 }),
      line({ tag: "B24", confidence: 0.9 }),
    ]);
    expect(out).toHaveLength(1);
    expect(out[0].confidence).toBe(0.9);
  });

  it("merges identical untagged lines (overlapping-tile dupes)", () => {
    const out = dedupeLines([
      line({ tag: null, width_in: 36, room: "Kitchen", confidence: 0.7 }),
      line({ tag: null, width_in: 36, room: "Kitchen", confidence: 0.8 }),
    ]);
    expect(out).toHaveLength(1);
    expect(out[0].confidence).toBe(0.8);
  });

  it("keeps distinct lines", () => {
    const out = dedupeLines([
      line({ tag: "B24" }),
      line({ tag: "W3030", category: "casework_wall" }),
      line({ tag: null, width_in: 30 }),
      line({ tag: null, width_in: 36 }),
    ]);
    expect(out).toHaveLength(4);
  });

  it("preserves input order", () => {
    const out = dedupeLines([
      line({ tag: "A", confidence: 0.5 }),
      line({ tag: "B", confidence: 0.5 }),
      line({ tag: "A", confidence: 0.9 }),
    ]);
    expect(out.map((l) => l.tag)).toEqual(["A", "B"]);
  });
});

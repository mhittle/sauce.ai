import { z } from "zod";
import type { CabinetLineItem, PageClass } from "./schemas.js";

// ---------------------------------------------------------------------------
// Region detection + render planning (PRD §4 — legible large-format reads).
//
// Claude downscales any image past the model's native vision resolution before
// it sees it (Sonnet 4.6: 1568 px long edge AND a ~1568 visual-token budget,
// where one token = a 28x28 px patch). A 36x44" sheet rendered at 200 DPI is
// squashed to ~1568 px and its schedule text becomes ~4 px — illegible. The
// fix is to read the page in pieces small enough to render at a legible DPI
// without tripping either limit, instead of squashing the whole sheet.
//
// This module is pure (IO-free): the worker handles the actual rasterization
// and model calls; here we only decide *what rectangles to render and at what
// DPI*, and de-duplicate lines that overlapping tiles see twice.
// ---------------------------------------------------------------------------

// Sonnet 4.6 vision limits. Kept as defaults so an Opus high-res model
// (2576 px / 4784 tokens) can be passed in later without touching callers.
export const MODEL_MAX_EDGE_PX = 1568;
export const MODEL_MAX_TOKENS = 1530; // a hair under 1568 for safety margin
export const VISUAL_PATCH_PX = 28;

// Below this effective DPI a single image's small annotation text (dimension
// strings on a 1/2"=1'-0" elevation) stops being legible, so the rect must be
// read in tiles rather than as one image. Letter-size design sheets fit above
// this floor in one shot; large-format sheets fall well below it.
export const MIN_LEGIBLE_DPI = 100;
// Target DPI when a region must be tiled — a notch above the floor so tiled
// reads are comfortably legible, while keeping tile counts sane on big sheets.
export const TILE_TARGET_DPI = 120;
// Don't render any single image above this (a small crop would otherwise be
// rendered absurdly large before the model downscales it anyway).
export const RENDER_DPI_CEILING = 200;

export interface PageDims {
  widthPt: number;
  heightPt: number;
}

export interface RectPt {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

// One thing to rasterize and send to the extractor.
export interface RenderJob {
  rect: RectPt; // crop rectangle in PDF points
  dpi: number;
  widthPx: number;
  heightPx: number;
  regionId: number; // overlapping tiles of the same source region share this
  regionKind: RegionKind;
}

export const RegionKind = z.enum([
  "schedule",
  "elevation",
  "plan",
  "other",
]);
export type RegionKind = z.infer<typeof RegionKind>;

// One located region in pixel coordinates of the sent image.
export const PageRegion = z.object({
  kind: RegionKind,
  // [x0, y0, x1, y1] in pixels of the sent image.
  box: z.tuple([z.number(), z.number(), z.number(), z.number()]),
  confidence: z.number().min(0).max(1).default(0.5),
});
export type PageRegion = z.infer<typeof PageRegion>;

// Output of the vision "locate" call: distinct drawings / rooms on a sheet.
export const PageRegions = z.object({
  regions: z.array(PageRegion).default([]),
});
export type PageRegions = z.infer<typeof PageRegions>;

// Lenient parse: keep the well-formed regions, drop malformed ones (a single
// bad box from the model must not discard the whole locate result).
export function parsePageRegionsLenient(raw: unknown): PageRegions {
  const obj = (raw ?? {}) as { regions?: unknown };
  const arr = Array.isArray(obj.regions) ? obj.regions : [];
  const regions = arr.flatMap((r) => {
    const parsed = PageRegion.safeParse(r);
    return parsed.success ? [parsed.data] : [];
  });
  return { regions };
}

const PT_PER_IN = 72;

function ceilDiv(a: number, b: number): number {
  return Math.ceil(a / b);
}

function patchCount(widthPx: number, heightPx: number): number {
  return (
    Math.ceil(widthPx / VISUAL_PATCH_PX) * Math.ceil(heightPx / VISUAL_PATCH_PX)
  );
}

// A full-page single render is only legible when it isn't downscaled hard —
// i.e. the whole page fits in one image at or above the legibility floor.
export function needsRegioning(
  page: PageDims,
  maxEdgePx = MODEL_MAX_EDGE_PX,
  maxTokens = MODEL_MAX_TOKENS
): boolean {
  const widthIn = page.widthPt / PT_PER_IN;
  const heightIn = page.heightPt / PT_PER_IN;
  if (widthIn <= 0 || heightIn <= 0) return false;
  return fitDpi(widthIn, heightIn, maxEdgePx, maxTokens) < MIN_LEGIBLE_DPI;
}

// Largest DPI (capped at ceiling) at which a rect of the given size fits both
// the edge-length and visual-token budgets in a single image.
export function fitDpi(
  widthIn: number,
  heightIn: number,
  maxEdgePx = MODEL_MAX_EDGE_PX,
  maxTokens = MODEL_MAX_TOKENS,
  ceiling = RENDER_DPI_CEILING
): number {
  const longEdgeIn = Math.max(widthIn, heightIn);
  if (longEdgeIn <= 0) return ceiling;
  const byEdge = maxEdgePx / longEdgeIn;
  // patches ≈ (wIn*dpi/28)*(hIn*dpi/28) = wIn*hIn*dpi²/28² ≤ maxTokens
  const byTokens =
    VISUAL_PATCH_PX * Math.sqrt(maxTokens / Math.max(widthIn * heightIn, 1e-6));
  return Math.max(1, Math.min(ceiling, byEdge, byTokens));
}

function makeJob(
  rect: RectPt,
  dpi: number,
  regionId: number,
  regionKind: RegionKind
): RenderJob {
  const widthPx = Math.max(1, Math.round(((rect.x1 - rect.x0) / PT_PER_IN) * dpi));
  const heightPx = Math.max(1, Math.round(((rect.y1 - rect.y0) / PT_PER_IN) * dpi));
  return { rect, dpi, widthPx, heightPx, regionId, regionKind };
}

export function clampRectToPage(rect: RectPt, page: PageDims): RectPt {
  return {
    x0: Math.max(0, Math.min(rect.x0, page.widthPt)),
    y0: Math.max(0, Math.min(rect.y0, page.heightPt)),
    x1: Math.max(0, Math.min(rect.x1, page.widthPt)),
    y1: Math.max(0, Math.min(rect.y1, page.heightPt)),
  };
}

// Expand a detected region a little so titles/dimension strings at its edge
// aren't clipped, then clamp to the page.
export function padRectToPage(
  rect: RectPt,
  padFrac: number,
  page: PageDims
): RectPt {
  const padX = (rect.x1 - rect.x0) * padFrac;
  const padY = (rect.y1 - rect.y0) * padFrac;
  return clampRectToPage(
    {
      x0: rect.x0 - padX,
      y0: rect.y0 - padY,
      x1: rect.x1 + padX,
      y1: rect.y1 + padY,
    },
    page
  );
}

// Map a model-returned pixel box (relative to the sent image) back to PDF
// points on the page. The sent image is the page rendered to fit, so the
// scale is uniform.
export function mapBoxToPagePoints(
  box: [number, number, number, number],
  sentImage: { widthPx: number; heightPx: number },
  page: PageDims
): RectPt {
  const sx = page.widthPt / sentImage.widthPx;
  const sy = page.heightPt / sentImage.heightPx;
  const x0 = Math.min(box[0], box[2]);
  const x1 = Math.max(box[0], box[2]);
  const y0 = Math.min(box[1], box[3]);
  const y1 = Math.max(box[1], box[3]);
  return clampRectToPage(
    { x0: x0 * sx, y0: y0 * sy, x1: x1 * sx, y1: y1 * sy },
    page
  );
}

export interface PlanOptions {
  maxEdgePx?: number;
  maxTokens?: number;
  targetDpi?: number;
  ceiling?: number;
  overlapFrac?: number;
}

// Turn a rectangle into one or more render jobs that each fit the model's
// vision budget. Small rects → one job at the best legible DPI; rects too
// large to read legibly in one image → an overlapping grid at the target DPI.
export function planRenderJobs(
  rect: RectPt,
  page: PageDims,
  regionId: number,
  regionKind: RegionKind,
  opts: PlanOptions = {}
): RenderJob[] {
  const maxEdgePx = opts.maxEdgePx ?? MODEL_MAX_EDGE_PX;
  const maxTokens = opts.maxTokens ?? MODEL_MAX_TOKENS;
  const targetDpi = opts.targetDpi ?? TILE_TARGET_DPI;
  const ceiling = opts.ceiling ?? RENDER_DPI_CEILING;
  const overlapFrac = opts.overlapFrac ?? 0.06;

  const r = clampRectToPage(rect, page);
  const widthIn = (r.x1 - r.x0) / PT_PER_IN;
  const heightIn = (r.y1 - r.y0) / PT_PER_IN;
  if (widthIn <= 0 || heightIn <= 0) return [];

  // Fits legibly in a single image?
  const oneShotDpi = fitDpi(widthIn, heightIn, maxEdgePx, maxTokens, ceiling);
  if (oneShotDpi >= MIN_LEGIBLE_DPI) {
    return [makeJob(r, oneShotDpi, regionId, regionKind)];
  }

  // Otherwise tile. Size cells so each fits the budget at the target DPI.
  const cellMaxEdgeIn = maxEdgePx / targetDpi;
  const cellMaxSideByTokens =
    (VISUAL_PATCH_PX / targetDpi) * Math.sqrt(maxTokens);
  const cellSideIn = Math.min(cellMaxEdgeIn, cellMaxSideByTokens);

  const cols = Math.max(1, ceilDiv(widthIn, cellSideIn));
  const rows = Math.max(1, ceilDiv(heightIn, cellSideIn));
  const tileWpt = (r.x1 - r.x0) / cols;
  const tileHpt = (r.y1 - r.y0) / rows;
  const overlapXpt = tileWpt * overlapFrac;
  const overlapYpt = tileHpt * overlapFrac;

  const jobs: RenderJob[] = [];
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const tile = clampRectToPage(
        {
          x0: r.x0 + col * tileWpt - (col > 0 ? overlapXpt : 0),
          y0: r.y0 + row * tileHpt - (row > 0 ? overlapYpt : 0),
          x1: r.x0 + (col + 1) * tileWpt + (col < cols - 1 ? overlapXpt : 0),
          y1: r.y0 + (row + 1) * tileHpt + (row < rows - 1 ? overlapYpt : 0),
        },
        page
      );
      const tWin = (tile.x1 - tile.x0) / PT_PER_IN;
      const tHin = (tile.y1 - tile.y0) / PT_PER_IN;
      // Recompute DPI for the (slightly larger) overlapped tile so it still fits.
      const dpi = fitDpi(tWin, tHin, maxEdgePx, maxTokens, ceiling);
      jobs.push(makeJob(tile, dpi, regionId, regionKind));
    }
  }
  return jobs;
}

// De-duplicate lines that overlapping tiles of the SAME region saw twice.
// Tagged lines key on their tag (a unique cabinet identifier); untagged lines
// (common on elevations) key on category + dimensions + room + door style.
// Keep the highest-confidence instance. Only call this within one region —
// distinct drawings legitimately repeat tags/sizes and must not be merged.
export function dedupeLines<T extends CabinetLineItem>(lines: T[]): T[] {
  const byKey = new Map<string, T>();
  const out: T[] = [];
  for (const line of lines) {
    const key =
      line.tag != null && line.tag.trim() !== ""
        ? `tag:${line.tag.trim().toLowerCase()}`
        : [
            "u",
            line.category,
            line.width_in ?? "",
            line.height_in ?? "",
            line.depth_in ?? "",
            (line.room ?? "").toLowerCase(),
            (line.door_style ?? "").toLowerCase(),
            line.qty,
          ].join("|");
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, line);
      out.push(line);
    } else if (line.confidence > existing.confidence) {
      // Replace in place: keep output order stable, swap to the better copy.
      const idx = out.indexOf(existing);
      if (idx !== -1) out[idx] = line;
      byKey.set(key, line);
    }
  }
  return out;
}

// Collapse cross-VIEW duplication in no-schedule estimation: a room shown in
// BOTH a floor plan and its elevations gets enumerated once per view ("Kitchen"
// vs "Kitchen - North Wall Run"), and the estimate path sums every region with
// no dedup — so multi-view inputs balloon 2-4x. Collapse per NORMALIZED room
// (strip the "- <wall>" suffix): for each cabinet tag keep the MAX count seen
// in any single view (not the sum), which removes cross-view duplicates while
// preserving legitimate repeats. Single-view rooms pass through unchanged.
// Shared by the real pipeline (takeoff/process) and the backtest harness so the
// two never drift.
export function collapseCrossViewDuplicates<T extends CabinetLineItem>(
  lines: T[]
): T[] {
  const normRoom = (r: string | null) =>
    (r ?? "").toLowerCase().split(/[-—–]/)[0].trim();
  const tagKey = (l: T) => (l.tag ?? l.category ?? "").toLowerCase().trim();
  const byRoom = new Map<string, T[]>();
  for (const l of lines) {
    const k = normRoom(l.room);
    byRoom.set(k, [...(byRoom.get(k) ?? []), l]);
  }
  const out: T[] = [];
  for (const roomLines of byRoom.values()) {
    // group this room's lines by source view (raw room label)
    const byView = new Map<string, T[]>();
    for (const l of roomLines) {
      const v = (l.room ?? "").toLowerCase().trim();
      byView.set(v, [...(byView.get(v) ?? []), l]);
    }
    // per cabinet tag, keep the view that enumerated the most of it
    const bestPerTag = new Map<string, T[]>();
    for (const viewLines of byView.values()) {
      const tagCount = new Map<string, T[]>();
      for (const l of viewLines)
        tagCount.set(tagKey(l), [...(tagCount.get(tagKey(l)) ?? []), l]);
      for (const [t, ls] of tagCount) {
        if ((bestPerTag.get(t)?.length ?? 0) < ls.length) bestPerTag.set(t, ls);
      }
    }
    for (const ls of bestPerTag.values()) out.push(...ls);
  }
  return out;
}

// Pick the element with the MEDIAN `count` (lower median for even-sized inputs).
// Used to tame run-to-run vision variance (SCR-006): reading the same estimate
// page N times and keeping the median read discards the occasional outlier.
// Throws on an empty input — callers must pass at least one candidate.
export function pickMedian<T>(items: T[], count: (t: T) => number): T {
  if (items.length === 0) throw new Error("pickMedian: no candidates");
  const sorted = [...items].sort((a, b) => count(a) - count(b));
  return sorted[Math.floor((sorted.length - 1) / 2)];
}

const PRICED_BOX_CATEGORIES = new Set([
  "casework_base",
  "casework_wall",
  "casework_tall",
  "vanity",
]);

// Quote-total proxy for a set of estimate lines: the total cabinet FACE AREA
// (sum of width×height×qty over box lines, in in²). Box price AND door/front ft²
// both scale with this, so it tracks the quote far better than a raw box COUNT —
// two reads with the same count but different sizes price very differently (Q8:
// same 20 boxes priced −6% vs −28%). Used to select the median-of-N consensus
// read (SCR-006) by the thing that actually drives the total, not by count.
// Faces (door/drawer_front) and zero-dimension lines are skipped.
export function boxFaceArea(lines: CabinetLineItem[]): number {
  let area = 0;
  for (const l of lines) {
    if (!PRICED_BOX_CATEGORIES.has(l.category)) continue;
    if (isNonBoxCasework(l)) continue; // fillers/crown/returns aren't real boxes
    const w = l.width_in ?? 0;
    const h = l.height_in ?? 0;
    if (w > 0 && h > 0) area += w * h * (l.qty ?? 1);
  }
  return area;
}

// ---------------------------------------------------------------------------
// Non-box casework (fillers, end panels, crown/returns, toe-kick, scribe…)
// ---------------------------------------------------------------------------
// The estimator emits fillers and end panels as `casework_base` (so they price
// SOMETHING and skip door-face expansion), and the model sometimes emits crown
// molding / returns / light rail / toe-kick the same way. Priced through the box
// formula, a 3" filler strip or a length of crown is charged as a full cabinet
// carcass — a real over-read $ (e.g. Q24, a tiny vanity job, ballooned +132%
// partly on filler/molding pricing). These aren't cabinet boxes; detect them so
// the caller can stop box-pricing them.
const NON_BOX_CASEWORK_RE =
  /\b(filler|end[\s-]?panel|end[\s-]?cap|crown|valance|light[\s-]?rail|toe[\s-]?kick|toekick|scribe|mould?ing|return|riser|skin|spacer)\b/i;

// True when a line is a box-category casework item that is really trim/filler,
// not a cabinet box. Only box categories can be mislabeled this way; faces and
// non-box categories return false.
export function isNonBoxCasework(line: {
  tag: string | null;
  notes?: string | null;
  category: string;
}): boolean {
  if (!PRICED_BOX_CATEGORIES.has(line.category)) return false;
  return NON_BOX_CASEWORK_RE.test(`${line.tag ?? ""} ${line.notes ?? ""}`);
}

// Drop fillers/crown/returns so they don't price as cabinet boxes. They stay out
// of the quote total rather than being box-priced; linear filler/trim pricing is
// a later refinement (the directive here is "stop pricing them as boxes").
export function dropNonBoxCasework<T extends CabinetLineItem>(lines: T[]): T[] {
  return lines.filter((l) => !isNonBoxCasework(l));
}

// ---------------------------------------------------------------------------
// Page-role router — count each room ONCE (SCR-003 over-read fix)
// ---------------------------------------------------------------------------
// The estimate pipeline SUMS cabinet lines across every relevant page, and the
// only guard is a label-based collapse that can't fire when the model names the
// same room differently per view ("Kitchen" / "Kitchen 2" / "Kitchen - North").
// So elevation/millwork pages RE-ENUMERATE cabinets a plan or schedule already
// counted, and the total balloons 2-4x (Q14 +169%, Q19 +257%, Q24 +132%).
//
// The fix is to stop treating every page as an additive source. Pick ONE
// authoritative count source for the document by role precedence —
// schedule > floor plan > elevation — and count from that role only. The other
// roles (elevations under a plan/schedule) are demoted: they refine sizes in a
// later pass, but never ADD to the count. Elevation-ONLY docs still count from
// elevations (there's no higher source), collapsing cross-view duplicates as
// before; that residual multi-wall case is handled separately.

export type PageRole = "schedule" | "plan" | "elevation" | "other";

export function pageClassToRole(c: PageClass): PageRole {
  switch (c) {
    case "cabinet_schedule_table":
      return "schedule";
    case "floor_plan":
      return "plan";
    case "kitchen_or_millwork_elevation":
      return "elevation";
    default:
      // finish_schedule, cover_index, spec_text, other — not a cabinet count source
      return "other";
  }
}

export interface RoleRouteResult<T extends CabinetLineItem> {
  // Which role supplied the authoritative count (or "passthrough" when no
  // recognized role had any boxes — everything is kept, deduped).
  regime: PageRole | "passthrough";
  // The authoritative, deduped/collapsed count lines.
  lines: T[];
  // Lines dropped because they came from a demoted role (cross-view re-counts).
  droppedFromOtherRoles: number;
  // Lines removed by the per-regime dedup/collapse within the chosen role.
  collapsedWithinRole: number;
}

// Pick the authoritative count from the highest-priority page role that actually
// produced cabinet boxes, then dedup WITHIN that role. `roleByPage` maps a
// source_page number to its role (built from the page classification). A line
// with no/unknown source_page is treated as role "other".
export function routeByPageRole<T extends CabinetLineItem>(
  lines: T[],
  roleByPage: Map<number, PageRole>
): RoleRouteResult<T> {
  const roleOf = (l: T): PageRole =>
    (l.source_page != null ? roleByPage.get(l.source_page) : undefined) ??
    "other";
  const isBox = (l: T): boolean =>
    PRICED_BOX_CATEGORIES.has(l.category) && !isNonBoxCasework(l);

  // Highest-priority role that produced at least one real box wins. The
  // ≥1-box guard means a misclassified site plan (a "plan" page with no
  // cabinets) falls through to elevations instead of zeroing the count.
  const priority: PageRole[] = ["schedule", "plan", "elevation"];
  let chosen: PageRole | null = null;
  for (const role of priority) {
    if (lines.some((l) => roleOf(l) === role && isBox(l))) {
      chosen = role;
      break;
    }
  }

  if (chosen == null) {
    // No recognized authoritative role with boxes — keep everything, deduped.
    const deduped = dedupeLines(lines);
    return {
      regime: "passthrough",
      lines: deduped,
      droppedFromOtherRoles: 0,
      collapsedWithinRole: lines.length - deduped.length,
    };
  }

  const kept = lines.filter((l) => roleOf(l) === chosen);
  const droppedFromOtherRoles = lines.length - kept.length;
  // Schedules are labeled (cabinet A/B/C…) so a tag dedup merges plan+elevation
  // repeats of the same tag; plan/elevation estimates have varying labels, so
  // collapse cross-view duplicates per normalized room instead.
  const counted =
    chosen === "schedule"
      ? dedupeLines(kept)
      : collapseCrossViewDuplicates(kept);
  return {
    regime: chosen,
    lines: counted,
    droppedFromOtherRoles,
    collapsedWithinRole: kept.length - counted.length,
  };
}

import { z } from "zod";
import type { CabinetLineItem } from "./schemas.js";

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

// Output of the vision "locate" call: distinct drawings on a sheet, in pixel
// coordinates relative to the image the model was sent.
export const PageRegions = z.object({
  regions: z
    .array(
      z.object({
        kind: RegionKind,
        // [x0, y0, x1, y1] in pixels of the sent image.
        box: z.tuple([z.number(), z.number(), z.number(), z.number()]),
        confidence: z.number().min(0).max(1).default(0.5),
      })
    )
    .default([]),
});
export type PageRegions = z.infer<typeof PageRegions>;

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

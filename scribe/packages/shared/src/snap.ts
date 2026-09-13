import { z } from "zod";
import type { RectPtLike } from "./scale.js";

// ---------------------------------------------------------------------------
// Vector snapping (Stage V item 0 — v0-drawing-scale-plan.md §3).
// ---------------------------------------------------------------------------
// The detector's boxes are loose. On a vector PDF the cabinet outlines are
// real line segments, so each box edge can move onto the nearest drawn line
// that runs along it — deterministically, zero API. Pure; the worker's
// pageSegments() supplies the segments in upright page points.

// A horizontal segment lies at y = `at` from x = `from` to x = `to`; a
// vertical one at x = `at` from y = `from` to `to`. from < to.
export const Segment = z.object({ at: z.number(), from: z.number(), to: z.number() });
export type Segment = z.infer<typeof Segment>;

export const PageSegments = z.object({ h: z.array(Segment), v: z.array(Segment) });
export type PageSegments = z.infer<typeof PageSegments>;

export const SnappedEdges = z.object({
  l: z.boolean(),
  r: z.boolean(),
  t: z.boolean(),
  b: z.boolean(),
});
export type SnappedEdges = z.infer<typeof SnappedEdges>;

// Per-line geometry provenance (takeoff_lines.geom). PR B fills the snap
// fields; PR C fills the sizes and size_source.
export const LineGeom = z.object({
  width_in: z.number().nullable().optional(),
  height_in: z.number().nullable().optional(),
  depth_in: z.number().nullable().optional(),
  in_per_pt: z.number().nullable().optional(),
  snapped: SnappedEdges.optional(),
  // Largest edge move as a fraction of that side (0 = box was already on the lines).
  snap_moved: z.number().optional(),
  size_source: z.enum(["printed", "geometry", "default", "manual"]).optional(),
  mismatch_in: z.number().nullable().optional(),
});
export type LineGeom = z.infer<typeof LineGeom>;

export interface SnapOptions {
  // Edge search tolerance: max(minTolPt, tolFrac × the side perpendicular to the edge).
  tolFrac?: number;
  minTolPt?: number;
  // A candidate line must overlap at least this fraction of the side it would replace.
  minOverlap?: number;
  // Never move an edge further than this fraction of its side.
  maxMoveFrac?: number;
}

// Search window 10% of the side (detector boxes are looser than a few
// percent — July spike); the 15% move cap and the overlap rule bound the risk.
const DEFAULTS: Required<SnapOptions> = {
  tolFrac: 0.1,
  minTolPt: 6,
  minOverlap: 0.5,
  maxMoveFrac: 0.15,
};

export interface SnapResult {
  box: RectPtLike;
  snapped: SnappedEdges;
  moved: number;
}

function overlapLen(a0: number, a1: number, b0: number, b1: number): number {
  return Math.max(0, Math.min(a1, b1) - Math.max(a0, b0));
}

// Best line for one edge: parallel segments within `tol` of the edge that
// overlap the side by ≥ minOverlap; nearest wins, longer overlap breaks ties.
function pickEdge(
  edgeAt: number,
  side0: number,
  side1: number,
  candidates: Segment[],
  tol: number,
  minOverlap: number
): number | null {
  const sideLen = side1 - side0;
  let best: { at: number; d: number; ov: number } | null = null;
  for (const s of candidates) {
    const d = Math.abs(s.at - edgeAt);
    if (d > tol) continue;
    const ov = overlapLen(side0, side1, s.from, s.to);
    if (ov < minOverlap * sideLen) continue;
    if (!best || d < best.d - 1e-6 || (Math.abs(d - best.d) <= 1e-6 && ov > best.ov)) {
      best = { at: s.at, d, ov };
    }
  }
  return best ? best.at : null;
}

export function snapBox(
  box: RectPtLike,
  segments: PageSegments,
  opts: SnapOptions = {}
): SnapResult {
  const o = { ...DEFAULTS, ...opts };
  const w = box.x1 - box.x0;
  const h = box.y1 - box.y0;
  if (w <= 0 || h <= 0 || (segments.h.length === 0 && segments.v.length === 0)) {
    return { box: { ...box }, snapped: { l: false, r: false, t: false, b: false }, moved: 0 };
  }
  const tolX = Math.max(o.minTolPt, o.tolFrac * w);
  const tolY = Math.max(o.minTolPt, o.tolFrac * h);
  const out = { ...box };
  const snapped = { l: false, r: false, t: false, b: false };
  let moved = 0;

  const tryEdge = (
    key: "l" | "r" | "t" | "b",
    edgeAt: number,
    side0: number,
    side1: number,
    cands: Segment[],
    tol: number,
    sideLen: number,
    apply: (v: number) => void
  ) => {
    const at = pickEdge(edgeAt, side0, side1, cands, tol, o.minOverlap);
    if (at == null) return;
    const move = Math.abs(at - edgeAt);
    if (move > o.maxMoveFrac * sideLen) return;
    apply(at);
    snapped[key] = true;
    moved = Math.max(moved, move / sideLen);
  };

  tryEdge("l", box.x0, box.y0, box.y1, segments.v, tolX, w, (v) => (out.x0 = v));
  tryEdge("r", box.x1, box.y0, box.y1, segments.v, tolX, w, (v) => (out.x1 = v));
  tryEdge("t", box.y0, box.x0, box.x1, segments.h, tolY, h, (v) => (out.y0 = v));
  tryEdge("b", box.y1, box.x0, box.x1, segments.h, tolY, h, (v) => (out.y1 = v));
  if (out.x1 <= out.x0 || out.y1 <= out.y0) {
    return { box: { ...box }, snapped: { l: false, r: false, t: false, b: false }, moved: 0 };
  }
  return { box: out, snapped, moved };
}

// Collinear segments within `tol` of each other that overlap (or touch) merge
// into one — a thin filled rectangle contributes two long edges 0.5 pt apart,
// and CAD exports often draw one line as several pieces.
export function mergeSegments(segs: PageSegments, tol = 1): PageSegments {
  const mergeAxis = (list: Segment[]): Segment[] => {
    const sorted = [...list].sort((a, b) => a.at - b.at || a.from - b.from);
    const out: Segment[] = [];
    for (const s of sorted) {
      const last = out[out.length - 1];
      if (
        last &&
        Math.abs(last.at - s.at) <= tol &&
        s.from <= last.to + tol &&
        s.to >= last.from - tol
      ) {
        const from = Math.min(last.from, s.from);
        const to = Math.max(last.to, s.to);
        // Position: length-weighted mean of the two.
        const wl = last.to - last.from;
        const ws = s.to - s.from;
        const at = wl + ws > 0 ? (last.at * wl + s.at * ws) / (wl + ws) : (last.at + s.at) / 2;
        out[out.length - 1] = { at: Math.round(at * 100) / 100, from, to };
      } else {
        out.push({ ...s });
      }
    }
    return out;
  };
  return { h: mergeAxis(segs.h), v: mergeAxis(segs.v) };
}

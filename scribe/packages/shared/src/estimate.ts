import type { CabinetLineItem } from "./schemas.js";

// Cabinetry estimated from a floor plan / elevation (no schedule present, PRD
// §4) is inherently rough, so estimated lines are capped well below the
// review threshold (0.8) — they always surface as low-confidence for a human
// to verify, and never read as schedule-grade quantities.
export const ESTIMATE_MAX_CONFIDENCE = 0.5;

export const ESTIMATED_NOTE_PREFIX = "[ESTIMATED]";

// Category-average fallback dimensions for the beta detect wizard: a detected
// cabinet whose measurements can't be read off the drawing still needs SOME
// size to be priced, so it gets the category average and is marked estimated.
// w/h from common stock sizes; h/d match the nomenclature defaults the extract
// prompt teaches (base 34.5"h × 24"d, wall 12"d, tall 84"h × 24"d, vanity
// 32.5"h × 21"d).
export const BETA_DEFAULT_DIMS: Record<
  string,
  { w: number; h: number; d: number } | undefined
> = {
  casework_base: { w: 30, h: 34.5, d: 24 },
  casework_wall: { w: 30, h: 30, d: 12 },
  casework_tall: { w: 24, h: 84, d: 24 },
  vanity: { w: 30, h: 32.5, d: 21 },
};

// Mark a line as estimated: set the flag, cap confidence, and prefix the note
// so the provenance is visible in the review screen (which has no dedicated
// estimated-line UI — it relies on the note + low-confidence highlighting).
export function markEstimated<T extends CabinetLineItem>(line: T): T {
  const note = line.notes?.trim();
  const notes =
    note && note.startsWith(ESTIMATED_NOTE_PREFIX)
      ? note
      : [ESTIMATED_NOTE_PREFIX, note].filter(Boolean).join(" ");
  return {
    ...line,
    estimated: true,
    confidence: Math.min(line.confidence, ESTIMATE_MAX_CONFIDENCE),
    notes,
  };
}

// ---------------------------------------------------------------------------
// Plan-run decomposition (measure-v6)
// ---------------------------------------------------------------------------
// A plan-view marker boxes a counter RUN, and the measure pass splits it into
// the units a shop builds. The run has ONE box, so each unit needs its own
// visual anchor: slice the run's box along its long axis in proportion to the
// unit widths. Advisory only — like every bbox in this pipeline it is an
// anchor for the reviewer, not a measurement.

export type RunBBox = [number, number, number, number];

export function sliceRunBbox(
  bbox: RunBBox,
  widths: number[]
): (RunBBox | null)[] {
  if (widths.length === 0) return [];
  const [x0, y0, x1, y1] = [
    Math.min(bbox[0], bbox[2]),
    Math.min(bbox[1], bbox[3]),
    Math.max(bbox[0], bbox[2]),
    Math.max(bbox[1], bbox[3]),
  ];
  const total = widths.reduce((s, w) => s + (w > 0 ? w : 0), 0);
  // Nothing to divide by (all widths missing/zero) — every unit inherits the
  // whole run box rather than getting a degenerate sliver.
  if (total <= 0) return widths.map(() => [x0, y0, x1, y1] as RunBBox);
  const horizontal = x1 - x0 >= y1 - y0;
  const span = horizontal ? x1 - x0 : y1 - y0;
  let at = 0;
  return widths.map((w) => {
    const frac = (w > 0 ? w : 0) / total;
    const start = at;
    at += frac * span;
    return horizontal
      ? ([x0 + start, y0, x0 + at, y1] as RunBBox)
      : ([x0, y0 + start, x1, y0 + at] as RunBBox);
  });
}

// A door-schedule callout ("NEW 2668", "2868 PKT.", "3068 S.G.D.") is a door
// size in feet-inches (2'6" x 6'8"), not a cabinet name — the plan-view
// detector picks them up next to vanities (owner-reported false vanity on the
// Piestewa read, 2026-08-18). Cabinet codes never end in a door height, so the
// height suffix is what makes this safe: B24/W3030/2436 do not match.
const DOOR_CALLOUT =
  /\b(?:new\s+)?[1-9]\d(?:68|80|610)(?:\s*(?:pkt|pocket|s\.?g\.?d|bi-?fold|door))?\.?/gi;

export function stripDoorCallout(tag: string): string {
  return tag.replace(DOOR_CALLOUT, "").replace(/\s{2,}/g, " ").trim();
}

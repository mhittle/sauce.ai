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

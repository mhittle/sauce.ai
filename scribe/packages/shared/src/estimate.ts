import type { CabinetLineItem } from "./schemas.js";

// Cabinetry estimated from a floor plan / elevation (no schedule present, PRD
// §4) is inherently rough, so estimated lines are capped well below the
// review threshold (0.8) — they always surface as low-confidence for a human
// to verify, and never read as schedule-grade quantities.
export const ESTIMATE_MAX_CONFIDENCE = 0.5;

export const ESTIMATED_NOTE_PREFIX = "[ESTIMATED]";

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

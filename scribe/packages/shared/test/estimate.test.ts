import { describe, expect, it } from "vitest";
import {
  ESTIMATE_MAX_CONFIDENCE,
  ESTIMATED_NOTE_PREFIX,
  LOW_CONFIDENCE_THRESHOLD,
  markEstimated,
} from "../src/index.js";
import type { CabinetLineItem } from "../src/schemas.js";

function line(over: Partial<CabinetLineItem> = {}): CabinetLineItem {
  return {
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
    confidence: 0.9,
    estimated: false,
    ...over,
  };
}

describe("markEstimated", () => {
  it("sets the flag and caps confidence below the review threshold", () => {
    const out = markEstimated(line({ confidence: 0.95 }));
    expect(out.estimated).toBe(true);
    expect(out.confidence).toBeLessThanOrEqual(ESTIMATE_MAX_CONFIDENCE);
    expect(out.confidence).toBeLessThan(LOW_CONFIDENCE_THRESHOLD);
  });

  it("never raises an already-lower confidence", () => {
    const out = markEstimated(line({ confidence: 0.2 }));
    expect(out.confidence).toBe(0.2);
  });

  it("prefixes the note and preserves existing text", () => {
    const out = markEstimated(line({ notes: "Kitchen base run ~12 LF" }));
    expect(out.notes?.startsWith(ESTIMATED_NOTE_PREFIX)).toBe(true);
    expect(out.notes).toContain("Kitchen base run ~12 LF");
  });

  it("does not double-prefix", () => {
    const once = markEstimated(line({ notes: "x" }));
    const twice = markEstimated(once);
    expect(twice.notes?.indexOf(ESTIMATED_NOTE_PREFIX)).toBe(
      twice.notes?.lastIndexOf(ESTIMATED_NOTE_PREFIX)
    );
  });

  it("handles a null note", () => {
    const out = markEstimated(line({ notes: null }));
    expect(out.notes).toBe(ESTIMATED_NOTE_PREFIX);
  });
});

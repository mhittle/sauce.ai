import { describe, expect, it } from "vitest";
import { buildApprovedPayload } from "../src/callbacks.js";

describe("buildApprovedPayload", () => {
  it("maps lines to snake_case with nulls kept and numerics as numbers", () => {
    const approvedAt = new Date("2026-11-09T18:02:11.123Z");
    const p = buildApprovedPayload(
      { id: "t1", externalSource: "cabinethub", externalRef: "ref-1", sourceFilename: "A-401.pdf" },
      [
        {
          id: "l1", tag: "B24", room: "Kitchen", qty: 2, category: "base",
          widthIn: 24, heightIn: 34.5, depthIn: null, doorStyle: "Shaker", material: "Maple",
          finish: null, assembled: true, notes: null, confidence: 0.91, sourcePage: 3,
        },
      ],
      approvedAt,
      "t1:1"
    );
    expect(p.event).toBe("takeoff.approved");
    expect(p.event_id).toBe("t1:1");
    expect(p.external_ref).toBe("ref-1");
    expect(p.approved_at).toBe("2026-11-09T18:02:11.123Z");
    expect(p.lines[0]).toEqual({
      id: "l1", tag: "B24", room: "Kitchen", qty: 2, category: "base",
      width_in: 24, height_in: 34.5, depth_in: null, door_style: "Shaker", material: "Maple",
      finish: null, assembled: true, notes: null, confidence: 0.91, source_page: 3,
    });
  });
});

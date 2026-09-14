import { describe, expect, it } from "vitest";
import { friendlyError, friendlyNote, friendlyNotes } from "./messages";

describe("friendlyError", () => {
  it("hides the SQL behind a plain sentence and keeps it as detail", () => {
    const raw =
      'build takeoff failed: Failed query: delete from "takeoff_lines" where ("takeoff_lines"."takeoff_id" = $1 and … = ANY(($2, $3))) params: 9018debb';
    const f = friendlyError(raw);
    expect(f.text).toBe("We couldn't finish building this takeoff. Please try Build again.");
    expect(f.detail).toBe(raw);
  });

  it("maps a billing failure to a service-unavailable line", () => {
    expect(
      friendlyError(
        '400 {"type":"error","error":{"type":"invalid_request_error","message":"Your credit balance is too low to access the Anthropic API."}}'
      ).text
    ).toMatch(/isn't available right now/);
  });

  it("maps a media-type mismatch to an upload hint", () => {
    expect(
      friendlyError("400 … image was specified using the image/png media type, but the image appears to be a image/jpeg image").text
    ).toMatch(/PNG or JPEG/);
  });

  it("falls back to a generic sentence", () => {
    expect(friendlyError("ECONNRESET").text).toMatch(/Something went wrong/);
  });
});

describe("friendlyNote", () => {
  it("hides a salvage note that changed nothing", () => {
    expect(
      friendlyNote("measurements response was not valid JSON — 22 complete cabinet answers salvaged, nothing defaulted").text
    ).toBeNull();
  });

  it("counts the defaulted cabinets when salvage was partial", () => {
    expect(
      friendlyNote("measurements response was not valid JSON — 20 complete cabinet answers salvaged, 4 of 24 defaulted").text
    ).toBe("4 cabinets couldn't be measured and use standard sizes — check them.");
  });

  it("rewrites the estimated-dimensions count", () => {
    expect(friendlyNote("3 of 25 cabinets have estimated dimensions — verify against the drawing").text).toMatch(
      /^3 cabinets have estimated sizes/
    );
  });

  it("keeps the schedule note in plain words", () => {
    expect(
      friendlyNote("No cabinet schedule detected — quantities below are ESTIMATED from the floor plan/elevations and must be verified before quoting.").text
    ).toMatch(/quantities are estimated/);
  });

  it("uses a generic line for an unknown note and keeps the raw text", () => {
    const f = friendlyNote("page 3: something odd (stack trace)");
    expect(f.text).toMatch(/couldn't be read fully/);
    expect(f.detail).toBe("page 3: something odd (stack trace)");
  });
});

describe("friendlyNotes", () => {
  const raws = [
    "No cabinet schedule detected — quantities below are ESTIMATED from the floor plan/elevations and must be verified before quoting.",
    "measurements response was not valid JSON — 22 complete cabinet answers salvaged, nothing defaulted",
    "p2: cross-validation skipped (timeout)",
    "page 3: estimate failed (boom)",
    "page 4: extraction failed (boom)",
  ];

  it("drops developer-only notes for customers and merges duplicates", () => {
    const notes = friendlyNotes(raws);
    expect(notes.map((n) => n.text)).toEqual([
      "No cabinet schedule was found, so the quantities are estimated from the drawings — check them before quoting.",
      "Part of a page couldn't be read — check its cabinets.",
    ]);
    expect(notes[1].details).toHaveLength(2);
  });

  it("shows admins the developer-only notes too", () => {
    const notes = friendlyNotes(raws, true);
    expect(notes).toHaveLength(4);
    expect(notes.some((n) => n.text.startsWith("(developer note)"))).toBe(true);
  });
});

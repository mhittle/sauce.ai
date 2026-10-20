import { describe, expect, it } from "vitest";
import { friendlyError, friendlyNote, friendlyNotes, creditCostLine, creditsShort, CREDITS_INSUFFICIENT, submitErrorText, customBuyLabel, customHint, friendlyPriceIssue, lineSaveErrorText, unpricedLineTitle, QUOTE_OLD_RATES, QUOTE_PLACEHOLDER_ADMIN } from "./messages";

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

describe("credits copy", () => {
  it("shows the free first job until there is a balance", () => {
    expect(creditsShort(0, true)).toBe("First job free");
    expect(creditsShort(5, true)).toBe("5 pages left");
    expect(creditsShort(1, false)).toBe("1 page left");
  });

  it("previews the job's cost against the balance", () => {
    expect(creditCostLine({ pages: 3, credits: 0, free: true }, 0)).toMatch(/first job is free/);
    expect(creditCostLine({ pages: 3, credits: 3, free: false }, 20)).toBe(
      "Reading 3 pages uses 3 from your balance. 17 left after this job."
    );
    expect(creditCostLine({ pages: 2, credits: 5, free: false }, 1)).toBe(
      "Reading 2 pages uses 5 from your balance (5-page minimum per job). Your balance is 1."
    );
  });

  it("maps a 402 to the plain credits line", () => {
    expect(submitErrorText(Object.assign(new Error("not enough credits: …"), { status: 402 }))).toBe(
      CREDITS_INSUFFICIENT
    );
    expect(submitErrorText(new Error("boom"))).toBe("boom");
  });
});

describe("custom page purchase copy", () => {
  const custom = { min: 5, max: 5000, pagePriceCents: 100 };
  it("labels the price and explains the limits", () => {
    expect(customBuyLabel(10, 100)).toBe("Buy for $10");
    expect(customBuyLabel(1200, 100)).toBe("Buy for $1,200");
    expect(customHint(3, custom)).toBe("Minimum 5 pages.");
    expect(customHint(6000, custom)).toBe("Up to 5,000 pages at a time.");
    expect(customHint(10, custom)).toMatch(/^\$1 a page/);
  });
});

describe("unpriced line copy (SCR-016)", () => {
  it("explains an out-of-range width in plain words with the fix", () => {
    expect(friendlyPriceIssue('width 58" outside 9"–48"')).toBe(
      '58" width is outside what this product takes (9"–48"). Change the width, or split it into two cabinets.'
    );
    expect(friendlyPriceIssue('depth 2" outside 4"–30"')).toMatch(/Change the depth, or pick another product/);
  });
  it("maps the other pricing reasons and passes unknown text through", () => {
    expect(friendlyPriceIssue("unmatched — resolve in the review screen")).toMatch(/No product picked yet/);
    expect(friendlyPriceIssue("product line x missing from pricing config")).toMatch(/isn't in the price list/);
    expect(friendlyPriceIssue("something new")).toBe("something new");
  });
  it("turns a refused hand-pick (422) into the plain reason", () => {
    const e = Object.assign(new Error('width 58" outside 9"–48"'), { status: 422 });
    expect(lineSaveErrorText(e)).toMatch(/^58" width is outside/);
    expect(lineSaveErrorText(new Error("boom"))).toBe("boom");
    expect(unpricedLineTitle("  ", 2)).toBe("Line 2");
  });
});

describe("placeholder-rate blocker copy", () => {
  it("tells an old quote to rebuild rather than pointing at Admin", () => {
    expect(QUOTE_OLD_RATES).toMatch(/build a new quote/);
    expect(QUOTE_OLD_RATES).not.toMatch(/Admin/);
    expect(QUOTE_PLACEHOLDER_ADMIN).toMatch(/Admin › Pricing/);
  });
});

describe("admin size limit copy", () => {
  it("explains a limit the admin set", () => {
    expect(friendlyPriceIssue('width 58" is over the 48" max set for Framed Casework')).toBe(
      '58" width is over the 48" max set for Framed Casework in Admin › Pricing. Change the width, split it into two cabinets, or pick another product.'
    );
    expect(friendlyPriceIssue('depth 3" is under the 4" min set for Doors')).toMatch(/Change the depth, or pick another product/);
  });
});

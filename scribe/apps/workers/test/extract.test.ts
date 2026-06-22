import { describe, expect, it } from "vitest";
import { salvageLineObjects } from "../src/takeoff/extract.js";

describe("salvageLineObjects", () => {
  it("recovers complete objects from a JSON response truncated mid-array", () => {
    // Simulates a max_tokens cut-off: the last object is incomplete and the
    // array/braces never close.
    const truncated = `{"lines": [
      {"tag": "Sink Base 36", "qty": 1, "width_in": 36},
      {"tag": "Base 3 Drawers 37.25", "qty": 2, "width_in": 37.25},
      {"tag": "Oven Base 30", "qty": 1, "wid`;
    const objs = salvageLineObjects(truncated) as Array<{ tag: string }>;
    expect(objs).toHaveLength(2);
    expect(objs.map((o) => o.tag)).toEqual(["Sink Base 36", "Base 3 Drawers 37.25"]);
  });

  it("is not fooled by braces or brackets inside string values", () => {
    const text = `{"lines": [
      {"tag": "Base 24", "notes": "fills run {north} [east] segment"},
      {"tag": "Wall 30", "notes": "ok"}
    ]}`;
    const objs = salvageLineObjects(text) as Array<{ tag: string }>;
    expect(objs).toHaveLength(2);
    expect(objs[0].tag).toBe("Base 24");
  });

  it("returns [] when there is no lines array", () => {
    expect(salvageLineObjects("garbage with no json")).toEqual([]);
    expect(salvageLineObjects(`{"uncertainties": []}`)).toEqual([]);
  });
});

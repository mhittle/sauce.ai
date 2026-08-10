import { describe, expect, it } from "vitest";
import { selectRelevantPages, type PageClassification } from "../src/index.js";

const classified: PageClassification[] = [
  { page: 1, class: "cover_index", confidence: 0.9 },
  { page: 2, class: "floor_plan", confidence: 0.8 },
  { page: 3, class: "kitchen_or_millwork_elevation", confidence: 0.7 },
  { page: 4, class: "cabinet_schedule_table", confidence: 0.9 },
  { page: 5, class: "other", confidence: 0.6 },
];

describe("selectRelevantPages", () => {
  it("null selection reproduces the autonomous flow (schedule mode drops floor plans)", () => {
    const { estimationMode, relevant } = selectRelevantPages(classified, null);
    expect(estimationMode).toBe(false);
    expect(relevant.map((r) => r.page)).toEqual([4, 3]);
  });

  it("restricts reads to the selected pages", () => {
    const { estimationMode, relevant } = selectRelevantPages(classified, [
      { page: 2 },
      { page: 3 },
    ]);
    // Schedule page 4 was NOT selected → estimation mode, floor plan relevant.
    expect(estimationMode).toBe(true);
    // Read order: elevation before floor plan.
    expect(relevant.map((r) => r.page)).toEqual([3, 2]);
  });

  it("a user tag override replaces the classifier's class", () => {
    const { estimationMode, relevant } = selectRelevantPages(classified, [
      { page: 5, class: "cabinet_schedule_table" },
      { page: 2 },
    ]);
    // Human tagged page 5 as a schedule → schedule mode; the untagged floor
    // plan (page 2) is no longer a relevant source.
    expect(estimationMode).toBe(false);
    expect(relevant).toEqual([
      { page: 5, class: "cabinet_schedule_table", confidence: 1 },
    ]);
  });

  it("an override to floor_plan changes how the page is read", () => {
    const { relevant } = selectRelevantPages(classified, [
      { page: 3, class: "floor_plan" },
    ]);
    expect(relevant).toEqual([{ page: 3, class: "floor_plan", confidence: 1 }]);
  });

  it("selected pages with a non-readable class are excluded", () => {
    const { relevant } = selectRelevantPages(classified, [
      { page: 1 },
      { page: 5 },
      { page: 2 },
    ]);
    expect(relevant.map((r) => r.page)).toEqual([2]);
  });

  it("admits a selected page the classifier never saw, using its override class", () => {
    const { relevant } = selectRelevantPages(classified.slice(0, 1), [
      { page: 9, class: "kitchen_or_millwork_elevation" },
    ]);
    expect(relevant).toEqual([
      { page: 9, class: "kitchen_or_millwork_elevation", confidence: 1 },
    ]);
  });

  it("keeps read order: schedules, finish schedules, elevations, floor plans", () => {
    const all: PageClassification[] = [
      { page: 1, class: "floor_plan", confidence: 0.5 },
      { page: 2, class: "kitchen_or_millwork_elevation", confidence: 0.5 },
      { page: 3, class: "finish_schedule", confidence: 0.5 },
      { page: 4, class: "cabinet_schedule_table", confidence: 0.5 },
    ];
    const { relevant } = selectRelevantPages(all, [
      { page: 1 },
      { page: 2 },
      { page: 3 },
      { page: 4 },
    ]);
    expect(relevant.map((r) => r.page)).toEqual([4, 3, 2]);
    // (floor plan excluded — a schedule was selected, so schedule mode.)
  });
});

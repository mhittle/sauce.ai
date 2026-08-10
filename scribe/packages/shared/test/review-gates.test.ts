import { describe, expect, it } from "vitest";
import {
  CabinetLineItem,
  canTransitionTakeoff,
  SelectedPage,
  TakeoffStatus,
} from "../src/index.js";

const baseLine = {
  source_page: 1,
  tag: "B24",
  room: null,
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
};

describe("CabinetLineItem.bbox_2d", () => {
  it("parses a well-formed pixel box", () => {
    const line = CabinetLineItem.parse({ ...baseLine, bbox_2d: [10, 20, 110, 220] });
    expect(line.bbox_2d).toEqual([10, 20, 110, 220]);
  });

  it("defaults to null when missing", () => {
    expect(CabinetLineItem.parse(baseLine).bbox_2d).toBeNull();
  });

  it("is lenient: a malformed box becomes null, the line survives", () => {
    // Wrong arity / wrong types must not drop the whole line.
    expect(
      CabinetLineItem.parse({ ...baseLine, bbox_2d: [1, 2, 3] }).bbox_2d
    ).toBeNull();
    expect(
      CabinetLineItem.parse({ ...baseLine, bbox_2d: "10,20,30,40" }).bbox_2d
    ).toBeNull();
  });
});

describe("takeoff status machine (two review gates)", () => {
  it("accepts the new gate statuses", () => {
    expect(TakeoffStatus.parse("awaiting_pages")).toBe("awaiting_pages");
    expect(TakeoffStatus.parse("awaiting_boxes")).toBe("awaiting_boxes");
  });

  it("walks the happy path: processing → pages → processing → boxes → review → approved", () => {
    expect(canTransitionTakeoff("processing", "awaiting_pages")).toBe(true);
    expect(canTransitionTakeoff("awaiting_pages", "processing")).toBe(true);
    expect(canTransitionTakeoff("processing", "awaiting_boxes")).toBe(true);
    expect(canTransitionTakeoff("awaiting_boxes", "processing")).toBe(true);
    expect(canTransitionTakeoff("processing", "review")).toBe(true);
    expect(canTransitionTakeoff("review", "approved")).toBe(true);
  });

  it("spreadsheets skip both gates (processing → review is legal directly)", () => {
    expect(canTransitionTakeoff("processing", "review")).toBe(true);
  });

  it("rejects gate-skipping and backwards moves", () => {
    expect(canTransitionTakeoff("awaiting_pages", "review")).toBe(false);
    expect(canTransitionTakeoff("awaiting_boxes", "review")).toBe(false);
    expect(canTransitionTakeoff("awaiting_pages", "approved")).toBe(false);
    expect(canTransitionTakeoff("awaiting_boxes", "approved")).toBe(false);
    expect(canTransitionTakeoff("review", "awaiting_boxes")).toBe(false);
    expect(canTransitionTakeoff("approved", "processing")).toBe(false);
  });

  it("legacy 'extracted' rows can still be approved but never re-enter the flow", () => {
    expect(canTransitionTakeoff("extracted", "approved")).toBe(true);
    expect(canTransitionTakeoff("extracted", "awaiting_boxes")).toBe(false);
  });
});

describe("SelectedPage", () => {
  it("accepts a bare page and an overridden class", () => {
    expect(SelectedPage.parse({ page: 3 })).toEqual({ page: 3 });
    expect(SelectedPage.parse({ page: 3, class: "floor_plan" })).toEqual({
      page: 3,
      class: "floor_plan",
    });
  });

  it("rejects a non-positive page or unknown class", () => {
    expect(SelectedPage.safeParse({ page: 0 }).success).toBe(false);
    expect(SelectedPage.safeParse({ page: 1, class: "nope" }).success).toBe(false);
  });
});

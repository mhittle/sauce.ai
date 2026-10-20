import { describe, expect, it } from "vitest";
import { chargeBlocked, CUSTOM_PAGES_MAX, CUSTOM_PAGES_MIN, findPack, jobCharge } from "../src/credits.js";

describe("jobCharge", () => {
  it("charges a page per selected page, with no minimum by default", () => {
    expect(jobCharge(3, { minPagesPerJob: 1 }, false)).toEqual({ pages: 3, credits: 3, free: false });
  });

  it("applies a configured minimum", () => {
    expect(jobCharge(2, { minPagesPerJob: 5 }, false).credits).toBe(5);
  });

  it("makes the first job free whatever its size", () => {
    expect(jobCharge(40, { minPagesPerJob: 5 }, true)).toEqual({ pages: 40, credits: 0, free: true });
  });
});

describe("chargeBlocked", () => {
  const charge = jobCharge(10, { minPagesPerJob: 1 }, false);
  it("never blocks while credits are not enforced", () => {
    expect(chargeBlocked(charge, 0, { creditsEnforced: false })).toBe(false);
  });
  it("blocks only a job the balance cannot cover once enforced", () => {
    expect(chargeBlocked(charge, 9, { creditsEnforced: true })).toBe(true);
    expect(chargeBlocked(charge, 10, { creditsEnforced: true })).toBe(false);
    expect(chargeBlocked(jobCharge(10, { minPagesPerJob: 1 }, true), 0, { creditsEnforced: true })).toBe(false);
  });
});

describe("findPack", () => {
  it("finds fixed packs and ignores a pages value for them", () => {
    expect(findPack("pages_100")?.priceCents).toBe(9_000);
    expect(findPack("pages_100", 7)?.pages).toBe(100);
    expect(findPack("pages_7")).toBeNull();
  });

  it("prices a custom amount at $1 a page within the limits", () => {
    expect(findPack("custom", 10)).toEqual({ id: "custom", pages: 10, priceCents: 1_000 });
    expect(findPack("custom", CUSTOM_PAGES_MIN - 1)).toBeNull();
    expect(findPack("custom", CUSTOM_PAGES_MAX + 1)).toBeNull();
    expect(findPack("custom", 10.5)).toBeNull();
    expect(findPack("custom")).toBeNull();
  });
});

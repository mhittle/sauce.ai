import { describe, expect, it } from "vitest";
import { chargeBlocked, jobCharge } from "../src/credits.js";

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

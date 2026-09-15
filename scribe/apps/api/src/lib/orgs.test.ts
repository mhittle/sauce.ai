import { describe, expect, it } from "vitest";
import { resolveOrgId } from "./orgs.js";

const OWN = "11111111-1111-1111-1111-111111111111";
const OTHER = "22222222-2222-2222-2222-222222222222";

describe("resolveOrgId", () => {
  it("is the user's org unless a platform admin asks for another", () => {
    expect(resolveOrgId({ orgId: OWN, isPlatformAdmin: false }, OTHER)).toBe(OWN);
    expect(resolveOrgId({ orgId: OWN, isPlatformAdmin: true }, OTHER)).toBe(OTHER);
    expect(resolveOrgId({ orgId: OWN, isPlatformAdmin: true }, undefined)).toBe(OWN);
    expect(resolveOrgId({ orgId: OWN, isPlatformAdmin: true }, "not-a-uuid")).toBe(OWN);
    expect(resolveOrgId({ orgId: OWN, isPlatformAdmin: true }, [OTHER, OWN])).toBe(OTHER);
  });
});

import { describe, expect, it } from "vitest";
import { hashToken, inviteState, newToken } from "./tokens.js";

describe("tokens", () => {
  it("makes url-safe 32-byte tokens that hash deterministically", () => {
    const t = newToken();
    expect(t).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(newToken()).not.toBe(t);
    expect(hashToken(t)).toBe(hashToken(t));
    expect(hashToken(t)).toHaveLength(64);
  });

  it("orders invite states: used > revoked > expired > pending", () => {
    const now = new Date("2026-09-15T00:00:00Z");
    const future = new Date("2026-09-29T00:00:00Z");
    const past = new Date("2026-09-01T00:00:00Z");
    expect(inviteState({ usedAt: null, revokedAt: null, expiresAt: future }, now)).toBe("pending");
    expect(inviteState({ usedAt: null, revokedAt: null, expiresAt: past }, now)).toBe("expired");
    expect(inviteState({ usedAt: null, revokedAt: now, expiresAt: future }, now)).toBe("revoked");
    expect(inviteState({ usedAt: now, revokedAt: now, expiresAt: past }, now)).toBe("used");
  });
});

import { createHmac, timingSafeEqual } from "node:crypto";
import { describe, expect, it } from "vitest";
import { callbackHeaders, classifyResponse, signCallbackBody } from "../src/callbacks/deliver.js";

// Mirrors the api's verifyStripeSignature so the signer stays byte-compatible
// with a Stripe-style receiver.
function verify(body: string, header: string, secret: string, nowSec: number): boolean {
  const parts = header.split(",").map((p) => p.split("=") as [string, string]);
  const t = parts.find(([k]) => k === "t")?.[1];
  const sigs = parts.filter(([k]) => k === "v1").map(([, v]) => v);
  if (!t || sigs.length === 0 || Math.abs(nowSec - Number(t)) > 300) return false;
  const expected = createHmac("sha256", secret).update(`${t}.${body}`).digest();
  return sigs.some((s) => {
    const got = Buffer.from(s, "hex");
    return got.length === expected.length && timingSafeEqual(got, expected);
  });
}

describe("signCallbackBody", () => {
  it("verifies with a Stripe-style verifier and rejects tampering, wrong key, stale t", () => {
    const body = JSON.stringify({ a: 1 });
    const header = signCallbackBody(body, "secret", 1_700_000_000);
    expect(verify(body, header, "secret", 1_700_000_010)).toBe(true);
    expect(verify(body + " ", header, "secret", 1_700_000_010)).toBe(false);
    expect(verify(body, header, "other", 1_700_000_010)).toBe(false);
    expect(verify(body, header, "secret", 1_700_001_000)).toBe(false);
  });
});

describe("classifyResponse", () => {
  it("2xx delivered, most 4xx permanent, 408/429/5xx retry", () => {
    expect(classifyResponse(200)).toBe("delivered");
    expect(classifyResponse(204)).toBe("delivered");
    expect(classifyResponse(400)).toBe("permanent");
    expect(classifyResponse(404)).toBe("permanent");
    expect(classifyResponse(408)).toBe("retry");
    expect(classifyResponse(429)).toBe("retry");
    expect(classifyResponse(500)).toBe("retry");
    expect(classifyResponse(503)).toBe("retry");
  });
});

describe("callbackHeaders", () => {
  it("sends JSON with a timestamped HMAC signature", () => {
    const h = callbackHeaders('{"a":1}', "s", 1_700_000_000);
    expect(h["content-type"]).toBe("application/json");
    expect(h["user-agent"]).toBe("scribe-callbacks/1");
    expect(h["scribe-signature"]).toMatch(/^t=1700000000,v1=[0-9a-f]{64}$/);
  });
});

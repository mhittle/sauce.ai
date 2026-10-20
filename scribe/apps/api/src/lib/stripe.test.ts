import { createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";
import { PAGE_PACKS } from "@scribe/shared";
import { checkoutForm, verifyStripeSignature } from "./stripe.js";

const secret = "whsec_test";
const body = JSON.stringify({ id: "evt_1", type: "checkout.session.completed" });
const sign = (t: number, payload = body, key = secret) =>
  createHmac("sha256", key).update(`${t}.${payload}`).digest("hex");

describe("verifyStripeSignature", () => {
  const now = 1_800_000_000;
  it("accepts a fresh, correctly signed payload", () => {
    expect(verifyStripeSignature(body, `t=${now},v1=${sign(now)}`, secret, now)).toBe(true);
    expect(verifyStripeSignature(Buffer.from(body), `t=${now},v1=deadbeef,v1=${sign(now)}`, secret, now)).toBe(true);
  });
  it("rejects a tampered body, a wrong secret, a stale timestamp and junk headers", () => {
    expect(verifyStripeSignature(body + " ", `t=${now},v1=${sign(now)}`, secret, now)).toBe(false);
    expect(verifyStripeSignature(body, `t=${now},v1=${sign(now, body, "whsec_other")}`, secret, now)).toBe(false);
    expect(verifyStripeSignature(body, `t=${now - 301},v1=${sign(now - 301)}`, secret, now)).toBe(false);
    expect(verifyStripeSignature(body, undefined, secret, now)).toBe(false);
    expect(verifyStripeSignature(body, "garbage", secret, now)).toBe(false);
  });
});

describe("checkoutForm", () => {
  it("prices the pack inline and carries the org on the session", () => {
    const f = checkoutForm({
      pack: PAGE_PACKS[1],
      orgId: "org-1",
      userId: "user-1",
      email: "a@b.co",
      successUrl: "https://web/account?purchased=1",
      cancelUrl: "https://web/account",
    });
    expect(f.get("mode")).toBe("payment");
    expect(f.get("line_items[0][price_data][unit_amount]")).toBe("9000");
    expect(f.get("line_items[0][price_data][currency]")).toBe("usd");
    expect(f.get("metadata[org_id]")).toBe("org-1");
    expect(f.get("metadata[pack]")).toBe("pages_100");
    expect(f.get("client_reference_id")).toBe("org-1");
  });
});

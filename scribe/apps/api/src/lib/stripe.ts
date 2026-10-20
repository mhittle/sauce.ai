import { createHmac, timingSafeEqual } from "node:crypto";
import type { PagePack } from "@scribe/shared";

// Stripe over its REST API (no SDK — two calls: create a Checkout session,
// verify a webhook). Same shape as packages/email: unconfigured is a state,
// not a crash.

export function billingConfigured(): boolean {
  return Boolean(process.env.STRIPE_SECRET_KEY && process.env.STRIPE_WEBHOOK_SECRET);
}

export interface CheckoutInput {
  pack: PagePack;
  orgId: string;
  userId: string;
  email: string;
  successUrl: string;
  cancelUrl: string;
}

// Form-encoded body for POST /v1/checkout/sessions. Pure, so it is tested.
export function checkoutForm(input: CheckoutInput): URLSearchParams {
  const f = new URLSearchParams();
  f.set("mode", "payment");
  f.set("success_url", input.successUrl);
  f.set("cancel_url", input.cancelUrl);
  f.set("client_reference_id", input.orgId);
  f.set("customer_email", input.email);
  f.set("line_items[0][quantity]", "1");
  f.set("line_items[0][price_data][currency]", "usd");
  f.set("line_items[0][price_data][unit_amount]", String(input.pack.priceCents));
  f.set("line_items[0][price_data][product_data][name]", `Scribe — ${input.pack.pages} pages`);
  f.set(
    "line_items[0][price_data][product_data][description]",
    "Pages of plan reading. One page read uses one page."
  );
  f.set("metadata[org_id]", input.orgId);
  f.set("metadata[user_id]", input.userId);
  f.set("metadata[pack]", input.pack.id);
  f.set("metadata[pages]", String(input.pack.pages));
  return f;
}

export async function createCheckoutSession(input: CheckoutInput): Promise<{ id: string; url: string }> {
  const res = await fetch("https://api.stripe.com/v1/checkout/sessions", {
    method: "POST",
    headers: {
      authorization: `Bearer ${process.env.STRIPE_SECRET_KEY}`,
      "content-type": "application/x-www-form-urlencoded",
    },
    body: checkoutForm(input),
  });
  const body = (await res.json().catch(() => ({}))) as {
    id?: string;
    url?: string;
    error?: { message?: string };
  };
  if (!res.ok || !body.id || !body.url) {
    throw new Error(`stripe checkout ${res.status}: ${body.error?.message ?? "no session"}`);
  }
  return { id: body.id, url: body.url };
}

// Stripe-Signature: "t=<unix>,v1=<hex hmac>[,v1=…]"; the signed payload is
// "<t>.<raw body>" under the endpoint's whsec_ secret. Rejects stale
// timestamps (replay) beyond `toleranceSec`.
export function verifyStripeSignature(
  rawBody: Buffer | string,
  header: string | undefined,
  secret: string,
  nowSec: number = Math.floor(Date.now() / 1000),
  toleranceSec = 300
): boolean {
  if (!header) return false;
  const parts = header.split(",").map((p) => p.split("=") as [string, string]);
  const t = parts.find(([k]) => k === "t")?.[1];
  const sigs = parts.filter(([k]) => k === "v1").map(([, v]) => v);
  if (!t || sigs.length === 0 || !/^\d+$/.test(t)) return false;
  if (Math.abs(nowSec - Number(t)) > toleranceSec) return false;
  const expected = createHmac("sha256", secret)
    .update(`${t}.${typeof rawBody === "string" ? rawBody : rawBody.toString("utf8")}`)
    .digest();
  return sigs.some((s) => {
    const got = Buffer.from(s, "hex");
    return got.length === expected.length && timingSafeEqual(got, expected);
  });
}

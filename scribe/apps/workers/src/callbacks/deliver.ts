import { createHmac } from "node:crypto";
import { eq, sql } from "drizzle-orm";
import type pino from "pino";
import { getDb, takeoffCallbacks } from "@scribe/db";

// Delivers one takeoff_callbacks row (migrations/0022). A 2xx marks it
// delivered; a 4xx other than 408/429 is permanent and recorded; anything
// else throws so BullMQ retries with the approve handler's backoff.

export type Outcome = "delivered" | "permanent" | "retry";

// Stripe-style signature ("t=<unix>,v1=<hex>", HMAC-SHA256 over "<t>.<body>")
// so the receiver can reuse its existing verifier.
export function signCallbackBody(
  body: string,
  secret: string,
  t: number = Math.floor(Date.now() / 1000)
): string {
  const v1 = createHmac("sha256", secret).update(`${t}.${body}`).digest("hex");
  return `t=${t},v1=${v1}`;
}

export function classifyResponse(status: number): Outcome {
  if (status >= 200 && status < 300) return "delivered";
  if (status >= 400 && status < 500 && status !== 408 && status !== 429) return "permanent";
  return "retry";
}

export function callbackHeaders(body: string, secret: string, t?: number): Record<string, string> {
  return {
    "content-type": "application/json",
    "scribe-signature": signCallbackBody(body, secret, t),
    "user-agent": "scribe-callbacks/1",
  };
}

export async function deliverCallback(
  callbackId: string,
  log: pino.Logger,
  fetchImpl: typeof fetch = fetch
): Promise<void> {
  const db = getDb();
  const [cb] = await db
    .select()
    .from(takeoffCallbacks)
    .where(eq(takeoffCallbacks.id, callbackId));
  if (!cb) {
    log.warn({ callbackId }, "callback row missing");
    return;
  }
  if (cb.deliveredAt) return;

  const secret = process.env.CALLBACK_SIGNING_SECRET;
  if (!secret) {
    log.error({ callbackId }, "CALLBACK_SIGNING_SECRET unset; callback not delivered");
    await db
      .update(takeoffCallbacks)
      .set({ lastError: "CALLBACK_SIGNING_SECRET unset", lastAttemptAt: new Date() })
      .where(eq(takeoffCallbacks.id, callbackId));
    return;
  }

  const body = JSON.stringify(cb.payload);
  let status = 0;
  let snippet = "";
  try {
    const res = await fetchImpl(cb.callbackUrl, {
      method: "POST",
      headers: callbackHeaders(body, secret),
      body,
      signal: AbortSignal.timeout(15_000),
    });
    status = res.status;
    snippet = (await res.text().catch(() => "")).slice(0, 300);
  } catch (err) {
    snippet = err instanceof Error ? err.message : String(err);
  }

  const outcome = status === 0 ? "retry" : classifyResponse(status);
  const error = outcome === "delivered" ? null : `HTTP ${status || "none"} ${snippet}`.trim();
  await db
    .update(takeoffCallbacks)
    .set({
      attempts: sql`${takeoffCallbacks.attempts} + 1`,
      lastAttemptAt: new Date(),
      lastError: error,
      ...(outcome === "delivered" ? { deliveredAt: new Date() } : {}),
    })
    .where(eq(takeoffCallbacks.id, callbackId));

  log.info({ callbackId, takeoff: cb.takeoffId, status, outcome }, "callback delivery");
  if (outcome === "retry") throw new Error(`callback ${callbackId}: ${error}`);
}

import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { and, eq } from "drizzle-orm";
import { creditLedger, getDb, orgBalance, users, writeLedger } from "@scribe/db";
import { receiptEmail, sendEmail } from "@scribe/email";
import { findPack } from "@scribe/shared";
import { billingConfigured, createCheckoutSession, verifyStripeSignature } from "../lib/stripe.js";
import { webUrl } from "./auth.js";

// Page packs via Stripe Checkout (accounts-plan.md §4): the customer pays on
// Stripe's page; the signed webhook writes one `purchase` ledger row per
// Checkout session (unique on external_ref, so redelivery is harmless).

export async function billingRoutes(app: FastifyInstance): Promise<void> {
  app.post("/billing/checkout", { preHandler: app.requireUser }, async (req, reply) => {
    const body = z.object({ pack: z.string() }).parse(req.body);
    const pack = findPack(body.pack);
    if (!pack) return reply.code(400).send({ error: `unknown pack ${body.pack}` });
    if (!billingConfigured()) {
      return reply.code(503).send({ error: "billing is not configured", code: "billing_unconfigured" });
    }
    const session = await createCheckoutSession({
      pack,
      orgId: req.orgId,
      userId: req.user!.id,
      email: req.user!.email,
      successUrl: `${webUrl()}/account?purchased=1`,
      cancelUrl: `${webUrl()}/account`,
    });
    req.log.info({ orgId: req.orgId, pack: pack.id, session: session.id }, "checkout session created");
    return { url: session.url };
  });
}

// Its own plugin: Stripe signs the exact bytes, so this route must see the raw
// body, not Fastify's parsed JSON.
export async function stripeWebhookRoutes(app: FastifyInstance): Promise<void> {
  app.addContentTypeParser("application/json", { parseAs: "buffer" }, (_req, body, done) =>
    done(null, body)
  );

  app.post("/billing/webhook", async (req, reply) => {
    const secret = process.env.STRIPE_WEBHOOK_SECRET;
    if (!secret) return reply.code(503).send({ error: "billing is not configured" });
    const raw = req.body as Buffer;
    if (!verifyStripeSignature(raw, req.headers["stripe-signature"] as string | undefined, secret)) {
      req.log.warn("stripe webhook: bad signature");
      return reply.code(400).send({ error: "bad signature" });
    }
    const event = JSON.parse(raw.toString("utf8")) as {
      id: string;
      type: string;
      data: { object: StripeSession };
    };
    if (event.type !== "checkout.session.completed") return { received: true };
    const s = event.data.object;
    if (s.payment_status !== "paid") return { received: true, ignored: "not paid" };

    const pack = findPack(s.metadata?.pack ?? "");
    const orgId = s.metadata?.org_id;
    // Acknowledge (200) so Stripe stops retrying, but never credit a session
    // whose pack or amount does not match what we sell.
    if (!pack || !orgId || s.amount_total !== pack.priceCents) {
      req.log.error({ session: s.id, metadata: s.metadata, amount: s.amount_total }, "stripe webhook: session does not match a pack");
      return { received: true, ignored: "pack mismatch" };
    }

    const db = getDb();
    const prior = await db
      .select({ id: creditLedger.id })
      .from(creditLedger)
      .where(and(eq(creditLedger.reason, "purchase"), eq(creditLedger.externalRef, s.id)));
    if (prior.length > 0) return { received: true, duplicate: true };
    try {
      await writeLedger(db, {
        orgId,
        delta: pack.pages,
        reason: "purchase",
        externalRef: s.id,
        actorUserId: s.metadata?.user_id ?? null,
        note: `${pack.pages} pages — $${(pack.priceCents / 100).toFixed(2)}`,
      });
    } catch (err) {
      const code = (err as { code?: string; cause?: { code?: string } }).code ??
        (err as { cause?: { code?: string } }).cause?.code;
      if (code === "23505") return { received: true, duplicate: true };
      throw err;
    }
    req.log.info({ orgId, session: s.id, pages: pack.pages }, "purchase credited");

    // Receipt: best-effort, logged-only until email is configured (MA-013).
    try {
      const to = s.customer_details?.email ?? s.customer_email;
      if (to) {
        const [u] = s.metadata?.user_id
          ? await db.select({ name: users.name }).from(users).where(eq(users.id, s.metadata.user_id))
          : [];
        await sendEmail(
          receiptEmail({
            to,
            name: u?.name ?? null,
            pages: pack.pages,
            amountCents: pack.priceCents,
            balance: await orgBalance(db, orgId),
            accountLink: `${webUrl()}/account`,
          }),
          (obj, msg) => req.log.info(obj, msg)
        );
      }
    } catch (err) {
      req.log.warn({ err, session: s.id }, "receipt not sent");
    }
    return { received: true };
  });
}

interface StripeSession {
  id: string;
  payment_status: string;
  amount_total: number | null;
  customer_email: string | null;
  customer_details?: { email?: string | null } | null;
  metadata?: { org_id?: string; user_id?: string; pack?: string; pages?: string } | null;
}

import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { desc, eq } from "drizzle-orm";
import {
  customers,
  getDb,
  quotes,
  takeoffLines,
  takeoffs,
} from "@scribe/db";
import { QUOTE_VALIDITY_DAYS } from "@scribe/shared";
import { getObject, putObject, signedGetUrl } from "@scribe/storage";
import {
  loadLatestPricingConfig,
  loadOrgSettings,
  loadPricingConfigById,
} from "../lib/settings.js";
import { runPricing, type DbLine } from "../lib/pricing-run.js";
import { renderQuotePdf } from "../lib/quote-pdf.js";

const QuotePatch = z.object({
  markup_pct: z.number().min(-100).max(500).optional(),
  handling_cents: z.number().int().nonnegative().optional(),
  freight_cents: z.number().int().nonnegative().optional(),
  customer_id: z.string().uuid().nullable().optional(),
  status: z.enum(["draft", "sent", "won", "lost", "expired"]).optional(),
  actual_freight_cents: z.number().int().nonnegative().nullable().optional(),
});

async function loadQuoteLines(takeoffId: string): Promise<DbLine[]> {
  const db = getDb();
  return db
    .select()
    .from(takeoffLines)
    .where(eq(takeoffLines.takeoffId, takeoffId));
}

export async function quoteRoutes(app: FastifyInstance): Promise<void> {
  app.addHook("preHandler", app.requireUser);

  app.post("/quotes", async (req, reply) => {
    const body = z
      .object({
        takeoff_id: z.string().uuid(),
        customer_id: z.string().uuid().optional(),
      })
      .parse(req.body);

    const db = getDb();
    const tRows = await db
      .select()
      .from(takeoffs)
      .where(eq(takeoffs.id, body.takeoff_id));
    if (tRows.length === 0) {
      return reply.code(404).send({ error: "takeoff not found" });
    }
    if (tRows[0].status !== "approved") {
      return reply
        .code(409)
        .send({ error: "takeoff must be approved before quoting" });
    }

    const [settings, config] = await Promise.all([
      loadOrgSettings(),
      loadLatestPricingConfig(),
    ]);
    const lines = await loadQuoteLines(body.takeoff_id);
    const run = await runPricing(lines, config.snapshot, settings, {
      markup_pct: 0,
      handling_cents: settings.defaultHandlingCents,
    });

    const validUntil = new Date();
    validUntil.setDate(validUntil.getDate() + QUOTE_VALIDITY_DAYS);

    const [quote] = await db
      .insert(quotes)
      .values({
        takeoffId: body.takeoff_id,
        customerId: body.customer_id ?? null,
        pricingConfigId: config.id,
        subtotalCents: run.totals.subtotal_cents,
        markupPct: 0,
        handlingCents: settings.defaultHandlingCents,
        freightCents: run.totals.freight_cents,
        freightPallets: run.freight_pallets,
        totalCents: run.totals.total_cents,
        validUntil: validUntil.toISOString().slice(0, 10),
        maxLeadTimeDays: run.totals.max_lead_time_days,
        linePrices: { priced: run.priced, unpriced: run.unpriced },
        createdBy: req.user!.id,
      })
      .returning();

    return reply.code(201).send({
      ...quote,
      pricing: run,
    });
  });

  app.get("/quotes", async () => {
    const db = getDb();
    return db.select().from(quotes).orderBy(desc(quotes.createdAt)).limit(200);
  });

  app.get<{ Params: { id: string } }>("/quotes/:id", async (req, reply) => {
    const db = getDb();
    const rows = await db.select().from(quotes).where(eq(quotes.id, req.params.id));
    if (rows.length === 0) return reply.code(404).send({ error: "not found" });
    const quote = rows[0];

    const settings = await loadOrgSettings();
    const config = await loadPricingConfigById(quote.pricingConfigId);
    const lines = await loadQuoteLines(quote.takeoffId);
    const run = await runPricing(lines, config.snapshot, settings, {
      markup_pct: quote.markupPct,
      handling_cents: quote.handlingCents,
      freight_override_cents: quote.freightCents,
    });
    return { ...quote, pricing: run, pricing_config_version: config.version };
  });

  // Re-prices against the quote's PINNED pricing config (reproducibility).
  app.patch<{ Params: { id: string } }>("/quotes/:id", async (req, reply) => {
    const patch = QuotePatch.parse(req.body);
    const db = getDb();
    const rows = await db.select().from(quotes).where(eq(quotes.id, req.params.id));
    if (rows.length === 0) return reply.code(404).send({ error: "not found" });
    const quote = rows[0];

    const settings = await loadOrgSettings();
    const config = await loadPricingConfigById(quote.pricingConfigId);
    const lines = await loadQuoteLines(quote.takeoffId);

    const markupPct = patch.markup_pct ?? quote.markupPct;
    const handlingCents = patch.handling_cents ?? quote.handlingCents;
    const freightOverride = patch.freight_cents ?? quote.freightCents;

    const run = await runPricing(lines, config.snapshot, settings, {
      markup_pct: markupPct,
      handling_cents: handlingCents,
      freight_override_cents: freightOverride,
    });

    // Send gates (PRD §6.5, §12): freight must be verified; no NEEDS REVIEW
    // rates may reach a customer.
    if (patch.status === "sent") {
      if (run.freight_verification_required && !quote.freightVerified) {
        return reply.code(409).send({
          error: "freight must be verified before this quote can be sent",
        });
      }
      if (run.totals.any_needs_review) {
        return reply.code(409).send({
          error:
            "quote prices against NEEDS REVIEW rates — an admin must enter real rates first",
        });
      }
      if (run.unpriced.length > 0) {
        return reply.code(409).send({
          error: `${run.unpriced.length} line(s) are unpriced — resolve or remove them first`,
        });
      }
    }

    const [updated] = await db
      .update(quotes)
      .set({
        markupPct,
        handlingCents,
        freightCents: freightOverride,
        customerId:
          patch.customer_id !== undefined ? patch.customer_id : quote.customerId,
        status: patch.status ?? quote.status,
        actualFreightCents:
          patch.actual_freight_cents !== undefined
            ? patch.actual_freight_cents
            : quote.actualFreightCents,
        subtotalCents: run.totals.subtotal_cents,
        totalCents: run.totals.total_cents,
        maxLeadTimeDays: run.totals.max_lead_time_days,
        linePrices: { priced: run.priced, unpriced: run.unpriced },
        sentAt: patch.status === "sent" ? new Date() : quote.sentAt,
        updatedAt: new Date(),
      })
      .where(eq(quotes.id, req.params.id))
      .returning();

    return { ...updated, pricing: run };
  });

  app.post<{ Params: { id: string } }>(
    "/quotes/:id/verify-freight",
    async (req, reply) => {
      const db = getDb();
      const rows = await db
        .update(quotes)
        .set({ freightVerified: true, updatedAt: new Date() })
        .where(eq(quotes.id, req.params.id))
        .returning();
      if (rows.length === 0) return reply.code(404).send({ error: "not found" });
      return rows[0];
    }
  );

  app.post<{ Params: { id: string } }>(
    "/quotes/:id/pdf",
    async (req, reply) => {
      const db = getDb();
      const rows = await db
        .select()
        .from(quotes)
        .where(eq(quotes.id, req.params.id));
      if (rows.length === 0) return reply.code(404).send({ error: "not found" });
      const quote = rows[0];

      const settings = await loadOrgSettings();
      const config = await loadPricingConfigById(quote.pricingConfigId);
      const lines = await loadQuoteLines(quote.takeoffId);
      const run = await runPricing(lines, config.snapshot, settings, {
        markup_pct: quote.markupPct,
        handling_cents: quote.handlingCents,
        freight_override_cents: quote.freightCents,
      });

      let customerCompany: string | null = null;
      if (quote.customerId) {
        const c = await db
          .select()
          .from(customers)
          .where(eq(customers.id, quote.customerId));
        customerCompany = c[0]?.company ?? null;
      }

      let logo: Buffer | null = null;
      if (settings.logoS3Key) {
        try {
          logo = await getObject(settings.logoS3Key);
        } catch {
          logo = null;
        }
      }

      const lineById = new Map(lines.map((l) => [l.id, l]));
      const plById = new Map(
        config.snapshot.product_lines.map((p) => [p.id, p])
      );

      const pdf = await renderQuotePdf({
        quote_number: quote.id.slice(0, 8).toUpperCase(),
        created_at: quote.createdAt,
        valid_until: quote.validUntil ? new Date(quote.validUntil) : null,
        customer_company: customerCompany,
        lines: run.priced.map((p) => {
          const l = lineById.get(p.takeoff_line_id)!;
          const pl = plById.get(p.product_line_id);
          const dims = [l.widthIn, l.heightIn, l.depthIn]
            .map((d) => (d == null ? "—" : `${d}"`))
            .join(" × ");
          return {
            tag: l.tag,
            room: l.room,
            description: `${pl?.name ?? p.product_line_id} ${dims} ${l.material ?? ""} ${l.finish ?? ""}`.trim(),
            qty: l.qty,
            unit_cents: p.unit_cents,
            total_cents: p.total_cents,
            lead_time_days: p.lead_time_days,
          };
        }),
        subtotal_cents: run.totals.subtotal_cents,
        markup_cents: run.totals.markup_cents,
        handling_cents: run.totals.handling_cents,
        freight_cents: run.totals.freight_cents,
        freight_pallets: quote.freightPallets,
        total_cents: run.totals.total_cents,
        max_lead_time_days: quote.maxLeadTimeDays,
        settings,
        logo,
      });

      const key = `quotes/${quote.id}/quote.pdf`;
      await putObject(key, pdf, "application/pdf");
      await db
        .update(quotes)
        .set({ pdfS3Key: key, updatedAt: new Date() })
        .where(eq(quotes.id, quote.id));

      return { pdf_s3_key: key, url: await signedGetUrl(key, 3600) };
    }
  );

  // BigCommerce draft order — optional integration (PRD §7.1).
  app.post<{ Params: { id: string } }>(
    "/quotes/:id/draft-order",
    async (_req, reply) => {
      if (!process.env.BIGCOMMERCE_STORE_HASH) {
        return reply.code(501).send({
          error:
            "BigCommerce is not configured (BIGCOMMERCE_STORE_HASH / BIGCOMMERCE_ACCESS_TOKEN)",
        });
      }
      return reply.code(501).send({
        error:
          "BigCommerce draft orders require parametric product mapping — tracked on the roadmap",
      });
    }
  );

  app.post("/customers", async (req, reply) => {
    const body = z
      .object({
        company: z.string().min(1),
        contact: z.record(z.string()).optional(),
      })
      .parse(req.body);
    const db = getDb();
    const [c] = await db
      .insert(customers)
      .values({ company: body.company, contact: body.contact ?? null })
      .returning();
    return reply.code(201).send(c);
  });

  app.get("/customers", async () => {
    const db = getDb();
    return db.select().from(customers).orderBy(customers.company);
  });
}

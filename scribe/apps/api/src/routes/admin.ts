import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { desc, eq } from "drizzle-orm";
import {
  exportTemplates,
  getDb,
  orgSettings,
  pricingConfigs,
  productLines,
  sources,
  users,
} from "@scribe/db";
import {
  ExportTemplate,
  PalletConfig,
  PricingSnapshot,
  ProductLineConfig,
  ResolvedParams,
} from "@scribe/shared";
import { priceLine } from "@scribe/pricing";
import { putObject, signedGetUrl } from "@scribe/storage";
import { getCrawlerQueue } from "../lib/queue.js";

export async function adminRoutes(app: FastifyInstance): Promise<void> {
  app.addHook("preHandler", app.requireAdmin);

  // --- Pricing editor (PRD §6.4) ---

  app.get("/admin/pricing", async () => {
    const db = getDb();
    const lines = await db.select().from(productLines).orderBy(productLines.name);
    const versions = await db
      .select({
        id: pricingConfigs.id,
        version: pricingConfigs.version,
        createdAt: pricingConfigs.createdAt,
      })
      .from(pricingConfigs)
      .orderBy(desc(pricingConfigs.version))
      .limit(20);
    return { product_lines: lines, versions };
  });

  // Replaces the product-line set and creates a new immutable pricing_config
  // version. Old quotes keep pricing against their pinned version.
  app.put("/admin/pricing", async (req, reply) => {
    const body = z.object({ product_lines: z.array(ProductLineConfig) }).parse(req.body);
    const db = getDb();

    for (const pl of body.product_lines) {
      await db
        .insert(productLines)
        .values({
          id: pl.id,
          name: pl.name,
          categories: pl.categories,
          sizeMeasure: pl.size_measure,
          materialRates: pl.material_rates,
          finishAdders: pl.finish_adders,
          assemblyAdder: pl.assembly_adder,
          dimBounds: pl.dim_bounds,
          leadTimeDays: pl.lead_time_days,
          active: pl.active,
          updatedAt: new Date(),
        })
        .onConflictDoUpdate({
          target: productLines.id,
          set: {
            name: pl.name,
            categories: pl.categories,
            sizeMeasure: pl.size_measure,
            materialRates: pl.material_rates,
            finishAdders: pl.finish_adders,
            assemblyAdder: pl.assembly_adder,
            dimBounds: pl.dim_bounds,
            leadTimeDays: pl.lead_time_days,
            active: pl.active,
            updatedAt: new Date(),
          },
        });
    }

    const latest = await db
      .select({ version: pricingConfigs.version })
      .from(pricingConfigs)
      .orderBy(desc(pricingConfigs.version))
      .limit(1);
    const nextVersion = (latest[0]?.version ?? 0) + 1;
    const snapshot: PricingSnapshot = {
      version: nextVersion,
      product_lines: body.product_lines,
    };
    const [config] = await db
      .insert(pricingConfigs)
      .values({
        version: nextVersion,
        snapshot,
        createdBy: req.user!.id,
      })
      .returning();

    return reply.code(201).send({ version: config.version, id: config.id });
  });

  // Test calculator: price a sample line against a DRAFT product line before
  // saving (PRD §6.4).
  app.post("/admin/pricing/test-calc", async (req) => {
    const body = z
      .object({
        product_line: ProductLineConfig,
        params: ResolvedParams,
      })
      .parse(req.body);
    return priceLine(body.product_line, body.params);
  });

  // --- Org settings: branding, terms, freight config (PRD §7.1) ---

  app.get("/admin/org-settings", async () => {
    const db = getDb();
    const rows = await db.select().from(orgSettings).where(eq(orgSettings.id, 1));
    const row = rows[0] ?? null;
    let logoUrl: string | null = null;
    if (row?.logoS3Key) {
      logoUrl = await signedGetUrl(row.logoS3Key);
    }
    return { ...row, logo_url: logoUrl };
  });

  app.put("/admin/org-settings", async (req) => {
    const body = z
      .object({
        quote_terms_md: z.string().optional(),
        quote_footer_md: z.string().optional(),
        default_handling_cents: z.number().int().nonnegative().optional(),
        pallet_rate_cents: z.number().int().nonnegative().optional(),
        pallet_config: PalletConfig.partial().optional(),
        freight_provider: z.enum(["flat_pallet", "uber_freight"]).optional(),
      })
      .parse(req.body);

    const db = getDb();
    const set: Record<string, unknown> = {
      updatedBy: req.user!.id,
      updatedAt: new Date(),
    };
    if (body.quote_terms_md !== undefined) set.quoteTermsMd = body.quote_terms_md;
    if (body.quote_footer_md !== undefined) set.quoteFooterMd = body.quote_footer_md;
    if (body.default_handling_cents !== undefined)
      set.defaultHandlingCents = body.default_handling_cents;
    if (body.pallet_rate_cents !== undefined)
      set.palletRateCents = body.pallet_rate_cents;
    if (body.freight_provider !== undefined)
      set.freightProvider = body.freight_provider;
    if (body.pallet_config !== undefined) {
      const rows = await db
        .select()
        .from(orgSettings)
        .where(eq(orgSettings.id, 1));
      const current = PalletConfig.parse(rows[0]?.palletConfig ?? {});
      set.palletConfig = { ...current, ...body.pallet_config };
    }

    const [updated] = await db
      .update(orgSettings)
      .set(set)
      .where(eq(orgSettings.id, 1))
      .returning();
    return updated;
  });

  app.post("/admin/org-settings/logo", async (req, reply) => {
    const file = await req.file();
    if (!file) return reply.code(400).send({ error: "no file uploaded" });
    const ext = file.filename.split(".").pop()?.toLowerCase();
    if (!ext || !["png", "svg", "jpg", "jpeg"].includes(ext)) {
      return reply.code(400).send({ error: "logo must be PNG, SVG, or JPEG" });
    }
    const key = `branding/logo-${randomUUID()}.${ext}`;
    await putObject(key, await file.toBuffer(), file.mimetype);
    const db = getDb();
    await db
      .update(orgSettings)
      .set({ logoS3Key: key, updatedBy: req.user!.id, updatedAt: new Date() })
      .where(eq(orgSettings.id, 1));
    return { logo_s3_key: key, url: await signedGetUrl(key) };
  });

  // --- Export template mapping editor (PRD §7.3) ---

  app.get("/admin/export-templates", async () => {
    const db = getDb();
    return db.select().from(exportTemplates).orderBy(exportTemplates.name);
  });

  app.put("/admin/export-templates", async (req) => {
    const body = z.object({ templates: z.array(ExportTemplate) }).parse(req.body);
    const db = getDb();
    const saved = [];
    for (const t of body.templates) {
      const [row] = await db
        .insert(exportTemplates)
        .values({
          name: t.name,
          target: t.target,
          delimiter: t.delimiter,
          unitFormat: t.unit_format,
          columns: t.columns,
          updatedAt: new Date(),
        })
        .onConflictDoUpdate({
          target: exportTemplates.name,
          set: {
            target: t.target,
            delimiter: t.delimiter,
            unitFormat: t.unit_format,
            columns: t.columns,
            updatedAt: new Date(),
          },
        })
        .returning();
      saved.push(row);
    }
    return saved;
  });

  // --- Crawler sources (PRD §5) ---

  app.get("/admin/sources", async () => {
    const db = getDb();
    return db.select().from(sources).orderBy(sources.name);
  });

  app.post("/admin/sources", async (req, reply) => {
    const body = z
      .object({
        name: z.string().min(1),
        type: z.string().min(1),
        base_url: z.string().url(),
        config: z.record(z.unknown()).default({}),
      })
      .parse(req.body);
    const db = getDb();
    const [row] = await db
      .insert(sources)
      .values({
        name: body.name,
        type: body.type,
        baseUrl: body.base_url,
        config: body.config,
      })
      .returning();
    return reply.code(201).send(row);
  });

  app.patch<{ Params: { id: string } }>(
    "/admin/sources/:id",
    async (req, reply) => {
      const body = z
        .object({
          status: z.enum(["active", "paused", "blocked"]).optional(),
          config: z.record(z.unknown()).optional(),
        })
        .parse(req.body);
      const db = getDb();
      const set: Record<string, unknown> = {};
      if (body.status) set.status = body.status;
      if (body.config) set.config = body.config;
      const rows = await db
        .update(sources)
        .set(set)
        .where(eq(sources.id, req.params.id))
        .returning();
      if (rows.length === 0) return reply.code(404).send({ error: "not found" });
      return rows[0];
    }
  );

  app.post<{ Params: { id: string } }>(
    "/admin/sources/:id/run",
    async (req) => {
      await getCrawlerQueue().add("run-source", { source_id: req.params.id });
      return { enqueued: true };
    }
  );

  // --- Users (no self-signup; admin manages the list) ---

  app.get("/admin/users", async () => {
    const db = getDb();
    return db.select().from(users).orderBy(users.email);
  });

  app.post("/admin/users", async (req, reply) => {
    const body = z
      .object({
        email: z.string().email(),
        role: z.enum(["estimator", "sales", "admin"]).default("estimator"),
        name: z.string().optional(),
      })
      .parse(req.body);
    const db = getDb();
    const [u] = await db
      .insert(users)
      .values({
        email: body.email.toLowerCase(),
        role: body.role,
        name: body.name ?? null,
      })
      .onConflictDoNothing()
      .returning();
    return reply.code(201).send(u ?? { error: "user already exists" });
  });
}

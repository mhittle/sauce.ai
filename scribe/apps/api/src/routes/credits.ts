import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { eq, sql } from "drizzle-orm";
import {
  firstJobFreeAvailable,
  getCreditSettings,
  getDb,
  orgBalance,
  orgs,
  platformSettings,
  recentLedger,
  writeLedger,
} from "@scribe/db";

// Credits (accounts-plan.md §3): 1 credit = 1 page read. Customer view is the
// org's balance, settings for the cost preview, and its ledger; platform
// admins set the rules and adjust balances.

export async function creditRoutes(app: FastifyInstance): Promise<void> {
  app.addHook("preHandler", app.requireUser);

  app.get("/credits", async (req) => {
    const db = getDb();
    const settings = await getCreditSettings(db);
    return {
      balance: await orgBalance(db, req.orgId),
      settings,
      firstJobFree: await firstJobFreeAvailable(db, req.orgId, settings),
      ledger: await recentLedger(db, req.orgId, 50),
    };
  });
}

export async function adminCreditRoutes(app: FastifyInstance): Promise<void> {
  app.addHook("preHandler", app.requireAdmin);

  app.get("/admin/credits", async () => {
    const db = getDb();
    const settings = await getCreditSettings(db);
    const rows = await db.execute(sql`
      SELECT o.id, o.name, o.is_platform, o.credit_balance,
             count(l.*) FILTER (WHERE l.reason = 'hold')::int AS jobs,
             COALESCE(-sum(l.delta) FILTER (WHERE l.reason IN ('hold','release')), 0)::int AS pages_spent,
             COALESCE(sum(l.delta) FILTER (WHERE l.reason IN ('signup_grant','admin_grant','purchase','refund','adjust')), 0)::int AS pages_added,
             max(l.created_at) AS last_activity
      FROM orgs o LEFT JOIN credit_ledger l ON l.org_id = o.id
      GROUP BY o.id ORDER BY o.is_platform DESC, o.name
    `);
    return { settings, orgs: rows.rows };
  });

  app.get<{ Params: { orgId: string } }>("/admin/credits/:orgId/ledger", async (req) => {
    return recentLedger(getDb(), z.string().uuid().parse(req.params.orgId), 200);
  });

  app.patch("/admin/credit-settings", async (req) => {
    const body = z
      .object({
        minPagesPerJob: z.number().int().min(1).max(100).optional(),
        firstJobFree: z.boolean().optional(),
        creditsEnforced: z.boolean().optional(),
      })
      .parse(req.body);
    const db = getDb();
    await db
      .insert(platformSettings)
      .values({ id: 1, ...body, updatedAt: new Date() })
      .onConflictDoUpdate({ target: platformSettings.id, set: { ...body, updatedAt: new Date() } });
    return getCreditSettings(db);
  });

  // A grant (+) or a correction (−), always with a reason a person can read.
  app.post("/admin/credits/adjust", async (req, reply) => {
    const body = z
      .object({
        orgId: z.string().uuid(),
        delta: z.number().int().min(-100_000).max(100_000).refine((n) => n !== 0),
        note: z.string().trim().min(1).max(500),
      })
      .parse(req.body);
    const db = getDb();
    const [org] = await db.select({ id: orgs.id }).from(orgs).where(eq(orgs.id, body.orgId));
    if (!org) return reply.code(404).send({ error: "org not found" });
    const row = await writeLedger(db, {
      orgId: body.orgId,
      delta: body.delta,
      reason: body.delta > 0 ? "admin_grant" : "adjust",
      actorUserId: req.user!.id,
      note: body.note,
    });
    return reply.code(201).send(row);
  });
}

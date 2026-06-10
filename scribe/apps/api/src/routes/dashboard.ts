import type { FastifyInstance } from "fastify";
import { sql } from "drizzle-orm";
import { getDb } from "@scribe/db";

// Pipeline dashboard aggregates (PRD §7.1): quotes by status, $ quoted/won
// per week, turnaround, estimated-vs-actual freight.

export async function dashboardRoutes(app: FastifyInstance): Promise<void> {
  app.addHook("preHandler", app.requireUser);

  app.get("/dashboard", async () => {
    const db = getDb();

    const byStatus = await db.execute(sql`
      SELECT status, count(*)::int AS count, COALESCE(sum(total_cents),0)::bigint AS total_cents
      FROM quotes GROUP BY status
    `);

    const weekly = await db.execute(sql`
      SELECT date_trunc('week', created_at)::date AS week,
             count(*)::int AS quotes,
             COALESCE(sum(total_cents),0)::bigint AS quoted_cents,
             COALESCE(sum(total_cents) FILTER (WHERE status = 'won'),0)::bigint AS won_cents
      FROM quotes
      GROUP BY 1 ORDER BY 1 DESC LIMIT 12
    `);

    const turnaround = await db.execute(sql`
      SELECT avg(EXTRACT(EPOCH FROM (q.sent_at - t.created_at)) / 60)::numeric(10,1) AS avg_minutes
      FROM quotes q JOIN takeoffs t ON t.id = q.takeoff_id
      WHERE q.sent_at IS NOT NULL
    `);

    const freight = await db.execute(sql`
      SELECT count(*)::int AS orders,
             COALESCE(avg(freight_cents),0)::bigint AS avg_estimated_cents,
             COALESCE(avg(actual_freight_cents),0)::bigint AS avg_actual_cents
      FROM quotes
      WHERE actual_freight_cents IS NOT NULL
    `);

    const prospects = await db.execute(sql`
      SELECT status, count(*)::int AS count FROM projects GROUP BY status
    `);

    return {
      quotes_by_status: byStatus.rows,
      weekly: weekly.rows,
      avg_turnaround_minutes: turnaround.rows[0]?.avg_minutes ?? null,
      freight_estimate_vs_actual: freight.rows[0],
      prospects_by_status: prospects.rows,
    };
  });
}

import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { sql } from "drizzle-orm";
import { getDb } from "@scribe/db";

// Admin → Usage (accounts-plan.md §3.3): what model calls cost, read from
// usage_events. Platform admins only; costs are integer microcents
// (cents × 1e6) on the wire, formatted by the web.

const Query = z.object({
  from: z.string().date().optional(),
  to: z.string().date().optional(),
  org_id: z.string().uuid().optional(),
});

// Pages a job is billed on: the pages picked on Pages, else the whole PDF;
// an image or spreadsheet is one page.
const JOB_PAGES = sql`CASE
  WHEN jsonb_typeof(t.selected_pages) = 'array' AND jsonb_array_length(t.selected_pages) > 0
    THEN jsonb_array_length(t.selected_pages)
  WHEN t.source_kind = 'pdf' THEN COALESCE(t.page_count, 1)
  ELSE 1 END`;

export async function usageRoutes(app: FastifyInstance): Promise<void> {
  app.addHook("preHandler", app.requireAdmin);

  app.get("/admin/usage", async (req) => {
    const q = Query.parse(req.query);
    const db = getDb();
    const to = q.to ?? new Date().toISOString().slice(0, 10);
    const from =
      q.from ?? new Date(Date.parse(to) - 29 * 86_400_000).toISOString().slice(0, 10);
    const org = q.org_id ?? null;
    // `to` is inclusive: the whole of that day.
    const where = sql`e.created_at >= ${from}::date
      AND e.created_at < ${to}::date + 1
      AND (${org}::uuid IS NULL OR e.org_id = ${org}::uuid)`;

    const byTakeoff = await db.execute(sql`
      WITH per AS (
        SELECT e.takeoff_id,
               count(*)::int AS calls,
               sum(e.input_tokens + e.cache_write_tokens + e.cache_read_tokens)::bigint AS input_tokens,
               sum(e.output_tokens)::bigint AS output_tokens,
               sum(e.cost_microcents)::bigint AS cost,
               count(DISTINCT e.page_number)::int AS pages_read,
               jsonb_object_agg(e.stage, e.stage_cost) AS by_stage,
               min(e.created_at) AS first_call
        FROM (
          SELECT e.*, sum(e.cost_microcents) OVER (PARTITION BY e.takeoff_id, e.stage)::bigint AS stage_cost
          FROM usage_events e WHERE ${where}
        ) e
        WHERE e.takeoff_id IS NOT NULL
        GROUP BY e.takeoff_id
      )
      SELECT per.*, t.source_filename, t.source_kind, t.status, o.name AS org_name,
             (${JOB_PAGES})::int AS pages,
             (per.cost / GREATEST((${JOB_PAGES}), 1))::bigint AS cost_per_page
      FROM per
      JOIN takeoffs t ON t.id = per.takeoff_id
      JOIN orgs o ON o.id = t.org_id
      ORDER BY per.first_call DESC
      LIMIT 500
    `);

    const byStage = await db.execute(sql`
      SELECT e.stage, e.model,
             count(*)::int AS calls,
             sum(e.input_tokens + e.cache_write_tokens + e.cache_read_tokens)::bigint AS input_tokens,
             sum(e.output_tokens)::bigint AS output_tokens,
             sum(e.image_count)::int AS images,
             sum(e.cost_microcents)::bigint AS cost
      FROM usage_events e WHERE ${where}
      GROUP BY e.stage, e.model
      ORDER BY cost DESC
    `);

    // Per page kind: only calls that are about one page. The measuring pass
    // reads the whole job at once and is reported per job, not per page.
    const byPageKind = await db.execute(sql`
      WITH pages AS (
        SELECT e.takeoff_id, e.page_number,
               COALESCE(max(e.page_kind), 'unknown') AS page_kind,
               sum(e.cost_microcents)::bigint AS cost
        FROM usage_events e
        WHERE ${where} AND e.page_number IS NOT NULL
        GROUP BY e.takeoff_id, e.page_number
      )
      SELECT page_kind,
             count(*)::int AS pages,
             sum(cost)::bigint AS cost,
             percentile_cont(0.5) WITHIN GROUP (ORDER BY cost)::bigint AS median_cost,
             percentile_cont(0.9) WITHIN GROUP (ORDER BY cost)::bigint AS p90_cost
      FROM pages GROUP BY page_kind ORDER BY pages DESC
    `);

    const summary = await db.execute(sql`
      WITH jobs AS (
        SELECT e.takeoff_id, sum(e.cost_microcents)::bigint AS cost,
               (${JOB_PAGES})::int AS pages
        FROM usage_events e JOIN takeoffs t ON t.id = e.takeoff_id
        WHERE ${where}
        GROUP BY e.takeoff_id, t.id
      )
      SELECT count(*)::int AS jobs,
             COALESCE(sum(pages), 0)::int AS pages,
             COALESCE(sum(cost), 0)::bigint AS cost,
             percentile_cont(0.5) WITHIN GROUP (ORDER BY cost)::bigint AS median_job,
             percentile_cont(0.9) WITHIN GROUP (ORDER BY cost)::bigint AS p90_job,
             percentile_cont(0.5) WITHIN GROUP (ORDER BY cost / GREATEST(pages, 1))::bigint AS median_page,
             percentile_cont(0.9) WITHIN GROUP (ORDER BY cost / GREATEST(pages, 1))::bigint AS p90_page
      FROM jobs
    `);

    const orgList = await db.execute(sql`
      SELECT DISTINCT o.id, o.name FROM usage_events e JOIN orgs o ON o.id = e.org_id ORDER BY o.name
    `);

    return {
      from,
      to,
      summary: summary.rows[0],
      by_takeoff: byTakeoff.rows,
      by_stage: byStage.rows,
      by_page_kind: byPageKind.rows,
      orgs: orgList.rows,
    };
  });
}

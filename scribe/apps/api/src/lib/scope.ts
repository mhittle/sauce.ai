import type { FastifyReply, FastifyRequest } from "fastify";
import { and, eq } from "drizzle-orm";
import { getDb, quotes, takeoffs } from "@scribe/db";

// Org scoping (accounts-plan.md §1.7). Every takeoff/quote lookup goes
// through one of these so a cross-org id reads as "not found".

export function takeoffInOrg(orgId: string, id: string) {
  return and(eq(takeoffs.id, id), eq(takeoffs.orgId, orgId));
}

export function quoteInOrg(orgId: string, id: string) {
  return and(eq(quotes.id, id), eq(quotes.orgId, orgId));
}

// Subquery of the org's takeoff ids, for tables keyed by takeoff_id
// (lines, detections) that are addressed by their own id.
export function orgTakeoffIds(orgId: string) {
  return getDb().select({ id: takeoffs.id }).from(takeoffs).where(eq(takeoffs.orgId, orgId));
}

// preHandler for `/takeoffs/:id/…`: the takeoff must exist in the request's
// org, or the route never runs. Routes that load the takeoff themselves keep
// doing so (they need the row); this closes the ones that only touch children.
export async function requireTakeoffInOrg(
  req: FastifyRequest,
  reply: FastifyReply
): Promise<void> {
  const id = (req.params as { id?: string }).id;
  if (!id) return;
  const rows = await getDb()
    .select({ id: takeoffs.id })
    .from(takeoffs)
    .where(takeoffInOrg(req.orgId, id));
  if (rows.length === 0) await reply.code(404).send({ error: "not found" });
}

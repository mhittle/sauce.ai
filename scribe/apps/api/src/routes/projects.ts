import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { and, desc, eq, gte, SQL } from "drizzle-orm";
import { getDb, projectDocuments, projects } from "@scribe/db";
import { ProjectStatus } from "@scribe/shared";
import { signedGetUrl } from "@scribe/storage";

export async function projectRoutes(app: FastifyInstance): Promise<void> {
  app.addHook("preHandler", app.requireUser);

  app.get<{
    Querystring: { status?: string; min_score?: string; assigned_to?: string };
  }>("/projects", async (req) => {
    const db = getDb();
    const conds: SQL[] = [];
    if (req.query.status) {
      conds.push(eq(projects.status, ProjectStatus.parse(req.query.status)));
    }
    if (req.query.min_score) {
      conds.push(
        gte(projects.cabinetRelevanceScore, Number(req.query.min_score))
      );
    }
    if (req.query.assigned_to) {
      conds.push(eq(projects.assignedTo, req.query.assigned_to));
    }

    const rows = await db
      .select()
      .from(projects)
      .where(conds.length > 0 ? and(...conds) : undefined)
      .orderBy(desc(projects.cabinetRelevanceScore))
      .limit(500);

    const docs = await db.select().from(projectDocuments);
    const docsByProject = new Map<string, typeof docs>();
    for (const d of docs) {
      const list = docsByProject.get(d.projectId) ?? [];
      list.push(d);
      docsByProject.set(d.projectId, list);
    }

    return rows.map((p) => ({
      ...p,
      documents: docsByProject.get(p.id) ?? [],
    }));
  });

  app.get<{ Params: { id: string } }>("/projects/:id", async (req, reply) => {
    const db = getDb();
    const rows = await db
      .select()
      .from(projects)
      .where(eq(projects.id, req.params.id));
    if (rows.length === 0) return reply.code(404).send({ error: "not found" });
    const docs = await db
      .select()
      .from(projectDocuments)
      .where(eq(projectDocuments.projectId, req.params.id));
    return { ...rows[0], documents: docs };
  });

  app.patch<{ Params: { id: string } }>("/projects/:id", async (req, reply) => {
    const patch = z
      .object({
        status: ProjectStatus.optional(),
        assigned_to: z.string().uuid().nullable().optional(),
      })
      .parse(req.body);
    const db = getDb();
    const set: Record<string, unknown> = { updatedAt: new Date() };
    if (patch.status) set.status = patch.status;
    if (patch.assigned_to !== undefined) set.assignedTo = patch.assigned_to;
    const rows = await db
      .update(projects)
      .set(set)
      .where(eq(projects.id, req.params.id))
      .returning();
    if (rows.length === 0) return reply.code(404).send({ error: "not found" });
    return rows[0];
  });

  app.get<{ Params: { id: string } }>(
    "/project-documents/:id/url",
    async (req, reply) => {
      const db = getDb();
      const rows = await db
        .select()
        .from(projectDocuments)
        .where(eq(projectDocuments.id, req.params.id));
      if (rows.length === 0) return reply.code(404).send({ error: "not found" });
      return { url: await signedGetUrl(rows[0].s3Key) };
    }
  );
}

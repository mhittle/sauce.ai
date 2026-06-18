import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { desc, eq } from "drizzle-orm";
import {
  getDb,
  exportTemplates,
  productLines,
  projectDocuments,
  takeoffs,
  takeoffLines,
  evalFixtures,
} from "@scribe/db";
import { ESTIMATED_NOTE_PREFIX, ExportTemplate, SourceKind } from "@scribe/shared";
import { exportCsv, type ExportableLine } from "@scribe/export";
import { putObject, signedGetUrl } from "@scribe/storage";
import { getTakeoffQueue } from "../lib/queue.js";

const EXT_TO_KIND: Record<string, SourceKind> = {
  pdf: "pdf",
  xlsx: "xlsx",
  xls: "xlsx",
  csv: "csv",
  png: "image",
  jpg: "image",
  jpeg: "image",
  webp: "image",
};

const LinePatch = z.object({
  tag: z.string().nullable().optional(),
  room: z.string().nullable().optional(),
  qty: z.number().positive().optional(),
  category: z.string().optional(),
  width_in: z.number().positive().nullable().optional(),
  height_in: z.number().positive().nullable().optional(),
  depth_in: z.number().positive().nullable().optional(),
  door_style: z.string().nullable().optional(),
  material: z.string().nullable().optional(),
  finish: z.string().nullable().optional(),
  assembled: z.boolean().nullable().optional(),
  notes: z.string().nullable().optional(),
  product_line_id: z.string().nullable().optional(),
  resolved_params: z.record(z.unknown()).nullable().optional(),
  confidence: z.number().min(0).max(1).optional(),
});

export async function takeoffRoutes(app: FastifyInstance): Promise<void> {
  app.addHook("preHandler", app.requireUser);

  // Read-only product-line list for the review screen's unmatched bucket.
  app.get("/product-lines", async () => {
    const db = getDb();
    return db.select().from(productLines).orderBy(productLines.name);
  });

  // Multipart upload (PDF/XLSX/CSV/image) or JSON {project_document_id}.
  app.post("/takeoffs", async (req, reply) => {
    const db = getDb();
    let s3Key: string;
    let filename: string;
    let kind: SourceKind;
    let projectId: string | null = null;

    if (req.isMultipart()) {
      const file = await req.file();
      if (!file) return reply.code(400).send({ error: "no file uploaded" });
      filename = file.filename;
      const ext = filename.split(".").pop()?.toLowerCase() ?? "";
      const mapped = EXT_TO_KIND[ext];
      if (!mapped) {
        return reply
          .code(400)
          .send({ error: `unsupported file type .${ext}` });
      }
      kind = mapped;
      const buf = await file.toBuffer();
      s3Key = `takeoffs/${randomUUID()}/${filename}`;
      await putObject(s3Key, buf, file.mimetype);
    } else {
      const body = z
        .object({ project_document_id: z.string().uuid() })
        .parse(req.body);
      const docs = await db
        .select()
        .from(projectDocuments)
        .where(eq(projectDocuments.id, body.project_document_id));
      if (docs.length === 0) {
        return reply.code(404).send({ error: "project document not found" });
      }
      const doc = docs[0];
      s3Key = doc.s3Key;
      filename = doc.s3Key.split("/").pop() ?? "document.pdf";
      kind = "pdf";
      projectId = doc.projectId;
    }

    const [takeoff] = await db
      .insert(takeoffs)
      .values({
        projectId,
        uploadedBy: req.user!.id,
        sourceFileS3Key: s3Key,
        sourceFilename: filename,
        sourceKind: kind,
        status: "processing",
      })
      .returning();

    await getTakeoffQueue().add("process", { takeoff_id: takeoff.id });
    return reply.code(201).send(takeoff);
  });

  app.get("/takeoffs", async () => {
    const db = getDb();
    return db.select().from(takeoffs).orderBy(desc(takeoffs.createdAt)).limit(200);
  });

  app.get<{ Params: { id: string } }>("/takeoffs/:id", async (req, reply) => {
    const db = getDb();
    const rows = await db
      .select()
      .from(takeoffs)
      .where(eq(takeoffs.id, req.params.id));
    if (rows.length === 0) return reply.code(404).send({ error: "not found" });
    const lines = await db
      .select()
      .from(takeoffLines)
      .where(eq(takeoffLines.takeoffId, req.params.id))
      .orderBy(takeoffLines.sourcePage, takeoffLines.createdAt);
    return { ...rows[0], lines };
  });

  // Signed URL for a rasterized page image (review-screen provenance).
  app.get<{ Params: { id: string; page: string } }>(
    "/takeoffs/:id/pages/:page/image",
    async (req) => {
      const key = `takeoffs/${req.params.id}/pages/${req.params.page}.png`;
      return { url: await signedGetUrl(key) };
    }
  );

  app.patch<{ Params: { id: string } }>(
    "/takeoff-lines/:id",
    async (req, reply) => {
      const patch = LinePatch.parse(req.body);
      const db = getDb();
      const set: Record<string, unknown> = { reviewerEdited: true, updatedAt: new Date() };
      const map: Record<string, string> = {
        tag: "tag",
        room: "room",
        qty: "qty",
        category: "category",
        width_in: "widthIn",
        height_in: "heightIn",
        depth_in: "depthIn",
        door_style: "doorStyle",
        material: "material",
        finish: "finish",
        assembled: "assembled",
        notes: "notes",
        product_line_id: "productLineId",
        resolved_params: "resolvedParams",
        confidence: "confidence",
      };
      for (const [k, v] of Object.entries(patch)) {
        if (v !== undefined) set[map[k]] = v;
      }
      const rows = await db
        .update(takeoffLines)
        .set(set)
        .where(eq(takeoffLines.id, req.params.id))
        .returning();
      if (rows.length === 0) return reply.code(404).send({ error: "not found" });
      return rows[0];
    }
  );

  app.delete<{ Params: { id: string } }>(
    "/takeoff-lines/:id",
    async (req, reply) => {
      const db = getDb();
      const rows = await db
        .delete(takeoffLines)
        .where(eq(takeoffLines.id, req.params.id))
        .returning();
      if (rows.length === 0) return reply.code(404).send({ error: "not found" });
      return { ok: true };
    }
  );

  // Approve gate: locks the takeoff and snapshots approved lines as eval
  // ground truth (the pre-correction extraction was stored at extraction time).
  app.post<{ Params: { id: string } }>(
    "/takeoffs/:id/approve",
    async (req, reply) => {
      const db = getDb();
      const rows = await db
        .select()
        .from(takeoffs)
        .where(eq(takeoffs.id, req.params.id));
      if (rows.length === 0) return reply.code(404).send({ error: "not found" });
      if (!["extracted", "review"].includes(rows[0].status)) {
        return reply
          .code(409)
          .send({ error: `cannot approve takeoff in status ${rows[0].status}` });
      }

      const lines = await db
        .select()
        .from(takeoffLines)
        .where(eq(takeoffLines.takeoffId, req.params.id));

      const [updated] = await db
        .update(takeoffs)
        .set({ status: "approved", updatedAt: new Date() })
        .where(eq(takeoffs.id, req.params.id))
        .returning();

      const fixtures = await db
        .select()
        .from(evalFixtures)
        .where(eq(evalFixtures.takeoffId, req.params.id));
      if (fixtures.length > 0) {
        await db
          .update(evalFixtures)
          .set({ approvedLines: lines })
          .where(eq(evalFixtures.takeoffId, req.params.id));
      }

      return updated;
    }
  );

  app.get<{ Params: { id: string }; Querystring: { template?: string } }>(
    "/takeoffs/:id/export.csv",
    async (req, reply) => {
      const db = getDb();
      const templateName = req.query.template ?? "Generic (all fields)";
      const tpls = await db
        .select()
        .from(exportTemplates)
        .where(eq(exportTemplates.name, templateName));
      if (tpls.length === 0) {
        return reply
          .code(404)
          .send({ error: `export template "${templateName}" not found` });
      }
      const t = tpls[0];
      const template = ExportTemplate.parse({
        name: t.name,
        target: t.target,
        delimiter: t.delimiter,
        unit_format: t.unitFormat,
        columns: t.columns,
      });

      const lines = await db
        .select()
        .from(takeoffLines)
        .where(eq(takeoffLines.takeoffId, req.params.id))
        .orderBy(takeoffLines.sourcePage);

      const exportable: ExportableLine[] = lines.map((l) => ({
        source_page: l.sourcePage,
        tag: l.tag,
        room: l.room,
        qty: l.qty,
        category: l.category as ExportableLine["category"],
        width_in: l.widthIn,
        height_in: l.heightIn,
        depth_in: l.depthIn,
        door_style: l.doorStyle,
        material: l.material,
        finish: l.finish,
        assembled: l.assembled,
        notes: l.notes,
        confidence: l.confidence,
        // No estimated column on takeoff_lines; the [ESTIMATED] note prefix
        // (set in the worker) carries the flag.
        estimated: l.notes?.startsWith(ESTIMATED_NOTE_PREFIX) ?? false,
      }));

      reply
        .header("content-type", "text/csv; charset=utf-8")
        .header(
          "content-disposition",
          `attachment; filename="takeoff-${req.params.id.slice(0, 8)}-${template.target}.csv"`
        );
      return exportCsv(exportable, template);
    }
  );
}

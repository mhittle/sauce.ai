import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { and, desc, eq, sql } from "drizzle-orm";
import {
  getDb,
  exportTemplates,
  pricingConfigs,
  productLines,
  projectDocuments,
  takeoffs,
  takeoffDetections,
  takeoffLines,
  evalFixtures,
} from "@scribe/db";
import {
  CabinetLineItem,
  canTransitionTakeoff,
  ESTIMATED_NOTE_PREFIX,
  expandToComponents,
  ExportTemplate,
  LineCategory,
  PricingSnapshot,
  SelectedPage,
  SourceKind,
  type TakeoffStatus,
} from "@scribe/shared";
import { matchLine } from "@scribe/pricing";
import { exportCsv, type ExportableLine } from "@scribe/export";
import { objectExists, putObject, signedGetUrl } from "@scribe/storage";
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

const BBox = z.tuple([z.number(), z.number(), z.number(), z.number()]);

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
  // Box-review gate: moving/resizing a box is a visual-anchor edit only —
  // the inches fields drive pricing.
  bbox: BBox.nullable().optional(),
});

// A reviewer-drawn box becomes a new line (box gate "add box" flow).
const LineCreate = z.object({
  takeoff_id: z.string().uuid(),
  category: LineCategory,
  qty: z.number().positive().default(1),
  tag: z.string().nullable().optional(),
  room: z.string().nullable().optional(),
  width_in: z.number().positive().nullable().optional(),
  height_in: z.number().positive().nullable().optional(),
  depth_in: z.number().positive().nullable().optional(),
  notes: z.string().nullable().optional(),
  source_page: z.number().int().positive().nullable().optional(),
  bbox: BBox.nullable().optional(),
  read_image_key: z.string().nullable().optional(),
});

// DB row → the pure line shape pricing + expansion work on.
function lineFromRow(
  row: typeof takeoffLines.$inferSelect
): CabinetLineItem {
  return {
    source_page: row.sourcePage,
    tag: row.tag,
    room: row.room,
    qty: row.qty,
    category: row.category as CabinetLineItem["category"],
    width_in: row.widthIn,
    height_in: row.heightIn,
    depth_in: row.depthIn,
    door_style: row.doorStyle,
    material: row.material,
    finish: row.finish,
    assembled: row.assembled,
    notes: row.notes,
    confidence: row.confidence,
    estimated: row.notes?.startsWith(ESTIMATED_NOTE_PREFIX) ?? false,
    bbox_2d: null,
  };
}

async function latestSnapshot(): Promise<PricingSnapshot> {
  const db = getDb();
  const cfgRows = await db
    .select()
    .from(pricingConfigs)
    .orderBy(desc(pricingConfigs.version))
    .limit(1);
  if (cfgRows.length === 0) throw new Error("no pricing config — seed the DB");
  return PricingSnapshot.parse(cfgRows[0].snapshot);
}

function matchCols(m: ReturnType<typeof matchLine>) {
  return {
    productLineId: m.product_line_id,
    resolvedParams: "resolved" in m ? m.resolved : null,
    matchConfidence: "match_confidence" in m ? m.match_confidence : null,
    alternates: "alternates" in m ? m.alternates : null,
    unmatchedReason: "reason" in m ? m.reason : null,
  };
}

// Interactive review: a cabinet's door/drawer-front faces derive from its box
// line. When the box changes (or is created) at review, drop and re-derive
// its faces so the priced list follows the edit. Faces link to their cabinet
// via raw_model_output {expanded: true, parent: <lineId>}.
async function refreshDerivedFaces(
  takeoffId: string,
  parentId: string,
  line: CabinetLineItem,
  snapshot: PricingSnapshot
): Promise<void> {
  const db = getDb();
  await db
    .delete(takeoffLines)
    .where(
      and(
        eq(takeoffLines.takeoffId, takeoffId),
        sql`${takeoffLines.rawModelOutput}->>'parent' = ${parentId}`
      )
    );
  for (const face of expandToComponents(line)) {
    const m = matchLine(face, snapshot);
    await db.insert(takeoffLines).values({
      takeoffId,
      sourcePage: face.source_page,
      tag: face.tag,
      room: face.room,
      qty: face.qty,
      category: face.category,
      widthIn: face.width_in,
      heightIn: face.height_in,
      depthIn: face.depth_in,
      doorStyle: face.door_style,
      material: face.material,
      finish: face.finish,
      assembled: face.assembled,
      notes: face.notes,
      confidence: face.confidence,
      ...matchCols(m),
      rawModelOutput: { expanded: true, parent: parentId },
    });
  }
}

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

    // Two-gate flow: PDFs stop at the page picker first; single images have
    // nothing to pick and go straight to extraction (then the box gate);
    // spreadsheets keep the ungated single-stage job.
    const jobName =
      kind === "pdf" ? "prepare" : kind === "image" ? "extract" : "process";
    await getTakeoffQueue().add(jobName, { takeoff_id: takeoff.id });
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

  // Signed URL for a page-picker thumbnail (written by the prepare stage).
  app.get<{ Params: { id: string; page: string } }>(
    "/takeoffs/:id/thumbs/:page/image",
    async (req, reply) => {
      const db = getDb();
      const rows = await db
        .select()
        .from(takeoffs)
        .where(eq(takeoffs.id, req.params.id));
      if (rows.length === 0) return reply.code(404).send({ error: "not found" });
      const page = Number(req.params.page);
      const pageCount = rows[0].pageCount;
      if (
        !Number.isInteger(page) ||
        page < 1 ||
        (pageCount != null && page > pageCount)
      ) {
        return reply.code(404).send({ error: "page out of range" });
      }
      const key = `takeoffs/${req.params.id}/thumbs/${page}.png`;
      return { url: await signedGetUrl(key) };
    }
  );

  // Signed URL for the EXACT image a set of lines was read from (box-review
  // overlay). readId is a worker-generated slug (e.g. "p3-c1-r0"); reject
  // anything that could traverse the key space.
  app.get<{ Params: { id: string; readId: string } }>(
    "/takeoffs/:id/reads/:readId/image",
    async (req, reply) => {
      const db = getDb();
      const rows = await db
        .select()
        .from(takeoffs)
        .where(eq(takeoffs.id, req.params.id));
      if (rows.length === 0) return reply.code(404).send({ error: "not found" });
      if (!/^[A-Za-z0-9._-]+$/.test(req.params.readId)) {
        return reply.code(400).send({ error: "invalid read id" });
      }
      const key = `takeoffs/${req.params.id}/reads/${req.params.readId}.png`;
      return { url: await signedGetUrl(key) };
    }
  );

  // -------------------------------------------------------------------------
  // Beta drag-to-detect view: on-demand region scans, independent of the
  // takeoff line pipeline (no status transitions, no takeoff_lines writes).
  // -------------------------------------------------------------------------

  // Signed URL for the beta display render of a page. If the render doesn't
  // exist yet, enqueue it (deduped by jobId) and return {url: null} — the
  // client polls until the worker has written the PNG.
  app.get<{ Params: { id: string; page: string } }>(
    "/takeoffs/:id/beta/pages/:page/image",
    async (req, reply) => {
      const db = getDb();
      const rows = await db
        .select()
        .from(takeoffs)
        .where(eq(takeoffs.id, req.params.id));
      if (rows.length === 0) return reply.code(404).send({ error: "not found" });
      const page = Number(req.params.page);
      const pageCount = rows[0].pageCount;
      if (
        !Number.isInteger(page) ||
        page < 1 ||
        (pageCount != null && page > pageCount)
      ) {
        return reply.code(404).send({ error: "page out of range" });
      }
      if (rows[0].sourceKind !== "pdf") {
        return reply.code(400).send({ error: "detect view is PDF-only" });
      }
      const key = `takeoffs/${req.params.id}/beta/pages/${page}.png`;
      if (await objectExists(key)) return { url: await signedGetUrl(key) };
      await getTakeoffQueue().add(
        "beta_render",
        { takeoff_id: req.params.id, page },
        { jobId: `beta-render-${req.params.id}-${page}` }
      );
      return { url: null };
    }
  );

  // One drag = one DRAWN detection (wizard step 2). Nothing is sent to the
  // model yet — the run endpoint below queues all drawn boxes at once.
  // rect is [x0,y0,x1,y1] in pixels of the beta display render.
  app.post<{ Params: { id: string } }>(
    "/takeoffs/:id/detections",
    async (req, reply) => {
      const body = z
        .object({
          page: z.number().int().positive(),
          rect: BBox,
        })
        .parse(req.body);
      const db = getDb();
      const rows = await db
        .select()
        .from(takeoffs)
        .where(eq(takeoffs.id, req.params.id));
      if (rows.length === 0) return reply.code(404).send({ error: "not found" });
      if (rows[0].sourceKind !== "pdf") {
        return reply.code(400).send({ error: "detect view is PDF-only" });
      }
      const pageCount = rows[0].pageCount;
      if (pageCount != null && body.page > pageCount) {
        return reply
          .code(400)
          .send({ error: `page out of range (document has ${pageCount} pages)` });
      }
      const [detection] = await db
        .insert(takeoffDetections)
        .values({
          takeoffId: req.params.id,
          page: body.page,
          rect: body.rect,
          status: "drawn",
        })
        .returning();
      return detection;
    }
  );

  // Wizard step 3: send every drawn box to the model at once.
  app.post<{ Params: { id: string } }>(
    "/takeoffs/:id/detections/run",
    async (req, reply) => {
      const db = getDb();
      const drawn = await db
        .update(takeoffDetections)
        .set({ status: "queued" })
        .where(
          and(
            eq(takeoffDetections.takeoffId, req.params.id),
            eq(takeoffDetections.status, "drawn")
          )
        )
        .returning();
      if (drawn.length === 0)
        return reply.code(400).send({ error: "no drawn boxes to detect" });
      const queue = getTakeoffQueue();
      for (const d of drawn) {
        await queue.add("detect", {
          takeoff_id: req.params.id,
          detection_id: d.id,
        });
      }
      return { queued: drawn.length };
    }
  );

  // Remove ONE detected box (wizard: the table ✕). The row disappears with
  // its last item.
  app.delete<{ Params: { id: string; detectionId: string; index: string } }>(
    "/takeoffs/:id/detections/:detectionId/items/:index",
    async (req, reply) => {
      const db = getDb();
      const rows = await db
        .select()
        .from(takeoffDetections)
        .where(
          and(
            eq(takeoffDetections.id, req.params.detectionId),
            eq(takeoffDetections.takeoffId, req.params.id)
          )
        );
      if (rows.length === 0) return reply.code(404).send({ error: "not found" });
      const items = Array.isArray(rows[0].items) ? [...rows[0].items] : [];
      const index = Number(req.params.index);
      if (!Number.isInteger(index) || index < 0 || index >= items.length) {
        return reply.code(400).send({ error: "item index out of range" });
      }
      items.splice(index, 1);
      if (items.length === 0) {
        await db
          .delete(takeoffDetections)
          .where(eq(takeoffDetections.id, req.params.detectionId));
      } else {
        await db
          .update(takeoffDetections)
          .set({ items })
          .where(eq(takeoffDetections.id, req.params.detectionId));
      }
      return { ok: true, remaining: items.length };
    }
  );

  // All detections for a takeoff (optionally one page), newest first.
  app.get<{ Params: { id: string }; Querystring: { page?: string } }>(
    "/takeoffs/:id/detections",
    async (req) => {
      const db = getDb();
      const page = req.query.page != null ? Number(req.query.page) : null;
      const where =
        page != null && Number.isInteger(page)
          ? and(
              eq(takeoffDetections.takeoffId, req.params.id),
              eq(takeoffDetections.page, page)
            )
          : eq(takeoffDetections.takeoffId, req.params.id);
      return db
        .select()
        .from(takeoffDetections)
        .where(where)
        .orderBy(desc(takeoffDetections.createdAt));
    }
  );

  // Wizard step 4: turn every detected cabinet into real takeoff lines —
  // one whole-input measurements pass, then the standard price+faces tail.
  // REPLACES any existing lines (the UI confirms first).
  app.post<{ Params: { id: string } }>(
    "/takeoffs/:id/build-takeoff",
    async (req, reply) => {
      const db = getDb();
      const rows = await db
        .select()
        .from(takeoffs)
        .where(eq(takeoffs.id, req.params.id));
      if (rows.length === 0) return reply.code(404).send({ error: "not found" });
      const takeoff = rows[0];
      if (takeoff.sourceKind !== "pdf") {
        return reply.code(400).send({ error: "detect view is PDF-only" });
      }
      if (!["awaiting_pages", "review"].includes(takeoff.status)) {
        return reply.code(409).send({
          error: `cannot build takeoff from detections in status ${takeoff.status}`,
        });
      }
      const detections = await db
        .select()
        .from(takeoffDetections)
        .where(
          and(
            eq(takeoffDetections.takeoffId, req.params.id),
            eq(takeoffDetections.status, "done")
          )
        );
      const itemCount = detections.reduce(
        (n, d) => n + (Array.isArray(d.items) ? d.items.length : 0),
        0
      );
      if (itemCount === 0) {
        return reply
          .code(400)
          .send({ error: "no detected cabinets — run detection first" });
      }
      const [updated] = await db
        .update(takeoffs)
        .set({ status: "processing", error: null, updatedAt: new Date() })
        .where(eq(takeoffs.id, req.params.id))
        .returning();
      await getTakeoffQueue().add("beta_build", {
        takeoff_id: req.params.id,
        prior_status: takeoff.status,
      });
      return updated;
    }
  );

  app.delete<{ Params: { id: string; detectionId: string } }>(
    "/takeoffs/:id/detections/:detectionId",
    async (req, reply) => {
      const db = getDb();
      const deleted = await db
        .delete(takeoffDetections)
        .where(
          and(
            eq(takeoffDetections.id, req.params.detectionId),
            eq(takeoffDetections.takeoffId, req.params.id)
          )
        )
        .returning();
      if (deleted.length === 0)
        return reply.code(404).send({ error: "not found" });
      return { ok: true };
    }
  );

  // Page-picker gate: record which pages the human wants read (+ optional
  // per-page type overrides) and kick off extraction.
  app.post<{ Params: { id: string } }>(
    "/takeoffs/:id/pages",
    async (req, reply) => {
      const body = z
        .object({ pages: z.array(SelectedPage).min(1) })
        .parse(req.body);
      const db = getDb();
      const rows = await db
        .select()
        .from(takeoffs)
        .where(eq(takeoffs.id, req.params.id));
      if (rows.length === 0) return reply.code(404).send({ error: "not found" });
      const takeoff = rows[0];
      if (
        takeoff.status !== "awaiting_pages" ||
        !canTransitionTakeoff(takeoff.status as TakeoffStatus, "processing")
      ) {
        return reply.code(409).send({
          error: `cannot select pages for takeoff in status ${takeoff.status}`,
        });
      }
      const pageCount = takeoff.pageCount;
      if (pageCount != null && body.pages.some((p) => p.page > pageCount)) {
        return reply
          .code(400)
          .send({ error: `page out of range (document has ${pageCount} pages)` });
      }

      const [updated] = await db
        .update(takeoffs)
        .set({
          selectedPages: body.pages,
          status: "processing",
          error: null,
          updatedAt: new Date(),
        })
        .where(eq(takeoffs.id, req.params.id))
        .returning();
      await getTakeoffQueue().add("extract", { takeoff_id: req.params.id });
      return updated;
    }
  );

  // Box-review gate: the human approved the boxes — expand faces + price.
  app.post<{ Params: { id: string } }>(
    "/takeoffs/:id/finalize-boxes",
    async (req, reply) => {
      const db = getDb();
      const rows = await db
        .select()
        .from(takeoffs)
        .where(eq(takeoffs.id, req.params.id));
      if (rows.length === 0) return reply.code(404).send({ error: "not found" });
      const takeoff = rows[0];
      if (
        takeoff.status !== "awaiting_boxes" ||
        !canTransitionTakeoff(takeoff.status as TakeoffStatus, "processing")
      ) {
        return reply.code(409).send({
          error: `cannot finalize boxes for takeoff in status ${takeoff.status}`,
        });
      }

      const [updated] = await db
        .update(takeoffs)
        .set({ status: "processing", error: null, updatedAt: new Date() })
        .where(eq(takeoffs.id, req.params.id))
        .returning();
      await getTakeoffQueue().add("finalize", { takeoff_id: req.params.id });
      return updated;
    }
  );

  // Create a line for a reviewer-drawn box. At review (the interactive priced
  // list) the new cabinet is matched and its door/drawer faces derived
  // immediately; at the legacy awaiting_boxes gate the finalize job does it.
  app.post("/takeoff-lines", async (req, reply) => {
    const body = LineCreate.parse(req.body);
    const db = getDb();
    const rows = await db
      .select()
      .from(takeoffs)
      .where(eq(takeoffs.id, body.takeoff_id));
    if (rows.length === 0) {
      return reply.code(404).send({ error: "takeoff not found" });
    }
    if (!["awaiting_boxes", "review"].includes(rows[0].status)) {
      return reply.code(409).send({
        error: `cannot add lines to takeoff in status ${rows[0].status}`,
      });
    }
    const [line] = await db
      .insert(takeoffLines)
      .values({
        takeoffId: body.takeoff_id,
        sourcePage: body.source_page ?? null,
        tag: body.tag ?? null,
        room: body.room ?? null,
        qty: body.qty,
        category: body.category,
        widthIn: body.width_in ?? null,
        heightIn: body.height_in ?? null,
        depthIn: body.depth_in ?? null,
        notes: body.notes ?? null,
        // A human drew this box — it is not a model guess.
        confidence: 1,
        reviewerEdited: true,
        bbox: body.bbox ?? null,
        readImageKey: body.read_image_key ?? null,
      })
      .returning();
    if (rows[0].status !== "review") return reply.code(201).send(line);

    const snapshot = await latestSnapshot();
    const cab = lineFromRow(line);
    const [priced] = await db
      .update(takeoffLines)
      .set(matchCols(matchLine(cab, snapshot)))
      .where(eq(takeoffLines.id, line.id))
      .returning();
    if (["pdf", "image"].includes(rows[0].sourceKind)) {
      await refreshDerivedFaces(body.takeoff_id, line.id, cab, snapshot);
    }
    return reply.code(201).send(priced);
  });

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
        bbox: "bbox",
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
      const row = rows[0];

      // Interactive review: a pricing-relevant edit re-matches the line and
      // re-derives its door/drawer faces, so the priced list follows the
      // edit. Manual product-line assignment (the unmatched bucket) is left
      // untouched, and derived faces stand alone.
      const manualAssign =
        patch.product_line_id !== undefined || patch.resolved_params !== undefined;
      const PRICING_FIELDS = [
        "tag",
        "qty",
        "category",
        "width_in",
        "height_in",
        "depth_in",
        "material",
        "finish",
        "assembled",
        "notes",
      ] as const;
      const pricingTouched = PRICING_FIELDS.some(
        (f) => patch[f] !== undefined
      );
      const isDerivedFace =
        (row.rawModelOutput as { expanded?: boolean } | null)?.expanded === true;
      if (manualAssign || !pricingTouched || isDerivedFace) return row;

      const tk = await db
        .select()
        .from(takeoffs)
        .where(eq(takeoffs.id, row.takeoffId));
      // Only priced flows: extraction-stage rows (legacy awaiting_boxes) get
      // matched by the finalize job instead.
      if (tk.length === 0 || !["review", "extracted"].includes(tk[0].status)) {
        return row;
      }
      const snapshot = await latestSnapshot();
      const line = lineFromRow(row);
      const [repriced] = await db
        .update(takeoffLines)
        .set(matchCols(matchLine(line, snapshot)))
        .where(eq(takeoffLines.id, row.id))
        .returning();
      // Faces exist only on visual flows (spreadsheets never expand).
      if (["pdf", "image"].includes(tk[0].sourceKind)) {
        await refreshDerivedFaces(row.takeoffId, row.id, line, snapshot);
      }
      return repriced;
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
      // Deleting a cabinet also removes the door/drawer faces derived from it.
      await db
        .delete(takeoffLines)
        .where(
          and(
            eq(takeoffLines.takeoffId, rows[0].takeoffId),
            sql`${takeoffLines.rawModelOutput}->>'parent' = ${req.params.id}`
          )
        );
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
        bbox_2d: null,
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

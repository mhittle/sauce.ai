import { randomUUID } from "node:crypto";
import { and, eq } from "drizzle-orm";
import { getDb, orgSettings, takeoffDetections, takeoffLines, takeoffs } from "@scribe/db";

// The tutorial's sample job (accounts-plan.md §2): the platform admin marks
// one finished takeoff as the sample; each new org gets a copy — rows only,
// the page/read images stay shared through storage_id. Best-effort: a
// missing or unset sample never fails a sign-up.
export async function cloneSampleTakeoff(orgId: string, userId: string): Promise<string | null> {
  const db = getDb();
  const [settings] = await db
    .select({ sampleTakeoffId: orgSettings.sampleTakeoffId })
    .from(orgSettings)
    .where(eq(orgSettings.id, 1));
  const sourceId = settings?.sampleTakeoffId;
  if (!sourceId) return null;
  const [src] = await db.select().from(takeoffs).where(eq(takeoffs.id, sourceId));
  if (!src) return null;
  const already = await db
    .select({ id: takeoffs.id })
    .from(takeoffs)
    .where(and(eq(takeoffs.orgId, orgId), eq(takeoffs.isSample, true)));
  if (already.length > 0) return already[0].id;

  const lines = await db.select().from(takeoffLines).where(eq(takeoffLines.takeoffId, sourceId));
  const dets = await db.select().from(takeoffDetections).where(eq(takeoffDetections.takeoffId, sourceId));

  return db.transaction(async (tx) => {
    const { id: _id, createdAt: _c, updatedAt: _u, ...rest } = src;
    const [t] = await tx
      .insert(takeoffs)
      .values({
        ...rest,
        orgId,
        uploadedBy: userId,
        projectId: null,
        sourceFilename: `Sample — ${src.sourceFilename ?? "kitchen"}`,
        status: src.status === "approved" ? "review" : src.status,
        isSample: true,
        storageId: src.storageId ?? src.id,
        tokensUsed: 0,
      })
      .returning();
    const detMap = new Map<string, string>();
    for (const d of dets) {
      const { id, createdAt: _dc, ...drest } = d;
      const nid = randomUUID();
      detMap.set(id, nid);
      await tx.insert(takeoffDetections).values({ ...drest, id: nid, takeoffId: t.id });
    }
    // Derived faces point at their parent cabinet by id inside raw_model_output.
    const lineMap = new Map<string, string>(lines.map((l) => [l.id, randomUUID()]));
    for (const l of lines) {
      const { id, createdAt: _lc, updatedAt: _lu, ...lrest } = l;
      const raw = (lrest.rawModelOutput ?? null) as { parent?: string } | null;
      const rawOut =
        raw && typeof raw.parent === "string" && lineMap.has(raw.parent)
          ? { ...raw, parent: lineMap.get(raw.parent) }
          : raw;
      await tx.insert(takeoffLines).values({
        ...lrest,
        id: lineMap.get(id),
        takeoffId: t.id,
        detectionId: lrest.detectionId ? (detMap.get(lrest.detectionId) ?? null) : null,
        rawModelOutput: rawOut,
      });
    }
    return t.id;
  });
}

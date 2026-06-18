import { createHash, randomUUID } from "node:crypto";
import type { Logger } from "pino";
import { and, eq, sql } from "drizzle-orm";
import {
  getDb,
  projectDocuments,
  projects,
  sources,
} from "@scribe/db";
import { NormalizedProject } from "@scribe/shared";
import { putObject } from "@scribe/storage";
import { politeFetch, SourceAdapter, SourceRow } from "./adapters/types.js";
import { socrataAdapter } from "./adapters/socrata.js";
import { samgovAdapter } from "./adapters/samgov.js";
import { scoreProject } from "./score.js";

const ADAPTERS: Record<string, SourceAdapter> = {
  [socrataAdapter.type]: socrataAdapter,
  [samgovAdapter.type]: samgovAdapter,
};

const MAX_DOCS_PER_PROJECT = 5;
const MAX_DOC_BYTES = 100 * 1024 * 1024;

export async function runAllSources(log: Logger): Promise<void> {
  const db = getDb();
  const rows = await db
    .select()
    .from(sources)
    .where(eq(sources.status, "active"));
  for (const row of rows) {
    try {
      await runSource(row.id, log);
    } catch (err) {
      log.error({ source: row.name, err: String(err) }, "source run failed");
    }
  }
}

export async function runSource(sourceId: string, log: Logger): Promise<void> {
  const db = getDb();
  const rows = await db.select().from(sources).where(eq(sources.id, sourceId));
  if (rows.length === 0) throw new Error(`source ${sourceId} not found`);
  const row = rows[0];

  const adapter = ADAPTERS[row.type];
  if (!adapter) {
    await db
      .update(sources)
      .set({ lastError: `no adapter for type "${row.type}"`, status: "error" })
      .where(eq(sources.id, sourceId));
    return;
  }

  const sourceRow: SourceRow = {
    id: row.id,
    name: row.name,
    type: row.type,
    baseUrl: row.baseUrl,
    config: row.config as Record<string, unknown>,
  };

  try {
    const result = await adapter.fetchSince(sourceRow, row.lastCursor);
    log.info(
      { source: row.name, records: result.projects.length },
      "fetched records"
    );

    for (const project of result.projects) {
      await upsertProject(project, log);
    }

    await db
      .update(sources)
      .set({
        lastCursor: result.nextCursor,
        lastRunAt: new Date(),
        lastError: null,
      })
      .where(eq(sources.id, sourceId));
  } catch (err) {
    await db
      .update(sources)
      .set({ lastError: String(err), lastRunAt: new Date() })
      .where(eq(sources.id, sourceId));
    throw err;
  }
}

// dedupe stage (PRD §5.4): match on permit number + jurisdiction, then
// canonical address; merge source_refs instead of inserting twice.
async function findExisting(
  p: NormalizedProject
): Promise<{ id: string; sourceRefs: unknown } | null> {
  const db = getDb();
  if (p.permit_number && p.jurisdiction) {
    const byPermit = await db
      .select({ id: projects.id, sourceRefs: projects.sourceRefs })
      .from(projects)
      .where(
        and(
          eq(projects.permitNumber, p.permit_number),
          eq(projects.jurisdiction, p.jurisdiction)
        )
      );
    if (byPermit.length > 0) return byPermit[0];
  }
  if (p.canonical_address) {
    const byAddress = await db
      .select({ id: projects.id, sourceRefs: projects.sourceRefs })
      .from(projects)
      .where(
        and(
          sql`lower(${projects.canonicalAddress}) = lower(${p.canonical_address})`,
          eq(projects.jurisdiction, p.jurisdiction)
        )
      );
    if (byAddress.length > 0) return byAddress[0];
  }
  return null;
}

async function upsertProject(
  p: NormalizedProject,
  log: Logger
): Promise<void> {
  const db = getDb();
  const existing = await findExisting(p);

  if (existing) {
    const refs = Array.isArray(existing.sourceRefs) ? existing.sourceRefs : [];
    const alreadySeen = refs.some(
      (r: { source_id?: string; external_id?: string }) =>
        r.source_id === p.source_ref.source_id &&
        r.external_id === p.source_ref.external_id
    );
    if (!alreadySeen) {
      await db
        .update(projects)
        .set({
          sourceRefs: [...refs, p.source_ref],
          updatedAt: new Date(),
        })
        .where(eq(projects.id, existing.id));
    }
    return;
  }

  const score = await scoreProject(p);

  const [inserted] = await db
    .insert(projects)
    .values({
      canonicalAddress: p.canonical_address,
      jurisdiction: p.jurisdiction,
      permitNumber: p.permit_number,
      parcel: p.parcel,
      projectType: p.project_type,
      valuationCents: p.valuation_cents,
      estCabinetScopeUsd: score.est_cabinet_scope_usd,
      description: p.description,
      gcName: p.gc_name,
      gcContact: p.gc_contact,
      cabinetRelevanceScore: score.cabinet_relevance_score,
      scoreRationale: score.rationale,
      sourceRefs: [p.source_ref],
    })
    .returning({ id: projects.id });

  // plan-discovery (PRD §5.4): download linked PDFs to R2 with provenance;
  // filename heuristics for doc class (first-page vision check on roadmap).
  if (score.cabinet_relevance_score >= 40 && p.document_urls.length > 0) {
    await discoverDocuments(inserted.id, p.document_urls, log);
  }
}

// SAM.gov resource-download links require the api_key; add it at fetch time
// only so the secret never persists to project_documents.fetched_from_url.
function authedDocUrl(url: string): string {
  const key = process.env.SAMGOV_API_KEY;
  if (!key) return url;
  const u = new URL(url);
  if (!u.host.endsWith("sam.gov")) return url;
  u.searchParams.set("api_key", key);
  return u.toString();
}

function classifyByFilename(url: string): string {
  const lower = url.toLowerCase();
  if (/(plan|drawing|dwg|arch|a\d{3})/.test(lower)) return "plan_set";
  if (/(spec|specification)/.test(lower)) return "spec_book";
  return "other";
}

async function discoverDocuments(
  projectId: string,
  urls: string[],
  log: Logger
): Promise<void> {
  const db = getDb();
  for (const url of urls.slice(0, MAX_DOCS_PER_PROJECT)) {
    try {
      const res = await politeFetch(authedDocUrl(url));
      if (!res.ok) continue;
      const contentType = res.headers.get("content-type") ?? "";
      const buf = Buffer.from(await res.arrayBuffer());
      if (buf.length > MAX_DOC_BYTES) continue;
      const isPdf =
        contentType.includes("pdf") || buf.subarray(0, 4).toString() === "%PDF";
      if (!isPdf) continue;

      const sha = createHash("sha256").update(buf).digest("hex");
      const dupe = await db
        .select({ id: projectDocuments.id })
        .from(projectDocuments)
        .where(
          and(
            eq(projectDocuments.projectId, projectId),
            eq(projectDocuments.sha256, sha)
          )
        );
      if (dupe.length > 0) continue;

      const key = `prospect-docs/${projectId}/${randomUUID()}.pdf`;
      await putObject(key, buf, "application/pdf");
      await db.insert(projectDocuments).values({
        projectId,
        s3Key: key,
        docClass: classifyByFilename(url),
        sha256: sha,
        fetchedFromUrl: url,
      });
    } catch (err) {
      log.warn({ url, err: String(err) }, "doc download failed");
    }
  }
}

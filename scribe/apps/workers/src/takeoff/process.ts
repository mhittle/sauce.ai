import type { Logger } from "pino";
import { desc, eq } from "drizzle-orm";
import {
  evalFixtures,
  getDb,
  pricingConfigs,
  takeoffLines,
  takeoffs,
} from "@scribe/db";
import {
  CabinetLineItem,
  PageClassification,
  PageExtraction,
  PricingSnapshot,
  RELEVANT_PAGE_CLASSES,
} from "@scribe/shared";
import { matchLine } from "@scribe/pricing";
import { EXTRACT_PROMPT_VERSION } from "@scribe/prompts";
import { getObject, putObject } from "@scribe/storage";
import { BudgetExceededError, TakeoffBudget } from "../lib/anthropic.js";
import { classifyPages } from "./classify.js";
import { extractPage } from "./extract.js";
import { EXTRACTION_DPI, openPdf, THUMBNAIL_DPI } from "./pdf.js";
import { parseSpreadsheet } from "./spreadsheet.js";

// Orchestrates one takeoff end-to-end: input → classified pages → extracted
// lines → product-line matching → review queue (PRD §6).

export async function processTakeoff(
  takeoffId: string,
  log: Logger
): Promise<void> {
  const db = getDb();
  const rows = await db.select().from(takeoffs).where(eq(takeoffs.id, takeoffId));
  if (rows.length === 0) throw new Error(`takeoff ${takeoffId} not found`);
  const takeoff = rows[0];
  const budget = new TakeoffBudget();

  try {
    const file = await getObject(takeoff.sourceFileS3Key);

    let lines: CabinetLineItem[];
    let raws: unknown[] = [];
    let classified: PageClassification[] | null = null;
    let pageCount: number | null = null;
    let summary: {
      uncertainties: string[];
      unreadable_pages: number[];
      warnings: string[];
    } = { uncertainties: [], unreadable_pages: [], warnings: [] };

    if (takeoff.sourceKind === "pdf") {
      const result = await processPdf(takeoffId, file, budget, log);
      lines = result.lines;
      raws = result.raws;
      classified = result.classified;
      pageCount = result.pageCount;
      summary = result.summary;
    } else if (takeoff.sourceKind === "xlsx" || takeoff.sourceKind === "csv") {
      const parsed = await parseSpreadsheet(file, budget, {
        modelAssist: Boolean(process.env.ANTHROPIC_API_KEY),
      });
      lines = parsed.lines;
      summary.warnings = parsed.warnings;
    } else {
      // image: single-page vision extraction; store the image for provenance.
      await putObject(`takeoffs/${takeoffId}/pages/1.png`, file, "image/png");
      const { extraction, raw } = await extractPage(1, file, budget);
      lines = extraction.lines;
      raws = [raw];
      summary.uncertainties = extraction.uncertainties;
      if (extraction.unreadable) summary.unreadable_pages = [1];
    }

    // Match lines to product lines against the latest pricing snapshot.
    const cfgRows = await db
      .select()
      .from(pricingConfigs)
      .orderBy(desc(pricingConfigs.version))
      .limit(1);
    if (cfgRows.length === 0) throw new Error("no pricing config — seed the DB");
    const snapshot = PricingSnapshot.parse(cfgRows[0].snapshot);

    for (const [i, line] of lines.entries()) {
      const match = matchLine(line, snapshot);
      await db.insert(takeoffLines).values({
        takeoffId,
        sourcePage: line.source_page,
        tag: line.tag,
        room: line.room,
        qty: line.qty,
        category: line.category,
        widthIn: line.width_in,
        heightIn: line.height_in,
        depthIn: line.depth_in,
        doorStyle: line.door_style,
        material: line.material,
        finish: line.finish,
        assembled: line.assembled,
        notes: line.notes,
        confidence: line.confidence,
        productLineId: match.product_line_id,
        resolvedParams: "resolved" in match ? match.resolved : null,
        matchConfidence: "match_confidence" in match ? match.match_confidence : null,
        alternates: "alternates" in match ? match.alternates : null,
        unmatchedReason: "reason" in match ? match.reason : null,
        rawModelOutput: raws.length > 0 ? { page_raw_index: i } : null,
      });
    }

    const docConfidence =
      lines.length > 0
        ? lines.reduce((s, l) => s + l.confidence, 0) / lines.length
        : null;

    // Pre-correction snapshot → self-building eval corpus (PRD §10).
    await db.insert(evalFixtures).values({
      takeoffId,
      extractedLines: lines,
      promptVersion: EXTRACT_PROMPT_VERSION,
    });

    await db
      .update(takeoffs)
      .set({
        status: "review",
        pageCount,
        classifiedPages: classified,
        docConfidence,
        docSummary: { ...summary, raw_outputs: raws },
        promptVersion: EXTRACT_PROMPT_VERSION,
        tokensUsed: budget.used,
        updatedAt: new Date(),
      })
      .where(eq(takeoffs.id, takeoffId));

    log.info(
      { takeoffId, lines: lines.length, tokens: budget.used },
      "takeoff processed"
    );
  } catch (err) {
    const message =
      err instanceof BudgetExceededError
        ? `cost guardrail: ${err.message}`
        : String(err instanceof Error ? err.message : err);
    await db
      .update(takeoffs)
      .set({
        status: "failed",
        error: message,
        tokensUsed: budget.used,
        updatedAt: new Date(),
      })
      .where(eq(takeoffs.id, takeoffId));
    throw err;
  }
}

async function processPdf(
  takeoffId: string,
  file: Buffer,
  budget: TakeoffBudget,
  log: Logger
): Promise<{
  lines: CabinetLineItem[];
  raws: unknown[];
  classified: PageClassification[];
  pageCount: number;
  summary: {
    uncertainties: string[];
    unreadable_pages: number[];
    warnings: string[];
  };
}> {
  const pdf = openPdf(file);
  try {
    const pageCount = pdf.pageCount;
    log.info({ takeoffId, pageCount }, "rasterizing thumbnails");

    const thumbnails: { page: number; png: Uint8Array }[] = [];
    for (let i = 0; i < pageCount; i++) {
      thumbnails.push({ page: i + 1, png: pdf.renderPage(i, THUMBNAIL_DPI) });
    }

    const classified = await classifyPages(thumbnails, budget);
    const relevant = classified
      .filter((c) => RELEVANT_PAGE_CLASSES.includes(c.class))
      // Schedules first; elevations as supplement (PRD §6.3).
      .sort((a, b) => {
        const rank = (c: PageClassification) =>
          c.class === "cabinet_schedule_table"
            ? 0
            : c.class === "finish_schedule"
              ? 1
              : 2;
        return rank(a) - rank(b);
      });

    log.info(
      { takeoffId, relevant: relevant.map((r) => r.page) },
      "classified pages"
    );

    const lines: CabinetLineItem[] = [];
    const raws: unknown[] = [];
    const summary = {
      uncertainties: [] as string[],
      unreadable_pages: [] as number[],
      warnings: [] as string[],
    };

    for (const pageInfo of relevant) {
      const png = pdf.renderPage(pageInfo.page - 1, EXTRACTION_DPI);
      // Persist for review-screen provenance (click line → source page).
      await putObject(
        `takeoffs/${takeoffId}/pages/${pageInfo.page}.png`,
        png,
        "image/png"
      );
      let extraction: PageExtraction;
      try {
        const result = await extractPage(pageInfo.page, png, budget);
        extraction = result.extraction;
        raws.push({ page: pageInfo.page, raw: result.raw });
      } catch (err) {
        if (err instanceof BudgetExceededError) throw err;
        summary.warnings.push(
          `page ${pageInfo.page}: extraction failed (${String(err)})`
        );
        continue;
      }
      lines.push(...extraction.lines);
      summary.uncertainties.push(
        ...extraction.uncertainties.map((u) => `p${pageInfo.page}: ${u}`)
      );
      if (extraction.unreadable) summary.unreadable_pages.push(pageInfo.page);
    }

    return { lines, raws, classified, pageCount, summary };
  } finally {
    pdf.close();
  }
}

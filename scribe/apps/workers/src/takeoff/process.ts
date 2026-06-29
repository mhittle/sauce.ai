import type { Logger } from "pino";
import { desc, eq } from "drizzle-orm";
import {
  evalFixtures,
  getDb,
  orgSettings,
  pricingConfigs,
  takeoffLines,
  takeoffs,
} from "@scribe/db";
import {
  CabinetLineItem,
  dedupeLines,
  fitDpi,
  mapBoxToPagePoints,
  needsRegioning,
  PageClass,
  PageClassification,
  PageExtraction,
  padRectToPage,
  planRenderJobs,
  PricingSnapshot,
  RegionKind,
  RELEVANT_PAGE_CLASSES,
  expandToComponents,
} from "@scribe/shared";
import { matchLine } from "@scribe/pricing";
import { EXTRACT_PROMPT_VERSION } from "@scribe/prompts";
import { getObject, putObject } from "@scribe/storage";
import { BudgetExceededError, TakeoffBudget } from "../lib/anthropic.js";
import { openaiConfigured } from "../lib/openai.js";
import { classifyPages } from "./classify.js";
import { crossValidatePage } from "./cross-validate.js";
import { extractPage } from "./extract.js";
import { OpenPdf, openPdf, THUMBNAIL_DPI } from "./pdf.js";
import { locateRegions, locateRooms } from "./regions.js";
import { parseSpreadsheet } from "./spreadsheet.js";

// Region kinds worth cropping + extracting (PRD §4 legible-reads path).
const EXTRACTABLE_REGION_KINDS: RegionKind[] = ["schedule", "elevation", "plan"];
// Ignore detected boxes smaller than this — too small to be a real drawing.
const MIN_REGION_IN = { width: 1.5, height: 1 };

// Optional secondary-model validation state, accumulated across pages.
interface CrossVal {
  enabled: boolean;
  tokens: number;
  secondaryRaws: unknown[];
}

// Best-effort: a cross-validation failure never fails the takeoff. On success
// the returned extraction has primary lines with lowered confidence where the
// two models disagree.
async function runCrossValidation(
  pageNumber: number,
  png: Uint8Array,
  extraction: PageExtraction,
  crossVal: CrossVal,
  warnings: string[],
  log: Logger
): Promise<PageExtraction> {
  try {
    const outcome = await crossValidatePage(pageNumber, png, extraction);
    crossVal.tokens += outcome.tokens;
    crossVal.secondaryRaws.push({ page: pageNumber, raw: outcome.secondaryRaw });
    for (const f of outcome.flags) {
      warnings.push(
        `p${pageNumber}: cross-val ${f.kind}${f.tag ? ` ${f.tag}` : ""} — ${f.detail}`
      );
    }
    return outcome.extraction;
  } catch (err) {
    const msg = String(err instanceof Error ? err.message : err);
    log.warn({ pageNumber, err: msg }, "cross-validation skipped");
    warnings.push(`p${pageNumber}: cross-validation skipped (${msg})`);
    return extraction;
  }
}

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

  const settingsRows = await db
    .select()
    .from(orgSettings)
    .where(eq(orgSettings.id, 1));
  const crossVal: CrossVal = {
    enabled: Boolean(settingsRows[0]?.crossValidationEnabled) && openaiConfigured(),
    tokens: 0,
    secondaryRaws: [],
  };

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
      const result = await processPdf(takeoffId, file, budget, crossVal, log);
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
      raws = [raw];
      const validated = crossVal.enabled
        ? await runCrossValidation(1, file, extraction, crossVal, summary.warnings, log)
        : extraction;
      lines = validated.lines;
      summary.uncertainties = validated.uncertainties;
      if (validated.unreadable) summary.unreadable_pages = [1];
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
        docSummary: {
          ...summary,
          raw_outputs: raws,
          cross_validation: crossVal.enabled
            ? {
                model: process.env.OPENAI_VISION_MODEL ?? "gpt-4.1",
                tokens: crossVal.tokens,
                secondary_outputs: crossVal.secondaryRaws,
              }
            : null,
        },
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
  crossVal: CrossVal,
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

    // No cabinet schedule → estimation mode (PRD §4): also read floor plans, and
    // flag everything extracted as an estimate (handled per-line in extractPage).
    const estimationMode = !classified.some(
      (c) => c.class === "cabinet_schedule_table"
    );
    const relevantClasses: PageClass[] = estimationMode
      ? [...RELEVANT_PAGE_CLASSES, "floor_plan"]
      : RELEVANT_PAGE_CLASSES;

    const relevant = classified
      .filter((c) => relevantClasses.includes(c.class))
      // Schedules first, then finish schedules, elevations, floor plans last
      // (least precise source — PRD §6.3).
      .sort((a, b) => {
        const rank = (c: PageClassification) =>
          c.class === "cabinet_schedule_table"
            ? 0
            : c.class === "finish_schedule"
              ? 1
              : c.class === "floor_plan"
                ? 3
                : 2;
        return rank(a) - rank(b);
      });

    log.info(
      { takeoffId, estimationMode, relevant: relevant.map((r) => r.page) },
      "classified pages"
    );

    const lines: CabinetLineItem[] = [];
    const raws: unknown[] = [];
    const summary = {
      uncertainties: [] as string[],
      unreadable_pages: [] as number[],
      warnings: [] as string[],
    };
    if (estimationMode) {
      summary.uncertainties.push(
        "No cabinet schedule detected — quantities below are ESTIMATED from the floor plan/elevations and must be verified before quoting."
      );
    }

    for (const pageInfo of relevant) {
      await readRelevantPage(
        takeoffId,
        pdf,
        pageInfo.page,
        budget,
        crossVal,
        log,
        estimationMode,
        pageInfo.class,
        { lines, raws, summary }
      );
    }

    // No-schedule estimation: a room shown in BOTH a floor plan and its
    // elevations gets enumerated once per view ("Kitchen" vs "Kitchen - North
    // Wall Run"), and the estimate path sums every region with no dedup — so
    // multi-view inputs balloon 2-4x. Collapse per NORMALIZED room (strip the
    // "- <wall>" suffix): for each cabinet tag keep the MAX count seen in any
    // single view (not the sum), which removes cross-view duplicates while
    // preserving legitimate repeats. Single-view rooms pass through unchanged.
    if (estimationMode) {
      const normRoom = (r: string | null) =>
        (r ?? "").toLowerCase().split(/[-—–]/)[0].trim();
      const tagKey = (l: CabinetLineItem) =>
        (l.tag ?? l.category ?? "").toLowerCase().trim();
      const byRoom = new Map<string, CabinetLineItem[]>();
      for (const l of lines) {
        const k = normRoom(l.room);
        byRoom.set(k, [...(byRoom.get(k) ?? []), l]);
      }
      const deduped: CabinetLineItem[] = [];
      for (const roomLines of byRoom.values()) {
        // group this room's lines by source view (raw room label)
        const byView = new Map<string, CabinetLineItem[]>();
        for (const l of roomLines) {
          const v = (l.room ?? "").toLowerCase().trim();
          byView.set(v, [...(byView.get(v) ?? []), l]);
        }
        // per cabinet tag, keep the view that enumerated the most of it
        const bestPerTag = new Map<string, CabinetLineItem[]>();
        for (const viewLines of byView.values()) {
          const tagCount = new Map<string, CabinetLineItem[]>();
          for (const l of viewLines)
            tagCount.set(tagKey(l), [...(tagCount.get(tagKey(l)) ?? []), l]);
          for (const [t, ls] of tagCount) {
            if ((bestPerTag.get(t)?.length ?? 0) < ls.length)
              bestPerTag.set(t, ls);
          }
        }
        for (const ls of bestPerTag.values()) deduped.push(...ls);
      }
      const removed = lines.length - deduped.length;
      lines.length = 0;
      lines.push(...deduped);
      if (removed > 0)
        log.info(
          { takeoffId, removed, kept: deduped.length },
          "collapsed cross-view duplicate cabinets (estimation)"
        );

      // each cabinet box also has doors + drawer fronts (priced separately by
      // ft²). Spawn those face line items so the schedule mirrors a real quote.
      const faces = lines.flatMap((l) => expandToComponents(l));
      lines.push(...faces);
      log.info({ takeoffId, faces: faces.length }, "expanded cabinets into door/front faces");
    }

    return { lines, raws, classified, pageCount, summary };
  } finally {
    pdf.close();
  }
}

// Read one relevant page. Large-format sheets are downscaled past legibility if
// sent whole (PRD §4), so they're segmented into their distinct drawings (one
// vision "locate" call) and each drawing is cropped + re-rendered at full
// resolution; drawings too big for one image are tiled and de-duplicated.
// Pages that already fit legibly are sent as a single image, as before.
async function readRelevantPage(
  takeoffId: string,
  pdf: OpenPdf,
  page: number,
  budget: TakeoffBudget,
  crossVal: CrossVal,
  log: Logger,
  estimate: boolean,
  pageClass: PageClass,
  acc: {
    lines: CabinetLineItem[];
    raws: unknown[];
    summary: { uncertainties: string[]; unreadable_pages: number[]; warnings: string[] };
  }
): Promise<void> {
  const idx = page - 1;
  const dims = pdf.pageDimsPt(idx);
  const widthIn = dims.widthPt / 72;
  const heightIn = dims.heightPt / 72;

  // Full page rendered at (at most) the model's native resolution: used both as
  // the review-screen provenance image and as the region-locate input.
  const locateDpi = fitDpi(widthIn, heightIn);
  const fullPng = pdf.renderPage(idx, locateDpi);
  await putObject(`takeoffs/${takeoffId}/pages/${page}.png`, fullPng, "image/png");

  const collect = (extraction: PageExtraction, into: CabinetLineItem[]): void => {
    into.push(...extraction.lines);
    acc.summary.uncertainties.push(
      ...extraction.uncertainties.map((u) => `p${page}: ${u}`)
    );
    if (extraction.unreadable && !acc.summary.unreadable_pages.includes(page)) {
      acc.summary.unreadable_pages.push(page);
    }
  };

  // Small enough to read whole: single image, original behavior.
  if (!needsRegioning(dims)) {
    let extraction: PageExtraction;
    try {
      const result = await extractPage(page, fullPng, budget, { estimate });
      extraction = result.extraction;
      acc.raws.push({ page, raw: result.raw });
    } catch (err) {
      if (err instanceof BudgetExceededError) throw err;
      acc.summary.warnings.push(`page ${page}: extraction failed (${String(err)})`);
      return;
    }
    if (crossVal.enabled) {
      extraction = await runCrossValidation(
        page,
        fullPng,
        extraction,
        crossVal,
        acc.summary.warnings,
        log
      );
    }
    collect(extraction, acc.lines);
    return;
  }

  // Large format: locate the distinct drawings, fall back to the whole page.
  const fullW = Math.round(widthIn * locateDpi);
  const fullH = Math.round(heightIn * locateDpi);
  let regions: { kind: RegionKind; rect: ReturnType<typeof padRectToPage> }[] = [];
  try {
    // No-schedule estimation on a floor plan: segment by ROOM so each room's
    // cabinetry is laid out from a coherent crop. Otherwise locate drawings.
    const located =
      estimate && pageClass === "floor_plan"
        ? await locateRooms(fullPng, fullW, fullH, budget)
        : await locateRegions(fullPng, fullW, fullH, budget);
    regions = located.regions
      .filter((r) => EXTRACTABLE_REGION_KINDS.includes(r.kind))
      .map((r) => ({
        kind: r.kind,
        rect: padRectToPage(
          mapBoxToPagePoints(r.box, { widthPx: fullW, heightPx: fullH }, dims),
          0.04,
          dims
        ),
      }))
      .filter(
        (r) =>
          (r.rect.x1 - r.rect.x0) / 72 >= MIN_REGION_IN.width &&
          (r.rect.y1 - r.rect.y0) / 72 >= MIN_REGION_IN.height
      );
  } catch (err) {
    if (err instanceof BudgetExceededError) throw err;
    acc.summary.warnings.push(
      `page ${page}: region detection skipped (${String(err)}); tiling whole page`
    );
  }
  if (regions.length === 0) {
    regions = [
      { kind: "other", rect: { x0: 0, y0: 0, x1: dims.widthPt, y1: dims.heightPt } },
    ];
  }

  // Estimation reads each region as ONE coherent image: a room must not be
  // fragmented across tiles, or the model can't lay out its whole cabinet run.
  // (Schedule/elevation extraction still tiles for legibility — below.)
  if (estimate) {
    for (const region of regions) {
      const wIn = (region.rect.x1 - region.rect.x0) / 72;
      const hIn = (region.rect.y1 - region.rect.y0) / 72;
      const crop = pdf.renderRegion(idx, region.rect, fitDpi(wIn, hIn));
      let extraction: PageExtraction;
      try {
        const result = await extractPage(page, crop, budget, {
          region: true,
          estimate: true,
        });
        extraction = result.extraction;
        acc.raws.push({ page, region: region.kind, raw: result.raw });
      } catch (err) {
        if (err instanceof BudgetExceededError) throw err;
        acc.summary.warnings.push(
          `page ${page} (${region.kind}): estimate failed (${String(err)})`
        );
        continue;
      }
      if (crossVal.enabled) {
        extraction = await runCrossValidation(
          page,
          crop,
          extraction,
          crossVal,
          acc.summary.warnings,
          log
        );
      }
      collect(extraction, acc.lines);
    }
    return;
  }

  const jobs = regions.flatMap((r, i) =>
    planRenderJobs(r.rect, dims, i, r.kind)
  );
  log.info(
    { takeoffId, page, regions: regions.length, jobs: jobs.length },
    "reading large-format page in regions"
  );

  // Extract each crop; de-duplicate within a region (overlapping tiles), but
  // not across regions (distinct drawings legitimately repeat tags/sizes).
  const linesByRegion = new Map<number, CabinetLineItem[]>();
  for (const job of jobs) {
    const crop = pdf.renderRegion(idx, job.rect, job.dpi);
    let extraction: PageExtraction;
    try {
      const result = await extractPage(page, crop, budget, {
        region: true,
        estimate,
      });
      extraction = result.extraction;
      acc.raws.push({ page, region: job.regionId, raw: result.raw });
    } catch (err) {
      if (err instanceof BudgetExceededError) throw err;
      acc.summary.warnings.push(
        `page ${page} region ${job.regionId}: extraction failed (${String(err)})`
      );
      continue;
    }
    if (crossVal.enabled) {
      extraction = await runCrossValidation(
        page,
        crop,
        extraction,
        crossVal,
        acc.summary.warnings,
        log
      );
    }
    const bucket = linesByRegion.get(job.regionId) ?? [];
    collect(extraction, bucket);
    linesByRegion.set(job.regionId, bucket);
  }
  for (const regionLines of linesByRegion.values()) {
    acc.lines.push(...dedupeLines(regionLines));
  }
}

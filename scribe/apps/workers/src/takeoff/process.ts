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
  boxFaceArea,
  CabinetLineItem,
  dedupeLines,
  dropNonBoxCasework,
  extractCabinetSchedule,
  fitDpi,
  MIN_SCHEDULE_ROWS,
  pickMedian,
  mapBoxToPagePoints,
  needsRegioning,
  PageClass,
  PageClassification,
  PageExtraction,
  PageRole,
  pageClassToRole,
  padRectToPage,
  planRenderJobs,
  PricingSnapshot,
  RegionKind,
  RELEVANT_PAGE_CLASSES,
  routeByPageRole,
  expandToComponents,
  buildDimGrounding,
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

    // Class 1 — the input already LISTS the cabinets in a text-layer schedule
    // table (spec sheet / cut list / itemized quote). Read it verbatim: exact,
    // free, and no zero-shot counting ceiling. When found, skip vision entirely.
    const scheduleInput = [];
    for (let i = 0; i < pageCount; i++) {
      scheduleInput.push({ page: i + 1, fragments: pdf.pageTextFragments(i) });
    }
    const sched = extractCabinetSchedule(scheduleInput);
    if (sched.lines.length >= MIN_SCHEDULE_ROWS) {
      log.info(
        { takeoffId, schedulePages: sched.schedulePages, lines: sched.lines.length },
        "read cabinet schedule from text layer — skipping vision estimation"
      );
      const lines = [...sched.lines];
      const faces = lines.flatMap((l) => expandToComponents(l));
      lines.push(...faces);
      const scheduleSet = new Set(sched.schedulePages);
      const classified: PageClassification[] = Array.from(
        { length: pageCount },
        (_, i) => ({
          page: i + 1,
          class: scheduleSet.has(i + 1) ? "cabinet_schedule_table" : "other",
          confidence: scheduleSet.has(i + 1) ? 0.95 : 0.5,
        })
      );
      return {
        lines,
        raws: [{ schedule_pages: sched.schedulePages, source: "text_layer_schedule" }],
        classified,
        pageCount,
        summary: {
          uncertainties: [
            `Cabinets read directly from the document's text-layer schedule table (pages ${sched.schedulePages.join(", ")}) — not estimated. Verify against the drawings.`,
          ],
          unreadable_pages: [],
          warnings: [],
        },
      };
    }

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

    // Count each room ONCE (SCR-003). Per-page extraction SUMS cabinets across
    // every relevant page, so an elevation/millwork sheet re-enumerates cabinets
    // a plan or schedule already counted and the total balloons 2-4x. Instead of
    // summing, route to the single authoritative page role (schedule > floor
    // plan > elevation) and count from that role only; demoted roles refine
    // sizes later but never ADD to the count. (Replaces the old per-mode
    // collapse/dedupe — the router subsumes both.)
    const roleByPage = new Map<number, PageRole>(
      relevant.map((r) => [r.page, pageClassToRole(r.class)])
    );
    const routed = routeByPageRole(lines, roleByPage);
    // Stop pricing fillers/crown/returns through the box formula (a 3" filler or
    // a length of crown isn't a cabinet carcass — it over-prices the quote).
    const counted = dropNonBoxCasework(routed.lines);
    const nonBoxDropped = routed.lines.length - counted.length;
    lines.length = 0;
    lines.push(...counted);
    log.info(
      {
        takeoffId,
        regime: routed.regime,
        kept: counted.length,
        droppedFromOtherRoles: routed.droppedFromOtherRoles,
        collapsedWithinRole: routed.collapsedWithinRole,
        nonBoxCaseworkDropped: nonBoxDropped,
      },
      "page-role routed cabinet count"
    );

    // Each cabinet box also has doors + drawer fronts (priced separately by
    // ft²). Spawn those face line items in BOTH modes so the schedule mirrors a
    // real CabinetNow quote (cabinet boxes + a door/drawer list).
    const faces = lines.flatMap((l) => expandToComponents(l));
    lines.push(...faces);
    log.info(
      { takeoffId, faces: faces.length },
      "expanded cabinets into door/front faces"
    );

    return { lines, raws, classified, pageCount, summary };
  } finally {
    pdf.close();
  }
}

type PageAcc = {
  lines: CabinetLineItem[];
  raws: unknown[];
  summary: { uncertainties: string[]; unreadable_pages: number[]; warnings: string[] };
};

// Vision reads of the SAME estimate page vary run-to-run even at temperature 0
// (SCR-006: one plan returned 5 / 21 / 24 boxes on identical runs). For the
// no-schedule estimate path, read each page N times and keep the MEDIAN-box-
// count read, so a single noisy run can't swing a quote. Schedule-table reads
// are deterministic enough and stay at one read. Tunable via
// ESTIMATE_CONSENSUS_N (default 3; set 1 to disable); costs Nx the vision
// tokens on the estimate path only.
function estimateConsensusN(): number {
  const raw = process.env.ESTIMATE_CONSENSUS_N;
  const n = raw == null ? 3 : Number(raw);
  return Number.isFinite(n) && n >= 1 ? Math.floor(n) : 3;
}

// Read one relevant page, taking a median-of-N consensus in estimation mode to
// damp run-to-run vision variance (SCR-006). A single read otherwise.
async function readRelevantPage(
  takeoffId: string,
  pdf: OpenPdf,
  page: number,
  budget: TakeoffBudget,
  crossVal: CrossVal,
  log: Logger,
  estimate: boolean,
  pageClass: PageClass,
  acc: PageAcc
): Promise<void> {
  const n = estimate ? estimateConsensusN() : 1;
  if (n <= 1) {
    await readPageOnce(takeoffId, pdf, page, budget, crossVal, log, estimate, pageClass, acc);
    return;
  }

  // Read the page n times into throwaway accumulators, then keep the read whose
  // box count is the median (an outlier under- or over-read is discarded).
  const candidates: PageAcc[] = [];
  for (let i = 0; i < n; i++) {
    const local: PageAcc = {
      lines: [],
      raws: [],
      summary: { uncertainties: [], unreadable_pages: [], warnings: [] },
    };
    await readPageOnce(takeoffId, pdf, page, budget, crossVal, log, estimate, pageClass, local);
    candidates.push(local);
  }
  // Select by quote-total proxy (cabinet face area), NOT box count: two reads
  // with the same count can price very differently by size (Q8: 20 boxes, −6% vs
  // −28%). The median-AREA read is the most representative for the total.
  const chosen = pickMedian(candidates, (c) => boxFaceArea(c.lines));
  log.info(
    {
      takeoffId,
      page,
      reads: n,
      counts: candidates.map((c) => c.lines.length),
      areas: candidates.map((c) => Math.round(boxFaceArea(c.lines))),
      keptBoxes: chosen.lines.length,
      keptArea: Math.round(boxFaceArea(chosen.lines)),
    },
    "estimate consensus: kept median-face-area read"
  );
  acc.lines.push(...chosen.lines);
  acc.raws.push(...chosen.raws);
  acc.summary.uncertainties.push(...chosen.summary.uncertainties);
  for (const p of chosen.summary.unreadable_pages)
    if (!acc.summary.unreadable_pages.includes(p)) acc.summary.unreadable_pages.push(p);
  acc.summary.warnings.push(...chosen.summary.warnings);
}

// Read one relevant page ONCE. Large-format sheets are downscaled past
// legibility if sent whole (PRD §4), so they're segmented into their distinct
// drawings (one vision "locate" call) and each drawing is cropped + re-rendered
// at full resolution; drawings too big for one image are tiled and
// de-duplicated. Pages that already fit legibly are sent as a single image.
async function readPageOnce(
  takeoffId: string,
  pdf: OpenPdf,
  page: number,
  budget: TakeoffBudget,
  crossVal: CrossVal,
  log: Logger,
  estimate: boolean,
  pageClass: PageClass,
  acc: PageAcc
): Promise<void> {
  const idx = page - 1;
  const dims = pdf.pageDimsPt(idx);
  const widthIn = dims.widthPt / 72;
  const heightIn = dims.heightPt / 72;

  // GATED (DIM_SKELETON=1): dimension-skeleton grounding — hand the estimate
  // prompt the sheet's own printed dimension chains (text layer, exact
  // positions) so vision assigns dimensioned segments instead of freestyle
  // counting. No-op when unset or when the page has no usable printed dims.
  const grounding =
    estimate && process.env.DIM_SKELETON
      ? buildDimGrounding(pdf.pageTextFragments(idx))
      : undefined;

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
      const result = await extractPage(page, fullPng, budget, { estimate, grounding });
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
    // Non-floor-plan sheets (kitchen elevation / millwork) often show the SAME
    // room as a plan PLUS several wall elevations. Segmenting into regions makes
    // the model re-enumerate the room once per view -> 2-4x over-count. Read the
    // whole sheet ONCE so each cabinet is counted a single time. Floor plans
    // still segment by room — each room needs its own coherent, legible crop.
    if (pageClass !== "floor_plan") {
      let extraction: PageExtraction;
      try {
        const result = await extractPage(page, fullPng, budget, {
          estimate: true,
          grounding,
        });
        extraction = result.extraction;
        acc.raws.push({ page, raw: result.raw });
      } catch (err) {
        if (err instanceof BudgetExceededError) throw err;
        acc.summary.warnings.push(
          `page ${page}: estimate failed (${String(err)})`
        );
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

    for (const region of regions) {
      const wIn = (region.rect.x1 - region.rect.x0) / 72;
      const hIn = (region.rect.y1 - region.rect.y0) / 72;
      const crop = pdf.renderRegion(idx, region.rect, fitDpi(wIn, hIn));
      let extraction: PageExtraction;
      try {
        const result = await extractPage(page, crop, budget, {
          region: true,
          estimate: true,
          grounding,
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
        grounding: estimate ? grounding : undefined,
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

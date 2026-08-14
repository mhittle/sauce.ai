import type { Logger } from "pino";
import { and, desc, eq, sql } from "drizzle-orm";
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
  ESTIMATED_NOTE_PREFIX,
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
  RectPt,
  RegionKind,
  routeByPageRole,
  SelectedPage,
  selectRelevantPages,
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
import { OpenPdf, openPdf, PICKER_THUMBNAIL_DPI } from "./pdf.js";
import { locateRegions, locateRooms } from "./regions.js";
import { parseSpreadsheet } from "./spreadsheet.js";

// ---------------------------------------------------------------------------
// 2-step human review (2026-08-11): ONE blocking gate (page selection), then
// an interactive priced review —
//   prepare  (pdf)   thumbnails + classification        → awaiting_pages
//   extract  (all)   vision read of the SELECTED pages,
//                    then price + face expansion         → review
// The review screen edits cabinets in place (the API re-prices/re-expands per
// edit); approve locks it. Spreadsheets keep the single-stage path; text-layer
// schedule PDFs skip the page gate too (no vision). `finalize` jobs remain
// only for takeoffs parked at the removed awaiting_boxes gate.
// ---------------------------------------------------------------------------

// Region kinds worth cropping + extracting (PRD §4 legible-reads path).
const EXTRACTABLE_REGION_KINDS: RegionKind[] = ["schedule", "elevation", "plan"];
// Ignore detected boxes smaller than this — too small to be a real drawing.
const MIN_REGION_IN = { width: 1.5, height: 1 };

// The exact render a set of lines was read from: storage key of the PNG sent
// to the model, plus the page rectangle (PDF points) + DPI it was rendered at
// so a box can later be mapped into page space.
export interface ReadRect extends RectPt {
  dpi: number;
}
interface ReadMeta {
  key: string;
  rect: ReadRect | null;
}
export type ReadLine = CabinetLineItem & {
  read_image_key?: string | null;
  read_rect?: ReadRect | null;
};

// Optional secondary-model validation state, accumulated across pages.
interface CrossVal {
  enabled: boolean;
  tokens: number;
  secondaryRaws: unknown[];
}

type TakeoffRow = typeof takeoffs.$inferSelect;

async function loadTakeoff(takeoffId: string): Promise<TakeoffRow> {
  const db = getDb();
  const rows = await db.select().from(takeoffs).where(eq(takeoffs.id, takeoffId));
  if (rows.length === 0) throw new Error(`takeoff ${takeoffId} not found`);
  return rows[0];
}

async function loadCrossVal(): Promise<CrossVal> {
  const db = getDb();
  const settingsRows = await db
    .select()
    .from(orgSettings)
    .where(eq(orgSettings.id, 1));
  return {
    enabled: Boolean(settingsRows[0]?.crossValidationEnabled) && openaiConfigured(),
    tokens: 0,
    secondaryRaws: [],
  };
}

async function loadPricingSnapshot(): Promise<PricingSnapshot> {
  const db = getDb();
  const cfgRows = await db
    .select()
    .from(pricingConfigs)
    .orderBy(desc(pricingConfigs.version))
    .limit(1);
  if (cfgRows.length === 0) throw new Error("no pricing config — seed the DB");
  return PricingSnapshot.parse(cfgRows[0].snapshot);
}

// Token spend accumulates ACROSS stages (each stage runs its own budget cap).
async function failTakeoff(
  takeoffId: string,
  priorTokens: number,
  budget: TakeoffBudget | null,
  err: unknown
): Promise<void> {
  const db = getDb();
  const message =
    err instanceof BudgetExceededError
      ? `cost guardrail: ${err.message}`
      : String(err instanceof Error ? err.message : err);
  await db
    .update(takeoffs)
    .set({
      status: "failed",
      error: message,
      tokensUsed: priorTokens + (budget?.used ?? 0),
      updatedAt: new Date(),
    })
    .where(eq(takeoffs.id, takeoffId));
}

function avgConfidence(lines: { confidence: number }[]): number | null {
  return lines.length > 0
    ? lines.reduce((s, l) => s + l.confidence, 0) / lines.length
    : null;
}

// Insert extraction-stage lines at BOX level — no pricing match, no face
// expansion (both happen at finalize, after the human approves the boxes).
// Deletes existing lines first so a worker retry can't double-insert.
export async function replaceLines(
  takeoffId: string,
  lines: ReadLine[],
  hasRaws: boolean
): Promise<void> {
  const db = getDb();
  await db.delete(takeoffLines).where(eq(takeoffLines.takeoffId, takeoffId));
  for (const [i, line] of lines.entries()) {
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
      rawModelOutput: hasRaws ? { page_raw_index: i } : null,
      bbox: line.bbox_2d ?? null,
      readImageKey: line.read_image_key ?? null,
      readRect: line.read_rect ?? null,
    });
  }
}

// Pre-correction snapshot → self-building eval corpus (PRD §10). Delete-then-
// insert so a stage re-run can't stack duplicate fixtures.
async function replaceEvalFixture(
  takeoffId: string,
  lines: CabinetLineItem[]
): Promise<void> {
  const db = getDb();
  await db.delete(evalFixtures).where(eq(evalFixtures.takeoffId, takeoffId));
  await db.insert(evalFixtures).values({
    takeoffId,
    extractedLines: lines,
    promptVersion: EXTRACT_PROMPT_VERSION,
  });
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

// ---------------------------------------------------------------------------
// Legacy entry ("process" jobs). Spreadsheets run their whole single-stage
// flow here; PDFs/images enqueued under the old job name (in-flight across a
// deploy) are routed into the gated flow.
// ---------------------------------------------------------------------------

export async function processTakeoff(
  takeoffId: string,
  log: Logger
): Promise<void> {
  const takeoff = await loadTakeoff(takeoffId);
  if (takeoff.sourceKind === "pdf") return prepareTakeoff(takeoffId, log);
  if (takeoff.sourceKind === "image") return extractTakeoff(takeoffId, log);

  // Spreadsheets skip both gates: the parsed schedule goes straight to the
  // pricing review screen (processing → review), exactly as before.
  const db = getDb();
  const budget = new TakeoffBudget();
  try {
    const file = await getObject(takeoff.sourceFileS3Key);
    const parsed = await parseSpreadsheet(file, budget, {
      modelAssist: Boolean(process.env.ANTHROPIC_API_KEY),
    });
    const lines = parsed.lines;
    const snapshot = await loadPricingSnapshot();

    await db.delete(takeoffLines).where(eq(takeoffLines.takeoffId, takeoffId));
    for (const line of lines) {
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
        matchConfidence:
          "match_confidence" in match ? match.match_confidence : null,
        alternates: "alternates" in match ? match.alternates : null,
        unmatchedReason: "reason" in match ? match.reason : null,
        rawModelOutput: null,
      });
    }

    await replaceEvalFixture(takeoffId, lines);

    await db
      .update(takeoffs)
      .set({
        status: "review",
        docConfidence: avgConfidence(lines),
        docSummary: {
          uncertainties: [],
          unreadable_pages: [],
          warnings: parsed.warnings,
          raw_outputs: [],
          cross_validation: null,
        },
        promptVersion: EXTRACT_PROMPT_VERSION,
        tokensUsed: (takeoff.tokensUsed ?? 0) + budget.used,
        updatedAt: new Date(),
      })
      .where(eq(takeoffs.id, takeoffId));

    log.info(
      { takeoffId, lines: lines.length, tokens: budget.used },
      "spreadsheet takeoff processed"
    );
  } catch (err) {
    await failTakeoff(takeoffId, takeoff.tokensUsed ?? 0, budget, err);
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Stage 1 — prepare (PDF only): thumbnails of EVERY page + classification,
// then stop at the page-picker gate. Text-layer schedule PDFs (Class 1) skip
// the picker (nothing visual to pick) and go straight to the priced review.
// ---------------------------------------------------------------------------

export async function prepareTakeoff(
  takeoffId: string,
  log: Logger
): Promise<void> {
  const takeoff = await loadTakeoff(takeoffId);
  const db = getDb();
  const budget = new TakeoffBudget();
  try {
    if (takeoff.sourceKind !== "pdf") {
      throw new Error(`prepare stage only handles PDFs (got ${takeoff.sourceKind})`);
    }
    const file = await getObject(takeoff.sourceFileS3Key);
    const pdf = openPdf(file);
    try {
      const pageCount = pdf.pageCount;

      // Class 1 — the input already LISTS the cabinets in a text-layer schedule
      // table. Read it verbatim: exact, free, no vision — no pages to pick.
      // Stops at the box gate as a list-only review (no bboxes).
      const scheduleInput = [];
      for (let i = 0; i < pageCount; i++) {
        scheduleInput.push({ page: i + 1, fragments: pdf.pageTextFragments(i) });
      }
      const sched = extractCabinetSchedule(scheduleInput);
      if (sched.lines.length >= MIN_SCHEDULE_ROWS) {
        log.info(
          { takeoffId, schedulePages: sched.schedulePages, lines: sched.lines.length },
          "read cabinet schedule from text layer — skipping page selection"
        );
        const scheduleSet = new Set(sched.schedulePages);
        const classified: PageClassification[] = Array.from(
          { length: pageCount },
          (_, i) => ({
            page: i + 1,
            class: scheduleSet.has(i + 1) ? "cabinet_schedule_table" : "other",
            confidence: scheduleSet.has(i + 1) ? 0.95 : 0.5,
          })
        );
        const lines: ReadLine[] = sched.lines.map((l) => ({
          ...l,
          read_image_key: null,
          read_rect: null,
        }));
        await replaceLines(takeoffId, lines, true);
        await replaceEvalFixture(takeoffId, sched.lines);
        await db
          .update(takeoffs)
          .set({
            pageCount,
            classifiedPages: classified,
            docConfidence: avgConfidence(sched.lines),
            docSummary: {
              uncertainties: [
                `Cabinets read directly from the document's text-layer schedule table (pages ${sched.schedulePages.join(", ")}) — not estimated. Verify against the drawings.`,
              ],
              unreadable_pages: [],
              warnings: [],
              raw_outputs: [
                { schedule_pages: sched.schedulePages, source: "text_layer_schedule" },
              ],
              cross_validation: null,
            },
            promptVersion: EXTRACT_PROMPT_VERSION,
            tokensUsed: (takeoff.tokensUsed ?? 0) + budget.used,
            updatedAt: new Date(),
          })
          .where(eq(takeoffs.id, takeoffId));
        await priceAndExpand(takeoffId, log);
        return;
      }

      // Picker thumbnails: EVERY page (the autonomous flow only wrote read
      // pages), stored for the picker UI and reused as classification input.
      log.info({ takeoffId, pageCount }, "rendering picker thumbnails");
      const thumbnails: { page: number; png: Uint8Array }[] = [];
      for (let i = 0; i < pageCount; i++) {
        const png = pdf.renderPage(i, PICKER_THUMBNAIL_DPI);
        await putObject(
          `takeoffs/${takeoffId}/thumbs/${i + 1}.png`,
          png,
          "image/png"
        );
        thumbnails.push({ page: i + 1, png });
      }

      const classified = await classifyPages(thumbnails, budget);

      await db
        .update(takeoffs)
        .set({
          status: "awaiting_pages",
          pageCount,
          classifiedPages: classified,
          tokensUsed: (takeoff.tokensUsed ?? 0) + budget.used,
          updatedAt: new Date(),
        })
        .where(eq(takeoffs.id, takeoffId));

      log.info({ takeoffId, pageCount }, "awaiting page selection");
    } finally {
      pdf.close();
    }
  } catch (err) {
    await failTakeoff(takeoffId, takeoff.tokensUsed ?? 0, budget, err);
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Stage 2 — extract: vision-read the user-selected pages (or the single
// image), insert BOX-level lines carrying bbox + read-image provenance, then
// price + expand immediately (priceAndExpand) → review.
// ---------------------------------------------------------------------------

export async function extractTakeoff(
  takeoffId: string,
  log: Logger
): Promise<void> {
  const takeoff = await loadTakeoff(takeoffId);
  const db = getDb();
  const budget = new TakeoffBudget();
  const crossVal = await loadCrossVal();
  try {
    const file = await getObject(takeoff.sourceFileS3Key);

    let lines: ReadLine[];
    let raws: unknown[] = [];
    let summary: {
      uncertainties: string[];
      unreadable_pages: number[];
      warnings: string[];
    } = { uncertainties: [], unreadable_pages: [], warnings: [] };

    if (takeoff.sourceKind === "image") {
      // Single-page vision extraction; store the image for provenance and as
      // the read image the box overlay draws on.
      await putObject(`takeoffs/${takeoffId}/pages/1.png`, file, "image/png");
      const readKey = `takeoffs/${takeoffId}/reads/p1-c0-full.png`;
      await putObject(readKey, file, "image/png");
      const { extraction, raw } = await extractPage(1, file, budget);
      raws = [raw];
      const validated = crossVal.enabled
        ? await runCrossValidation(1, file, extraction, crossVal, summary.warnings, log)
        : extraction;
      lines = validated.lines.map((l) => ({
        ...l,
        read_image_key: readKey,
        read_rect: null,
      }));
      summary.uncertainties = validated.uncertainties;
      if (validated.unreadable) summary.unreadable_pages = [1];
    } else if (takeoff.sourceKind === "pdf") {
      const classified = Array.isArray(takeoff.classifiedPages)
        ? (takeoff.classifiedPages as PageClassification[])
        : [];
      const selected = Array.isArray(takeoff.selectedPages)
        ? (takeoff.selectedPages as SelectedPage[])
        : null;
      const result = await extractPdf(
        takeoffId,
        file,
        classified,
        selected,
        budget,
        crossVal,
        log
      );
      lines = result.lines;
      raws = result.raws;
      summary = result.summary;
    } else {
      throw new Error(
        `extract stage does not handle sourceKind ${takeoff.sourceKind}`
      );
    }

    await replaceLines(takeoffId, lines, raws.length > 0);
    await replaceEvalFixture(takeoffId, lines);

    await db
      .update(takeoffs)
      .set({
        docConfidence: avgConfidence(lines),
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
        tokensUsed: (takeoff.tokensUsed ?? 0) + budget.used,
        updatedAt: new Date(),
      })
      .where(eq(takeoffs.id, takeoffId));

    // 2-step flow (owner decision 2026-08-11): no box gate — price + expand
    // immediately, landing on the interactive review screen.
    await priceAndExpand(takeoffId, log);

    log.info(
      { takeoffId, lines: lines.length, tokens: budget.used },
      "extraction complete — in review"
    );
  } catch (err) {
    await failTakeoff(takeoffId, takeoff.tokensUsed ?? 0, budget, err);
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Pricing pass: re-match every line, expand cabinets into their door/drawer-
// front faces, land on the review screen. Runs at the end of extraction (the
// 2-step flow) and for legacy `finalize` jobs (takeoffs parked at the removed
// awaiting_boxes gate). The API re-runs the same expansion per line when the
// reviewer edits a cabinet at review.
// ---------------------------------------------------------------------------

export async function priceAndExpand(
  takeoffId: string,
  log: Logger
): Promise<void> {
  const db = getDb();
  // Re-run safety: drop previously derived faces before re-deriving them.
  await db
    .delete(takeoffLines)
    .where(
      and(
        eq(takeoffLines.takeoffId, takeoffId),
        sql`${takeoffLines.rawModelOutput}->>'expanded' = 'true'`
      )
    );

  const rows = await db
    .select()
    .from(takeoffLines)
    .where(eq(takeoffLines.takeoffId, takeoffId))
    .orderBy(takeoffLines.sourcePage, takeoffLines.createdAt);
  const snapshot = await loadPricingSnapshot();

  const confidences: { confidence: number }[] = [];
  let faceCount = 0;
  for (const row of rows) {
    const line = rowToLine(row);
    confidences.push(line);
    const match = matchLine(line, snapshot);
    await db
      .update(takeoffLines)
      .set({
        productLineId: match.product_line_id,
        resolvedParams: "resolved" in match ? match.resolved : null,
        matchConfidence:
          "match_confidence" in match ? match.match_confidence : null,
        alternates: "alternates" in match ? match.alternates : null,
        unmatchedReason: "reason" in match ? match.reason : null,
        updatedAt: new Date(),
      })
      .where(eq(takeoffLines.id, row.id));

    // Each cabinet box also has doors + drawer fronts (priced separately by
    // ft²). Spawn those face line items so the schedule mirrors a real
    // CabinetNow quote (cabinet boxes + a door/drawer list). `parent` links a
    // face to its cabinet so an edit/delete of the cabinet refreshes them.
    for (const face of expandToComponents(line)) {
      const faceMatch = matchLine(face, snapshot);
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
        productLineId: faceMatch.product_line_id,
        resolvedParams: "resolved" in faceMatch ? faceMatch.resolved : null,
        matchConfidence:
          "match_confidence" in faceMatch ? faceMatch.match_confidence : null,
        alternates: "alternates" in faceMatch ? faceMatch.alternates : null,
        unmatchedReason: "reason" in faceMatch ? faceMatch.reason : null,
        rawModelOutput: { expanded: true, parent: row.id },
      });
      faceCount++;
      confidences.push(face);
    }
  }

  await db
    .update(takeoffs)
    .set({
      status: "review",
      docConfidence: avgConfidence(confidences),
      updatedAt: new Date(),
    })
    .where(eq(takeoffs.id, takeoffId));

  log.info(
    { takeoffId, boxes: rows.length, faces: faceCount },
    "takeoff priced — in review"
  );
}

// Legacy job: takeoffs parked at the removed awaiting_boxes gate (or queued
// finalize jobs from before the 2-step flow) still price out through here.
export async function finalizeTakeoff(
  takeoffId: string,
  log: Logger
): Promise<void> {
  const takeoff = await loadTakeoff(takeoffId);
  try {
    await priceAndExpand(takeoffId, log);
  } catch (err) {
    await failTakeoff(takeoffId, takeoff.tokensUsed ?? 0, null, err);
    throw err;
  }
}

// Reviewer-edited DB row → the pure line shape pricing + expansion work on.
function rowToLine(row: typeof takeoffLines.$inferSelect): CabinetLineItem {
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

// ---------------------------------------------------------------------------
// PDF vision extraction over the user-selected pages.
// ---------------------------------------------------------------------------

async function extractPdf(
  takeoffId: string,
  file: Buffer,
  classified: PageClassification[],
  selected: SelectedPage[] | null,
  budget: TakeoffBudget,
  crossVal: CrossVal,
  log: Logger
): Promise<{
  lines: ReadLine[];
  raws: unknown[];
  summary: {
    uncertainties: string[];
    unreadable_pages: number[];
    warnings: string[];
  };
}> {
  const pdf = openPdf(file);
  try {
    // Honor the human page selection (+ per-page tag overrides). A null
    // selection reproduces the autonomous flow (legacy jobs only).
    const { estimationMode, relevant } = selectRelevantPages(classified, selected);

    log.info(
      { takeoffId, estimationMode, relevant: relevant.map((r) => r.page) },
      "reading selected pages"
    );

    const lines: ReadLine[] = [];
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
    if (relevant.length === 0) {
      summary.warnings.push(
        "None of the selected pages has a readable type (schedule / elevation / floor plan) — nothing was extracted. Re-tag pages if this is wrong."
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
    // sizes later but never ADD to the count. Surviving lines keep their bbox +
    // read-image provenance (the router drops lines, not boxes).
    const roleByPage = new Map<number, PageRole>(
      relevant.map((r) => [r.page, pageClassToRole(r.class)])
    );
    const routed = routeByPageRole(lines, roleByPage);
    // Stop pricing fillers/crown/returns through the box formula (a 3" filler or
    // a length of crown isn't a cabinet carcass — it over-prices the quote).
    const counted = dropNonBoxCasework(routed.lines);
    const nonBoxDropped = routed.lines.length - counted.length;
    const result = counted;
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

    // NOTE: expandToComponents moved to the finalize stage — the box gate
    // reviews CABINETS, and faces must derive from the human-corrected boxes.

    return { lines: result, raws, summary };
  } finally {
    pdf.close();
  }
}

type PageAcc = {
  lines: ReadLine[];
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
    await readPageOnce(takeoffId, pdf, page, budget, crossVal, log, estimate, pageClass, 0, acc);
    return;
  }

  // Read the page n times into throwaway accumulators, then keep the read whose
  // box count is the median (an outlier under- or over-read is discarded).
  // Each candidate persists its own read images (region locate can differ per
  // read), so the chosen read's boxes always match the image they were read on.
  const candidates: PageAcc[] = [];
  for (let i = 0; i < n; i++) {
    const local: PageAcc = {
      lines: [],
      raws: [],
      summary: { uncertainties: [], unreadable_pages: [], warnings: [] },
    };
    await readPageOnce(takeoffId, pdf, page, budget, crossVal, log, estimate, pageClass, i, local);
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
// Every image actually sent to the model is persisted under
// takeoffs/{id}/reads/ (keyed by page + consensus-candidate + region/tile) so
// the box-review overlay can draw each line's bbox on the EXACT pixels the
// model saw; `cand` disambiguates consensus candidates.
async function readPageOnce(
  takeoffId: string,
  pdf: OpenPdf,
  page: number,
  budget: TakeoffBudget,
  crossVal: CrossVal,
  log: Logger,
  estimate: boolean,
  pageClass: PageClass,
  cand: number,
  acc: PageAcc
): Promise<void> {
  const idx = page - 1;
  const dims = pdf.pageDimsPt(idx);
  const widthIn = dims.widthPt / 72;
  const heightIn = dims.heightPt / 72;
  const readKey = (suffix: string): string =>
    `takeoffs/${takeoffId}/reads/p${page}-c${cand}-${suffix}.png`;

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
  const fullRect: ReadRect = {
    x0: 0,
    y0: 0,
    x1: dims.widthPt,
    y1: dims.heightPt,
    dpi: locateDpi,
  };

  const collect = (
    extraction: PageExtraction,
    into: ReadLine[],
    read: ReadMeta | null
  ): void => {
    into.push(
      ...extraction.lines.map((l) => ({
        ...l,
        read_image_key: read?.key ?? null,
        read_rect: read?.rect ?? null,
      }))
    );
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
    const key = readKey("full");
    await putObject(key, fullPng, "image/png");
    collect(extraction, acc.lines, { key, rect: fullRect });
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
      const key = readKey("full");
      await putObject(key, fullPng, "image/png");
      collect(extraction, acc.lines, { key, rect: fullRect });
      return;
    }

    for (const [ri, region] of regions.entries()) {
      const wIn = (region.rect.x1 - region.rect.x0) / 72;
      const hIn = (region.rect.y1 - region.rect.y0) / 72;
      const cropDpi = fitDpi(wIn, hIn);
      const crop = pdf.renderRegion(idx, region.rect, cropDpi);
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
      const key = readKey(`r${ri}`);
      await putObject(key, crop, "image/png");
      collect(extraction, acc.lines, {
        key,
        rect: { ...region.rect, dpi: cropDpi },
      });
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
  const linesByRegion = new Map<number, ReadLine[]>();
  for (const [ti, job] of jobs.entries()) {
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
    const key = readKey(`r${job.regionId}-t${ti}`);
    await putObject(key, crop, "image/png");
    const bucket = linesByRegion.get(job.regionId) ?? [];
    collect(extraction, bucket, {
      key,
      rect: { ...job.rect, dpi: job.dpi },
    });
    linesByRegion.set(job.regionId, bucket);
  }
  for (const regionLines of linesByRegion.values()) {
    acc.lines.push(...dedupeLines(regionLines));
  }
}

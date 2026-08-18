import type { Logger } from "pino";
import { and, eq } from "drizzle-orm";
import { getDb, takeoffDetections } from "@scribe/db";
import {
  betaDisplayDpi,
  fitDpi,
  mapBoxToPagePoints,
  needsRegioning,
  padRectToPage,
  PageClassification,
  RectPt,
  SelectedPage,
  selectRelevantPages,
} from "@scribe/shared";
import { TakeoffBudget } from "../lib/anthropic.js";
import { buildFromDetections, detectRegion } from "./detect.js";
import { openPdf } from "./pdf.js";
import { locateRegions, locateRooms } from "./regions.js";

// ---------------------------------------------------------------------------
// STAGED extraction (STAGED_READS=1): the automated pipeline restructured to
// mirror the human-in-the-loop wizard —
//   1 segment  locateRegions/locateRooms finds the distinct drawings/rooms
//   2 boxes    each region becomes a takeoff_detections row (wizard step 2)
//   3 read     detectRegion counts/labels cabinets per region, no dims
//   4 measure  buildFromDetections sizes every marker in one whole-set pass,
//              then replaceLines + priceAndExpand land on review
// Because the stages share the wizard's tables/jobs, an automated run is
// inspectable (and correctable) in the wizard view afterwards.
// ---------------------------------------------------------------------------

const PT_PER_IN = 72;
// Same floor the classic reader uses: ignore located boxes too small to be a
// real drawing.
const MIN_REGION_IN = { width: 1.5, height: 1 };
// Region kinds worth detecting cabinets in. Schedule tables have no drawn
// cabinets to box; v1 skips them (the classic path still reads them).
const DETECTABLE_KINDS = new Set(["elevation", "plan"]);

export async function stagedExtractPdf(
  takeoffId: string,
  file: Buffer,
  classified: PageClassification[],
  selected: SelectedPage[] | null,
  budget: TakeoffBudget,
  log: Logger
): Promise<void> {
  const db = getDb();
  const warnings: string[] = [];
  const pdf = openPdf(file);
  try {
    const { estimationMode, relevant } = selectRelevantPages(
      classified,
      selected
    );
    if (relevant.length === 0) {
      throw new Error(
        "none of the selected pages has a readable type (schedule / elevation / floor plan)"
      );
    }
    if (estimationMode) {
      warnings.push(
        "No cabinet schedule detected — quantities below are ESTIMATED from the floor plan/elevations and must be verified before quoting."
      );
    }
    log.info(
      { takeoffId, estimationMode, relevant: relevant.map((r) => r.page) },
      "staged extraction start"
    );

    // Rebuild from scratch: an automated run owns the detection set.
    await db
      .delete(takeoffDetections)
      .where(eq(takeoffDetections.takeoffId, takeoffId));

    // Stage 1: locate regions on every page first. Kinds are needed across
    // pages before seeding: when the set has ELEVATION regions, plan-view
    // regions are dropped — a plan re-counts cabinets the elevations already
    // show, and the 2026-08-05 attribution showed elevations are the better
    // count source (plan-only docs still keep their plan regions).
    const located: { page: number; kind: string; rect: RectPt }[] = [];
    for (const pageInfo of relevant) {
      const page = pageInfo.page;
      if (
        pageInfo.class === "cabinet_schedule_table" ||
        pageInfo.class === "finish_schedule"
      ) {
        warnings.push(
          `page ${page} (${pageInfo.class}) is not used by staged reads yet — verify its counts by hand`
        );
        continue;
      }
      const dims = pdf.pageDimsPt(page - 1);
      const wholePage: RectPt = {
        x0: 0,
        y0: 0,
        x1: dims.widthPt,
        y1: dims.heightPt,
      };
      const wholeKind =
        pageInfo.class === "floor_plan" ? "plan" : "elevation";

      let regions: { kind: string; rect: RectPt }[] = [
        { kind: wholeKind, rect: wholePage },
      ];
      if (needsRegioning(dims)) {
        const dpi = fitDpi(dims.widthPt / PT_PER_IN, dims.heightPt / PT_PER_IN);
        const w = Math.round((dims.widthPt / PT_PER_IN) * dpi);
        const h = Math.round((dims.heightPt / PT_PER_IN) * dpi);
        const png = pdf.renderPage(page - 1, dpi);
        try {
          const located =
            estimationMode && pageInfo.class === "floor_plan"
              ? await locateRooms(png, w, h, budget)
              : await locateRegions(png, w, h, budget);
          const mapped = located.regions
            .filter((r) => DETECTABLE_KINDS.has(r.kind))
            .map((r) => ({
              kind: r.kind,
              rect: padRectToPage(
                mapBoxToPagePoints(r.box, { widthPx: w, heightPx: h }, dims),
                0.04,
                dims
              ),
            }))
            .filter(
              (r) =>
                (r.rect.x1 - r.rect.x0) / PT_PER_IN >= MIN_REGION_IN.width &&
                (r.rect.y1 - r.rect.y0) / PT_PER_IN >= MIN_REGION_IN.height
            );
          if (mapped.length > 0) regions = mapped;
          else
            warnings.push(
              `page ${page}: no cabinet regions located — scanned the whole page`
            );
        } catch (err) {
          warnings.push(
            `page ${page}: region location failed (${err instanceof Error ? err.message : err}) — scanned the whole page`
          );
        }
      }
      for (const r of regions) located.push({ page, ...r });
    }

    // Stage 2: elevation-primary — drop plan regions when elevations exist,
    // then seed one detection row per surviving region.
    const hasElevation = located.some((r) => r.kind === "elevation");
    const seeded = located.filter((r) => !(hasElevation && r.kind === "plan"));
    const droppedPlans = located.length - seeded.length;
    if (droppedPlans > 0) {
      warnings.push(
        `${droppedPlans} plan region(s) skipped — elevations are the count source; the plan would re-count the same cabinets`
      );
    }
    for (const r of seeded) {
      const dims = pdf.pageDimsPt(r.page - 1);
      const ptToDisplay = betaDisplayDpi(dims) / PT_PER_IN;
      await db.insert(takeoffDetections).values({
        takeoffId,
        page: r.page,
        // Carried into the measure stage: plan regions are RUNS to decompose.
        kind: r.kind,
        rect: [
          r.rect.x0 * ptToDisplay,
          r.rect.y0 * ptToDisplay,
          r.rect.x1 * ptToDisplay,
          r.rect.y1 * ptToDisplay,
        ],
        status: "queued",
      });
    }
  } finally {
    pdf.close();
  }

  // Stage 3: detect cabinets per region (small bounded calls). Token spend is
  // folded into the budget after each call so the per-takeoff cap still binds.
  const queued = await db
    .select()
    .from(takeoffDetections)
    .where(
      and(
        eq(takeoffDetections.takeoffId, takeoffId),
        eq(takeoffDetections.status, "queued")
      )
    )
    .orderBy(takeoffDetections.page, takeoffDetections.createdAt);
  if (queued.length === 0) throw new Error("no regions to scan");
  for (const row of queued) {
    await detectRegion(row.id, log);
    const [after] = await db
      .select()
      .from(takeoffDetections)
      .where(eq(takeoffDetections.id, row.id));
    if (after?.status === "error") {
      warnings.push(
        `page ${after.page}: region scan failed (${after.error ?? "unknown"})`
      );
    }
    budget.record({
      input_tokens: after?.tokensUsed ?? 0,
      output_tokens: 0,
    });
  }

  // Stage 4: measurements + lines + pricing + review (throws on failure so
  // extractTakeoff's failTakeoff handling applies).
  const merged = await buildFromDetections(takeoffId, "processing", log, {
    onError: "throw",
    evalFixture: true,
    extraWarnings: warnings,
  });
  if (merged.length === 0) {
    throw new Error("staged extraction found no cabinets");
  }
  log.info(
    { takeoffId, lines: merged.length, tokens: budget.used },
    "staged extraction complete — in review"
  );
}

import type { Logger } from "pino";
import { eq, sql } from "drizzle-orm";
import { getDb, takeoffDetections, takeoffs } from "@scribe/db";
import {
  PageClassification,
  SelectedPage,
  selectRelevantPages,
} from "@scribe/shared";
import { TakeoffBudget } from "../lib/anthropic.js";
import { setProgress } from "./progress.js";
import { renderBetaPage } from "./detect.js";

// ---------------------------------------------------------------------------
// STAGED extraction — the ONE flow (2026-09-14, owner: "I don't want 2
// modes"): locate the drawings and hand the human the wizard —
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
  const { estimationMode, relevant } = selectRelevantPages(classified, selected);
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
  for (const pageInfo of relevant) {
    if (
      pageInfo.class === "cabinet_schedule_table" ||
      pageInfo.class === "finish_schedule"
    ) {
      warnings.push(
        `page ${pageInfo.page} (${pageInfo.class}) is not read by the wizard yet — verify its counts by hand`
      );
    }
  }
  // No pre-selection (owner, 2026-09-14): nothing is boxed for the human.
  // Render the wizard's page images so Mark opens with no wait, keep the
  // notes for the build, park at awaiting_boxes. Scale and plan/elevation
  // kind attach to each area when the human draws it.
  let done = 0;
  for (const pageInfo of relevant) {
    await setProgress(takeoffId, "prepare", {
      done,
      total: relevant.length,
      message: `Rendering page ${pageInfo.page} for marking`,
    });
    await renderBetaPage(takeoffId, pageInfo.page, log);
    done++;
  }
  await db
    .update(takeoffs)
    .set({
      status: "awaiting_boxes",
      docSummary: { warnings, seeded: true },
      tokensUsed: sql`${takeoffs.tokensUsed} + ${budget.used}`,
      updatedAt: new Date(),
    })
    .where(eq(takeoffs.id, takeoffId));
  await setProgress(takeoffId, "prepare", {
    done: relevant.length,
    total: relevant.length,
    message: "Pages ready — mark the cabinet areas",
  });
  log.info({ takeoffId, pages: relevant.map((r) => r.page) }, "pages ready — awaiting the wizard");
  void file;
}

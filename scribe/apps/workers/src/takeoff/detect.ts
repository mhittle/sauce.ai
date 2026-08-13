import type { Logger } from "pino";
import { eq } from "drizzle-orm";
import { getDb, takeoffDetections, takeoffs } from "@scribe/db";
import {
  betaDisplayDpi,
  clampRectToPage,
  DetectionItem,
  fitDpi,
  padRectToPage,
  RectPt,
} from "@scribe/shared";
import { DETECT_SYSTEM, detectUserText, SONNET_MODEL } from "@scribe/prompts";
import { getObject, objectExists, putObject } from "@scribe/storage";
import {
  extractJson,
  getAnthropic,
  imageBlock,
  textOf,
  withSocketRetry,
} from "../lib/anthropic.js";
import { openPdf, OpenPdf } from "./pdf.js";

// ---------------------------------------------------------------------------
// Beta drag-to-detect: on-demand cabinet detection over a user-dragged region
// of one page. Fully separate from the takeoff line pipeline — nothing here
// touches takeoff status or takeoff_lines. Coordinate round-trip:
//   drag rect (display-render px) → page points → high-DPI crop → model boxes
//   (crop px) → page points → display-render px, persisted on the detection.
// ---------------------------------------------------------------------------

const DETECT_MODEL = process.env.VISION_MODEL || SONNET_MODEL;
const PT_PER_IN = 72;
// Same edge padding the region reader uses, so a cabinet clipped mid-stroke by
// the drag still shows the model its outline (and its printed tag).
const DETECT_PAD_FRAC = 0.02;

export function betaPageKey(takeoffId: string, page: number): string {
  return `takeoffs/${takeoffId}/beta/pages/${page}.png`;
}

async function openTakeoffPdf(takeoffId: string): Promise<OpenPdf> {
  const db = getDb();
  const rows = await db
    .select()
    .from(takeoffs)
    .where(eq(takeoffs.id, takeoffId));
  if (rows.length === 0) throw new Error(`takeoff ${takeoffId} not found`);
  return openPdf(await getObject(rows[0].sourceFileS3Key));
}

// Render the beta display PNG for one page. Idempotent: the queue dedupes by
// jobId and the render itself is skipped when the object already exists.
export async function renderBetaPage(
  takeoffId: string,
  page: number,
  log: Logger
): Promise<void> {
  const key = betaPageKey(takeoffId, page);
  if (await objectExists(key)) return;
  const pdf = await openTakeoffPdf(takeoffId);
  try {
    const dpi = betaDisplayDpi(pdf.pageDimsPt(page - 1));
    await putObject(key, pdf.renderPage(page - 1, dpi), "image/png");
    log.info({ takeoff: takeoffId, page, dpi }, "beta page rendered");
  } finally {
    pdf.close();
  }
}

// Run one queued detection: crop the dragged region at a legible DPI, ask the
// model for cabinet boxes, map them back to display-render pixels.
export async function detectRegion(
  detectionId: string,
  log: Logger
): Promise<void> {
  const db = getDb();
  const rows = await db
    .select()
    .from(takeoffDetections)
    .where(eq(takeoffDetections.id, detectionId));
  if (rows.length === 0) throw new Error(`detection ${detectionId} not found`);
  const detection = rows[0];
  await db
    .update(takeoffDetections)
    .set({ status: "running" })
    .where(eq(takeoffDetections.id, detectionId));

  try {
    const pdf = await openTakeoffPdf(detection.takeoffId);
    try {
      const page = detection.page;
      const dims = pdf.pageDimsPt(page - 1);
      const displayDpi = betaDisplayDpi(dims);
      const toPt = PT_PER_IN / displayDpi;

      const dragPx = detection.rect as [number, number, number, number];
      const dragPt: RectPt = clampRectToPage(
        {
          x0: Math.min(dragPx[0], dragPx[2]) * toPt,
          y0: Math.min(dragPx[1], dragPx[3]) * toPt,
          x1: Math.max(dragPx[0], dragPx[2]) * toPt,
          y1: Math.max(dragPx[1], dragPx[3]) * toPt,
        },
        dims
      );
      const cropPt = padRectToPage(dragPt, DETECT_PAD_FRAC, dims);
      const cropWIn = (cropPt.x1 - cropPt.x0) / PT_PER_IN;
      const cropHIn = (cropPt.y1 - cropPt.y0) / PT_PER_IN;
      if (cropWIn <= 0 || cropHIn <= 0) throw new Error("empty region");
      const cropDpi = fitDpi(cropWIn, cropHIn);

      const png = pdf.renderRegion(page - 1, cropPt, cropDpi);
      const cropKey = `takeoffs/${detection.takeoffId}/beta/detections/${detectionId}.png`;
      await putObject(cropKey, png, "image/png");

      const client = getAnthropic();
      const message = await withSocketRetry(() =>
        client.messages
          .stream({
            model: DETECT_MODEL,
            max_tokens: 8000,
            ...(DETECT_MODEL.startsWith("claude-opus-4-8")
              ? {}
              : { temperature: 0 }),
            system: DETECT_SYSTEM,
            messages: [
              {
                role: "user",
                content: [
                  imageBlock(png),
                  { type: "text", text: detectUserText(page) },
                ],
              },
            ],
          })
          .finalMessage()
      );
      const tokens =
        message.usage.input_tokens + message.usage.output_tokens;

      let rawItems: unknown[] = [];
      try {
        const obj = (extractJson(textOf(message)) ?? {}) as {
          items?: unknown;
        };
        if (Array.isArray(obj.items)) rawItems = obj.items;
      } catch {
        // no parseable JSON — persist an empty result rather than failing
      }

      // Lenient per-item parse, then map each box crop px → page pt → display px.
      const cropToPt = PT_PER_IN / cropDpi;
      const ptToDisplay = displayDpi / PT_PER_IN;
      const items = rawItems.flatMap((raw) => {
        const parsed = DetectionItem.safeParse(raw);
        if (!parsed.success) return [];
        const item = parsed.data;
        if (item.bbox_2d) {
          const [bx0, by0, bx1, by1] = item.bbox_2d;
          const boxPt = clampRectToPage(
            {
              x0: cropPt.x0 + Math.min(bx0, bx1) * cropToPt,
              y0: cropPt.y0 + Math.min(by0, by1) * cropToPt,
              x1: cropPt.x0 + Math.max(bx0, bx1) * cropToPt,
              y1: cropPt.y0 + Math.max(by0, by1) * cropToPt,
            },
            dims
          );
          item.bbox_2d = [
            boxPt.x0 * ptToDisplay,
            boxPt.y0 * ptToDisplay,
            boxPt.x1 * ptToDisplay,
            boxPt.y1 * ptToDisplay,
          ];
        }
        return [item];
      });

      await db
        .update(takeoffDetections)
        .set({
          status: "done",
          items,
          displayDpi,
          cropImageKey: cropKey,
          model: DETECT_MODEL,
          tokensUsed: tokens,
          error: null,
        })
        .where(eq(takeoffDetections.id, detectionId));
      log.info(
        { detection: detectionId, page, items: items.length, tokens },
        "detection done"
      );
    } finally {
      pdf.close();
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    await db
      .update(takeoffDetections)
      .set({ status: "error", error: msg })
      .where(eq(takeoffDetections.id, detectionId));
    log.error({ detection: detectionId, err: msg }, "detection failed");
  }
}

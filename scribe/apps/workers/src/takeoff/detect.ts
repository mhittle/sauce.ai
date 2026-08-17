import type { Logger } from "pino";
import { and, eq, sql } from "drizzle-orm";
import sharp from "sharp";
import { z } from "zod";
import { evalFixtures, getDb, takeoffDetections, takeoffs } from "@scribe/db";
import {
  BETA_DEFAULT_DIMS,
  betaDisplayDpi,
  buildDimGrounding,
  dimsNearRect,
  CabinetLineItem,
  clampRectToPage,
  DetectionItem,
  fitDpi,
  LineCategory,
  markEstimated,
  padRectToPage,
  RectPt,
  TextFragment,
} from "@scribe/shared";
import {
  DETECT_SYSTEM,
  detectUserText,
  MEASURE_PROMPT_VERSION,
  MEASURE_SYSTEM,
  MeasureMarker,
  measureUserText,
  SONNET_MODEL,
} from "@scribe/prompts";
import { getObject, objectExists, putObject } from "@scribe/storage";
import {
  extractJson,
  getAnthropic,
  imageBlock,
  textOf,
  withSocketRetry,
} from "../lib/anthropic.js";
import { openPdf, OpenPdf } from "./pdf.js";
import { priceAndExpand, ReadLine, replaceLines } from "./process.js";

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

// Pure detection-response processing: lenient JSON parse, per-item schema
// parse, then map each box crop px → page pt → display px. Split out so the
// offline kit harness replays raw responses through the IDENTICAL logic.
export interface DetectionResponseCtx {
  cropPt: RectPt;
  cropDpi: number;
  displayDpi: number;
  dims: { widthPt: number; heightPt: number };
}

export function processDetectionResponse(
  text: string,
  ctx: DetectionResponseCtx
): DetectionItem[] {
  let rawItems: unknown[] = [];
  try {
    const obj = (extractJson(text) ?? {}) as { items?: unknown };
    if (Array.isArray(obj.items)) rawItems = obj.items;
  } catch {
    // no parseable JSON — an empty result, not a failure
  }
  const cropToPt = PT_PER_IN / ctx.cropDpi;
  const ptToDisplay = ctx.displayDpi / PT_PER_IN;
  return rawItems.flatMap((raw) => {
    const parsed = DetectionItem.safeParse(raw);
    if (!parsed.success) return [];
    const item = parsed.data;
    if (item.bbox_2d) {
      const [bx0, by0, bx1, by1] = item.bbox_2d;
      const boxPt = clampRectToPage(
        {
          x0: ctx.cropPt.x0 + Math.min(bx0, bx1) * cropToPt,
          y0: ctx.cropPt.y0 + Math.min(by0, by1) * cropToPt,
          x1: ctx.cropPt.x0 + Math.max(bx0, bx1) * cropToPt,
          y1: ctx.cropPt.y0 + Math.max(by0, by1) * cropToPt,
        },
        ctx.dims
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
      const items = processDetectionResponse(textOf(message), {
        cropPt,
        cropDpi,
        displayDpi,
        dims,
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

// ---------------------------------------------------------------------------
// Wizard step 4: build the takeoff from detections. One whole-input
// measurements pass (all pages together, cabinets numbered on the images,
// printed dims as grounding), then the standard replace → price → review tail.
// ---------------------------------------------------------------------------

// The measurements pass sends the WHOLE plan set in one call — an unmarked
// floor plan or schedule page often carries the dims/scale that size the
// marked cabinets. Each page image costs ≤~1.5k tokens (model-budget-fitted),
// so even a 23-page set is ~35k input tokens. The cap is a runaway guard for
// pathological documents: marker pages always make the cut, context pages
// fill the remainder in page order.
const MEASURE_MAX_PAGES = 30;

const ANNOTATE_COLORS: Record<string, string> = {
  casework_base: "rgb(0,170,0)",
  casework_wall: "rgb(200,0,200)",
  casework_tall: "rgb(0,90,220)",
  vanity: "rgb(230,140,0)",
};

// One numbered cabinet entering the measurements pass.
export interface MarkerEntry {
  marker: number;
  page: number;
  label: string;
  category: string;
  confidence: number;
  // bbox in the reads-image pixels of that page's render (null = not locatable)
  bboxReadPx: [number, number, number, number] | null;
}

const MeasuredCabinet = z.object({
  marker: z.number().int(),
  tag: z.string().nullable().catch(null).default(null),
  category: z.string().catch("other").default("other"),
  width_in: z.number().positive().nullable().catch(null).default(null),
  height_in: z.number().positive().nullable().catch(null).default(null),
  depth_in: z.number().positive().nullable().catch(null).default(null),
  confidence: z.number().min(0).max(1).catch(0.5).default(0.5),
  measured: z.boolean().catch(false).default(false),
});
type MeasuredCabinet = z.infer<typeof MeasuredCabinet>;

function toLineCategory(category: string): LineCategory {
  const parsed = LineCategory.safeParse(category);
  return parsed.success && parsed.data !== "unknown" ? parsed.data : "unknown";
}

const CATEGORY_TAG_LABEL: Record<string, string> = {
  casework_base: "Base cabinet",
  casework_wall: "Wall cabinet",
  casework_tall: "Tall cabinet",
  vanity: "Vanity",
};

// A bare number or measurement ("8", "19 1/4", "27 1/2\"") is a dimension
// string the detector picked up, not a name.
export function isBareNumberTag(tag: string): boolean {
  return /^[\d\s/.\-]*\d[\s/.\-]*(?:"|”|in\.?)?$/i.test(tag.trim());
}

// Backstop for the prompt rule: if the tag is still a bare number (or
// missing), synthesize a recognizable one from category + width + marker.
export function meaningfulTag(
  tag: string | null,
  category: string,
  widthIn: number | null,
  marker: number
): { tag: string; callout: string | null } {
  if (tag && tag.trim() && !isBareNumberTag(tag)) {
    return { tag: tag.trim(), callout: null };
  }
  const base = CATEGORY_TAG_LABEL[category] ?? "Cabinet";
  const width = widthIn != null ? ` ${widthIn}"w` : "";
  return { tag: `${base}${width} (#${marker})`, callout: tag?.trim() || null };
}

// Pure merge of the measurements answer onto the numbered markers: model dims
// where given, category-average defaults where not (marked estimated). Split
// out for unit testing.
export function mergeMeasuredLines(
  entries: MarkerEntry[],
  rawCabinets: unknown[]
): CabinetLineItem[] {
  const byMarker = new Map<number, MeasuredCabinet>();
  for (const raw of rawCabinets) {
    const parsed = MeasuredCabinet.safeParse(raw);
    if (parsed.success) byMarker.set(parsed.data.marker, parsed.data);
  }
  return entries.map((entry) => {
    const answer = byMarker.get(entry.marker);
    const category = toLineCategory(answer?.category ?? entry.category);
    const defaults =
      BETA_DEFAULT_DIMS[answer?.category ?? entry.category] ??
      BETA_DEFAULT_DIMS[entry.category];
    const width = answer?.width_in ?? defaults?.w ?? null;
    const height = answer?.height_in ?? defaults?.h ?? null;
    const depth = answer?.depth_in ?? defaults?.d ?? null;
    const defaulted =
      answer?.width_in == null || answer?.height_in == null || answer == null;
    const { tag, callout } = meaningfulTag(
      answer?.tag ?? (entry.label || null),
      answer?.category ?? entry.category,
      width,
      entry.marker
    );
    const line: CabinetLineItem = {
      source_page: entry.page,
      tag,
      room: null,
      qty: 1,
      category,
      width_in: width,
      height_in: height,
      depth_in: depth,
      door_style: null,
      material: null,
      finish: null,
      assembled: null,
      // Keep the drawing's bare-number callout as provenance when the tag
      // had to be synthesized.
      notes: callout ? `drawing callout: ${callout}` : null,
      confidence: Math.min(entry.confidence, answer?.confidence ?? 0.5),
      estimated: false,
      bbox_2d: entry.bboxReadPx,
    };
    return answer?.measured && !defaulted ? line : markEstimated(line);
  });
}

// Draw numbered category-colored boxes onto a page render (the set-of-marks
// input for the measurements pass). Exported for the offline staged kit.
export async function annotatePage(
  png: Uint8Array,
  widthPx: number,
  heightPx: number,
  boxes: { marker: number; category: string; bbox: [number, number, number, number] }[]
): Promise<Buffer> {
  const stroke = Math.max(2, Math.round(widthPx * 0.002));
  const badge = Math.max(14, Math.round(widthPx * 0.014));
  const parts = boxes.map(({ marker, category, bbox }) => {
    const color = ANNOTATE_COLORS[category] ?? "rgb(220,38,38)";
    const [x0, y0, x1, y1] = bbox;
    const bx = Math.max(0, x0 - stroke);
    const by = Math.max(badge * 1.4, y0);
    return `
      <rect x="${x0}" y="${y0}" width="${Math.max(1, x1 - x0)}" height="${Math.max(1, y1 - y0)}"
        fill="none" stroke="${color}" stroke-width="${stroke}"/>
      <rect x="${bx}" y="${by - badge * 1.4}" width="${badge * (String(marker).length * 0.62 + 0.9)}" height="${badge * 1.3}" fill="${color}"/>
      <text x="${bx + badge * 0.45}" y="${by - badge * 0.35}" font-family="sans-serif"
        font-size="${badge}" font-weight="bold" fill="white">${marker}</text>`;
  });
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${widthPx}" height="${heightPx}">${parts.join("")}</svg>`;
  return sharp(Buffer.from(png))
    .composite([{ input: Buffer.from(svg) }])
    .png()
    .toBuffer();
}

export function betaReadKey(takeoffId: string, page: number): string {
  return `takeoffs/${takeoffId}/reads/p${page}-beta-full.png`;
}

// Pure measure-response parse (harness-replayable): the cabinets array plus
// human-visible warnings when the response is unusable.
export function parseMeasureResponse(text: string): {
  cabinets: unknown[];
  warnings: string[];
} {
  try {
    const obj = (extractJson(text) ?? {}) as { cabinets?: unknown };
    if (Array.isArray(obj.cabinets)) return { cabinets: obj.cabinets, warnings: [] };
    return {
      cabinets: [],
      warnings: ["measurements response had no cabinets array — sizes defaulted"],
    };
  } catch {
    return {
      cabinets: [],
      warnings: ["measurements response was not parseable JSON — sizes defaulted"],
    };
  }
}

export interface BuildOpts {
  // "restore" (wizard default): failure puts the takeoff back to priorStatus.
  // "throw": rethrow so the caller's failure handling (failTakeoff) runs.
  onError?: "restore" | "throw";
  // Staged pipeline parity: also write the eval fixture and docConfidence.
  evalFixture?: boolean;
  // Upstream warnings (e.g. locate fallbacks) surfaced ahead of the build's own.
  extraWarnings?: string[];
}

// Build the takeoff from all done detections: measure, replace lines, price.
// On failure the takeoff returns to the status it was in before the build
// (or rethrows under opts.onError = "throw"). Returns the merged lines.
export async function buildFromDetections(
  takeoffId: string,
  priorStatus: string,
  log: Logger,
  opts: BuildOpts = {}
): Promise<CabinetLineItem[]> {
  const db = getDb();
  try {
    const detections = await db
      .select()
      .from(takeoffDetections)
      .where(
        and(
          eq(takeoffDetections.takeoffId, takeoffId),
          eq(takeoffDetections.status, "done")
        )
      )
      .orderBy(takeoffDetections.page, takeoffDetections.createdAt);
    if (detections.length === 0) throw new Error("no completed detections");

    const pdf = await openTakeoffPdf(takeoffId);
    try {
      // Number every detected cabinet globally (page order, then scan order).
      const pages = [...new Set(detections.map((d) => d.page))].sort(
        (a, b) => a - b
      );
      let nextMarker = 1;
      const entries: MarkerEntry[] = [];
      const perPage = new Map<
        number,
        { entry: MarkerEntry; displayBbox: [number, number, number, number] | null }[]
      >();
      for (const page of pages) perPage.set(page, []);
      for (const d of detections) {
        const items = z.array(DetectionItem).catch([]).parse(d.items ?? []);
        for (const item of items) {
          const entry: MarkerEntry = {
            marker: nextMarker++,
            page: d.page,
            label: item.label,
            category: item.category,
            confidence: item.confidence,
            bboxReadPx: null, // filled after the page render DPI is known
          };
          entries.push(entry);
          perPage.get(d.page)!.push({ entry, displayBbox: item.bbox_2d });
        }
      }
      if (entries.length === 0) throw new Error("no detected cabinets");

      // The call sends EVERY page of the set (capped): marker pages get an
      // annotated render, the rest ride along as clean context (an unused
      // floor plan or schedule often holds the sizing context).
      const allPages = Array.from({ length: pdf.pageCount }, (_, i) => i + 1);
      const contextPages = allPages.filter((p) => !pages.includes(p));
      const sentPages = [...pages, ...contextPages]
        .slice(0, MEASURE_MAX_PAGES)
        .sort((a, b) => a - b);
      const omitted = allPages.length - sentPages.length;

      // Per page: render + (marker pages only) reads copy + annotation,
      // converting boxes display-px → render-px.
      const imageByPage = new Map<number, Buffer | Uint8Array>();
      const groundingByPage = new Map<number, string | undefined>();
      const fragmentsByPage = new Map<number, TextFragment[]>();
      const readRectByPage = new Map<number, RectPt & { dpi: number }>();
      for (const page of sentPages) {
        const dims = pdf.pageDimsPt(page - 1);
        const dpi = fitDpi(dims.widthPt / PT_PER_IN, dims.heightPt / PT_PER_IN);
        const png = pdf.renderPage(page - 1, dpi);
        try {
          fragmentsByPage.set(page, pdf.pageTextFragments(page - 1));
        } catch {
          fragmentsByPage.set(page, []);
        }
        groundingByPage.set(
          page,
          buildDimGrounding(fragmentsByPage.get(page) ?? [])
        );
        if (!pages.includes(page)) {
          imageByPage.set(page, png); // clean context page
          continue;
        }
        const displayDpi = betaDisplayDpi(dims);
        const toRender = dpi / displayDpi;
        await putObject(betaReadKey(takeoffId, page), png, "image/png");
        readRectByPage.set(page, {
          x0: 0,
          y0: 0,
          x1: dims.widthPt,
          y1: dims.heightPt,
          dpi,
        });
        const boxes: { marker: number; category: string; bbox: [number, number, number, number] }[] = [];
        for (const { entry, displayBbox } of perPage.get(page)!) {
          if (!displayBbox) continue;
          const bbox: [number, number, number, number] = [
            displayBbox[0] * toRender,
            displayBbox[1] * toRender,
            displayBbox[2] * toRender,
            displayBbox[3] * toRender,
          ];
          entry.bboxReadPx = bbox;
          boxes.push({ marker: entry.marker, category: entry.category, bbox });
        }
        const widthPx = Math.round((dims.widthPt / PT_PER_IN) * dpi);
        const heightPx = Math.round((dims.heightPt / PT_PER_IN) * dpi);
        const annotated = await annotatePage(png, widthPx, heightPx, boxes);
        await putObject(
          `takeoffs/${takeoffId}/beta/annotated/${page}.png`,
          annotated,
          "image/png"
        );
        imageByPage.set(page, annotated);
      }

      // Measurements pass: ONE call with the whole (capped) set.
      const client = getAnthropic();
      let tokens = 0;
      const cabinets: unknown[] = [];
      const parseWarnings: string[] = [];
      if (omitted > 0) {
        parseWarnings.push(
          `plan set has ${allPages.length} pages — ${omitted} context page(s) beyond the ${MEASURE_MAX_PAGES}-page cap were not sent to the measurements pass`
        );
      }
      const markers: MeasureMarker[] = entries.map((e) => {
        // Box center as % of the page: a text-side anchor so marker
        // attribution survives even if the painted badge is illegible.
        const rect = readRectByPage.get(e.page);
        const b = e.bboxReadPx;
        const pct =
          rect && b
            ? {
                xPct:
                  (((b[0] + b[2]) / 2) * (PT_PER_IN / rect.dpi) * 100) /
                  (rect.x1 - rect.x0),
                yPct:
                  (((b[1] + b[3]) / 2) * (PT_PER_IN / rect.dpi) * 100) /
                  (rect.y1 - rect.y0),
              }
            : {};
        // Per-marker printed-dim shortlist: box in page points + half-box
        // slack so the dimension bands beside/above the cabinet are included.
        let nearbyDims: string[] | undefined;
        if (rect && b) {
          const toPt = PT_PER_IN / rect.dpi;
          const boxPt = {
            x0: Math.min(b[0], b[2]) * toPt,
            y0: Math.min(b[1], b[3]) * toPt,
            x1: Math.max(b[0], b[2]) * toPt,
            y1: Math.max(b[1], b[3]) * toPt,
          };
          const slack = Math.max(
            36,
            0.5 * Math.max(boxPt.x1 - boxPt.x0, boxPt.y1 - boxPt.y0)
          );
          const found = dimsNearRect(
            fragmentsByPage.get(e.page) ?? [],
            boxPt,
            slack
          );
          if (found.length > 0) nearbyDims = found;
        }
        return {
          marker: e.marker,
          page: e.page,
          label: e.label,
          category: e.category,
          ...pct,
          ...(nearbyDims ? { nearbyDims } : {}),
        };
      });
      const message = await withSocketRetry(() =>
        client.messages
          .stream({
            model: DETECT_MODEL,
            max_tokens: 16000,
            ...(DETECT_MODEL.startsWith("claude-opus-4-8")
              ? {}
              : { temperature: 0 }),
            system: MEASURE_SYSTEM,
            messages: [
              {
                role: "user",
                content: [
                  ...sentPages.map((p) => imageBlock(imageByPage.get(p)!)),
                  {
                    type: "text" as const,
                    text: measureUserText(
                      markers,
                      groundingByPage,
                      sentPages.map((p) => ({
                        page: p,
                        hasMarkers: pages.includes(p),
                      }))
                    ),
                  },
                ],
              },
            ],
          })
          .finalMessage()
      );
      tokens += message.usage.input_tokens + message.usage.output_tokens;
      // Persist the raw response — when sizing goes wrong ("everything
      // defaulted"), this is the evidence of what the model actually said.
      const responseText = textOf(message);
      await putObject(
        `takeoffs/${takeoffId}/beta/measure/response-0.txt`,
        Buffer.from(responseText, "utf-8"),
        "text/plain"
      );
      const parsedResponse = parseMeasureResponse(responseText);
      cabinets.push(...parsedResponse.cabinets);
      parseWarnings.push(...parsedResponse.warnings);

      const merged = mergeMeasuredLines(entries, cabinets);
      const lines: ReadLine[] = merged.map((line, i) => ({
        ...line,
        read_image_key: betaReadKey(takeoffId, entries[i].page),
        read_rect: readRectByPage.get(entries[i].page) ?? null,
      }));

      await replaceLines(takeoffId, lines, false);
      const estimatedCount = merged.filter((l) => l.estimated).length;
      const warnings = [
        ...(opts.extraWarnings ?? []),
        ...parseWarnings,
        ...(estimatedCount > 0
          ? [
              `${estimatedCount} of ${merged.length} cabinets have estimated dimensions — verify against the drawing`,
            ]
          : []),
      ];
      const avgConfidence =
        merged.length > 0
          ? merged.reduce((s, l) => s + l.confidence, 0) / merged.length
          : null;
      await db
        .update(takeoffs)
        .set({
          docSummary: { warnings },
          promptVersion: MEASURE_PROMPT_VERSION,
          tokensUsed: sql`${takeoffs.tokensUsed} + ${tokens}`,
          ...(opts.evalFixture ? { docConfidence: avgConfidence } : {}),
          updatedAt: new Date(),
        })
        .where(eq(takeoffs.id, takeoffId));
      if (opts.evalFixture) {
        // Staged-pipeline parity with extractTakeoff: snapshot the
        // pre-correction lines so the eval corpus keeps building.
        await db
          .delete(evalFixtures)
          .where(eq(evalFixtures.takeoffId, takeoffId));
        await db.insert(evalFixtures).values({
          takeoffId,
          extractedLines: merged,
          promptVersion: MEASURE_PROMPT_VERSION,
        });
      }
      await priceAndExpand(takeoffId, log);
      log.info(
        { takeoff: takeoffId, cabinets: merged.length, estimatedCount, tokens },
        "beta build done"
      );
      return merged;
    } finally {
      pdf.close();
    }
  } catch (err) {
    if (opts.onError === "throw") throw err;
    const msg = err instanceof Error ? err.message : String(err);
    // Never fail the takeoff outright — restore where the user was.
    await db
      .update(takeoffs)
      .set({ status: priorStatus, error: `build takeoff failed: ${msg}`, updatedAt: new Date() })
      .where(eq(takeoffs.id, takeoffId));
    log.error({ takeoff: takeoffId, err: msg }, "beta build failed");
    return [];
  }
}


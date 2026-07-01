import { PageRegions, parsePageRegionsLenient } from "@scribe/shared";
import {
  locateRegionsUserText,
  LOCATE_REGIONS_SYSTEM,
  locateRoomsUserText,
  LOCATE_ROOMS_SYSTEM,
  SONNET_MODEL,
} from "@scribe/prompts";
import {
  extractJson,
  getAnthropic,
  imageBlock,
  TakeoffBudget,
  textOf,
  withSocketRetry,
} from "../lib/anthropic.js";

// Ask the model to segment a full-page sheet image into its distinct drawings
// (PRD §4). The image MUST be sized so the model doesn't downscale it, so the
// returned pixel boxes map cleanly back to page points. Best-effort: returns an
// empty region list on any failure so the caller falls back to whole-page tiling.
async function locate(
  system: string,
  userText: string,
  pageImage: Uint8Array,
  budget: TakeoffBudget
): Promise<PageRegions> {
  const client = getAnthropic();
  const message = await withSocketRetry(() =>
    client.messages.create({
      model: SONNET_MODEL,
      max_tokens: 2000,
      // Deterministic region splitting — varying crops change which cabinets are
      // read, a major source of run-to-run quote drift.
      temperature: 0,
      system,
      messages: [
        {
          role: "user",
          content: [imageBlock(pageImage), { type: "text", text: userText }],
        },
      ],
    })
  );
  budget.record(message.usage);
  return parsePageRegionsLenient(extractJson(textOf(message)));
}

export function locateRegions(
  pageImage: Uint8Array,
  imageWidthPx: number,
  imageHeightPx: number,
  budget: TakeoffBudget
): Promise<PageRegions> {
  return locate(
    LOCATE_REGIONS_SYSTEM,
    locateRegionsUserText(imageWidthPx, imageHeightPx),
    pageImage,
    budget
  );
}

// Segment a whole-dwelling FLOOR PLAN into per-room cabinetry crops (PRD §4
// no-schedule estimation), so each room is laid out from a coherent view.
export function locateRooms(
  pageImage: Uint8Array,
  imageWidthPx: number,
  imageHeightPx: number,
  budget: TakeoffBudget
): Promise<PageRegions> {
  return locate(
    LOCATE_ROOMS_SYSTEM,
    locateRoomsUserText(imageWidthPx, imageHeightPx),
    pageImage,
    budget
  );
}

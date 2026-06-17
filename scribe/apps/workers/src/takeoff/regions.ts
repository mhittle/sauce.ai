import { PageRegions } from "@scribe/shared";
import {
  locateRegionsUserText,
  LOCATE_REGIONS_SYSTEM,
  SONNET_MODEL,
} from "@scribe/prompts";
import {
  extractJson,
  getAnthropic,
  imageBlock,
  TakeoffBudget,
  textOf,
} from "../lib/anthropic.js";

// Ask the model to segment a full-page sheet image into its distinct drawings
// (PRD §4). The image MUST be sized so the model doesn't downscale it, so the
// returned pixel boxes map cleanly back to page points. Best-effort: returns an
// empty region list on any failure so the caller falls back to whole-page tiling.
export async function locateRegions(
  pageImage: Uint8Array,
  imageWidthPx: number,
  imageHeightPx: number,
  budget: TakeoffBudget
): Promise<PageRegions> {
  const client = getAnthropic();
  const message = await client.messages.create({
    model: SONNET_MODEL,
    max_tokens: 2000,
    system: LOCATE_REGIONS_SYSTEM,
    messages: [
      {
        role: "user",
        content: [
          imageBlock(pageImage),
          {
            type: "text",
            text: locateRegionsUserText(imageWidthPx, imageHeightPx),
          },
        ],
      },
    ],
  });
  budget.record(message.usage);
  return PageRegions.parse(extractJson(textOf(message)));
}

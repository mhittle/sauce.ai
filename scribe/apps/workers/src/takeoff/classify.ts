import { z } from "zod";
import { PageClassification } from "@scribe/shared";
import {
  CLASSIFY_SYSTEM,
  classifyUserText,
  SONNET_MODEL,
} from "@scribe/prompts";
import {
  extractJson,
  getAnthropic,
  imageBlock,
  TakeoffBudget,
  textOf,
} from "../lib/anthropic.js";

const BATCH_SIZE = 8;

// Batch-classify page thumbnails. A 200-page set costs ~25 low-res vision
// calls — under the <40-call target in PRD §6.2. (The sheet-index shortcut is
// a further optimization tracked on the roadmap.)
export async function classifyPages(
  thumbnails: { page: number; png: Uint8Array }[],
  budget: TakeoffBudget
): Promise<PageClassification[]> {
  const client = getAnthropic();
  const results: PageClassification[] = [];

  for (let i = 0; i < thumbnails.length; i += BATCH_SIZE) {
    const batch = thumbnails.slice(i, i + BATCH_SIZE);
    const message = await client.messages.create({
      model: SONNET_MODEL,
      max_tokens: 2000,
      system: CLASSIFY_SYSTEM,
      messages: [
        {
          role: "user",
          content: [
            ...batch.map((t) => imageBlock(t.png)),
            {
              type: "text",
              text: classifyUserText(batch.map((t) => t.page)),
            },
          ],
        },
      ],
    });
    budget.record(message.usage);

    const parsed = z
      .array(PageClassification)
      .parse(extractJson(textOf(message)));
    // Trust the order shown over model-reported page numbers when they drift.
    for (const [j, item] of parsed.entries()) {
      const expected = batch[j]?.page;
      results.push(
        expected != null && item.page !== expected
          ? { ...item, page: expected }
          : item
      );
    }
  }

  return results;
}

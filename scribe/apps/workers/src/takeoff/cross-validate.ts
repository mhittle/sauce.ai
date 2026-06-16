import {
  applyCrossValidation,
  type CrossValidationFlag,
  PageExtraction,
  repairLine,
} from "@scribe/shared";
import { EXTRACT_SYSTEM, extractUserText } from "@scribe/prompts";
import { extractJson } from "../lib/anthropic.js";
import { getOpenAI, OPENAI_VISION_MODEL } from "../lib/openai.js";

export interface CrossValidationOutcome {
  extraction: PageExtraction;
  flags: CrossValidationFlag[];
  secondaryRaw: unknown;
  tokens: number;
}

// Runs the same extraction prompt + page image through the secondary OpenAI
// vision model and diffs it against the primary (Anthropic) extraction. The
// primary line set is never replaced — only confidences are lowered where the
// two models disagree. Best-effort: callers treat a thrown error as a warning.
export async function crossValidatePage(
  pageNumber: number,
  png: Uint8Array,
  primary: PageExtraction
): Promise<CrossValidationOutcome> {
  const client = getOpenAI();
  const b64 = Buffer.from(png).toString("base64");
  const res = await client.chat.completions.create({
    model: OPENAI_VISION_MODEL,
    max_completion_tokens: 16000,
    response_format: { type: "json_object" },
    messages: [
      { role: "system", content: EXTRACT_SYSTEM },
      {
        role: "user",
        content: [
          { type: "text", text: extractUserText(pageNumber) },
          {
            type: "image_url",
            image_url: { url: `data:image/png;base64,${b64}` },
          },
        ],
      },
    ],
  });

  const text = res.choices[0]?.message?.content ?? "";
  const raw = extractJson(text);
  const secondary = PageExtraction.parse(raw);
  const secondaryLines = secondary.lines.map((l) =>
    repairLine({ ...l, source_page: l.source_page ?? pageNumber })
  );

  const { lines, flags } = applyCrossValidation(primary.lines, secondaryLines);

  return {
    extraction: { ...primary, lines },
    flags,
    secondaryRaw: raw,
    tokens: res.usage?.total_tokens ?? 0,
  };
}

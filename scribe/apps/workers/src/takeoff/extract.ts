import { markEstimated, PageExtraction, repairLine } from "@scribe/shared";
import {
  ESTIMATE_SYSTEM,
  estimateUserText,
  EXTRACT_SYSTEM,
  extractRegionUserText,
  extractUserText,
  SONNET_MODEL,
} from "@scribe/prompts";
import {
  extractJson,
  getAnthropic,
  imageBlock,
  TakeoffBudget,
  textOf,
} from "../lib/anthropic.js";

// Extract structured line items from one high-DPI page render (PRD §6.3).
// Model output is zod-validated and passed through the deterministic
// nomenclature post-parser; raw output is returned for audit persistence.
export async function extractPage(
  pageNumber: number,
  png: Uint8Array,
  budget: TakeoffBudget,
  opts: { region?: boolean; estimate?: boolean } = {}
): Promise<{ extraction: PageExtraction; raw: unknown }> {
  const client = getAnthropic();
  const userText = opts.estimate
    ? estimateUserText(pageNumber)
    : opts.region
      ? extractRegionUserText(pageNumber)
      : extractUserText(pageNumber);
  const message = await client.messages.create({
    model: SONNET_MODEL,
    max_tokens: 16000,
    system: opts.estimate ? ESTIMATE_SYSTEM : EXTRACT_SYSTEM,
    messages: [
      {
        role: "user",
        content: [imageBlock(png), { type: "text", text: userText }],
      },
    ],
  });
  budget.record(message.usage);

  const raw = extractJson(textOf(message));
  const extraction = PageExtraction.parse(raw);

  const repaired = {
    ...extraction,
    lines: extraction.lines.map((l) =>
      repairLine({ ...l, source_page: l.source_page ?? pageNumber })
    ),
  };

  // Multi-unit handling (PRD §6.3): multiply only when this page carries
  // exactly one unambiguous unit count; otherwise flag for review.
  const multipliers = repaired.unit_multipliers.filter((m) => !m.ambiguous);
  const ambiguous = repaired.unit_multipliers.filter(
    (m) => m.ambiguous || m.count == null
  );
  if (multipliers.length === 1 && multipliers[0].count != null) {
    const factor = multipliers[0].count;
    if (factor > 1) {
      repaired.lines = repaired.lines.map((l) => ({
        ...l,
        qty: l.qty * factor,
        notes: [l.notes, `×${factor} (${multipliers[0].unit_type})`]
          .filter(Boolean)
          .join("; "),
      }));
    }
  } else if (repaired.unit_multipliers.length > 0) {
    repaired.uncertainties.push(
      `unit multipliers not applied automatically: ${repaired.unit_multipliers
        .map((m) => `${m.unit_type}×${m.count ?? "?"}`)
        .join(", ")} — verify quantities`
    );
    repaired.lines = repaired.lines.map((l) => ({
      ...l,
      confidence: Math.min(l.confidence, 0.7),
    }));
  }
  void ambiguous;

  // No-schedule estimate (PRD §4): flag every line + cap confidence so it
  // surfaces for review and never reads as a schedule-grade quantity.
  if (opts.estimate) {
    repaired.lines = repaired.lines.map(markEstimated);
  }

  return { extraction: repaired, raw };
}

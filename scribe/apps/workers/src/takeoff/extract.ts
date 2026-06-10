import { PageExtraction, repairLine } from "@scribe/shared";
import {
  EXTRACT_SYSTEM,
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
  budget: TakeoffBudget
): Promise<{ extraction: PageExtraction; raw: unknown }> {
  const client = getAnthropic();
  const message = await client.messages.create({
    model: SONNET_MODEL,
    max_tokens: 16000,
    system: EXTRACT_SYSTEM,
    messages: [
      {
        role: "user",
        content: [
          imageBlock(png),
          { type: "text", text: extractUserText(pageNumber) },
        ],
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

  return { extraction: repaired, raw };
}

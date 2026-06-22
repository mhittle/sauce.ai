import {
  CabinetLineItem,
  markEstimated,
  PageExtraction,
  repairLine,
} from "@scribe/shared";
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

// Recover complete line objects from a response whose JSON is unparseable
// (typically truncated at max_tokens). Walks the `"lines": [ ... ]` array with
// a string-aware brace scanner and JSON.parses each balanced {...}; an
// incomplete trailing object is simply skipped. Returns [] if no lines array.
export function salvageLineObjects(text: string): unknown[] {
  const li = text.indexOf('"lines"');
  if (li === -1) return [];
  const arrStart = text.indexOf("[", li);
  if (arrStart === -1) return [];
  const objs: unknown[] = [];
  let depth = 0;
  let inStr = false;
  let esc = false;
  let objStart = -1;
  for (let i = arrStart + 1; i < text.length; i++) {
    const ch = text[i];
    if (inStr) {
      if (esc) esc = false;
      else if (ch === "\\") esc = true;
      else if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') inStr = true;
    else if (ch === "{") {
      if (depth === 0) objStart = i;
      depth++;
    } else if (ch === "}") {
      depth--;
      if (depth === 0 && objStart !== -1) {
        try {
          objs.push(JSON.parse(text.slice(objStart, i + 1)));
        } catch {
          // skip a malformed object
        }
        objStart = -1;
      }
    } else if (ch === "]" && depth === 0) {
      break; // end of the lines array
    }
  }
  return objs;
}

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
    max_tokens: 32000,
    system: opts.estimate ? ESTIMATE_SYSTEM : EXTRACT_SYSTEM,
    messages: [
      {
        role: "user",
        content: [imageBlock(png), { type: "text", text: userText }],
      },
    ],
  });
  budget.record(message.usage);

  const text = textOf(message);
  // A whole region (e.g. a cabinet-dense kitchen) used to be silently dropped
  // when its response was truncated at max_tokens — JSON.parse throws on the
  // partial array, and the caller catches+continues. Parse defensively: if the
  // top-level parse fails OR yields no lines, SALVAGE every complete {...}
  // object from the lines array so a cut-off tail only loses its last cabinet.
  let rawObj: Record<string, unknown> = {};
  try {
    rawObj = (extractJson(text) ?? {}) as Record<string, unknown>;
  } catch {
    rawObj = {};
  }
  let rawLines = Array.isArray(rawObj.lines) ? rawObj.lines : [];
  const truncated = message.stop_reason === "max_tokens";
  if (rawLines.length === 0) {
    const salvaged = salvageLineObjects(text);
    if (salvaged.length > 0) rawLines = salvaged;
  }
  // Parse lines leniently: one malformed line (e.g. qty 0, a stray "gap"
  // marker) must NOT discard the whole page/region's extraction.
  const validLines = rawLines.flatMap((l) => {
    const parsed = CabinetLineItem.safeParse({
      ...(l as object),
      source_page: (l as { source_page?: unknown }).source_page ?? pageNumber,
    });
    return parsed.success ? [parsed.data] : [];
  });
  const raw = Object.keys(rawObj).length > 0 ? rawObj : { salvaged_from_text: text };
  const extraction = PageExtraction.parse({ ...rawObj, lines: validLines });
  if (truncated) {
    extraction.uncertainties.push(
      `model response was truncated (max_tokens) — recovered ${validLines.length} item(s) on this page/region; some cabinets may be missing, verify`
    );
  }

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

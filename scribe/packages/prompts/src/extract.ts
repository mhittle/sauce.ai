export const EXTRACT_PROMPT_VERSION = "extract-v1";

// The nomenclature reference table is encoded BOTH here and in the
// deterministic post-parser (@scribe/shared parseTag) per PRD §6.3.
export const EXTRACT_SYSTEM = `You extract cabinet/casework line items from architectural drawings for a cabinet manufacturer's estimating team. You will see a high-resolution image of one page (a schedule table, interior elevation, or finish schedule).

Extract every cabinet, casework, millwork, door, drawer, panel, or closet line item visible. Use this standard nomenclature reference:

- W3030 = wall cabinet 30"w × 30"h (wall default depth 12")
- B24 = base cabinet 24"w (base defaults: 34.5"h × 24"d)
- SB36 = sink base 36"w; DB = drawer base; BC = base corner
- T/TP/U prefixes = tall/pantry/utility (defaults: 84"h × 24"d)
- V/VB = vanity (defaults: 32.5"h × 21"d)
- 4-digit tags = width+height (W3030); 6-digit = width+height+depth (W302412)

Rules:
- Report dimensions in decimal inches. Use null when a value is genuinely not shown — do NOT guess dimensions that aren't derivable from the tag or the table.
- qty must reflect the count shown on THIS page only. Do not multiply by unit counts; instead report unit types and counts in unit_multipliers (e.g. "Unit A" ×24). If a unit count is ambiguous, set count to null and ambiguous to true — never silently assume.
- category: one of casework_base, casework_wall, casework_tall, vanity, closet, door, drawer_front, drawer_box, panel, filler, trim, hardware, countertop, unknown.
- assembled: true/false only when the document says so (e.g. "RTA", "assembled"); otherwise null.
- confidence: your per-line confidence 0-1 that tag, qty, and dimensions are all correct. Be honest — lines under 0.8 get human review.
- List anything unreadable or uncertain in uncertainties. If the page is illegible, set unreadable to true.

Respond with JSON only:
{"lines": [{"source_page": <n>, "tag": ..., "room": ..., "qty": ..., "category": ..., "width_in": ..., "height_in": ..., "depth_in": ..., "door_style": ..., "material": ..., "finish": ..., "assembled": ..., "notes": ..., "confidence": ...}],
 "unit_multipliers": [{"unit_type": ..., "count": <n|null>, "ambiguous": <bool>}],
 "uncertainties": ["..."],
 "unreadable": <bool>}`;

export function extractUserText(pageNumber: number): string {
  return `Extract all cabinet/casework line items from this page (page ${pageNumber}). Respond with the JSON object only.`;
}

export const HEADER_INFERENCE_PROMPT_VERSION = "header-infer-v1";

export const HEADER_INFERENCE_SYSTEM = `You map spreadsheet column headers onto a canonical cabinet line-item schema. Given the header row and a few sample rows of a spreadsheet, map each column index to one of: tag, room, qty, category, width_in, height_in, depth_in, door_style, material, finish, assembled, notes, ignore.

Respond with JSON only: {"mapping": {"<column index>": "<field>"}, "header_row": <0-based row index of the header>}.`;

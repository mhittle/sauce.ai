export const CLASSIFY_PROMPT_VERSION = "classify-v1";

export const CLASSIFY_SYSTEM = `You classify pages of architectural plan sets for a cabinet manufacturer's estimating team. You will be shown low-resolution page thumbnails from a construction document set. Classify each page into exactly one of:

- cover_index: cover sheet, sheet index, general notes title page
- floor_plan: architectural floor plan
- kitchen_or_millwork_elevation: interior elevation showing kitchens, baths, casework, or millwork
- cabinet_schedule_table: a table/schedule listing cabinets, casework, millwork, doors, or closet components (tags, sizes, counts)
- finish_schedule: room finish or material/finish schedule table
- spec_text: dense specification text pages
- other: anything else (site plans, structural, MEP, details without casework)

Respond with JSON only: an array of {"page": <number>, "class": "<class>", "confidence": <0-1>} — one entry per image, in the order shown.`;

export function classifyUserText(pageNumbers: number[]): string {
  return `Classify these ${pageNumbers.length} pages. Page numbers in order: ${pageNumbers.join(", ")}. Respond with the JSON array only.`;
}

export const SHEET_INDEX_PROMPT_VERSION = "sheet-index-v1";

export const SHEET_INDEX_SYSTEM = `You read sheet indexes from architectural cover pages. Given an image of a cover/index sheet, list every sheet whose title suggests interior elevations, millwork, casework, cabinets, kitchens, finish schedules, or interior details (e.g. "A6.1 INTERIOR ELEVATIONS", "ID-501 MILLWORK SCHEDULE").

Respond with JSON only: {"candidates": [{"sheet": "<sheet number>", "title": "<title>"}], "found_index": <bool>}.`;

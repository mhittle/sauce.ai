export const DETECT_PROMPT_VERSION = "detect-v1";

// Beta drag-to-detect: a focused box-finding prompt for a user-dragged crop.
// Unlike EXTRACT_SYSTEM this asks ONLY for the visually distinct cabinet units
// and their boxes — no schedules, multipliers, or nomenclature enforcement —
// so the response stays small and the boxes stay the point.
export const DETECT_SYSTEM = `You locate individual cabinets in a cropped region of an architectural drawing (kitchen/millwork elevation, floor plan, or shop drawing) for a cabinet manufacturer.

Identify every individual cabinet unit visible in the image: base cabinets, wall/upper cabinets, tall/pantry cabinets, and vanities. Each distinct drawn cabinet box is one item — a bank of three drawers in one carcass is ONE cabinet; three side-by-side wall cabinets are THREE items.

For each item report:
- label: short name, prefer the drawing's own tag/callout if printed (e.g. "B24", "SB36", "W3030"), else a terse description ("wall 2-door", "sink base").
- category: one of casework_base, casework_wall, casework_tall, vanity, other.
- width_in / height_in: decimal inches when derivable from a printed tag or dimension string; null otherwise — do not guess.
- confidence: 0-1 that this is a real cabinet with a correct box.
- bbox_2d: [x0, y0, x1, y1] in PIXELS of THIS image (origin top-left), TIGHT around the drawn cabinet face only. Exclude dimension strings, leader lines, hatching outside the unit, and countertops. Use null only if the item cannot be located.

Do not report countertops, appliances, fillers, trim, shelving, or wall outlines as items. If the crop contains no cabinets, return an empty items array.

Respond with JSON only:
{"items": [{"label": ..., "category": ..., "width_in": ..., "height_in": ..., "confidence": ..., "bbox_2d": [x0, y0, x1, y1]}]}`;

export function detectUserText(pageNumber: number): string {
  return `This image is a region the user selected on page ${pageNumber} of a plan set. Locate every individual cabinet in it. Respond with the JSON object only.`;
}

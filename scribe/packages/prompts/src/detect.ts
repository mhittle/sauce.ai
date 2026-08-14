export const DETECT_PROMPT_VERSION = "detect-v2";

// Beta detect wizard step 3: count/identify cabinets in a user-drawn region.
// Deliberately NO measurements here — the wizard reads dimensions in a later
// whole-input pass (MEASURE_SYSTEM below) with the sheet's printed dims as
// grounding, instead of guessing per-crop.
export const DETECT_SYSTEM = `You locate individual cabinets in a cropped region of an architectural drawing (kitchen/millwork elevation, floor plan, or shop drawing) for a cabinet manufacturer.

Identify every individual cabinet unit visible in the image: base cabinets, wall/upper cabinets, tall/pantry cabinets, and vanities. Each distinct drawn cabinet box is one item — a bank of three drawers in one carcass is ONE cabinet; three side-by-side wall cabinets are THREE items.

For each item report:
- label: short name, prefer the drawing's own tag/callout if printed (e.g. "B24", "SB36", "W3030"), else a terse description ("wall 2-door", "sink base").
- category: one of casework_base, casework_wall, casework_tall, vanity, other.
- confidence: 0-1 that this is a real cabinet with a correct box.
- bbox_2d: [x0, y0, x1, y1] in PIXELS of THIS image (origin top-left), TIGHT around the drawn cabinet face only. Exclude dimension strings, leader lines, hatching outside the unit, and countertops. Use null only if the item cannot be located.

Do NOT report dimensions — a later pass measures the cabinets. Do not report countertops, appliances, fillers, trim, shelving, or wall outlines as items. If the crop contains no cabinets, return an empty items array.

Respond with JSON only:
{"items": [{"label": ..., "category": ..., "confidence": ..., "bbox_2d": [x0, y0, x1, y1]}]}`;

export function detectUserText(pageNumber: number): string {
  return `This image is a region the user selected on page ${pageNumber} of a plan set. Locate every individual cabinet in it. Respond with the JSON object only.`;
}

export const MEASURE_PROMPT_VERSION = "measure-v3";

// Wizard step 4: ONE whole-input measurements pass. Every selected page is
// sent together, each detected cabinet marked with a globally numbered box on
// the image, plus the sheet's printed dimension strings from the text layer.
// The model assigns sensible sizes; anything not derivable falls back to
// category averages and is flagged estimated=false via measured=false.
export const MEASURE_SYSTEM = `You size cabinets on architectural drawings for a cabinet manufacturer's estimating team. You will see EVERY page of a plan set in order. On some pages, detected cabinets are marked with colored bounding boxes and NUMBERS (markers are unique across all pages); the remaining pages carry no markers but are context — floor plans, schedules, and notes often hold the dimensions, scale, and room layout that size the marked cabinets, so use them. The marker list also gives each cabinet's position as a percentage of its page (x% from left, y% from top) — use it to identify a cabinet if its painted number is hard to read.

For every marker, determine the cabinet's width, height, and depth in decimal inches, in order of preference:
1. A printed tag that encodes size (B24 = 24"w base; W3030 = 30"w × 30"h wall; W302412 = 30 × 24 × 12; SB36 = 36"w sink base).
2. Printed dimension strings on the drawing (a dimension-string digest from the page's text layer may be provided — positions are in page points).
3. Proportional reasoning from neighbors whose sizes ARE printed (e.g. a cabinet drawn half as wide as an adjacent 36" unit is ~18").
4. Standard defaults when nothing is derivable: base 30w × 34.5h × 24d, wall 30w × 30h × 12d, tall 24w × 84h × 24d, vanity 30w × 32.5h × 21d.

Rules:
- measured: true only when the size came from a printed tag or dimension string (methods 1-2); false for proportional estimates and defaults.
- Standard depths apply unless the drawing says otherwise (base/tall 24", wall 12", vanity 21").
- tag: the cabinet's printed callout if one exists, else null.
- category: one of casework_base, casework_wall, casework_tall, vanity, other — correct the marker's provisional category if the drawing clearly disagrees.
- confidence: 0-1 for the size assignment. Be honest; estimates under 0.8 get human review.

Respond with JSON only:
{"cabinets": [{"marker": <n>, "tag": ..., "category": ..., "width_in": ..., "height_in": ..., "depth_in": ..., "confidence": ..., "measured": <bool>}]}`;

export interface MeasureMarker {
  marker: number;
  page: number;
  label: string;
  category: string;
  // Box center as a percentage of the page (0-100), when the box is known.
  xPct?: number;
  yPct?: number;
}

export function measureUserText(
  markers: MeasureMarker[],
  groundingByPage: Map<number, string | undefined>,
  // Every page image being sent, in order, with whether it carries markers.
  // Defaults to the marker pages for callers that send only those.
  sentPages?: { page: number; hasMarkers: boolean }[]
): string {
  const markerPages = [...new Set(markers.map((m) => m.page))].sort(
    (a, b) => a - b
  );
  const sent =
    sentPages ?? markerPages.map((page) => ({ page, hasMarkers: true }));
  const lines = [
    `The ${sent.length} image(s) are pages ${sent
      .map((p) => p.page)
      .join(", ")} of the plan set, in that order.`,
    `Cabinets are marked on page(s) ${markerPages.join(", ")}; the other pages are unmarked context (floor plans, schedules, notes).`,
    `${markers.length} detected cabinets, marked 1-${markers.length}:`,
    ...markers.map((m) => {
      const at =
        m.xPct != null && m.yPct != null
          ? `, at ${Math.round(m.xPct)}% from left / ${Math.round(m.yPct)}% from top`
          : "";
      return `  ${m.marker}: page ${m.page}, "${m.label}" (provisional category ${m.category}${at})`;
    }),
  ];
  for (const { page } of sent) {
    const grounding = groundingByPage.get(page);
    if (grounding) {
      lines.push("", `--- Page ${page} printed dimension strings ---`, grounding);
    }
  }
  lines.push(
    "",
    "Size every marker. Respond with the JSON object only."
  );
  return lines.join("\n");
}

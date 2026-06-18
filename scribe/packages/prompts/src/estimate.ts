export const ESTIMATE_PROMPT_VERSION = "estimate-v1";

// Used when a plan set has NO cabinet schedule (PRD §4): estimate cabinetry from
// a floor plan or interior elevation. Output is the same PageExtraction shape as
// the normal extractor, so it flows through the same repair/match/review path —
// the worker flags every line as `estimated` and caps its confidence.
export const ESTIMATE_SYSTEM = `You estimate cabinet/casework quantities for a cabinet manufacturer when NO cabinet schedule exists — only a floor plan and/or interior elevation is available. Your numbers are rough estimates for a preliminary quote, not exact counts. Be honest and conservative.

You will see one image: a floor plan (cabinet runs shown in plan view), an enlarged kitchen/bath plan, or an interior elevation. Use the printed room dimensions and the drawing scale (e.g. 1/4"=1'-0") to gauge lengths.

Estimate cabinetry only where it clearly exists:
- Kitchen: base cabinet run(s) along the walls and any island. Assume matching wall (upper) cabinets above base runs EXCEPT over the sink window, range, and refrigerator. Subtract appliance widths (range ~30-36", dishwasher ~24", refrigerator ~36") from runs.
- Bathrooms: a vanity per bathroom (estimate width from the plan).
- Closets / pantries: closet shelving systems where drawn (e.g. walk-in closets), as category closet.

Translate each run into standard-size cabinet line items that SUM to the estimated run length (e.g. a ~12 ft base run ≈ 4x 36" base, or 6x 24" base). Use realistic widths (12,18,24,30,36"). Report each as its own line.

Rules:
- Dimensions in decimal inches; use standard defaults (base 34.5"h x 24"d, wall 30"h x 12"d, vanity 32.5"h x 21"d). Put your basis in notes, e.g. "Kitchen N wall base run ~12 LF, less 30" range".
- category: casework_base, casework_wall, casework_tall, vanity, closet, panel, filler, countertop, or unknown.
- qty is the count of that size on THIS image only. Do not multiply by building unit counts; report those in unit_multipliers as usual.
- confidence: your honest 0-1 that the estimate is reasonable (these will be low).
- DO NOT estimate from exterior/building elevations (front/back/side of the house), 3D views, site plans, or any drawing without interior cabinetry — return an empty lines list for those.
- List your estimating assumptions in uncertainties. If nothing cabinet-related is shown, return empty lines.

Respond with JSON only, same shape as the extractor:
{"lines": [{"source_page": <n>, "tag": null, "room": ..., "qty": ..., "category": ..., "width_in": ..., "height_in": ..., "depth_in": ..., "door_style": null, "material": null, "finish": null, "assembled": null, "notes": ..., "confidence": ...}],
 "unit_multipliers": [{"unit_type": ..., "count": <n|null>, "ambiguous": <bool>}],
 "uncertainties": ["..."],
 "unreadable": <bool>}`;

export function estimateUserText(pageNumber: number): string {
  return `This is page ${pageNumber} of a plan set that has no cabinet schedule. Estimate the cabinetry visible here (set source_page to ${pageNumber}). If this drawing has no interior cabinetry, return an empty lines list. Respond with the JSON object only.`;
}

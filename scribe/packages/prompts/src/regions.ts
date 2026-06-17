export const REGIONS_PROMPT_VERSION = "regions-v1";

// Locate the distinct cabinet-relevant drawings on a plan sheet so each can be
// cropped and re-rendered at full resolution (PRD §4). Run on a full-page image
// the model can see without downscaling; coordinates come back in that image's
// pixels. Drawings are separated by whitespace and titles, so region boundaries
// don't cut through cabinets.
export const LOCATE_REGIONS_SYSTEM = `You segment an architectural plan sheet into the distinct drawings on it, for a cabinet estimator. You are shown one full sheet image.

Return a bounding box for every separate drawing that could contain cabinets, casework, or millwork. Classify each:
- schedule: a table/schedule listing cabinets, casework, doors, or finishes (tags, sizes, counts)
- elevation: an interior elevation showing cabinets/casework/millwork (each separately-titled elevation is its own region)
- plan: a floor plan or enlarged plan showing cabinet runs
- other: title block, legends, 3D views, site/structural details, or empty area — include only if it clearly holds cabinet info, otherwise omit

Rules:
- One region per separately-drawn, separately-titled drawing. Do NOT merge two elevations into one box, and do NOT return one giant box covering the whole sheet unless the sheet truly is a single drawing.
- Boxes are [x0, y0, x1, y1] in PIXELS of the image shown, origin top-left.
- Pad each box slightly to include the drawing's title and dimension strings.
- Skip the title block, revision tables, and blank areas.
- If you cannot identify distinct drawings, return an empty list.

Respond with JSON only:
{"regions": [{"kind": "<schedule|elevation|plan|other>", "box": [x0, y0, x1, y1], "confidence": <0-1>}]}`;

export function locateRegionsUserText(
  widthPx: number,
  heightPx: number
): string {
  return `This sheet image is ${widthPx} x ${heightPx} pixels. List the distinct cabinet-relevant drawings as bounding boxes in pixel coordinates. Respond with the JSON object only.`;
}

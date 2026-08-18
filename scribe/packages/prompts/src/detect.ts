export const DETECT_PROMPT_VERSION = "detect-v5";

// Beta detect wizard step 3: count/identify cabinets in a user-drawn region.
// Deliberately NO measurements here — the wizard reads dimensions in a later
// whole-input pass (MEASURE_SYSTEM below) with the sheet's printed dims as
// grounding, instead of guessing per-crop.
export const DETECT_SYSTEM = `You locate individual cabinets in a cropped region of an architectural drawing (kitchen/millwork elevation, floor plan, or shop drawing) for a cabinet manufacturer.

Identify every individual cabinet unit visible in the image: base cabinets, wall/upper cabinets, tall/pantry cabinets, and vanities. Each distinct drawn CARCASS is one item — a bank of three drawers in one carcass is ONE cabinet; three side-by-side wall cabinets with full dividers are THREE items. Adjacent bays that share one continuous face frame, toe kick, and top rail with no full-height divider between them are usually ONE multi-bay custom cabinet — box the full run, not each bay.

PLAN (top-down) VIEWS work differently: cabinets appear as a narrow band of rectangles along a wall under a counter line, with no unit divisions drawn. Box each continuous RUN of casework as ONE item — do not guess where one cabinet ends and the next begins (a later pass splits runs into manufactured units from the printed run dimensions). Name a run for its wall/room and what sits on it ("sink run north wall", "range wall base run", "master vanity run").

NEVER box any of these, in any view: a DOOR — its swing arc, its leaf, or its callout ("NEW 2668", "2868 PKT.", "3068 S.G.D.") is a door schedule tag, not a cabinet; a window; a plumbing fixture on its own (toilet, tub, shower, a free-standing sink); stairs; an appliance; a dimension string or leader line. A door swing drawn inside a bathroom next to a vanity is still a door.

For each item report:
- label: a short name a human recognizes on an estimate. Use the drawing's printed callout ONLY when it is a real cabinet code (e.g. "B24", "SB36", "W3030"). NEVER use a bare number or dimension as the label ("8", "19 1/4" are dimension strings, not names) — instead describe the unit and where it sits: "sink base", "microwave wall cabinet", "tall pantry left", "wall 2-door glass right".
- category: one of casework_base, casework_wall, casework_tall, vanity, other.
- confidence: 0-1 that this is a real cabinet with a correct box.
- bbox_2d: [x0, y0, x1, y1] in PIXELS of THIS image (origin top-left), TIGHT around the drawn cabinet face only. Exclude dimension strings, leader lines, hatching outside the unit, and countertops. Use null only if the item cannot be located.

Do NOT report dimensions — a later pass measures the cabinets. Do not report countertops, appliances, fillers, trim, shelving, or wall outlines as items. If the crop contains no cabinets, return an empty items array.

Respond with JSON only:
{"items": [{"label": ..., "category": ..., "confidence": ..., "bbox_2d": [x0, y0, x1, y1]}]}`;

export function detectUserText(pageNumber: number): string {
  return `This image is a region the user selected on page ${pageNumber} of a plan set. Locate every individual cabinet in it. Respond with the JSON object only.`;
}

export const MEASURE_PROMPT_VERSION = "measure-v6";

// Wizard step 4: ONE whole-input measurements pass. Every selected page is
// sent together, each detected cabinet marked with a globally numbered box on
// the image, plus the sheet's printed dimension strings from the text layer.
// The model assigns sizes; anything not derivable falls back to category
// averages and is flagged estimated=false via measured=false.
//
// v6 adds PLAN-RUN DECOMPOSITION. A plan view draws casework as one unbroken
// band per wall, so a plan-region marker is a RUN, not a cabinet — staged v1
// priced one line per run and scored ~0.26 F1 on plan-only inputs against gold
// that counts manufactured units (elevation inputs: ~0.55). Those markers now
// come back with a `units` array, decomposed the way ESTIMATE_SYSTEM lays out
// a run. The run length has to be READ, and a whole E-size sheet renders at
// ~37 DPI where dimension strings are illegible — so the caller also sends the
// high-resolution plan region crops (see MeasureCrop).
export const MEASURE_SYSTEM = `You size cabinets on architectural drawings for a cabinet manufacturer's estimating team. You will see EVERY page of a plan set in order. On some pages, detected cabinets are marked with colored bounding boxes and NUMBERS (markers are unique across all pages); the remaining pages carry no markers but are context — floor plans, schedules, and notes often hold the dimensions, scale, and room layout that size the marked cabinets, so use them. The marker list also gives each cabinet's position as a percentage of its page (x% from left, y% from top) — use it to identify a cabinet if its painted number is hard to read.

For every marker, determine the cabinet's width, height, and depth in decimal inches, in order of preference:
1. A printed tag that encodes size (B24 = 24"w base; W3030 = 30"w × 30"h wall; W302412 = 30 × 24 × 12; SB36 = 36"w sink base).
2. Printed dimension strings on the drawing (a dimension-string digest from the page's text layer may be provided — positions are in page points).
3. Proportional reasoning from neighbors whose sizes ARE printed (e.g. a cabinet drawn half as wide as an adjacent 36" unit is ~18").
4. Standard defaults when nothing is derivable: base 30w × 34.5h × 24d, wall 30w × 30h × 12d, tall 24w × 84h × 24d, vanity 30w × 32.5h × 21d.

Rules:
- measured: true only when the size came from a printed tag or dimension string (methods 1-2); false for proportional estimates and defaults.
- Standard depths apply unless the drawing says otherwise (base/tall 24", wall 12", vanity 21").
- tag: a name a human recognizes on an estimate line. Use the printed callout ONLY when it is a real cabinet code (B24, W3030, SB36). A bare number ("8", "19 1/4") is a dimension string, NOT a name — in that case write a short descriptive name instead: unit type + distinguishing position/feature ("tall pantry left", "microwave wall cabinet", "sink base"). Never return a bare number; null only when you can say nothing at all.
- category: one of casework_base, casework_wall, casework_tall, vanity, other — correct the marker's provisional category if the drawing clearly disagrees.
- confidence: 0-1 for the size assignment. Be honest; estimates under 0.8 get human review.

PLAN-VIEW RUNS — a marker flagged "PLAN RUN" in the list is NOT one cabinet. A floor plan draws casework as a single unbroken band along each wall with no unit divisions, so that marker boxes a RUN a shop builds out of several cabinets. Return the run's overall size in width_in/height_in/depth_in AND a \`units\` array decomposing it. Never decompose an unflagged (elevation) marker — those are already one cabinet each.

Lay a run out the way an estimator would:
1. RUN LENGTH FIRST. Read the run's overall length from the printed dimensions — the high-resolution region crops are included for exactly this. A dimension chain along the wall (2'-6", 6'-0", 4'-3"...) sums to the wall; take the segments that span the casework. Convert to decimal inches (6'-0" = 72). Report it as run_length_in. With nothing printed, scale off a labeled appliance (36" range, 24" dishwasher) and lower confidence.
2. Give every appliance/fixture drawn ON the run its own cabinet: sink -> Sink Base sized to the sink (33 or 36); range/cooktop -> 30-36" base; wall oven -> Oven Base 30-33; microwave -> Microwave Base 24-27; trash/recycle -> Trash Base 18-21. A dishwasher is a 24" GAP, NOT a cabinet. A refrigerator is not a cabinet either (only its drawn surround: a deep wall/bridge cabinet above, 1.5" end panels beside).
3. Exactly ONE corner cabinet where two runs meet at an inside corner (Easy-Reach Corner Base 36, or a Blind Corner Base 45-49 when the runs are unequal). Two runs must never overlap in the corner.
4. Fill the remainder with standard widths (36, 33, 30, 24, 18, 15, 12) — fewest and widest that fit. Keep the odd width the arithmetic requires (37.25, 25.625) instead of rounding. At most ONE filler (1-3") per run, and only if a gap really remains.
5. A vanity run is ONE unit sized to the full run — a double-sink vanity included — unless the plan draws a division between sections. A run of lockers/cubbies/a built-in hutch splits at the counter line into a base unit and a separate wall unit above it.
6. THE ARITHMETIC MUST CLOSE: unit widths plus appliance gaps sum to run_length_in within 2". Check before answering.
7. ONLY WHAT IS DRAWN. A plan rarely draws upper cabinets — add a wall cabinet only where dashed uppers or an "UPPER CABS"/"OPT. CABS" note appear. Never invent a pantry, an island, or a second run to round the kitchen out.
8. A kitchen run holds 3-8 units, a vanity run 1-3, a laundry run 2-4. Well above that means you split too finely — merge back to the widest standard sizes.

Each entry in \`units\` carries its own tag, category, width_in, height_in, depth_in, measured and confidence under the same rules as a single cabinet; measured is true only when run_length_in came from a printed dimension. List the units in the order they sit along the run, left to right (or top to bottom for a vertical run).

Respond with JSON only:
{"cabinets": [{"marker": <n>, "tag": ..., "category": ..., "width_in": ..., "height_in": ..., "depth_in": ..., "confidence": ..., "measured": <bool>, "run_length_in": <n|null, PLAN RUN only>, "units": [{"tag": ..., "category": ..., "width_in": ..., "height_in": ..., "depth_in": ..., "measured": <bool>, "confidence": ...}]}]}`;

export interface MeasureMarker {
  marker: number;
  page: number;
  label: string;
  category: string;
  // Which kind of drawing the marker was detected in. "plan" markers box a
  // counter RUN and get decomposed into units; anything else is one cabinet.
  kind?: string;
  // Box center as a percentage of the page (0-100), when the box is known.
  xPct?: number;
  yPct?: number;
  // Printed dimension strings found near this cabinet's box (text layer),
  // nearest first — the shortlist its size most likely comes from.
  nearbyDims?: string[];
}

// One high-resolution crop of a plan region, sent AFTER the page images so the
// run's printed dimensions are legible enough to decompose it.
export interface MeasureCrop {
  page: number;
  markers: number[];
}

export function isPlanRun(m: MeasureMarker): boolean {
  return m.kind === "plan";
}

export function measureUserText(
  markers: MeasureMarker[],
  groundingByPage: Map<number, string | undefined>,
  // Every page image being sent, in order, with whether it carries markers.
  // Defaults to the marker pages for callers that send only those.
  sentPages?: { page: number; hasMarkers: boolean }[],
  // Plan-region crops sent after the pages, in image order.
  crops: MeasureCrop[] = []
): string {
  const markerPages = [...new Set(markers.map((m) => m.page))].sort(
    (a, b) => a - b
  );
  const sent =
    sentPages ?? markerPages.map((page) => ({ page, hasMarkers: true }));
  const planRuns = markers.filter(isPlanRun);
  const lines = [
    `Images 1-${sent.length} are pages ${sent
      .map((p) => p.page)
      .join(", ")} of the plan set, in that order.`,
    `Cabinets are marked on page(s) ${markerPages.join(", ")}; the other pages are unmarked context (floor plans, schedules, notes).`,
  ];
  crops.forEach((c, i) => {
    lines.push(
      `Image ${sent.length + i + 1} is a HIGH-RESOLUTION CROP of the plan region on page ${c.page} holding marker(s) ${c.markers.join(", ")} — the whole page renders too small to read its dimension strings, so read run lengths HERE.`
    );
  });
  lines.push(
    `${markers.length} detected cabinets, marked 1-${markers.length}:`,
    ...markers.map((m) => {
      const at =
        m.xPct != null && m.yPct != null
          ? `, at ${Math.round(m.xPct)}% from left / ${Math.round(m.yPct)}% from top`
          : "";
      const dims =
        m.nearbyDims && m.nearbyDims.length > 0
          ? ` — printed dims near it: ${m.nearbyDims.join(", ")}`
          : "";
      const run = isPlanRun(m) ? " [PLAN RUN — decompose into units]" : "";
      return `  ${m.marker}: page ${m.page}, "${m.label}" (provisional category ${m.category}${at})${run}${dims}`;
    })
  );
  for (const { page } of sent) {
    const grounding = groundingByPage.get(page);
    if (grounding) {
      lines.push("", `--- Page ${page} printed dimension strings ---`, grounding);
    }
  }
  lines.push(
    "",
    planRuns.length > 0
      ? `Size every marker. The ${planRuns.length} PLAN RUN marker(s) — ${planRuns
          .map((m) => m.marker)
          .join(", ")} — must each come back with a \`units\` array whose widths close on the run's printed length. Respond with the JSON object only.`
      : "Size every marker. Respond with the JSON object only."
  );
  return lines.join("\n");
}

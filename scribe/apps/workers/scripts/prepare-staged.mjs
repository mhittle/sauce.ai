#!/usr/bin/env node
// Offline STAGED-pipeline kit generator (zero API): runs the deterministic
// steps of the staged extraction (segment → boxes → read → measure) for ONE
// plan PDF and stops at every vision-call boundary, writing the EXACT image +
// prompt as request files. Responses are produced on the owner's Claude plan
// (in-session) into responses/<id>.json; re-running advances the stage:
//   1. locate    (only pages that need regioning)
//   2. detect    (one request per region crop — count/label/box, no dims)
//   3. measure   (ONE request: every page, cabinets marked set-of-marks style)
// When the measure response exists, run replay-staged.mjs to merge, drop
// non-box casework, and score against labels.json.
//
// Page selection is the human step, passed inline:
//   node scripts/prepare-staged.mjs <plan.pdf> --kit <dir> \
//     --pages "2:elevation,3:elevation,4:plan"
// Classes: elevation | plan | schedule (schedule pages are skipped by staged
// v1 and only noted). Estimate mode = no schedule page in the selection.

import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import {
  betaDisplayDpi,
  buildDimGrounding,
  dimsNearRect,
  fitDpi,
  mapBoxToPagePoints,
  needsRegioning,
  padRectToPage,
  parsePageRegionsLenient,
} from "@scribe/shared";
import {
  DETECT_SYSTEM,
  detectUserText,
  LOCATE_REGIONS_SYSTEM,
  locateRegionsUserText,
  LOCATE_ROOMS_SYSTEM,
  locateRoomsUserText,
  MEASURE_SYSTEM,
  measureUserText,
  SONNET_MODEL,
} from "@scribe/prompts";
import { openPdf } from "../dist/takeoff/pdf.js";
import {
  annotatePage,
  processDetectionResponse,
} from "../dist/takeoff/detect.js";

const PT_PER_IN = 72;
const MIN_REGION_IN = { width: 1.5, height: 1 };
const DETECTABLE_KINDS = new Set(["elevation", "plan"]);
const MEASURE_MAX_PAGES = 30;

const args = process.argv.slice(2);
const input = args.find((a) => !a.startsWith("--"));
const flag = (n) => {
  const i = args.indexOf(n);
  return i >= 0 ? args[i + 1] : null;
};
const kitDir = flag("--kit");
const pagesArg = flag("--pages");
if (!input || !kitDir || !pagesArg) {
  console.error(
    'usage: prepare-staged.mjs <plan.pdf> --kit <dir> --pages "2:elevation,3:plan"'
  );
  process.exit(1);
}

const CLASS_MAP = {
  elevation: "kitchen_or_millwork_elevation",
  plan: "floor_plan",
  schedule: "cabinet_schedule_table",
};
const pages = pagesArg.split(",").map((s) => {
  const [p, cls] = s.trim().split(":");
  if (!CLASS_MAP[cls]) throw new Error(`unknown page class "${cls}"`);
  return { page: Number(p), class: CLASS_MAP[cls] };
});
const estimationMode = !pages.some(
  (p) => p.class === "cabinet_schedule_table"
);

const REQ = join(kitDir, "requests");
const RES = join(kitDir, "responses");
const STEPS = join(kitDir, "steps");
for (const d of [kitDir, REQ, RES, STEPS]) mkdirSync(d, { recursive: true });

const responseTextOf = (id) => {
  const p = join(RES, `${id}.json`);
  if (!existsSync(p)) return null;
  const raw = readFileSync(p, "utf8");
  try {
    const parsed = JSON.parse(raw);
    // Accept either raw JSON (returned as-is) or a {"text": "..."} wrapper.
    return typeof parsed?.text === "string" ? parsed.text : raw;
  } catch {
    return raw;
  }
};

function writeRequest(id, kind, system, userText, images) {
  writeFileSync(
    join(REQ, `${id}.json`),
    JSON.stringify(
      {
        id,
        kind,
        model: SONNET_MODEL,
        system,
        userText,
        images,
        responseFile: `responses/${id}.json`,
      },
      null,
      2
    )
  );
}

const pdf = openPdf(readFileSync(input));
const pageDims = new Map(
  pages.map((p) => [p.page, pdf.pageDimsPt(p.page - 1)])
);

// ---- Stage 1: locate --------------------------------------------------------
const pendingLocate = [];
const regionsByPage = new Map(); // page -> RectPt[] (page points)
for (const { page, class: cls } of pages) {
  if (cls === "cabinet_schedule_table") continue; // staged v1 skips schedules
  const dims = pageDims.get(page);
  const whole = { x0: 0, y0: 0, x1: dims.widthPt, y1: dims.heightPt };
  if (!needsRegioning(dims)) {
    regionsByPage.set(page, [
      { kind: cls === "floor_plan" ? "plan" : "elevation", rect: whole },
    ]);
    continue;
  }
  const dpi = fitDpi(dims.widthPt / PT_PER_IN, dims.heightPt / PT_PER_IN);
  const w = Math.round((dims.widthPt / PT_PER_IN) * dpi);
  const h = Math.round((dims.heightPt / PT_PER_IN) * dpi);
  const id = `locate-p${page}`;
  const rooms = estimationMode && cls === "floor_plan";
  const png = `${id}.png`;
  if (!existsSync(join(REQ, png)))
    writeFileSync(join(REQ, png), pdf.renderPage(page - 1, dpi));
  writeRequest(
    id,
    "locate",
    rooms ? LOCATE_ROOMS_SYSTEM : LOCATE_REGIONS_SYSTEM,
    rooms ? locateRoomsUserText(w, h) : locateRegionsUserText(w, h),
    [png]
  );
  const text = responseTextOf(id);
  if (text == null) {
    pendingLocate.push(id);
    continue;
  }
  let parsed;
  try {
    parsed = parsePageRegionsLenient(JSON.parse(text));
  } catch {
    parsed = { regions: [] };
  }
  const mapped = parsed.regions
    .filter((r) => DETECTABLE_KINDS.has(r.kind))
    .map((r) => ({
      kind: r.kind,
      rect: padRectToPage(
        mapBoxToPagePoints(r.box, { widthPx: w, heightPx: h }, dims),
        0.04,
        dims
      ),
    }))
    .filter(
      (r) =>
        (r.rect.x1 - r.rect.x0) / PT_PER_IN >= MIN_REGION_IN.width &&
        (r.rect.y1 - r.rect.y0) / PT_PER_IN >= MIN_REGION_IN.height
    );
  regionsByPage.set(
    page,
    mapped.length > 0
      ? mapped
      : [{ kind: cls === "floor_plan" ? "plan" : "elevation", rect: whole }]
  );
}
// Elevation-primary (mirrors staged.ts): plan regions re-count what the
// elevations already show — drop them when any elevation region exists.
{
  const all = [...regionsByPage.values()].flat();
  if (all.some((r) => r.kind === "elevation")) {
    for (const [page, regions] of regionsByPage) {
      regionsByPage.set(
        page,
        regions.filter((r) => r.kind !== "plan")
      );
    }
  }
}
if (pendingLocate.length > 0) {
  writeFileSync(
    join(kitDir, "kit.json"),
    JSON.stringify({ input, pages, estimationMode, status: "awaiting-locate", pending: pendingLocate }, null, 2)
  );
  console.error(`stage locate: ${pendingLocate.length} response(s) needed → ${REQ}`);
  process.exit(0);
}
writeFileSync(
  join(STEPS, "regions.json"),
  JSON.stringify([...regionsByPage].map(([page, regions]) => ({ page, regions })), null, 2)
);

// ---- Stage 2: detect --------------------------------------------------------
const pendingDetect = [];
const detections = []; // { page, rect(display px), items }
for (const [page, regions] of regionsByPage) {
  const dims = pageDims.get(page);
  const displayDpi = betaDisplayDpi(dims);
  regions.forEach(({ rect: cropPt }, i) => {
    const id = `detect-p${page}-r${i}`;
    const cropWIn = (cropPt.x1 - cropPt.x0) / PT_PER_IN;
    const cropHIn = (cropPt.y1 - cropPt.y0) / PT_PER_IN;
    const cropDpi = fitDpi(cropWIn, cropHIn);
    const png = `${id}.png`;
    if (!existsSync(join(REQ, png)))
      writeFileSync(join(REQ, png), pdf.renderRegion(page - 1, cropPt, cropDpi));
    writeRequest(id, "detect", DETECT_SYSTEM, detectUserText(page), [png]);
    const text = responseTextOf(id);
    if (text == null) {
      pendingDetect.push(id);
      return;
    }
    const items = processDetectionResponse(text, {
      cropPt,
      cropDpi,
      displayDpi,
      dims,
    });
    const toDisplay = displayDpi / PT_PER_IN;
    detections.push({
      page,
      rect: [
        cropPt.x0 * toDisplay,
        cropPt.y0 * toDisplay,
        cropPt.x1 * toDisplay,
        cropPt.y1 * toDisplay,
      ],
      items,
    });
  });
}
if (pendingDetect.length > 0) {
  writeFileSync(
    join(kitDir, "kit.json"),
    JSON.stringify({ input, pages, estimationMode, status: "awaiting-detect", pending: pendingDetect }, null, 2)
  );
  console.error(`stage detect: ${pendingDetect.length} response(s) needed → ${REQ}`);
  process.exit(0);
}
writeFileSync(join(STEPS, "detections.json"), JSON.stringify(detections, null, 2));

// ---- Stage 3: measure (mirrors buildFromDetections geometry) ----------------
const markerPages = [...new Set(detections.map((d) => d.page))].sort((a, b) => a - b);
const allPages = Array.from({ length: pdf.pageCount }, (_, i) => i + 1);
const sentPages = [...markerPages, ...allPages.filter((p) => !markerPages.includes(p))]
  .slice(0, MEASURE_MAX_PAGES)
  .sort((a, b) => a - b);

let nextMarker = 1;
const entries = [];
const boxesByPage = new Map(markerPages.map((p) => [p, []]));
for (const d of detections) {
  for (const item of d.items) {
    const entry = {
      marker: nextMarker++,
      page: d.page,
      label: item.label,
      category: item.category,
      confidence: item.confidence,
      bboxReadPx: null,
      displayBbox: item.bbox_2d,
    };
    entries.push(entry);
  }
}

const readRectByPage = {};
const groundingByPage = new Map();
const images = [];
for (const page of sentPages) {
  const dims = pdf.pageDimsPt(page - 1);
  const dpi = fitDpi(dims.widthPt / PT_PER_IN, dims.heightPt / PT_PER_IN);
  const png = pdf.renderPage(page - 1, dpi);
  let fragments = [];
  try {
    fragments = pdf.pageTextFragments(page - 1);
  } catch {
    fragments = [];
  }
  groundingByPage.set(page, buildDimGrounding(fragments));
  const name = `measure-page-${page}.png`;
  if (!markerPages.includes(page)) {
    if (!existsSync(join(REQ, name))) writeFileSync(join(REQ, name), png);
    images.push(name);
    continue;
  }
  readRectByPage[page] = { x0: 0, y0: 0, x1: dims.widthPt, y1: dims.heightPt, dpi };
  const displayDpi = betaDisplayDpi(dims);
  const toRender = dpi / displayDpi;
  const boxes = [];
  for (const e of entries) {
    if (e.page !== page || !e.displayBbox) continue;
    e.bboxReadPx = e.displayBbox.map((v) => v * toRender);
    boxes.push({ marker: e.marker, category: e.category, bbox: e.bboxReadPx });
  }
  const wPx = Math.round((dims.widthPt / PT_PER_IN) * dpi);
  const hPx = Math.round((dims.heightPt / PT_PER_IN) * dpi);
  const annotated = await annotatePage(png, wPx, hPx, boxes);
  writeFileSync(join(REQ, name), annotated);
  images.push(name);
  // Per-marker printed-dim shortlist (mirrors buildFromDetections).
  for (const e of entries) {
    if (e.page !== page || !e.bboxReadPx) continue;
    const toPt = PT_PER_IN / dpi;
    const boxPt = {
      x0: Math.min(e.bboxReadPx[0], e.bboxReadPx[2]) * toPt,
      y0: Math.min(e.bboxReadPx[1], e.bboxReadPx[3]) * toPt,
      x1: Math.max(e.bboxReadPx[0], e.bboxReadPx[2]) * toPt,
      y1: Math.max(e.bboxReadPx[1], e.bboxReadPx[3]) * toPt,
    };
    const slack = Math.max(36, 0.5 * Math.max(boxPt.x1 - boxPt.x0, boxPt.y1 - boxPt.y0));
    const found = dimsNearRect(fragments, boxPt, slack);
    if (found.length > 0) e.nearbyDims = found;
    const rect = readRectByPage[page];
    e.xPct = (((boxPt.x0 + boxPt.x1) / 2) * 100) / (rect.x1 - rect.x0);
    e.yPct = (((boxPt.y0 + boxPt.y1) / 2) * 100) / (rect.y1 - rect.y0);
  }
}

const markers = entries.map((e) => ({
  marker: e.marker,
  page: e.page,
  label: e.label,
  category: e.category,
  ...(e.xPct != null ? { xPct: e.xPct, yPct: e.yPct } : {}),
  ...(e.nearbyDims ? { nearbyDims: e.nearbyDims } : {}),
}));
writeRequest(
  "measure",
  "measure",
  MEASURE_SYSTEM,
  measureUserText(
    markers,
    groundingByPage,
    sentPages.map((p) => ({ page: p, hasMarkers: markerPages.includes(p) }))
  ),
  images
);
writeFileSync(
  join(STEPS, "markers.json"),
  JSON.stringify({ entries, readRectByPage }, null, 2)
);

const measureDone = responseTextOf("measure") != null;
writeFileSync(
  join(kitDir, "kit.json"),
  JSON.stringify(
    {
      input,
      pages,
      estimationMode,
      status: measureDone ? "ready-to-replay" : "awaiting-measure",
      pending: measureDone ? [] : ["measure"],
    },
    null,
    2
  )
);
console.error(
  measureDone
    ? "all responses present — run replay-staged.mjs"
    : `stage measure: 1 response needed → ${join(REQ, "measure.json")}`
);
pdf.close();

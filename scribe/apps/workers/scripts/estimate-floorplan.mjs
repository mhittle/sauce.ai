#!/usr/bin/env node
// Ad-hoc local runner: drives the REAL takeoff estimation modules on a floor
// plan PDF (no DB / storage / Redis) so we can iterate the no-schedule
// estimation reading and diff against a known quote.
//
// Run from the apps/workers dir so @scribe/* resolve:
//   AIRTABLE unused; needs the vision key:
//   ANTHROPIC_API_KEY=sk-... node scripts/estimate-floorplan.mjs "/path/to/floorplan.pdf"

import { readFileSync, existsSync } from "node:fs";
import { execSync } from "node:child_process";
import { tmpdir } from "node:os";
import { extname, join } from "node:path";
import {
  boxFaceArea,
  dedupeLines,
  dropNonBoxCasework,
  expandToComponents,
  fitDpi,
  mapBoxToPagePoints,
  needsRegioning,
  padRectToPage,
  pageClassToRole,
  pickMedian,
  planRenderJobs,
  RELEVANT_PAGE_CLASSES,
  routeByPageRole,
} from "@scribe/shared";
import { openPdf, THUMBNAIL_DPI } from "../dist/takeoff/pdf.js";
import { classifyPages } from "../dist/takeoff/classify.js";
import { locateRegions, locateRooms } from "../dist/takeoff/regions.js";
import { extractPage } from "../dist/takeoff/extract.js";
import { TakeoffBudget, BudgetExceededError } from "../dist/lib/anthropic.js";

const log = {
  info: (o, m) => console.error("·", m, o ? JSON.stringify(o) : ""),
  warn: (o, m) => console.error("!", m, o ? JSON.stringify(o) : ""),
};

const EXTRACTABLE = ["schedule", "elevation", "plan"];

// Mirror the pipeline's SCR-006 consensus: read each estimate page N times and
// keep the median-box-count read (default 3; ESTIMATE_CONSENSUS_N to tune). So
// a single harness run is prod-equivalent. Schedule reads stay at one.
function estimateConsensusN() {
  const raw = process.env.ESTIMATE_CONSENSUS_N;
  const n = raw == null ? 3 : Number(raw);
  return Number.isFinite(n) && n >= 1 ? Math.floor(n) : 3;
}

async function readPage(pdf, page, estimate, pageClass) {
  const n = estimate ? estimateConsensusN() : 1;
  if (n <= 1) return readPageOnce(pdf, page, estimate, pageClass);
  const candidates = [];
  for (let i = 0; i < n; i++)
    candidates.push(await readPageOnce(pdf, page, estimate, pageClass));
  // Select by quote-total proxy (cabinet face area), not box count — see process.ts.
  const chosen = pickMedian(candidates, (c) => boxFaceArea(c));
  console.error(
    `· estimate consensus p${page}: boxes [${candidates.map((c) => c.length).join("/")}]` +
      ` area [${candidates.map((c) => Math.round(boxFaceArea(c))).join("/")}] -> ${chosen.length} boxes / ${Math.round(boxFaceArea(chosen))} in²`
  );
  return chosen;
}

async function readPageOnce(pdf, page, estimate, pageClass) {
  const idx = page - 1;
  const dims = pdf.pageDimsPt(idx);
  const widthIn = dims.widthPt / 72;
  const heightIn = dims.heightPt / 72;
  const budget = readPage.budget;
  const locateDpi = fitDpi(widthIn, heightIn);
  const fullPng = pdf.renderPage(idx, locateDpi);
  const lines = [];

  if (!needsRegioning(dims)) {
    const { extraction } = await extractPage(page, fullPng, budget, { estimate });
    return extraction.lines;
  }

  const fullW = Math.round(widthIn * locateDpi);
  const fullH = Math.round(heightIn * locateDpi);
  let regions = [];
  try {
    const located =
      estimate && pageClass === "floor_plan"
        ? await locateRooms(fullPng, fullW, fullH, budget)
        : await locateRegions(fullPng, fullW, fullH, budget);
    regions = located.regions
      .filter((r) => EXTRACTABLE.includes(r.kind))
      .map((r) => ({
        kind: r.kind,
        rect: padRectToPage(
          mapBoxToPagePoints(r.box, { widthPx: fullW, heightPx: fullH }, dims),
          0.04,
          dims
        ),
      }))
      .filter(
        (r) => (r.rect.x1 - r.rect.x0) / 72 >= 1.5 && (r.rect.y1 - r.rect.y0) / 72 >= 1
      );
  } catch (e) {
    log.warn({ err: String(e) }, `region detect failed p${page}`);
  }
  if (regions.length === 0)
    regions = [{ kind: "other", rect: { x0: 0, y0: 0, x1: dims.widthPt, y1: dims.heightPt } }];

  // Estimation: read each region as ONE coherent image — a room must not be
  // fragmented across tiles, or the model can't lay out the whole run.
  if (estimate) {
    // Non-floor-plan sheets (kitchen elevation/millwork) often show the SAME
    // room as a plan + several wall elevations. Splitting into drawings makes
    // the model re-enumerate the room once per view -> 2-4x over-count. Read
    // the whole sheet ONCE so each cabinet is counted a single time.
    if (pageClass !== "floor_plan") {
      const { extraction } = await extractPage(page, fullPng, budget, {
        estimate: true,
      });
      return extraction.lines;
    }
    for (const r of regions) {
      const wIn = (r.rect.x1 - r.rect.x0) / 72;
      const hIn = (r.rect.y1 - r.rect.y0) / 72;
      const crop = pdf.renderRegion(idx, r.rect, fitDpi(wIn, hIn));
      try {
        const { extraction } = await extractPage(page, crop, budget, {
          region: true,
          estimate: true,
        });
        lines.push(...extraction.lines);
      } catch (e) {
        if (e instanceof BudgetExceededError) throw e;
        log.warn({ err: String(e) }, `estimate region failed p${page}`);
      }
    }
    return lines;
  }

  const jobs = regions.flatMap((r, i) => planRenderJobs(r.rect, dims, i, r.kind));
  log.info({ page, regions: regions.length, jobs: jobs.length }, "regioned page");

  const byRegion = new Map();
  for (const job of jobs) {
    const crop = pdf.renderRegion(idx, job.rect, job.dpi);
    try {
      const { extraction } = await extractPage(page, crop, budget, {
        region: true,
        estimate,
      });
      const bucket = byRegion.get(job.regionId) ?? [];
      bucket.push(...extraction.lines);
      byRegion.set(job.regionId, bucket);
    } catch (e) {
      if (e instanceof BudgetExceededError) throw e;
      log.warn({ err: String(e) }, `extract failed p${page} r${job.regionId}`);
    }
  }
  for (const rl of byRegion.values()) lines.push(...dedupeLines(rl));
  return lines;
}

const IMAGE_EXT = new Set([
  ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".heic",
]);

// Image inputs (a single render) aren't PDFs — convert to a temp PDF via macOS
// `sips` so openPdf can read them. PDFs pass through unchanged. Fails loudly:
// a missing file (e.g. a manifest path whose space is really a U+202F) or a
// sips conversion error throws a clear message instead of a cryptic ENOENT.
function toPdfPath(inputPath) {
  if (!IMAGE_EXT.has(extname(inputPath).toLowerCase())) return inputPath;
  if (!existsSync(inputPath))
    throw new Error(`input image not found (check the path exactly): ${inputPath}`);
  // Sanitized temp name — the source basename can carry spaces / odd unicode.
  const out = join(
    tmpdir(),
    `scribe-est-${Date.now()}-${Math.random().toString(36).slice(2)}.pdf`
  );
  let sipsErr = "";
  try {
    execSync(
      `sips -s format pdf ${JSON.stringify(inputPath)} --out ${JSON.stringify(out)}`,
      { stdio: ["ignore", "ignore", "pipe"] }
    );
  } catch (e) {
    sipsErr = String(e.stderr ?? e.message ?? e);
  }
  if (!existsSync(out))
    throw new Error(
      `sips could not convert image to PDF: ${inputPath}` +
        (sipsErr ? ` (${sipsErr.trim()})` : "")
    );
  return out;
}

// Run the REAL estimate pipeline on one input (PDF path/Buffer, or image path)
// and return structured results + LOW/MED/HIGH tier pricing. No console output —
// callers (CLI report, backtest.mjs) format it. The whole pipeline mirrors
// takeoff/process.ts via the shared helpers, so this tracks prod.
export async function estimatePdf(input) {
  const buf = Buffer.isBuffer(input) ? input : readFileSync(toPdfPath(input));
  const pdf = openPdf(buf);
  const budget = new TakeoffBudget();
  readPage.budget = budget;
  try {
    const thumbnails = [];
    for (let i = 0; i < pdf.pageCount; i++)
      thumbnails.push({ page: i + 1, png: pdf.renderPage(i, THUMBNAIL_DPI) });
    const classified = await classifyPages(thumbnails, budget);

    const estimationMode = !classified.some(
      (c) => c.class === "cabinet_schedule_table"
    );
    const relevantClasses = estimationMode
      ? [...RELEVANT_PAGE_CLASSES, "floor_plan"]
      : RELEVANT_PAGE_CLASSES;
    const relevant = classified.filter((c) => relevantClasses.includes(c.class));

    const lines = [];
    for (const p of relevant)
      lines.push(...(await readPage(pdf, p.page, estimationMode, p.class)));

    // Count each room ONCE via the SHARED page-role router (identical to prod's
    // process.ts): route to the authoritative role (schedule > floor plan >
    // elevation) instead of summing every page, then drop fillers/crown/returns
    // from box pricing. Subsumes the old per-mode collapse/dedupe.
    const roleByPage = new Map(
      relevant.map((r) => [r.page, pageClassToRole(r.class)])
    );
    const routed = routeByPageRole(lines, roleByPage);
    const counted = dropNonBoxCasework(routed.lines);
    console.error(
      `· page-role router: regime=${routed.regime} kept=${counted.length}` +
        ` droppedOtherRoles=${routed.droppedFromOtherRoles}` +
        ` collapsedWithinRole=${routed.collapsedWithinRole}` +
        ` nonBoxDropped=${routed.lines.length - counted.length}`
    );
    lines.length = 0;
    lines.push(...counted);
    // Expand into door/front faces in BOTH modes so the total mirrors a quote.
    lines.push(...lines.flatMap((l) => expandToComponents(l)));

    const { priceQuoteTiers, isCabinetBox } = await import("@scribe/pricing");
    const boxLines = lines.filter((l) => isCabinetBox(l.category));
    // Diagnostics: where do the boxes come from? (over-count = boxes piling up
    // across pages/rooms/views that are really the same cabinets.)
    const boxByPage = {};
    const boxByRoom = {};
    for (const l of boxLines) {
      boxByPage[l.source_page] = (boxByPage[l.source_page] ?? 0) + l.qty;
      const room = l.room ?? "?";
      boxByRoom[room] = (boxByRoom[room] ?? 0) + l.qty;
    }
    const tiers = priceQuoteTiers(
      lines.map((l) => ({
        category: l.category,
        width_in: l.width_in,
        height_in: l.height_in,
        depth_in: l.depth_in,
        qty: l.qty,
      }))
    );
    return {
      estimationMode,
      classified: classified.map((c) => ({ page: c.page, class: c.class })),
      lines,
      boxUnits: boxLines.reduce((a, l) => a + l.qty, 0),
      boxTypes: boxLines.length,
      boxByPage,
      boxByRoom,
      tokens: budget.used,
      tiers: {
        low: tiers.low.total_cents / 100,
        medium: tiers.medium.total_cents / 100,
        high: tiers.high.total_cents / 100,
      },
      tierBreakdown: tiers,
    };
  } finally {
    pdf.close();
  }
}

async function main() {
  const args = process.argv.slice(2);
  const asJson = args.includes("--json");
  const path = args.find((a) => !a.startsWith("--"));
  if (!path)
    throw new Error("usage: estimate-floorplan.mjs [--json] <plan.pdf|image>");

  const r = await estimatePdf(path);

  if (asJson) {
    process.stdout.write(
      JSON.stringify({
        input: path,
        estimationMode: r.estimationMode,
        boxUnits: r.boxUnits,
        boxTypes: r.boxTypes,
        tokens: r.tokens,
        tiers: r.tiers,
      }) + "\n"
    );
    return;
  }

  // Human report.
  console.error(
    "classified:",
    r.classified.map((c) => `${c.page}:${c.class}`).join(" ")
  );
  console.log(`\n===== ${r.lines.length} LINE ITEMS (tokens used: ${r.tokens}) =====`);
  console.log(`estimationMode=${r.estimationMode}`);
  console.log(`BOX COUNT: ${r.boxUnits} units across ${r.boxTypes} types`);
  console.log(`relevant pages read: ${r.classified.map((c) => `${c.page}:${c.class}`).join(" ")}`);
  console.log("boxes by source_page:", JSON.stringify(r.boxByPage));
  console.log("boxes by room:", JSON.stringify(r.boxByRoom));
  for (const t of ["low", "medium", "high"]) {
    const p = r.tierBreakdown[t];
    console.log(
      `  ${t.toUpperCase().padEnd(7)} boxes $${(p.box_cents / 100).toFixed(0)} + ` +
        `doors/fronts $${((p.door_cents + p.front_cents) / 100).toFixed(0)} + ` +
        `hw $${(p.hardware_cents / 100).toFixed(0)} = $${(p.total_cents / 100).toFixed(0)}`
    );
  }
  console.log("\n#  p | room | tag | qty | WxHxD | conf | notes");
  r.lines.forEach((l, i) =>
    console.log(
      `${String(i + 1).padStart(2)} p${l.source_page ?? "?"} | ${l.room ?? "?"} | ${l.tag ?? "—"} | x${l.qty} | ` +
        `${l.width_in ?? "?"}x${l.height_in ?? "?"}x${l.depth_in ?? "?"} | ${l.category} | ` +
        `${(l.confidence * 100).toFixed(0)}% | ${l.notes ?? ""}`
    )
  );
}

// Run as CLI only when invoked directly (not when imported by backtest.mjs).
if (process.argv[1] && process.argv[1].endsWith("estimate-floorplan.mjs")) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}

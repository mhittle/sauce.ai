#!/usr/bin/env node
// Ad-hoc local runner: drives the REAL takeoff estimation modules on a floor
// plan PDF (no DB / storage / Redis) so we can iterate the no-schedule
// estimation reading and diff against a known quote.
//
// Run from the apps/workers dir so @scribe/* resolve:
//   AIRTABLE unused; needs the vision key:
//   ANTHROPIC_API_KEY=sk-... node scripts/estimate-floorplan.mjs "/path/to/floorplan.pdf"

import { readFileSync } from "node:fs";
import {
  dedupeLines,
  expandToComponents,
  fitDpi,
  mapBoxToPagePoints,
  needsRegioning,
  padRectToPage,
  planRenderJobs,
  RELEVANT_PAGE_CLASSES,
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

async function readPage(pdf, page, estimate, pageClass) {
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

async function main() {
  const path = process.argv[2];
  if (!path) throw new Error("pass the floor-plan PDF path");
  const pdf = openPdf(readFileSync(path));
  const budget = new TakeoffBudget();
  readPage.budget = budget;
  try {
    const thumbnails = [];
    for (let i = 0; i < pdf.pageCount; i++)
      thumbnails.push({ page: i + 1, png: pdf.renderPage(i, THUMBNAIL_DPI) });
    const classified = await classifyPages(thumbnails, budget);
    console.error("classified:", classified.map((c) => `${c.page}:${c.class}`).join(" "));

    const estimationMode = !classified.some((c) => c.class === "cabinet_schedule_table");
    const relevantClasses = estimationMode
      ? [...RELEVANT_PAGE_CLASSES, "floor_plan"]
      : RELEVANT_PAGE_CLASSES;
    const relevant = classified.filter((c) => relevantClasses.includes(c.class));
    console.error(`estimationMode=${estimationMode} relevant pages=${relevant.map((r) => r.page)}`);

    const lines = [];
    for (const p of relevant)
      lines.push(...(await readPage(pdf, p.page, estimationMode, p.class)));

    if (!estimationMode) {
      // Labeled designs (cabinet A, B, C...) repeat the SAME cabinet on a plan
      // page AND its elevation pages; per-page extraction sums them. Dedup by tag
      // across ALL pages so each labeled cabinet counts once.
      const before = lines.length;
      const dd = dedupeLines(lines);
      lines.length = 0;
      lines.push(...dd);
      console.error(`· non-estimate cross-page dedup: ${before} -> ${lines.length} boxes`);
    }

    if (estimationMode) {
      // Collapse cross-view duplication: a room shown in a floor plan AND its
      // elevations gets enumerated once per view ("Kitchen" vs "Kitchen - North
      // Wall Run"); the region loop sums them. Per NORMALIZED room (strip the
      // "- <wall>" suffix), for each cabinet tag keep the MAX count seen in any
      // single view, not the sum — removes duplicates, preserves real repeats.
      const normRoom = (r) => (r ?? "").toLowerCase().split(/[-—–]/)[0].trim();
      const tagKey = (l) => (l.tag ?? l.category ?? "").toLowerCase().trim();
      const byRoom = new Map();
      for (const l of lines) {
        const k = normRoom(l.room);
        byRoom.set(k, [...(byRoom.get(k) ?? []), l]);
      }
      const collapsed = [];
      for (const roomLines of byRoom.values()) {
        const byView = new Map();
        for (const l of roomLines) {
          const v = (l.room ?? "").toLowerCase().trim();
          byView.set(v, [...(byView.get(v) ?? []), l]);
        }
        const bestPerTag = new Map();
        for (const viewLines of byView.values()) {
          const tagCount = new Map();
          for (const l of viewLines)
            tagCount.set(tagKey(l), [...(tagCount.get(tagKey(l)) ?? []), l]);
          for (const [t, ls] of tagCount)
            if ((bestPerTag.get(t)?.length ?? 0) < ls.length) bestPerTag.set(t, ls);
        }
        for (const ls of bestPerTag.values()) collapsed.push(...ls);
      }
      console.error(`· collapsed cross-view: ${lines.length} -> ${collapsed.length} boxes`);
      lines.length = 0;
      lines.push(...collapsed);
    }

    // Expand cabinets into door/front faces in BOTH modes so the total mirrors a
    // real CabinetNow quote (boxes + doors/fronts + hardware), not boxes alone.
    {
      const faces = lines.flatMap((l) => expandToComponents(l));
      lines.push(...faces);
    }

    // Report
    console.log(`\n===== ${lines.length} LINE ITEMS (tokens used: ${budget.used}) =====`);
    const byCat = {};
    for (const l of lines) byCat[l.category] = (byCat[l.category] ?? 0) + l.qty;
    console.log("by category:", byCat);

    const { priceQuoteTiers, isCabinetBox } = await import("@scribe/pricing");
    const boxLines = lines.filter((l) => isCabinetBox(l.category));
    const boxUnits = boxLines.reduce((a, l) => a + l.qty, 0);
    console.log(`\nBOX COUNT: ${boxUnits} units across ${boxLines.length} types (quote has 29 units / 24 types)`);
    const tiers = priceQuoteTiers(
      lines.map((l) => ({
        category: l.category,
        width_in: l.width_in,
        height_in: l.height_in,
        depth_in: l.depth_in,
        qty: l.qty,
      }))
    );
    console.log("===== FULL TIER PRICING (boxes + doors/fronts + hardware) vs $27,733.68 =====");
    for (const t of ["low", "medium", "high"]) {
      const p = tiers[t];
      const tot = p.total_cents / 100;
      const delta = ((tot - 27733.68) / 27733.68) * 100;
      console.log(
        `  ${t.toUpperCase().padEnd(7)} boxes $${(p.box_cents / 100).toFixed(0)} + ` +
          `doors/fronts $${((p.door_cents + p.front_cents) / 100).toFixed(0)} + ` +
          `hw $${(p.hardware_cents / 100).toFixed(0)} = $${tot.toFixed(0)} (${delta >= 0 ? "+" : ""}${delta.toFixed(0)}%)`
      );
    }
    console.log("\n#  room | tag | qty | WxHxD | conf | notes");
    lines.forEach((l, i) =>
      console.log(
        `${String(i + 1).padStart(2)} ${l.room ?? "?"} | ${l.tag ?? "—"} | x${l.qty} | ` +
          `${l.width_in ?? "?"}x${l.height_in ?? "?"}x${l.depth_in ?? "?"} | ${l.category} | ` +
          `${(l.confidence * 100).toFixed(0)}% | ${l.notes ?? ""}`
      )
    );
  } finally {
    pdf.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

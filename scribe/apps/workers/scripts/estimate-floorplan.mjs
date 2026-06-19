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
  fitDpi,
  mapBoxToPagePoints,
  needsRegioning,
  padRectToPage,
  planRenderJobs,
  RELEVANT_PAGE_CLASSES,
} from "@scribe/shared";
import { openPdf, THUMBNAIL_DPI } from "../dist/takeoff/pdf.js";
import { classifyPages } from "../dist/takeoff/classify.js";
import { locateRegions } from "../dist/takeoff/regions.js";
import { extractPage } from "../dist/takeoff/extract.js";
import { TakeoffBudget, BudgetExceededError } from "../dist/lib/anthropic.js";

const log = {
  info: (o, m) => console.error("·", m, o ? JSON.stringify(o) : ""),
  warn: (o, m) => console.error("!", m, o ? JSON.stringify(o) : ""),
};

const EXTRACTABLE = ["schedule", "elevation", "plan"];

async function readPage(pdf, page, estimate) {
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
    const located = await locateRegions(fullPng, fullW, fullH, budget);
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
    for (const p of relevant) lines.push(...(await readPage(pdf, p.page, estimationMode)));

    // Report
    console.log(`\n===== ${lines.length} LINE ITEMS (tokens used: ${budget.used}) =====`);
    const byCat = {};
    for (const l of lines) byCat[l.category] = (byCat[l.category] ?? 0) + l.qty;
    console.log("by category:", byCat);
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

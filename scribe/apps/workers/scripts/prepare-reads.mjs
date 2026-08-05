#!/usr/bin/env node
// Offline read-kit generator (zero API): run the deterministic steps of the
// estimate pipeline for ONE input and stop at every vision-call boundary,
// writing the EXACT image + prompt the pipeline would send as request files.
// The reads themselves happen on the owner's Claude plan (in-session or a
// local chat); replies are saved as responses/<id>.json and this script is
// re-run to advance to the next stage. Stages:
//   1. classify   (page thumbnails, batches of 8)
//   2. locate     (room segmentation for large-format floor plans)
//   3. extract    (the actual cabinet reads: full pages or room crops)
// When every extract response is present, run replay-reads.mjs to execute the
// downstream pipeline (parse → repair → router → dedupe → score).
//
// Mirrors estimate-floorplan.mjs / process.ts exactly — including passing
// `grounding` on the large-format estimate paths (prod behavior; the old
// harness omitted it there — the drift found in the pipeline exploration).
//
// Usage (from apps/workers):
//   node scripts/prepare-reads.mjs <plan.pdf|image> --kit <kitDir>
//   Env: DIM_SKELETON=1 / GROUND_READING=1 / ESTIMATE_PROMPT=precision as usual.

import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  readdirSync,
} from "node:fs";
import { execSync } from "node:child_process";
import { tmpdir } from "node:os";
import { extname, join } from "node:path";
import {
  buildDimGrounding,
  extractCabinetSchedule,
  fitDpi,
  MIN_SCHEDULE_ROWS,
  mapBoxToPagePoints,
  needsRegioning,
  PageClassification,
  parsePageRegionsLenient,
  padRectToPage,
  RELEVANT_PAGE_CLASSES,
} from "@scribe/shared";
import {
  CLASSIFY_SYSTEM,
  classifyUserText,
  ESTIMATE_DECOMPOSE_SUFFIX,
  ESTIMATE_PRECISION_SUFFIX,
  ESTIMATE_SYSTEM,
  estimateUserText,
  LOCATE_ROOMS_SYSTEM,
  locateRoomsUserText,
  SONNET_MODEL,
} from "@scribe/prompts";
import { openPdf, THUMBNAIL_DPI } from "../dist/takeoff/pdf.js";
import { z } from "zod";

const EXTRACTABLE = ["schedule", "elevation", "plan"];
const CLASSIFY_BATCH = 8;

const args = process.argv.slice(2);
const input = args.find((a) => !a.startsWith("--"));
const kitFlag = args.indexOf("--kit");
const kitDir = kitFlag >= 0 ? args[kitFlag + 1] : null;
if (!input || !kitDir) {
  console.error("usage: prepare-reads.mjs <plan.pdf|image> --kit <kitDir>");
  process.exit(1);
}

const IMAGE_EXT = new Set([".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".heic"]);
function toPdfPath(inputPath) {
  // Same image→PDF conversion as estimate-floorplan.mjs (macOS sips).
  if (!IMAGE_EXT.has(extname(inputPath).toLowerCase())) return inputPath;
  if (!existsSync(inputPath)) throw new Error(`input image not found: ${inputPath}`);
  const out = join(tmpdir(), `scribe-kit-${Date.now()}-${Math.random().toString(36).slice(2)}.pdf`);
  execSync(`sips -s format pdf ${JSON.stringify(inputPath)} --out ${JSON.stringify(out)}`, {
    stdio: ["ignore", "ignore", "pipe"],
  });
  if (!existsSync(out)) throw new Error(`sips could not convert image to PDF: ${inputPath}`);
  return out;
}

const REQ = join(kitDir, "requests");
const RES = join(kitDir, "responses");
const STEPS = join(kitDir, "steps");
for (const d of [kitDir, REQ, RES, STEPS]) mkdirSync(d, { recursive: true });

const responseOf = (id) => {
  const p = join(RES, `${id}.json`);
  return existsSync(p) ? JSON.parse(readFileSync(p, "utf8")) : null;
};

// The estimate system prompt, mirroring extract.ts (env captured at run time).
const ESTIMATE_SYSTEM_PROMPT =
  process.env.ESTIMATE_PROMPT === "precision"
    ? ESTIMATE_SYSTEM + ESTIMATE_PRECISION_SUFFIX
    : process.env.ESTIMATE_PROMPT === "decompose"
      ? ESTIMATE_SYSTEM + ESTIMATE_DECOMPOSE_SUFFIX
      : ESTIMATE_SYSTEM;

// Grounding policy — identical to the harness/prod gates.
function buildGrounding(pdf, idx) {
  if (process.env.DIM_SKELETON) return buildDimGrounding(pdf.pageTextFragments(idx));
  if (!process.env.GROUND_READING) return undefined;
  const fr = pdf.pageTextFragments(idx);
  const uniq = (a) => [...new Set(a)];
  const dims = uniq(fr.map((f) => f.text.trim()).filter((t) => /^\d{1,3}\s?\d?\/?\d?["”']?$/.test(t)));
  const labels = uniq(
    fr
      .map((f) => f.text.trim())
      .filter(
        (t) =>
          t.length >= 2 &&
          t.length <= 24 &&
          /(vanity|base|wall|tall|sink|drawer|pantry|linen|corner|oven|island|fridge)|[A-Za-z]{2,}\d{2,}/i.test(t)
      )
  );
  if (dims.length === 0 && labels.length === 0) return undefined;
  return (
    `PRINTED ON THIS SHEET (authoritative — size cabinets ONLY from these printed ` +
    `dimensions and identify them from these labels/codes; do NOT invent cabinets or ` +
    `dimensions not supported here; a run's cabinet widths should sum to its overall ` +
    `dimension):\nDIMENSIONS: ${dims.join(", ")}\nLABELS/CODES: ${labels.join(", ")}`
  );
}

function writeRequest(id, kind, system, userText, images, expected) {
  writeFileSync(
    join(REQ, `${id}.json`),
    JSON.stringify(
      {
        id,
        kind,
        model: SONNET_MODEL, // informational: what prod would call
        system,
        userText,
        images, // file names inside requests/, in order, shown BEFORE the text
        expectedResponse: expected,
        responseFile: `responses/${id}.json`,
      },
      null,
      2
    )
  );
}

const pdf = openPdf(readFileSync(toPdfPath(input)));
try {
  const pageDims = [];
  for (let i = 0; i < pdf.pageCount; i++) pageDims.push(pdf.pageDimsPt(i));

  // ---- Stage 0: text-layer schedule shortcut (vision-free) -----------------
  const scheduleInput = [];
  for (let i = 0; i < pdf.pageCount; i++)
    scheduleInput.push({ page: i + 1, fragments: pdf.pageTextFragments(i) });
  const sched = extractCabinetSchedule(scheduleInput);
  if (sched.lines.length >= MIN_SCHEDULE_ROWS) {
    writeFileSync(
      join(STEPS, "schedule.json"),
      JSON.stringify({ lines: sched.lines, schedulePages: sched.schedulePages }, null, 2)
    );
    writeFileSync(
      join(kitDir, "kit.json"),
      JSON.stringify(
        { input, pageCount: pdf.pageCount, status: "schedule-shortcut", pending: [] },
        null,
        2
      )
    );
    console.error(
      `Class-1 schedule shortcut fired (${sched.lines.length} lines) — no vision reads needed. Run replay-reads.mjs.`
    );
    process.exit(0);
  }

  // ---- Stage 1: classify ----------------------------------------------------
  const batches = [];
  for (let i = 0; i < pdf.pageCount; i += CLASSIFY_BATCH) {
    const pages = [];
    for (let p = i + 1; p <= Math.min(i + CLASSIFY_BATCH, pdf.pageCount); p++) pages.push(p);
    batches.push({ id: `classify-b${batches.length + 1}`, pages });
  }
  const pending = [];
  let classified = [];
  let classifyDone = true;
  for (const b of batches) {
    const res = responseOf(b.id);
    if (res == null) {
      classifyDone = false;
      const imgs = [];
      for (const p of b.pages) {
        const name = `${b.id}-p${p}.png`;
        const path = join(REQ, name);
        if (!existsSync(path)) writeFileSync(path, pdf.renderPage(p - 1, THUMBNAIL_DPI));
        imgs.push(name);
      }
      writeRequest(
        b.id,
        "classify",
        CLASSIFY_SYSTEM,
        classifyUserText(b.pages),
        imgs,
        `JSON array: [{"page":<n>,"class":"cover_index|floor_plan|kitchen_or_millwork_elevation|cabinet_schedule_table|finish_schedule|spec_text|other","confidence":0..1}, ...] — one entry per image, in order`
      );
      pending.push(b.id);
    } else {
      // Same order-trust correction as classify.ts.
      const parsed = z.array(PageClassification).parse(res);
      for (const [j, item] of parsed.entries()) {
        const expected = b.pages[j];
        classified.push(expected != null && item.page !== expected ? { ...item, page: expected } : item);
      }
    }
  }
  if (!classifyDone) {
    writeFileSync(
      join(kitDir, "kit.json"),
      JSON.stringify(
        { input, pageCount: pdf.pageCount, status: "awaiting-classify", pending },
        null,
        2
      )
    );
    console.error(`stage 1 (classify): ${pending.length} request(s) pending in ${REQ}`);
    process.exit(0);
  }
  writeFileSync(join(STEPS, "classified.json"), JSON.stringify(classified, null, 2));

  // ---- Relevant-page selection (mirrors harness) ---------------------------
  const estimationMode = !classified.some((c) => c.class === "cabinet_schedule_table");
  if (!estimationMode) {
    console.error(
      "kit supports estimate-mode documents only (a cabinet_schedule_table page was classified) — use the API harness for schedule-mode docs"
    );
    process.exit(1);
  }
  const relevantClasses = [...RELEVANT_PAGE_CLASSES, "floor_plan"];
  const relevant = classified.filter((c) => relevantClasses.includes(c.class));
  writeFileSync(join(STEPS, "relevant.json"), JSON.stringify(relevant, null, 2));

  // ---- Stages 2+3 per relevant page ----------------------------------------
  // NOTE (consensus): manual diagnosis is N=1 — one read per boundary — vs the
  // API baseline's N=3 median. Recorded in kit.json as a caveat.
  const regionRects = {}; // page -> [{kind, rect}]
  for (const rp of relevant) {
    const idx = rp.page - 1;
    const dims = pageDims[idx];
    const widthIn = dims.widthPt / 72;
    const heightIn = dims.heightPt / 72;
    const locateDpi = fitDpi(widthIn, heightIn);
    const grounding = buildGrounding(pdf, idx);

    const renderFull = () => pdf.renderPage(idx, locateDpi);

    if (!needsRegioning(dims)) {
      // Small page: one full-page estimate read.
      const id = `extract-p${rp.page}`;
      if (!responseOf(id)) {
        const name = `${id}.png`;
        if (!existsSync(join(REQ, name))) writeFileSync(join(REQ, name), renderFull());
        const base = estimateUserText(rp.page);
        writeRequest(
          id,
          "extract",
          ESTIMATE_SYSTEM_PROMPT,
          grounding ? `${base}\n\n${grounding}` : base,
          [name],
          `JSON: {"lines":[{source_page,tag,room,qty,category:"casework_base|casework_wall|casework_tall|vanity|door|drawer_front|filler|panel|other",width_in,height_in,depth_in,door_style,material,finish,assembled,notes,confidence}],"unit_multipliers":[],"uncertainties":[],"unreadable":false} — EVERY key required on every line (use null for unknown: door_style/material/finish/assembled are usually null); qty>0; confidence 0..1`
        );
        pending.push(id);
      }
      continue;
    }

    if (rp.class !== "floor_plan") {
      // Large non-floor-plan sheet (7b): prod reads the whole downscaled sheet
      // once, WITH grounding — kept faithful here (this is the illegible-DPI
      // path the diagnosis is designed to expose).
      const id = `extract-p${rp.page}`;
      if (!responseOf(id)) {
        const name = `${id}.png`;
        if (!existsSync(join(REQ, name))) writeFileSync(join(REQ, name), renderFull());
        const base = estimateUserText(rp.page);
        writeRequest(
          id,
          "extract",
          ESTIMATE_SYSTEM_PROMPT,
          grounding ? `${base}\n\n${grounding}` : base,
          [name],
          `JSON: {"lines":[{source_page,tag,room,qty,category:"casework_base|casework_wall|casework_tall|vanity|door|drawer_front|filler|panel|other",width_in,height_in,depth_in,door_style,material,finish,assembled,notes,confidence}],"unit_multipliers":[],"uncertainties":[],"unreadable":false} — EVERY key required on every line (use null for unknown: door_style/material/finish/assembled are usually null); qty>0; confidence 0..1`
        );
        pending.push(id);
      }
      continue;
    }

    // Large floor plan: locate rooms first, then per-room crop extracts.
    const locId = `locate-p${rp.page}`;
    const fullW = Math.round(widthIn * locateDpi);
    const fullH = Math.round(heightIn * locateDpi);
    const locRes = responseOf(locId);
    if (locRes == null) {
      const name = `${locId}.png`;
      if (!existsSync(join(REQ, name))) writeFileSync(join(REQ, name), renderFull());
      writeRequest(
        locId,
        "locate",
        LOCATE_ROOMS_SYSTEM,
        locateRoomsUserText(fullW, fullH),
        [name],
        `JSON: {"regions":[{"kind":"schedule|elevation|plan|other","box":[x0,y0,x1,y1] (pixels in the shown image),"confidence":0..1,"label":...}]}`
      );
      pending.push(locId);
      continue;
    }
    let regions = parsePageRegionsLenient(locRes)
      .regions.filter((r) => EXTRACTABLE.includes(r.kind))
      .map((r) => ({
        kind: r.kind,
        rect: padRectToPage(
          mapBoxToPagePoints(r.box, { widthPx: fullW, heightPx: fullH }, dims),
          0.04,
          dims
        ),
      }))
      .filter((r) => (r.rect.x1 - r.rect.x0) / 72 >= 1.5 && (r.rect.y1 - r.rect.y0) / 72 >= 1);
    if (regions.length === 0)
      regions = [{ kind: "other", rect: { x0: 0, y0: 0, x1: dims.widthPt, y1: dims.heightPt } }];
    regionRects[rp.page] = regions;

    regions.forEach((r, i) => {
      const id = `extract-p${rp.page}-r${i + 1}`;
      if (responseOf(id)) return;
      const wIn = (r.rect.x1 - r.rect.x0) / 72;
      const hIn = (r.rect.y1 - r.rect.y0) / 72;
      const name = `${id}.png`;
      if (!existsSync(join(REQ, name)))
        writeFileSync(join(REQ, name), pdf.renderRegion(idx, r.rect, fitDpi(wIn, hIn)));
      const base = estimateUserText(rp.page);
      writeRequest(
        id,
        "extract",
        ESTIMATE_SYSTEM_PROMPT,
        grounding ? `${base}\n\n${grounding}` : base,
        [name],
        `JSON: {"lines":[{source_page,tag,room,qty,category:"casework_base|casework_wall|casework_tall|vanity|door|drawer_front|filler|panel|other",width_in,height_in,depth_in,door_style,material,finish,assembled,notes,confidence}],"unit_multipliers":[],"uncertainties":[],"unreadable":false} — EVERY key required on every line (use null for unknown: door_style/material/finish/assembled are usually null); qty>0; confidence 0..1`
      );
      pending.push(id);
    });
  }
  writeFileSync(join(STEPS, "regions.json"), JSON.stringify(regionRects, null, 2));

  const status = pending.length === 0 ? "ready-to-replay" : "awaiting-reads";
  writeFileSync(
    join(kitDir, "kit.json"),
    JSON.stringify(
      {
        input,
        pageCount: pdf.pageCount,
        estimationMode,
        consensusNote: "manual reads are N=1 (API baseline used N=3 median)",
        env: {
          DIM_SKELETON: process.env.DIM_SKELETON ?? null,
          GROUND_READING: process.env.GROUND_READING ?? null,
          ESTIMATE_PROMPT: process.env.ESTIMATE_PROMPT ?? null,
        },
        status,
        pending,
      },
      null,
      2
    )
  );
  console.error(
    pending.length === 0
      ? `kit complete — all reads present. Run replay-reads.mjs --kit ${kitDir}`
      : `${pending.length} read(s) pending in ${REQ}: ${pending.join(", ")}`
  );
} finally {
  pdf.close();
}

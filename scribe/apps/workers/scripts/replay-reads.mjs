#!/usr/bin/env node
// Offline replay (zero API): consume a read kit's saved model responses and run
// the REAL downstream pipeline — the identical post-processing a live API read
// gets (processExtractionResponse: lenient parse → salvage → repair → unit
// multipliers → estimate marking), then the page-role router and non-box drop —
// and score against labels.json with the full per-unit alignment dump.
//
// Per-step artifacts land in <kit>/steps/: classified.json, relevant.json,
// regions.json (from prepare), pre-router.json, router.json, final.json,
// score.json. These are the step-attribution evidence.
//
// Usage (from apps/workers):
//   node scripts/replay-reads.mjs --kit <kitDir> [--labels <labels.json>] [--quote <n>]

import { existsSync, readFileSync, writeFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import {
  dropNonBoxCasework,
  pageClassToRole,
  routeByPageRole,
  scoreReadingDetailed,
} from "@scribe/shared";
import { processExtractionResponse } from "../dist/takeoff/extract.js";

const args = process.argv.slice(2);
const flag = (n, d) => {
  const i = args.indexOf(n);
  return i >= 0 ? args[i + 1] : d;
};
const kitDir = flag("--kit", null);
if (!kitDir) {
  console.error("usage: replay-reads.mjs --kit <kitDir> [--labels labels.json] [--quote n]");
  process.exit(1);
}
const HOME = process.env.HOME;
const labelsPath = flag("--labels", join(HOME, "Desktop/Scribe Testing/labels.json"));
const quoteId = flag("--quote", null);

const RES = join(kitDir, "responses");
const REQ = join(kitDir, "requests");
const STEPS = join(kitDir, "steps");
const kit = JSON.parse(readFileSync(join(kitDir, "kit.json"), "utf8"));

// ---- Class-1 shortcut kits: lines came from the text layer -----------------
let finalLines;
let preRouter = null;
let routerInfo = null;
if (kit.status === "schedule-shortcut") {
  const sched = JSON.parse(readFileSync(join(STEPS, "schedule.json"), "utf8"));
  finalLines = dropNonBoxCasework(sched.lines);
  routerInfo = { regime: "schedule-shortcut" };
} else {
  if (kit.status !== "ready-to-replay") {
    console.error(
      `kit status is "${kit.status}" — run prepare-reads.mjs and provide the pending responses first`
    );
    process.exit(1);
  }
  const classified = JSON.parse(readFileSync(join(STEPS, "classified.json"), "utf8"));
  const relevant = JSON.parse(readFileSync(join(STEPS, "relevant.json"), "utf8"));

  // Reassemble per-page lines from the extract responses through the REAL
  // response processor (identical to a live read).
  const lines = [];
  const perCall = [];
  for (const f of readdirSync(RES).sort()) {
    const m = f.match(/^extract-p(\d+)(?:-r(\d+))?\.json$/);
    if (!m) continue;
    const page = Number(m[1]);
    const isRegion = m[2] != null;
    const raw = readFileSync(join(RES, f), "utf8");
    // Accept either a raw JSON reply or a {"text": "..."} wrapper (verbatim
    // chat output). processExtractionResponse handles fenced/loose JSON text.
    let text = raw;
    try {
      const asObj = JSON.parse(raw);
      if (asObj && typeof asObj === "object" && typeof asObj.text === "string") text = asObj.text;
    } catch {
      // raw is not JSON at all — pass through, salvage will do its best
    }
    const { extraction } = processExtractionResponse(text, page, {
      estimate: true,
      region: isRegion,
    });
    perCall.push({ call: f.replace(/\.json$/, ""), page, lines: extraction.lines.length });
    lines.push(...extraction.lines);
  }

  const roleByPage = new Map(relevant.map((r) => [r.page, pageClassToRole(r.class)]));
  preRouter = lines.map((l) => ({
    page: l.source_page,
    role: roleByPage.get(l.source_page) ?? "other",
    tag: l.tag,
    room: l.room,
    category: l.category,
    w: l.width_in,
    h: l.height_in,
    qty: l.qty,
  }));
  writeFileSync(
    join(STEPS, "pre-router.json"),
    JSON.stringify({ perCall, totalLines: lines.length, lines: preRouter }, null, 2)
  );

  const routed = routeByPageRole(lines, roleByPage);
  const counted = dropNonBoxCasework(routed.lines);
  // The router doesn't return the dropped lines — reconstruct by identity.
  const keptSet = new Set(routed.lines);
  const droppedLines = lines.filter((l) => !keptSet.has(l));
  routerInfo = {
    regime: routed.regime,
    kept: counted.length,
    droppedFromOtherRoles: routed.droppedFromOtherRoles,
    collapsedWithinRole: routed.collapsedWithinRole,
    nonBoxDropped: routed.lines.length - counted.length,
    dropped: droppedLines.map((l) => ({
      page: l.source_page,
      role: roleByPage.get(l.source_page) ?? "other",
      tag: l.tag,
      room: l.room,
      category: l.category,
      w: l.width_in,
      h: l.height_in,
      qty: l.qty,
    })),
  };
  writeFileSync(join(STEPS, "router.json"), JSON.stringify(routerInfo, null, 2));
  finalLines = counted;
}

writeFileSync(
  join(STEPS, "final.json"),
  JSON.stringify(
    finalLines.map((l) => ({
      page: l.source_page,
      tag: l.tag,
      room: l.room,
      category: l.category,
      w: l.width_in,
      h: l.height_in,
      d: l.depth_in,
      qty: l.qty,
      confidence: l.confidence,
    })),
    null,
    2
  )
);

// ---- Score vs labels -------------------------------------------------------
const labels = JSON.parse(readFileSync(labelsPath, "utf8"));
const quote = quoteId
  ? labels.find((r) => String(r.quote) === String(quoteId))
  : labels.find((r) => kit.input.includes(`Quote ${r.quote}/`));
if (!quote || !quote.cabinets?.length) {
  console.error(
    quoteId
      ? `no labels for quote ${quoteId} in ${labelsPath}`
      : `could not infer quote from kit input "${kit.input}" — pass --quote <n>`
  );
  process.exit(1);
}

const predicted = finalLines.map((l) => ({
  category: l.category,
  w: l.width_in,
  h: l.height_in,
  qty: l.qty,
  // Fold page+room into the tag so the alignment dump identifies each unit.
  tag: `${l.tag ?? "—"} [p${l.source_page ?? "?"}${l.room ? " " + l.room : ""}]`,
}));
const gold = quote.cabinets.map((c) => ({ ...c, tag: c.tag }));
const { alignment, ...score } = scoreReadingDetailed(predicted, gold);
writeFileSync(
  join(STEPS, "score.json"),
  JSON.stringify({ quote: quote.quote, deal: quote.deal, score, alignment }, null, 2)
);

const pct = (n) => (n * 100).toFixed(0);
console.error(
  `Q${quote.quote} ${quote.deal}: recall ${pct(score.recall)}% precision ${pct(score.precision)}% ` +
    `F1 ${score.f1.toFixed(2)} (${score.predictedBoxes} pred vs ${score.labelBoxes} real, ` +
    `countErr ${score.countErrorPct.toFixed(0)}%, sizeErr ${score.meanSizeErrorIn.toFixed(1)}")`
);
if (routerInfo?.droppedFromOtherRoles)
  console.error(
    `router: regime=${routerInfo.regime} droppedOtherRoles=${routerInfo.droppedFromOtherRoles} collapsed=${routerInfo.collapsedWithinRole}`
  );
const misses = alignment.gold.filter((g) => !g.matchedPred).length;
const phantoms = alignment.pred.filter((p) => !p.matched).length;
console.error(
  `alignment: ${misses} MISSed gold units, ${phantoms} PHANTOM predictions, ` +
    `${alignment.droppedPred.nullOrZeroDims} pred dropped for null dims → ${join(STEPS, "score.json")}`
);

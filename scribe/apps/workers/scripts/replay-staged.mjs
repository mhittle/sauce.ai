#!/usr/bin/env node
// Offline STAGED replay (zero API): consume a staged kit's saved responses and
// run the REAL downstream logic — parseMeasureResponse + mergeMeasuredLines
// (the identical post-processing a live staged run gets) — then drop non-box
// casework and score against labels.json.
//
// Usage (from apps/workers):
//   node scripts/replay-staged.mjs --kit <kitDir> [--labels <labels.json>] [--quote <n>]

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { dropNonBoxCasework, scoreReadingDetailed } from "@scribe/shared";
import {
  mergeMeasuredLines,
  parseMeasureResponse,
} from "../dist/takeoff/detect.js";

const args = process.argv.slice(2);
const flag = (n, d) => {
  const i = args.indexOf(n);
  return i >= 0 ? args[i + 1] : d;
};
const kitDir = flag("--kit", null);
if (!kitDir) {
  console.error(
    "usage: replay-staged.mjs --kit <kitDir> [--labels labels.json] [--quote n]"
  );
  process.exit(1);
}
const labelsPath = flag(
  "--labels",
  join(process.env.HOME, "Desktop/Scribe Testing/labels.json")
);
const quoteId = flag("--quote", null);

const RES = join(kitDir, "responses");
const STEPS = join(kitDir, "steps");
const kit = JSON.parse(readFileSync(join(kitDir, "kit.json"), "utf8"));
if (kit.status !== "ready-to-replay") {
  console.error(
    `kit status is "${kit.status}" — run prepare-staged.mjs and provide the pending responses first`
  );
  process.exit(1);
}

const { entries } = JSON.parse(readFileSync(join(STEPS, "markers.json"), "utf8"));

const responsePath = join(RES, "measure.json");
if (!existsSync(responsePath)) {
  console.error("responses/measure.json missing");
  process.exit(1);
}
const raw = readFileSync(responsePath, "utf8");
let text = raw;
try {
  const parsed = JSON.parse(raw);
  if (typeof parsed?.text === "string") text = parsed.text;
} catch {
  // raw text response
}

const { cabinets, warnings: parseWarnings } = parseMeasureResponse(text);
const { lines: merged, warnings: mergeWarnings } = mergeMeasuredLines(
  entries,
  cabinets
);
const warnings = [...parseWarnings, ...mergeWarnings];
const finalLines = dropNonBoxCasework(merged);
writeFileSync(
  join(STEPS, "final.json"),
  JSON.stringify(
    {
      warnings,
      cabinets: cabinets.length,
      merged: merged.length,
      nonBoxDropped: merged.length - finalLines.length,
      lines: finalLines,
    },
    null,
    2
  )
);
for (const w of warnings) console.error(`warning: ${w}`);

// ---- Score vs labels (same shape as replay-reads.mjs) -----------------------
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
  tag: `${l.tag ?? "—"} [p${l.source_page ?? "?"}]`,
}));
const gold = quote.cabinets.map((c) => ({ ...c, tag: c.tag }));
const { alignment, ...score } = scoreReadingDetailed(predicted, gold);
writeFileSync(
  join(STEPS, "score.json"),
  JSON.stringify({ quote: quote.quote, deal: quote.deal, score, alignment }, null, 2)
);

const pct = (n) => (n * 100).toFixed(0);
console.error(
  `Q${quote.quote} ${quote.deal} [STAGED]: recall ${pct(score.recall)}% precision ${pct(score.precision)}% ` +
    `F1 ${score.f1.toFixed(2)} (${score.predictedBoxes} pred vs ${score.labelBoxes} real, ` +
    `countErr ${score.countErrorPct.toFixed(0)}%, sizeErr ${score.meanSizeErrorIn.toFixed(1)}")`
);
const misses = alignment.gold.filter((g) => !g.matchedPred).length;
const phantoms = alignment.pred.filter((p) => !p.matched).length;
console.error(
  `alignment: ${misses} MISSed gold units, ${phantoms} PHANTOM predictions → ${join(STEPS, "score.json")}`
);

#!/usr/bin/env node
// Reading-accuracy scorer (H2): run the pipeline on each drawing and score its
// predicted cabinets against the per-line ground truth in labels.json — reporting
// RECALL / PRECISION / count-error / size-error instead of the lossy $-total.
//
// Usage (from apps/workers, env loaded):
//   node scripts/score-reading.mjs [labels.json] [--concurrency N] [--out csv]
//   ESTIMATE_CONSENSUS_N=1 for a fast/cheap first pass; 3 (default) for stable.

import { spawn } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, isAbsolute } from "node:path";
import { scoreReading } from "@scribe/shared";

const HERE = dirname(fileURLToPath(import.meta.url));
const HARNESS = join(HERE, "estimate-floorplan.mjs");
const HOME = process.env.HOME;
const flag = (n, d) => {
  const i = process.argv.indexOf(n);
  return i >= 0 ? process.argv[i + 1] : d;
};
const labelsPath =
  process.argv[2] && !process.argv[2].startsWith("--")
    ? process.argv[2]
    : join(HOME, "Desktop/Scribe Testing/labels.json");
const baseDir = dirname(labelsPath);
const manifest = JSON.parse(readFileSync(join(baseDir, "backtest-quotes.json"), "utf8"));
const inputOf = Object.fromEntries(manifest.map((q) => [String(q.quote), q.input]));
const concurrency = Math.max(1, Number(flag("--concurrency", "4")));
const outPath = flag("--out", join(baseDir, "reading-scorecard.csv"));

// Coarse document class per quote (from the input-format survey).
const CLASS = {
  1: "scan", 2: "image", 3: "labeled", 5: "labeled", 6: "arch", 7: "labeled",
  8: "sparse", 9: "labeled", 10: "image", 11: "image/sketch", 13: "arch",
  14: "labeled", 20: "sparse", 21: "labeled", 22: "arch", 23: "arch", 24: "labeled",
};

const labels = JSON.parse(readFileSync(labelsPath, "utf8")).filter(
  (r) => r.cabinets && r.cabinets.length > 0
);

function runOne(rel) {
  return new Promise((resolve) => {
    const input = isAbsolute(rel) ? rel : join(baseDir, rel);
    const child = spawn("node", [HARNESS, "--json", input], { env: process.env });
    let out = "", err = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    child.on("close", (code) => {
      if (code !== 0) return resolve({ error: err.trim().split("\n").pop() || `exit ${code}` });
      try {
        resolve(JSON.parse(out.trim().split("\n").filter(Boolean).pop()));
      } catch (e) {
        resolve({ error: `parse: ${String(e)}` });
      }
    });
  });
}

async function mapLimit(items, limit, fn) {
  const out = new Array(items.length);
  let next = 0;
  const worker = async () => {
    while (next < items.length) {
      const i = next++;
      out[i] = await fn(items[i]);
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return out;
}

const pct = (n) => (n * 100).toFixed(0);
console.error(
  `scoring ${labels.length} quotes, concurrency ${concurrency}, consensus N=${process.env.ESTIMATE_CONSENSUS_N ?? "3"}`
);

const rows = await mapLimit(labels, concurrency, async (r) => {
  const rel = inputOf[String(r.quote)];
  const res = await runOne(rel);
  if (res.error) {
    console.error(`  Q${r.quote} ${r.deal}: ERROR ${res.error}`);
    return { quote: r.quote, deal: r.deal, cls: CLASS[r.quote] ?? "?", error: res.error };
  }
  const s = scoreReading(res.boxes ?? [], r.cabinets);
  console.error(
    `  Q${r.quote} ${r.deal}: recall ${pct(s.recall)}% precision ${pct(s.precision)}% ` +
      `(${s.predictedBoxes} pred vs ${s.labelBoxes} real)`
  );
  return { quote: r.quote, deal: r.deal, cls: CLASS[r.quote] ?? "?", ...s };
});

const HEADER = "Quote,Deal,Class,LabelBoxes,PredBoxes,Recall%,Precision%,F1,CountErr%,SizeErrIn,Error";
const line = (r) =>
  r.error
    ? `${r.quote},${r.deal},${r.cls},,,,,,,,${JSON.stringify(r.error)}`
    : `${r.quote},${r.deal},${r.cls},${r.labelBoxes},${r.predictedBoxes},${pct(r.recall)},${pct(r.precision)},${r.f1.toFixed(2)},${r.countErrorPct.toFixed(0)},${r.meanSizeErrorIn.toFixed(1)},`;
writeFileSync(outPath, HEADER + "\n" + rows.map(line).join("\n") + "\n");

const scored = rows.filter((r) => !r.error);
const mean = (f) => (scored.reduce((a, r) => a + f(r), 0) / scored.length);
console.error(`\n=== READING SCORECARD (${scored.length} scored) → ${outPath} ===`);
console.error(
  `OVERALL  recall ${pct(mean((r) => r.recall))}%  precision ${pct(mean((r) => r.precision))}%  ` +
    `F1 ${mean((r) => r.f1).toFixed(2)}  |countErr| ${mean((r) => Math.abs(r.countErrorPct)).toFixed(0)}%  ` +
    `sizeErr ${mean((r) => r.meanSizeErrorIn).toFixed(1)}in`
);
const byClass = {};
for (const r of scored) (byClass[r.cls] ??= []).push(r);
for (const [cls, rs] of Object.entries(byClass)) {
  const m = (f) => (rs.reduce((a, r) => a + f(r), 0) / rs.length);
  console.error(
    `  ${cls.padEnd(12)} n=${rs.length}  recall ${pct(m((r) => r.recall))}%  precision ${pct(m((r) => r.precision))}%  F1 ${m((r) => r.f1).toFixed(2)}`
  );
}

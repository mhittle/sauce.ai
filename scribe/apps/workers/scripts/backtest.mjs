#!/usr/bin/env node
// Backtest the no-schedule estimator against labeled real quotes and write a CSV.
//
// Spawns the estimate harness once per quote (each in its own process, so the
// per-run token budget and module state never collide), with bounded
// concurrency. For each quote it computes LOW/MED/HIGH generated totals, their
// % difference vs the real quote total, the closest tier, and a within-±10% flag.
// There is NO ~10-min wall limit here (that was only an artifact of Claude Code's
// background-shell sandbox) — run as many quotes as you like, as long as needed.
//
// Usage:
//   ANTHROPIC_API_KEY=sk-... node scripts/backtest.mjs <manifest.json> \
//     [--concurrency N] [--out results.csv]
//   ESTIMATE_CONSENSUS_N=3 (default) tunes the median-of-N read consensus.
//
// Manifest (JSON array), paths absolute or relative to the manifest's directory:
//   [{ "quote": "1", "deal": "Stephens", "input": "Quote 1/plan.pdf", "real": 36158.31 }, ...]
// See backtest-quotes.example.json.

import { spawn } from "node:child_process";
import { readFileSync, writeFileSync, appendFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, isAbsolute } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const HARNESS = join(HERE, "estimate-floorplan.mjs");

function flag(name, def) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : def;
}

const manifestArg = process.argv[2];
if (!manifestArg || manifestArg.startsWith("--")) {
  console.error(
    "usage: node scripts/backtest.mjs <manifest.json> [--concurrency N] [--out results.csv]"
  );
  process.exit(2);
}
const manifestPath = isAbsolute(manifestArg)
  ? manifestArg
  : join(process.cwd(), manifestArg);
const manifestDir = dirname(manifestPath);
const concurrency = Math.max(1, Number(flag("--concurrency", "3")));
const outPath = flag("--out", join(process.cwd(), "backtest-results.csv"));

const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const resolveInput = (p) => (isAbsolute(p) ? p : join(manifestDir, p));

function runOne(q) {
  return new Promise((resolve) => {
    const child = spawn("node", [HARNESS, "--json", resolveInput(q.input)], {
      env: process.env,
    });
    let out = "";
    let err = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    child.on("close", (code) => {
      if (code !== 0) {
        resolve({ ...q, error: err.trim().split("\n").pop() || `exit ${code}` });
        return;
      }
      try {
        const last = out.trim().split("\n").filter(Boolean).pop();
        resolve({ ...q, ...JSON.parse(last) });
      } catch (e) {
        resolve({ ...q, error: `parse: ${String(e)}` });
      }
    });
  });
}

// Run fn over items with at most `limit` in flight; preserves input order.
async function mapLimit(items, limit, fn) {
  const out = new Array(items.length);
  let next = 0;
  async function worker() {
    while (next < items.length) {
      const i = next++;
      out[i] = await fn(items[i]);
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, worker)
  );
  return out;
}

const pct = (gen, real) => ((gen - real) / real) * 100;
const f1 = (n) => (n == null || Number.isNaN(n) ? "" : n.toFixed(1));
// CSV-escape a field (deal names / error messages can contain commas/quotes).
const csvCell = (x) => {
  const s = String(x);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};
const csvLine = (a) => a.map(csvCell).join(",");

const HEADER = [
  "Quote", "Deal", "RealQuoteTotal", "Boxes",
  "GenLOW", "LOW_diff_%", "GenMED", "MED_diff_%", "GenHIGH", "HIGH_diff_%",
  "BestTier", "Best_diff_%", "Within_10%", "Error",
];

// Build a CSV row + score for one finished quote. Best tier = the LOW/MED/HIGH
// total closest to the real quote.
function score(r) {
  if (r.error || !r.tiers)
    return {
      row: [r.quote, r.deal, r.real ?? "", "", "", "", "", "", "", "", "", "", "", r.error ?? "no result"],
      scored: false,
    };
  const tiers = [["LOW", r.tiers.low], ["MED", r.tiers.medium], ["HIGH", r.tiers.high]];
  let best = tiers[0];
  let bestPct = pct(best[1], r.real);
  for (const t of tiers) {
    const p = pct(t[1], r.real);
    if (Math.abs(p) < Math.abs(bestPct)) {
      best = t;
      bestPct = p;
    }
  }
  const within = Math.abs(bestPct) <= 10;
  return {
    row: [
      r.quote, r.deal, r.real, r.boxUnits,
      Math.round(r.tiers.low), f1(pct(r.tiers.low, r.real)),
      Math.round(r.tiers.medium), f1(pct(r.tiers.medium, r.real)),
      Math.round(r.tiers.high), f1(pct(r.tiers.high, r.real)),
      best[0], f1(bestPct), within ? "YES" : "no", "",
    ],
    scored: true,
    within,
    absErr: Math.abs(bestPct),
    bestPct,
  };
}

// Write the header now and append each row as its quote finishes, so a long or
// interrupted run still leaves a valid partial CSV. (Rows land in completion
// order; the Quote column identifies them.)
writeFileSync(outPath, csvLine(HEADER) + "\n");
console.error(
  `backtest: ${manifest.length} quotes, concurrency ${concurrency}, ` +
    `consensus N=${process.env.ESTIMATE_CONSENSUS_N ?? "3 (default)"} → ${outPath}`
);

let hits = 0;
let sumAbs = 0;
let scored = 0;
const t0 = Date.now();
await mapLimit(manifest, concurrency, async (q) => {
  console.error(`· Q${q.quote} ${q.deal}: running…`);
  const r = await runOne(q);
  const s = score(r);
  appendFileSync(outPath, csvLine(s.row) + "\n");
  if (s.scored) {
    scored++;
    sumAbs += s.absErr;
    if (s.within) hits++;
  }
  console.error(
    r.error
      ? `  Q${q.quote} ERROR: ${r.error}`
      : `  Q${q.quote}: ${r.boxUnits} boxes, best ${f1(s.bestPct)}% ${s.within ? "✓" : ""}`
  );
  return r;
});

console.error(
  `\ndone: ${outPath}\nwithin ±10%: ${hits}/${scored} | ` +
    `mean abs err (best tier): ${scored ? (sumAbs / scored).toFixed(1) : "?"}% | ` +
    `${((Date.now() - t0) / 1000).toFixed(0)}s`
);

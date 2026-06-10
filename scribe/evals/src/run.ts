import { readdir, readFile, stat } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import { CabinetLineItem } from "@scribe/shared";
import { aggregate, scoreSet } from "./metrics.js";

// Eval runner (PRD §10): evals/plansets/<name>/{gold.json, predicted.json}.
// Reports per-set and aggregate recall/precision/field accuracy; fails on a
// > 2-point recall or precision regression vs the committed baseline.json.

const REGRESSION_POINTS = 2;

const Lines = z.array(CabinetLineItem);

async function main(): Promise<void> {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..");
  const plansetsDir = join(root, "plansets");

  const entries = await readdir(plansetsDir);
  const sets = [];
  for (const entry of entries.sort()) {
    const dir = join(plansetsDir, entry);
    if (!(await stat(dir)).isDirectory()) continue;
    const gold = Lines.parse(
      JSON.parse(await readFile(join(dir, "gold.json"), "utf8"))
    );
    const predicted = Lines.parse(
      JSON.parse(await readFile(join(dir, "predicted.json"), "utf8"))
    );
    sets.push(scoreSet(entry, gold, predicted));
  }

  if (sets.length === 0) {
    console.log("no eval fixtures found under evals/plansets/");
    return;
  }

  const agg = aggregate(sets);
  const pct = (x: number) => (x * 100).toFixed(1);

  console.log("\nScribe extraction eval");
  console.log("=".repeat(78));
  for (const s of agg.sets) {
    console.log(
      `${s.name.padEnd(32)} recall ${pct(s.recall)}%  precision ${pct(s.precision)}%  qty ${pct(s.qty_accuracy)}%  dims ${pct(s.dim_accuracy)}%  (${s.matched}/${s.gold_lines})`
    );
  }
  console.log("-".repeat(78));
  console.log(
    `${"AGGREGATE".padEnd(32)} recall ${pct(agg.recall)}%  precision ${pct(agg.precision)}%  qty ${pct(agg.qty_accuracy)}%  dims ${pct(agg.dim_accuracy)}%`
  );

  let baseline: { recall: number; precision: number } | null = null;
  try {
    baseline = JSON.parse(await readFile(join(root, "baseline.json"), "utf8"));
  } catch {
    console.log("\nno baseline.json — skipping regression gate");
  }

  if (baseline) {
    const recallDrop = (baseline.recall - agg.recall) * 100;
    const precisionDrop = (baseline.precision - agg.precision) * 100;
    if (recallDrop > REGRESSION_POINTS || precisionDrop > REGRESSION_POINTS) {
      console.error(
        `\nFAIL: regression vs baseline (recall ${recallDrop.toFixed(1)}pts, precision ${precisionDrop.toFixed(1)}pts)`
      );
      process.exit(1);
    }
    console.log(
      `\nOK vs baseline (recall ${baseline.recall}, precision ${baseline.precision})`
    );
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

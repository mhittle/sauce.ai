#!/usr/bin/env node
// Ad-hoc exploration of the CabinetNow "Material Master 2021" door/drawer price
// book in Airtable. Fetches ALL rows, then computes the percentile-based
// low/mid/high $/ft² tiers (PRD §6.4 pricing work — see
// research/plan-reading-and-crawler-spike.md / pricing memory).
//
// This is a throwaway analysis script, NOT wired into the pipeline yet.
//
// Run:  AIRTABLE_PAT=pat... node scribe/scripts/airtable-pricing-explore.mjs
// (token is read from the env so it never lives in the repo)

const PAT = process.env.AIRTABLE_PAT;
const BASE = process.env.AIRTABLE_BASE ?? "appBoHee0bMpXB0WK";
const TABLE = process.env.AIRTABLE_TABLE ?? "tbluXLOeUHLPiRtA3"; // Material Master 2021

if (!PAT) {
  console.error("Set AIRTABLE_PAT in the environment. Aborting.");
  process.exit(1);
}

// Door/front categories we care about for low/mid/high (boxes are priced
// elsewhere — doors-only for now per the plan).
const DOOR_CATEGORIES = ["cabinet door", "solid", "5-piece", "routed"];

async function fetchAll() {
  const rows = [];
  let offset;
  let page = 0;
  do {
    const url = new URL(`https://api.airtable.com/v0/${BASE}/${TABLE}`);
    url.searchParams.set("pageSize", "100");
    if (offset) url.searchParams.set("offset", offset);
    const res = await fetch(url, { headers: { Authorization: `Bearer ${PAT}` } });
    if (!res.ok) throw new Error(`Airtable ${res.status}: ${await res.text()}`);
    const data = await res.json();
    for (const r of data.records) rows.push(r.fields);
    offset = data.offset;
    page++;
  } while (offset && page < 200);
  return rows;
}

function percentile(sorted, p) {
  if (sorted.length === 0) return NaN;
  const k = ((sorted.length - 1) * p) / 100;
  const f = Math.floor(k);
  return f + 1 >= sorted.length
    ? sorted[f]
    : sorted[f] + (sorted[f + 1] - sorted[f]) * (k - f);
}

const money = (n) => `$${n.toFixed(2)}`;

function priceList(rows, predicate) {
  return rows
    .filter((f) => predicate(f) && typeof f.Price === "number" && f.Price > 0)
    .map((f) => f.Price)
    .sort((a, b) => a - b);
}

function nearest(rows, predicate, target) {
  let best = null;
  for (const f of rows) {
    if (!predicate(f) || typeof f.Price !== "number" || f.Price <= 0) continue;
    if (!best || Math.abs(f.Price - target) < Math.abs(best.Price - target)) best = f;
  }
  return best;
}

function main(rows) {
  console.log(`\nTotal rows fetched: ${rows.length}\n`);

  // Per-category distribution + percentile tiers.
  console.log("=== $/ft² distribution by category (Price = Base Cost × Mult + Tackons) ===");
  for (const cat of DOOR_CATEGORIES) {
    const ps = priceList(rows, (f) => f.Category === cat);
    if (ps.length === 0) continue;
    console.log(
      `[${cat.padEnd(12)}] n=${String(ps.length).padStart(4)}  ` +
        `min=${money(ps[0])}  p25=${money(percentile(ps, 25))}  ` +
        `p50=${money(percentile(ps, 50))}  p75=${money(percentile(ps, 75))}  ` +
        `p90=${money(percentile(ps, 90))}  max=${money(ps[ps.length - 1])}`
    );
  }

  // Proposed low/mid/high tiers (percentiles of the catalog) for doors + fronts.
  console.log("\n=== Proposed LOW / MID / HIGH tiers ($/ft²) ===");
  for (const [label, cat] of [
    ["Doors (cabinet door)", "cabinet door"],
    ["Drawer fronts (solid)", "solid"],
  ]) {
    const ps = priceList(rows, (f) => f.Category === cat);
    console.log(
      `${label.padEnd(24)}  LOW(p25)=${money(percentile(ps, 25))}  ` +
        `MID(p50)=${money(percentile(ps, 50))}  HIGH(p90)=${money(percentile(ps, 90))}`
    );
  }

  // What style/material sits at each percentile for cabinet doors.
  console.log("\n=== cabinet door: representative style / material near each percentile ===");
  const cdPrices = priceList(rows, (f) => f.Category === "cabinet door");
  for (const [label, p] of [["p10", 10], ["p25", 25], ["p50", 50], ["p75", 75], ["p90", 90]]) {
    const t = percentile(cdPrices, p);
    const n = nearest(rows, (f) => f.Category === "cabinet door", t);
    console.log(
      `  ${label}  ${money(t).padStart(8)}/ft²  ~ ${n.Style} / ${n["Material/Color"]} (${n.Finish})`
    );
  }

  // Finish mix (unfinished vs laminate vs MDF) — finish is a separate $/ft² lever.
  const finishes = {};
  for (const f of rows) {
    if (f.Category !== "cabinet door") continue;
    finishes[f.Finish] = (finishes[f.Finish] ?? 0) + 1;
  }
  console.log("\ncabinet-door finishes:", finishes);

  // Anchored reference: the Aries 3/4 family the quote used, by material.
  console.log("\n=== Aries 3/4 cabinet door by material (anchored-tier reference) ===");
  rows
    .filter((f) => f.Style === "Aries 3/4" && f.Category === "cabinet door" && typeof f.Price === "number")
    .sort((a, b) => a.Price - b.Price)
    .forEach((f) => console.log(`   ${money(f.Price).padStart(8)}  ${f["Material/Color"]}`));
}

fetchAll()
  .then(main)
  .catch((e) => {
    console.error(e);
    process.exit(1);
  });

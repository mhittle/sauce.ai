#!/usr/bin/env node
// Build per-line GROUND-TRUTH labels from the real CabinetNow quote packets
// (the "answer key" in each Quote N folder), for the reading-accuracy eval (H2).
//
// The packets are CabinetNow's own structured quotes: an R1C1-format cabinet
// schedule (tag / name / W / H / D / config, grouped by wall) plus a priced
// list (boxes / doors & fronts / hardware / subtotal). We parse the schedule
// with the SAME shared extractor prod uses (extractCabinetSchedule), so labels
// track the production reader's notion of a "cabinet line".
//
// Usage:  node scripts/extract-labels.mjs [manifest.json] [--out labels.json]
// Deterministic — no vision / no API. Writes labels next to the manifest.

import { readFileSync, writeFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { openPdf } from "../dist/takeoff/pdf.js";
import { extractCabinetSchedule } from "@scribe/shared";

const HOME = process.env.HOME;
const manifestPath =
  process.argv[2] && !process.argv[2].startsWith("--")
    ? process.argv[2]
    : path.join(HOME, "Desktop/Scribe Testing/backtest-quotes.json");
const outFlag = process.argv.indexOf("--out");
const baseDir = path.dirname(manifestPath);
const outPath =
  outFlag >= 0 ? process.argv[outFlag + 1] : path.join(baseDir, "labels.json");

const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));

// Some folders name the answer key oddly, or the "quote"-named file is a Scribe
// output rather than a CabinetNow packet. Pin those explicitly.
const PACKET_OVERRIDE = {
  24: "Stephen Jennings - Dean Vanity.pdf", // CabinetNow packet, not quote*.pdf
};

// Find the CabinetNow quote packet in a folder (not the drawing input).
function findPacket(folder, inputName) {
  const files = readdirSync(folder).filter(
    (f) => f !== inputName && f.toLowerCase().endsWith(".pdf")
  );
  // Prefer a file with "quote" or "packet" in the name; fall back to any PDF.
  return (
    files.find((f) => /quote|packet/i.test(f)) ??
    files.find((f) => !/_input_converted/.test(f)) ??
    null
  );
}

const MONEY = (re, text) => {
  const m = re.exec(text);
  return m ? Math.round(parseFloat(m[1].replace(/,/g, "")) * 100) : null;
};

// Pull the priced totals from the packet's flattened text (best-effort).
function parseTotals(text) {
  return {
    subtotal_cents:
      MONEY(/sub\s*total[^$]*\$\s*([\d,]+\.\d{2})/i, text) ??
      MONEY(/total cost of project[^$]*\$\s*([\d,]+\.\d{2})/i, text),
    boxes_cents: MONEY(/cabinet boxes[^$]*\$\s*([\d,]+\.\d{2})/i, text),
    doors_fronts_cents: MONEY(/doors?\s*(?:and|&)?\s*(?:drawer )?fronts[^$]*\$\s*([\d,]+\.\d{2})/i, text),
  };
}

const results = [];
let ok = 0;
for (const q of manifest) {
  const folder = path.join(baseDir, "Quote " + q.quote);
  const inputName = path.basename(q.input);
  const packet = PACKET_OVERRIDE[q.quote] ?? findPacket(folder, inputName);
  if (!packet) {
    results.push({ quote: q.quote, deal: q.deal, packet: null, cabinets: [], gap: "no packet in folder" });
    continue;
  }
  try {
    const pdf = openPdf(readFileSync(path.join(folder, packet)));
    const pages = [];
    let allText = "";
    for (let i = 0; i < pdf.pageCount; i++) {
      const fr = pdf.pageTextFragments(i);
      pages.push({ page: i + 1, fragments: fr });
      allText += fr.map((f) => f.text).join(" ") + "\n";
    }
    const sched = extractCabinetSchedule(pages);
    pdf.close();
    const cabinets = sched.lines.map((l) => ({
      tag: l.tag,
      category: l.category,
      w: l.width_in,
      h: l.height_in,
      d: l.depth_in,
      qty: l.qty,
      raw: (l.notes ?? "").replace(/^schedule:\s*/, ""),
    }));
    if (cabinets.length > 0) ok++;
    results.push({
      quote: q.quote,
      deal: q.deal,
      packet,
      real_total: q.real ?? null,
      schedule_pages: sched.schedulePages,
      cabinets,
      totals: parseTotals(allText),
      gap: cabinets.length === 0 ? "parsed 0 cabinets (format variant — inspect)" : undefined,
    });
  } catch (e) {
    results.push({ quote: q.quote, deal: q.deal, packet, cabinets: [], gap: `ERR ${String(e).slice(0, 60)}` });
  }
}

writeFileSync(outPath, JSON.stringify(results, null, 2));

// Report.
console.log(`labeled ${ok}/${manifest.length} quotes → ${outPath}\n`);
console.log("Q    deal           cabinets  subtotal   gap");
for (const r of results) {
  const sub = r.totals?.subtotal_cents ? "$" + (r.totals.subtotal_cents / 100).toFixed(0) : "—";
  console.log(
    `${String(r.quote).padEnd(4)} ${String(r.deal).slice(0, 13).padEnd(14)} ${String(r.cabinets.length).padStart(6)}   ${sub.padStart(8)}   ${r.gap ?? ""}`
  );
}
const totalCabs = results.reduce((a, r) => a + r.cabinets.length, 0);
console.log(`\ntotal labeled cabinets: ${totalCabs}`);

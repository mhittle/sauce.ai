#!/usr/bin/env node
// Door / drawer-front count eval (SCR-015). For every staged kit:
//  1. re-run the area scan (DETECT_SYSTEM, live API — costs money; answers are
//     cached under responses-faces/<detectPromptVersion>/ so reruns are free)
//     on each ELEVATION crop, which now also returns doors / drawers;
//  2. attach those counts to the kit's existing markers (matched by box IoU
//     against the kit's cached scan of the same crop), replay the kit's cached
//     measure answer through the real mergeMeasuredLines;
//  3. score faces per matched cabinet against the gold cabinet's CabinetNow
//     name ("Wall Pair Door", "Base 3 Drawers", …): counted (new) vs the
//     name heuristics (today).
//
//   ANTHROPIC_API_KEY=… node scripts/face-eval.mjs <staged-kits dir> [--labels labels.json] [--offline]
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import Anthropic from "@anthropic-ai/sdk";
import { DETECT_PROMPT_VERSION, DETECT_SYSTEM, SONNET_MODEL } from "@scribe/prompts";
import { DetectionItem, dropNonBoxCasework, expandToComponents, scoreReadingDetailed } from "@scribe/shared";
import { extractJson } from "../dist/lib/anthropic.js";
import { mergeMeasuredLines, parseMeasureResponse } from "../dist/takeoff/detect.js";

const args = process.argv.slice(2);
const dir = args[0];
const flag = (n, d) => (args.indexOf(n) >= 0 ? args[args.indexOf(n) + 1] : d);
const labels = JSON.parse(readFileSync(flag("--labels", join(dir, "..", "labels.json")), "utf8"));
const offline = args.includes("--offline");
const MODEL = process.env.VISION_MODEL || SONNET_MODEL;
const client = offline ? null : new Anthropic();

// ---- gold faces from the CabinetNow cabinet name (null = name doesn't say) --
export function faceGold(name, category) {
  const n = ` ${name.toLowerCase().replace(/\s+/g, " ")} `;
  const num = (re) => {
    const m = n.match(re);
    return m ? Number(m[1]) : null;
  };
  let drawers = num(/\b(\d+)\s*(?:drawers?|drw)\b/);
  if (drawers == null && /\bsingle drawer\b|\bdrawer over\b|\bover drawer\b/.test(n)) drawers = 1;
  const anyDrawer = /drawer|drw\b/.test(n);
  let doors = num(/\b(\d+)\s*doors?\b/) ?? num(/\b(\d+)\s*dr\b/);
  if (doors == null) {
    if (/pair door|full height doors|double door|door over door/.test(n)) doors = 2;
    else if (/single door\b|full height door\b|door only|\bdrawer over door\b/.test(n)) doors = 1;
    else if (anyDrawer && !/door/.test(n)) doors = 0;
  }
  if (drawers == null && !anyDrawer) {
    if (category === "casework_wall" || /full height door|door only|door over door|\bwall\b|\bupper\b/.test(n)) drawers = 0;
  }
  return { doors, drawers };
}

const iou = (a, b) => {
  const x0 = Math.max(a[0], b[0]), y0 = Math.max(a[1], b[1]);
  const x1 = Math.min(a[2], b[2]), y1 = Math.min(a[3], b[3]);
  const inter = Math.max(0, x1 - x0) * Math.max(0, y1 - y0);
  const area = (r) => Math.max(0, r[2] - r[0]) * Math.max(0, r[3] - r[1]);
  return inter / (area(a) + area(b) - inter || 1);
};
const itemsOf = (raw) => {
  try {
    const j = typeof raw === "string" ? extractJson(raw) : raw;
    return (j?.items ?? []).map((x) => DetectionItem.parse(x));
  } catch {
    return [];
  }
};
const faces = (line) => {
  const f = expandToComponents(line);
  const per = (k) => f.filter((x) => x.category === k).reduce((s, x) => s + x.qty, 0) / (line.qty || 1);
  return { doors: per("door"), drawers: per("drawer_front") };
};

async function scan(req, reqDir) {
  const content = [
    ...req.images.map((p) => ({
      type: "image",
      source: { type: "base64", media_type: "image/png", data: readFileSync(join(reqDir, p)).toString("base64") },
    })),
    { type: "text", text: req.userText },
  ];
  for (let i = 0; ; i++) {
    try {
      const m = await client.messages.create({ model: MODEL, max_tokens: 8000, temperature: 0, system: DETECT_SYSTEM, messages: [{ role: "user", content }] });
      return { text: m.content.filter((b) => b.type === "text").map((b) => b.text).join("\n"), usage: m.usage };
    } catch (err) {
      if (i < 4 && (err.status === 429 || err.status >= 500)) {
        await new Promise((r) => setTimeout(r, 3000 * (i + 1)));
        continue;
      }
      throw err;
    }
  }
}

const tally = { doors: { n: 0, old: 0, new: 0, counted: 0 }, drawers: { n: 0, old: 0, new: 0, counted: 0 } };
// Unambiguous pairs only: the size-only matcher can swap two real cabinets of
// the same type and near-equal size, which scores a face count against the
// wrong cabinet. A pair counts here only when no OTHER real cabinet of that
// category lies within 3" (w+h) of it.
const clean = { doors: { n: 0, old: 0, new: 0 }, drawers: { n: 0, old: 0, new: 0 } };
const rows = [];
let spendIn = 0, spendOut = 0;
for (const kitName of readdirSync(dir).filter((d) => /^q\d+$/.test(d)).sort((a, b) => +a.slice(1) - +b.slice(1))) {
  const kitDir = join(dir, kitName);
  const kit = JSON.parse(readFileSync(join(kitDir, "kit.json"), "utf8"));
  const steps = join(kitDir, "steps");
  if (!existsSync(join(steps, "markers.json")) || !existsSync(join(kitDir, "responses/measure.json"))) continue;
  const quote = labels.find((r) => kit.input.includes(`Quote ${r.quote}/`));
  if (!quote) continue;
  const elevationPages = new Set(
    (Array.isArray(kit.pages) ? kit.pages : []).filter((p) => !/plan/.test(p.class ?? "")).map((p) => p.page)
  );
  const { entries } = JSON.parse(readFileSync(join(steps, "markers.json"), "utf8"));
  const detections = JSON.parse(readFileSync(join(steps, "detections.json"), "utf8"));
  const reqDir = join(kitDir, "requests");
  const outDir = join(kitDir, "responses-faces", DETECT_PROMPT_VERSION);
  mkdirSync(outDir, { recursive: true });

  // detections[] are the kit's crops in request order (per page, r0, r1, …).
  const perPageIdx = new Map();
  let counted = 0;
  for (const det of detections) {
    const r = perPageIdx.get(det.page) ?? 0;
    perPageIdx.set(det.page, r + 1);
    if (det.kind === "plan" || !elevationPages.has(det.page)) continue;
    const id = `detect-p${det.page}-r${r}`;
    const reqPath = join(reqDir, `${id}.json`);
    if (!existsSync(reqPath)) continue;
    const cachePath = join(outDir, `${id}.json`);
    let answer;
    if (existsSync(cachePath)) answer = JSON.parse(readFileSync(cachePath, "utf8"));
    else if (offline) continue;
    else {
      answer = await scan(JSON.parse(readFileSync(reqPath, "utf8")), reqDir);
      writeFileSync(cachePath, JSON.stringify(answer, null, 1));
    }
    spendIn += answer.usage?.input_tokens ?? 0;
    spendOut += answer.usage?.output_tokens ?? 0;
    const fresh = itemsOf(answer.text);
    const cached = itemsOf(JSON.parse(readFileSync(join(kitDir, "responses", `${id}.json`), "utf8")));
    const used = new Set();
    cached.forEach((c, i) => {
      if (!c.bbox_2d) return;
      let best = -1, bestIou = 0.3;
      fresh.forEach((f, j) => {
        if (used.has(j) || !f.bbox_2d) return;
        const v = iou(c.bbox_2d, f.bbox_2d);
        if (v > bestIou) [best, bestIou] = [j, v];
      });
      if (best < 0) return;
      used.add(best);
      const disp = JSON.stringify(det.items[i]?.bbox_2d ?? null);
      const marker = entries.find((e) => e.page === det.page && JSON.stringify(e.displayBbox ?? null) === disp);
      if (marker && (fresh[best].doors != null || fresh[best].drawers != null)) {
        marker.doors = fresh[best].doors;
        marker.drawers = fresh[best].drawers;
        counted++;
      }
    });
  }

  let text = readFileSync(join(kitDir, "responses/measure.json"), "utf8");
  try {
    const p = JSON.parse(text);
    if (typeof p?.text === "string") text = p.text;
  } catch {}
  const { cabinets } = parseMeasureResponse(text);
  const lines = dropNonBoxCasework(mergeMeasuredLines(entries, cabinets).lines);
  const predicted = lines.map((l, i) => ({ category: l.category, w: l.width_in, h: l.height_in, qty: l.qty, tag: `#${i}` }));
  const { alignment } = scoreReadingDetailed(predicted, quote.cabinets);
  let kd = 0, kdOld = 0, kdNew = 0, kr = 0, krOld = 0, krNew = 0;
  for (const g of alignment.gold) {
    if (!g.matchedPred) continue;
    const line = lines[Number(g.matchedPred.tag.slice(1))];
    const gold = faceGold(g.unit.tag ?? "", g.unit.category);
    const now = faces(line);
    const old = faces({ ...line, doors: null, drawers: null });
    const wasCounted = line.doors != null || line.drawers != null;
    const ambiguous = alignment.gold.some(
      (o) => o !== g && o.unit.category === g.unit.category && Math.abs(o.unit.w - g.unit.w) + Math.abs(o.unit.h - g.unit.h) <= 3 && o.unit.tag !== g.unit.tag
    );
    if (!ambiguous && wasCounted) {
      for (const k of ["doors", "drawers"]) {
        if (gold[k] == null) continue;
        clean[k].n++;
        if (old[k] === gold[k]) clean[k].old++;
        if (now[k] === gold[k]) clean[k].new++;
      }
    }
    if (process.env.FACE_DEBUG && wasCounted)
      console.log(`  ${kitName} gold "${g.unit.tag}" ${g.unit.w}x${g.unit.h} → pred "${line.tag}" ${line.width_in}x${line.height_in} | gold d${gold.doors}/r${gold.drawers} old d${old.doors}/r${old.drawers} new d${now.doors}/r${now.drawers}`);
    if (gold.doors != null) {
      tally.doors.n++; kd++;
      if (old.doors === gold.doors) { tally.doors.old++; kdOld++; }
      if (now.doors === gold.doors) { tally.doors.new++; kdNew++; }
      if (wasCounted) tally.doors.counted++;
    }
    if (gold.drawers != null) {
      tally.drawers.n++; kr++;
      if (old.drawers === gold.drawers) { tally.drawers.old++; krOld++; }
      if (now.drawers === gold.drawers) { tally.drawers.new++; krNew++; }
      if (wasCounted) tally.drawers.counted++;
    }
  }
  rows.push({ kit: kitName, markersCounted: counted, doorPairs: kd, doorsOld: kdOld, doorsNew: kdNew, drawerPairs: kr, drawersOld: krOld, drawersNew: krNew });
  console.log(`${kitName.padEnd(4)} counted ${String(counted).padStart(3)} markers | doors ${kdOld}→${kdNew}/${kd} | drawers ${krOld}→${krNew}/${kr}`);
}
const pct = (a, b) => (b ? `${Math.round((100 * a) / b)}%` : "—");
console.log("\nexact match on matched cabinets whose name states the count (old = name heuristics, new = counted on the drawing):");
for (const k of ["doors", "drawers"]) {
  const t = tally[k];
  console.log(`  ${k.padEnd(8)} old ${pct(t.old, t.n)}  new ${pct(t.new, t.n)}  (n=${t.n}; ${t.counted} had a count from the scan)`);
}
console.log("\nunambiguous pairs that got a count from the scan (no other same-type real cabinet within 3\"):");
for (const k of ["doors", "drawers"]) {
  const t = clean[k];
  console.log(`  ${k.padEnd(8)} old ${pct(t.old, t.n)}  new ${pct(t.new, t.n)}  (n=${t.n})`);
}
console.log(`scan tokens: ${spendIn} in / ${spendOut} out ≈ $${((spendIn * 3 + spendOut * 15) / 1e6).toFixed(2)} (Sonnet list)`);
writeFileSync(join(dir, `face-eval-${DETECT_PROMPT_VERSION}.json`), JSON.stringify({ tally, clean, rows }, null, 2));

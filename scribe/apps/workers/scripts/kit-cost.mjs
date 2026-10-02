// Cost of the staged test kits WITHOUT generating anything: every stored
// request (locate / detect / measure) is re-counted with the free
// count_tokens endpoint, classify is re-built from the source PDF exactly as
// prepareTakeoff does (72-DPI thumbnails, batches of 8), and output tokens
// are the stored answers re-tokenized (a floor: prose around the JSON is not
// stored). Prices are the 0017 model_rates seed.
//
//   node scripts/kit-cost.mjs <staged-kits dir> [out.csv]
import { readFileSync, readdirSync, existsSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import Anthropic from "@anthropic-ai/sdk";
import { CLASSIFY_SYSTEM, classifyUserText, SONNET_MODEL } from "@scribe/prompts";
import { openPdf, PICKER_THUMBNAIL_DPI } from "../dist/takeoff/pdf.js";

const RATES = { "claude-sonnet-4-6": [300, 1500] }; // cents per MTok in/out
const dir = process.argv[2];
const out = process.argv[3];
const client = new Anthropic();

const img = (buf) => ({
  type: "image",
  source: { type: "base64", media_type: "image/png", data: Buffer.from(buf).toString("base64") },
});

async function count(model, system, content) {
  for (let i = 0; ; i++) {
    try {
      const r = await client.messages.countTokens({ model, system, messages: [{ role: "user", content }] });
      return r.input_tokens;
    } catch (err) {
      if (i < 5 && (err.status === 429 || err.status >= 500)) {
        await new Promise((r) => setTimeout(r, 2000 * (i + 1)));
        continue;
      }
      throw err;
    }
  }
}

// Output tokens: the stored answer as a bare user message, minus the
// per-message overhead of an empty one.
let overhead = null;
async function outTokens(model, text) {
  overhead ??= await count(model, undefined, "x");
  return Math.max(0, (await count(model, undefined, text)) - overhead);
}

const micro = (model, i, o) => i * RATES[model][0] + o * RATES[model][1];
const rows = [];
for (const kit of readdirSync(dir).filter((d) => /^q\d+$/.test(d)).sort((a, b) => +a.slice(1) - +b.slice(1))) {
  const k = JSON.parse(readFileSync(join(dir, kit, "kit.json"), "utf-8"));
  const stage = { classify: [0, 0, 0], locate: [0, 0, 0], detect: [0, 0, 0], measure: [0, 0, 0] };
  let pdfPages = 1;
  if (k.input.toLowerCase().endsWith(".pdf") && existsSync(k.input)) {
    const pdf = openPdf(readFileSync(k.input));
    pdfPages = pdf.pageCount;
    const thumbs = [];
    for (let i = 0; i < pdf.pageCount; i++) thumbs.push({ page: i + 1, png: pdf.renderPage(i, PICKER_THUMBNAIL_DPI) });
    pdf.close();
    for (let i = 0; i < thumbs.length; i += 8) {
      const batch = thumbs.slice(i, i + 8);
      const inTok = await count(SONNET_MODEL, CLASSIFY_SYSTEM, [
        ...batch.map((t) => img(t.png)),
        { type: "text", text: classifyUserText(batch.map((t) => t.page)) },
      ]);
      // Classification answers are ~60 tokens a page.
      const outTok = 60 * batch.length;
      stage.classify[0] += inTok;
      stage.classify[1] += outTok;
      stage.classify[2] += micro(SONNET_MODEL, inTok, outTok);
    }
  }
  const reqDir = join(dir, kit, "requests");
  for (const f of readdirSync(reqDir).filter((f) => f.endsWith(".json"))) {
    const r = JSON.parse(readFileSync(join(reqDir, f), "utf-8"));
    if (!stage[r.kind]) continue;
    const inTok = await count(r.model, r.system, [
      ...r.images.map((p) => img(readFileSync(join(reqDir, p)))),
      { type: "text", text: r.userText },
    ]);
    const respPath = join(dir, kit, r.responseFile);
    const outTok = existsSync(respPath) ? await outTokens(r.model, readFileSync(respPath, "utf-8")) : 0;
    stage[r.kind][0] += inTok;
    stage[r.kind][1] += outTok;
    stage[r.kind][2] += micro(r.model, inTok, outTok);
  }
  const selected = Array.isArray(k.pages) && k.pages.length > 0 ? k.pages.length : 1;
  const kinds = Array.isArray(k.pages) ? k.pages.map((p) => p.class).join("+") : "";
  // Prod today: classify + human-drawn areas (detect) + measure. locate is
  // the kit's stand-in for the human's areas and is reported, not summed.
  const job = stage.classify[2] + stage.detect[2] + stage.measure[2];
  const row = {
    kit, pdfPages, selected, kinds,
    classify: stage.classify[2], locate: stage.locate[2], detect: stage.detect[2], measure: stage.measure[2],
    inTok: stage.classify[0] + stage.detect[0] + stage.measure[0],
    outTok: stage.classify[1] + stage.detect[1] + stage.measure[1],
    job, perPage: Math.round(job / selected),
  };
  rows.push(row);
  console.log(
    `${kit.padEnd(4)} pdf=${String(pdfPages).padStart(3)} sel=${selected} ${kinds.padEnd(28)} ` +
      `job=$${(job / 1e8).toFixed(4)} /page=$${(row.perPage / 1e8).toFixed(4)} ` +
      `[classify ${(row.classify / 1e8).toFixed(4)} detect ${(row.detect / 1e8).toFixed(4)} measure ${(row.measure / 1e8).toFixed(4)} locate ${(row.locate / 1e8).toFixed(4)}]`
  );
}
if (out) {
  const cols = Object.keys(rows[0]);
  writeFileSync(out, [cols.join(","), ...rows.map((r) => cols.map((c) => r[c]).join(","))].join("\n") + "\n");
}

#!/usr/bin/env node
// API read-runner for read kits: answer a kit's pending requests by calling
// the real vision model with the exact image+prompt prepare-reads.mjs wrote —
// same call shape as prod extract.ts (Sonnet, temperature 0, 32k max_tokens,
// streaming, socket retry). Responses land as responses/<id>.json ({"text": …},
// the wrapper replay-reads.mjs already accepts), so the workflow is:
//
//   prepare-reads.mjs <input> --kit <kit>   # writes requests, lists pending
//   run-reads.mjs --kit <kit>               # answers pending via the API
//   prepare-reads.mjs <input> --kit <kit>   # advances stage / marks ready
//   … repeat until ready-to-replay, then replay-reads.mjs
//
// Prompt-change A/Bs (ESTIMATE_PROMPT / DIM_SKELETON) only alter the EXTRACT
// stage, so classify/locate responses can be copied between arm kits and only
// the extract reads paid for fresh.
//
// Usage (from apps/workers, key via env or --env-file):
//   node scripts/run-reads.mjs --kit <kitDir> [--concurrency 3]

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import {
  getAnthropic,
  imageBlock,
  textOf,
  withSocketRetry,
} from "../dist/lib/anthropic.js";

const args = process.argv.slice(2);
const flag = (n, d) => {
  const i = args.indexOf(n);
  return i >= 0 ? args[i + 1] : d;
};
const kitDir = flag("--kit", null);
const concurrency = Number(flag("--concurrency", "3"));
if (!kitDir) {
  console.error("usage: run-reads.mjs --kit <kitDir> [--concurrency n]");
  process.exit(1);
}

const REQ = join(kitDir, "requests");
const RES = join(kitDir, "responses");
const kit = JSON.parse(readFileSync(join(kitDir, "kit.json"), "utf8"));
const pending = (kit.pending ?? []).filter(
  (id) => !existsSync(join(RES, `${id}.json`))
);
if (pending.length === 0) {
  console.error("no pending reads — re-run prepare-reads.mjs to advance the kit");
  process.exit(0);
}

const client = getAnthropic();
const usage = { input_tokens: 0, output_tokens: 0 };

async function answer(id) {
  const req = JSON.parse(readFileSync(join(REQ, `${id}.json`), "utf8"));
  const content = req.images.map((name) =>
    imageBlock(readFileSync(join(REQ, name)))
  );
  content.push({ type: "text", text: req.userText });
  const message = await withSocketRetry(() =>
    client.messages
      .stream({
        model: req.model,
        max_tokens: 32000,
        ...(req.model.startsWith("claude-opus-4-8") ? {} : { temperature: 0 }),
        system: req.system,
        messages: [{ role: "user", content }],
      })
      .finalMessage()
  );
  usage.input_tokens += message.usage.input_tokens;
  usage.output_tokens += message.usage.output_tokens;
  writeFileSync(
    join(RES, `${id}.json`),
    JSON.stringify({
      text: textOf(message),
      model: message.model,
      stop_reason: message.stop_reason,
      usage: message.usage,
    })
  );
  console.error(
    `  ${id}: ${message.usage.input_tokens} in / ${message.usage.output_tokens} out` +
      (message.stop_reason === "max_tokens" ? " (TRUNCATED)" : "")
  );
}

const queue = [...pending];
const workers = Array.from({ length: Math.min(concurrency, queue.length) }, async () => {
  while (queue.length > 0) await answer(queue.shift());
});
await Promise.all(workers);
console.error(
  `${pending.length} read(s) answered — ${usage.input_tokens} input + ${usage.output_tokens} output tokens`
);

import Anthropic from "@anthropic-ai/sdk";
import { sql } from "drizzle-orm";
import { getDb, tokenSpend } from "@scribe/db";

let client: Anthropic | null = null;

export function getAnthropic(): Anthropic {
  if (!client) {
    if (!process.env.ANTHROPIC_API_KEY) {
      throw new Error("ANTHROPIC_API_KEY is not set");
    }
    client = new Anthropic();
  }
  return client;
}

export class BudgetExceededError extends Error {}

// Transient network faults that should be retried, not failed. Big multi-page
// docs occasionally drop a vision call mid-flight (`UND_ERR_SOCKET` /
// `ECONNRESET` / fetch "terminated"), which used to fail a whole takeoff (and a
// whole backtest quote). Retry a few times with backoff; non-transient errors
// (4xx, JSON, budget) propagate immediately.
const TRANSIENT_RE =
  /UND_ERR_SOCKET|ECONNRESET|ETIMEDOUT|EPIPE|ECONNREFUSED|ENOTFOUND|EAI_AGAIN|socket hang up|terminated|network|fetch failed|aborted|529|overloaded/i;

function isTransient(err: unknown): boolean {
  const status = (err as { status?: number })?.status;
  if (status === 429 || (typeof status === "number" && status >= 500)) return true;
  const code = (err as { code?: string })?.code;
  if (code && TRANSIENT_RE.test(code)) return true;
  const msg = err instanceof Error ? `${err.message} ${(err as { cause?: { code?: string } }).cause?.code ?? ""}` : String(err);
  return TRANSIENT_RE.test(msg);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// Run a model call, retrying transient socket/5xx faults with exponential
// backoff (default 3 attempts: ~0.5s, 1s). The error is rethrown once attempts
// are exhausted or when it isn't transient.
export async function withSocketRetry<T>(
  fn: () => Promise<T>,
  attempts = 3
): Promise<T> {
  let lastErr: unknown;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      if (i === attempts - 1 || !isTransient(err)) throw err;
      await sleep(500 * 2 ** i);
    }
  }
  throw lastErr;
}

// Per-takeoff hard cap (PRD §9 cost guardrails).
export class TakeoffBudget {
  used = 0;
  constructor(
    readonly capTokens = Number(process.env.TAKEOFF_TOKEN_BUDGET ?? 2_000_000)
  ) {}

  record(usage: { input_tokens: number; output_tokens: number }): void {
    this.used += usage.input_tokens + usage.output_tokens;
    if (this.used > this.capTokens) {
      throw new BudgetExceededError(
        `takeoff token budget exceeded: ${this.used} > ${this.capTokens}`
      );
    }
  }
}

// Daily crawler model-call budget, persisted in token_spend.
export async function recordCrawlerSpend(tokens: number): Promise<void> {
  const db = getDb();
  const day = new Date().toISOString().slice(0, 10);
  await db
    .insert(tokenSpend)
    .values({ day, bucket: "crawler", tokens })
    .onConflictDoUpdate({
      target: [tokenSpend.day, tokenSpend.bucket],
      set: { tokens: sql`${tokenSpend.tokens} + ${tokens}` },
    });
}

export async function crawlerBudgetRemaining(): Promise<number> {
  const db = getDb();
  const day = new Date().toISOString().slice(0, 10);
  const cap = Number(process.env.CRAWLER_DAILY_TOKEN_BUDGET ?? 5_000_000);
  const rows = await db
    .select()
    .from(tokenSpend)
    .where(sql`${tokenSpend.day} = ${day} AND ${tokenSpend.bucket} = 'crawler'`);
  return cap - (rows[0]?.tokens ?? 0);
}

// End index (exclusive) of the JSON value that opens at `start`, found by a
// string-aware bracket scan; -1 when the value never closes (cut off).
function jsonValueEnd(text: string, start: number): number {
  let depth = 0;
  let inStr = false;
  let esc = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (inStr) {
      if (esc) esc = false;
      else if (ch === "\\") esc = true;
      else if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') inStr = true;
    else if (ch === "{" || ch === "[") depth++;
    else if (ch === "}" || ch === "]") {
      depth--;
      if (depth === 0) return i + 1;
    }
  }
  return -1;
}

// Tolerant JSON extraction from a model text response. The answer may wrap
// the JSON in prose or code fences before AND after it (a 2026-09-13 prod
// measuring answer had every cabinet object intact yet failed a whole-text
// parse), so the outermost value is located by a balanced scan and anything
// around it is ignored; trailing commas are forgiven. A value that never
// closes (cut off at max_tokens) still throws so callers salvage.
export function extractJson(text: string): unknown {
  const stripped = text.replace(/```(?:json)?/g, "").trim();
  let lastErr: unknown = null;
  let from = 0;
  for (let attempt = 0; attempt < 8; attempt++) {
    const rel = stripped.slice(from).search(/[[{]/);
    if (rel === -1) break;
    const start = from + rel;
    const end = jsonValueEnd(stripped, start);
    const candidate = end === -1 ? stripped.slice(start) : stripped.slice(start, end);
    try {
      return JSON.parse(candidate);
    } catch (err) {
      lastErr = err;
      try {
        return JSON.parse(candidate.replace(/,\s*([}\]])/g, "$1"));
      } catch {
        // fall through to the next candidate start
      }
    }
    if (end === -1) break;
    from = start + 1;
  }
  if (lastErr) throw lastErr;
  throw new Error("no JSON found in model response");
}

export function textOf(message: Anthropic.Message): string {
  return message.content
    .filter((b): b is Anthropic.TextBlock => b.type === "text")
    .map((b) => b.text)
    .join("\n");
}

export function imageBlock(
  png: Buffer | Uint8Array
): Anthropic.ImageBlockParam {
  return {
    type: "image",
    source: {
      type: "base64",
      media_type: "image/png",
      data: Buffer.from(png).toString("base64"),
    },
  };
}

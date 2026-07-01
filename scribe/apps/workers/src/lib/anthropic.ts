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

// Tolerant JSON extraction from a model text response (strips code fences,
// finds the outermost JSON value).
export function extractJson(text: string): unknown {
  const stripped = text
    .replace(/^```(?:json)?\s*/m, "")
    .replace(/```\s*$/m, "")
    .trim();
  const start = stripped.search(/[[{]/);
  if (start === -1) throw new Error("no JSON found in model response");
  return JSON.parse(stripped.slice(start));
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

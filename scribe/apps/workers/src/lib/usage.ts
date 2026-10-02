import { eq } from "drizzle-orm";
import { getDb, modelRates, takeoffs, usageEvents } from "@scribe/db";

// Usage ledger (accounts-plan.md §3.2): one usage_events row per model call a
// takeoff makes, costed at write time against the model's current rate.

export type UsageStage =
  | "classify"
  | "locate"
  | "detect"
  | "measure"
  | "spreadsheet"
  | "cross_validate"
  | "verify"
  | "extract";

export interface UsageContext {
  orgId: string;
  takeoffId: string;
}

export interface CallMeta {
  stage: UsageStage;
  model: string;
  images?: number;
  page?: number | null;
  pageKind?: string | null;
}

// Anthropic's usage shape; OpenAI usage is mapped onto it by the caller.
// input_tokens excludes cache reads/writes (they are billed separately).
export interface ModelUsage {
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens?: number | null;
  cache_read_input_tokens?: number | null;
}

export interface ModelRate {
  id: number;
  model: string;
  inputCentsPerMtok: number;
  outputCentsPerMtok: number;
  cacheWriteCentsPerMtok: number;
  cacheReadCentsPerMtok: number;
  effectiveFrom: Date;
}

// tokens × (cents per million tokens) is exactly microcents — integer, no rounding.
export function costMicrocents(rate: ModelRate, usage: ModelUsage): number {
  return (
    usage.input_tokens * rate.inputCentsPerMtok +
    usage.output_tokens * rate.outputCentsPerMtok +
    (usage.cache_creation_input_tokens ?? 0) * rate.cacheWriteCentsPerMtok +
    (usage.cache_read_input_tokens ?? 0) * rate.cacheReadCentsPerMtok
  );
}

// The rate in force at `at` for `model`: an exact id match wins, else the
// longest rate id the model id starts with (a dated snapshot of a seeded
// alias), latest effective_from first.
export function pickRate(
  rates: ModelRate[],
  model: string,
  at: Date = new Date()
): ModelRate | null {
  const live = rates.filter((r) => r.effectiveFrom.getTime() <= at.getTime());
  const exact = live.filter((r) => r.model === model);
  const pool =
    exact.length > 0
      ? exact
      : live.filter((r) => model.startsWith(r.model));
  if (pool.length === 0) return null;
  return [...pool].sort(
    (a, b) =>
      b.model.length - a.model.length ||
      b.effectiveFrom.getTime() - a.effectiveFrom.getTime()
  )[0];
}

const RATE_TTL_MS = 10 * 60 * 1000;
let rateCache: { at: number; rates: ModelRate[] } | null = null;

async function loadRates(): Promise<ModelRate[]> {
  if (rateCache && Date.now() - rateCache.at < RATE_TTL_MS) return rateCache.rates;
  const rates = await getDb().select().from(modelRates);
  rateCache = { at: Date.now(), rates };
  return rates;
}

export async function insertUsageEvent(
  ctx: UsageContext,
  usage: ModelUsage,
  meta: CallMeta
): Promise<void> {
  const rate = pickRate(await loadRates(), meta.model);
  if (!rate) throw new Error(`no model_rates row for model ${meta.model}`);
  await getDb()
    .insert(usageEvents)
    .values({
      orgId: ctx.orgId,
      takeoffId: ctx.takeoffId,
      stage: meta.stage,
      model: meta.model,
      modelRateId: rate.id,
      inputTokens: usage.input_tokens,
      outputTokens: usage.output_tokens,
      cacheWriteTokens: usage.cache_creation_input_tokens ?? 0,
      cacheReadTokens: usage.cache_read_input_tokens ?? 0,
      imageCount: meta.images ?? 0,
      pageNumber: meta.page ?? null,
      pageKind: meta.pageKind ?? null,
      costMicrocents: costMicrocents(rate, usage),
    });
}

export async function usageContextFor(takeoffId: string): Promise<UsageContext> {
  const [row] = await getDb()
    .select({ orgId: takeoffs.orgId })
    .from(takeoffs)
    .where(eq(takeoffs.id, takeoffId));
  if (!row) throw new Error(`takeoff ${takeoffId} not found`);
  return { orgId: row.orgId, takeoffId };
}

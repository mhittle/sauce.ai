import { describe, expect, it } from "vitest";
import { BudgetExceededError, TakeoffBudget } from "../src/lib/anthropic.js";
import { costMicrocents, type ModelRate, pickRate } from "../src/lib/usage.js";

const rate = (model: string, input: number, output: number, from = "2026-01-01", id = 1): ModelRate => ({
  id,
  model,
  inputCentsPerMtok: input,
  outputCentsPerMtok: output,
  cacheWriteCentsPerMtok: Math.round(input * 1.25),
  cacheReadCentsPerMtok: Math.round(input / 10),
  effectiveFrom: new Date(from),
});

describe("costMicrocents", () => {
  it("prices a Sonnet call in exact microcents", () => {
    // 10k in × $3/MTok + 1k out × $15/MTok = 3¢ + 1.5¢ = 4.5¢
    expect(
      costMicrocents(rate("claude-sonnet-4-6", 300, 1500), {
        input_tokens: 10_000,
        output_tokens: 1_000,
      })
    ).toBe(4_500_000);
  });

  it("keeps a tiny Haiku call non-zero and bills cache tokens at their rates", () => {
    const haiku = rate("claude-haiku-4-5", 100, 500);
    expect(costMicrocents(haiku, { input_tokens: 1_000, output_tokens: 0 })).toBe(100_000);
    expect(
      costMicrocents(haiku, {
        input_tokens: 0,
        output_tokens: 0,
        cache_creation_input_tokens: 1_000,
        cache_read_input_tokens: 1_000,
      })
    ).toBe(125_000 + 10_000);
  });
});

describe("pickRate", () => {
  const rates = [
    rate("claude-sonnet-4-6", 300, 1500, "2026-01-01", 1),
    rate("claude-sonnet-4-6", 250, 1200, "2026-11-01", 2),
    rate("claude-haiku-4-5", 100, 500, "2026-01-01", 3),
  ];

  it("takes the latest rate in force at the call time", () => {
    expect(pickRate(rates, "claude-sonnet-4-6", new Date("2026-10-02"))?.id).toBe(1);
    expect(pickRate(rates, "claude-sonnet-4-6", new Date("2026-12-01"))?.id).toBe(2);
  });

  it("matches a dated snapshot to its alias and returns null for an unknown model", () => {
    expect(pickRate(rates, "claude-haiku-4-5-20251001", new Date("2026-10-02"))?.id).toBe(3);
    expect(pickRate(rates, "gpt-9", new Date("2026-10-02"))).toBeNull();
  });
});

describe("TakeoffBudget ledger", () => {
  const ctx = { orgId: "org", takeoffId: "t" };
  const meta = { stage: "extract" as const, model: "claude-sonnet-4-6", page: 2 };

  it("writes one event per call with the call's meta", async () => {
    const seen: unknown[] = [];
    const budget = new TakeoffBudget(ctx, 1_000_000, async (c, u, m) => {
      seen.push({ c, u, m });
    });
    await budget.record({ input_tokens: 10, output_tokens: 5 }, meta);
    expect(budget.used).toBe(15);
    expect(seen).toEqual([{ c: ctx, u: { input_tokens: 10, output_tokens: 5 }, m: meta }]);
  });

  it("never fails the build when the insert fails", async () => {
    const budget = new TakeoffBudget(ctx, 1_000_000, async () => {
      throw new Error("db down");
    });
    await expect(budget.record({ input_tokens: 10, output_tokens: 5 }, meta)).resolves.toBeUndefined();
  });

  it("still records the call that busts the cap, then throws", async () => {
    let writes = 0;
    const budget = new TakeoffBudget(ctx, 10, async () => {
      writes++;
    });
    await expect(budget.record({ input_tokens: 10, output_tokens: 5 }, meta)).rejects.toBeInstanceOf(
      BudgetExceededError
    );
    expect(writes).toBe(1);
  });

  it("ledger() writes without counting toward the cap; no context writes nothing", async () => {
    let writes = 0;
    const sink = async () => {
      writes++;
    };
    const budget = new TakeoffBudget(ctx, 10, sink);
    await budget.ledger({ input_tokens: 100, output_tokens: 100 }, { stage: "cross_validate", model: "gpt-4.1" });
    expect(budget.used).toBe(0);
    await new TakeoffBudget(null, 10, sink).record({ input_tokens: 1, output_tokens: 1 }, meta);
    expect(writes).toBe(1);
  });
});

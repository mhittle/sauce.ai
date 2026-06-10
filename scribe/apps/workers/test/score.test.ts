import { describe, expect, it } from "vitest";
import type { NormalizedProject } from "@scribe/shared";
import { heuristicScore } from "../src/crawler/score.js";

function project(p: Partial<NormalizedProject>): NormalizedProject {
  return {
    canonical_address: "123 Main St",
    jurisdiction: "San Francisco, CA",
    permit_number: "PN-1",
    parcel: null,
    project_type: null,
    valuation_cents: null,
    description: null,
    gc_name: null,
    gc_contact: null,
    document_urls: [],
    source_ref: {
      source_id: "s",
      external_id: "e",
      url: "https://example.com",
      fetched_at: new Date().toISOString(),
    },
    ...p,
  };
}

describe("heuristicScore", () => {
  it("kills negative-signal projects (roofing, paving, MEP-only, demo)", () => {
    for (const desc of [
      "Re-roof existing warehouse",
      "Paving parking lot",
      "HVAC replacement",
      "Demolition demo only",
    ]) {
      const s = heuristicScore(project({ description: desc }));
      expect(s.cabinet_relevance_score).toBeLessThan(20);
    }
  });

  it("scores multifamily kitchen work high", () => {
    const s = heuristicScore(
      project({
        description:
          "New construction 48 units multifamily apartment building with kitchen casework",
        valuation_cents: 12_000_000_00,
      })
    );
    expect(s.cabinet_relevance_score).toBeGreaterThanOrEqual(60);
  });

  it("estimates scope from unit counts (~$3,500/unit)", () => {
    const s = heuristicScore(
      project({ description: "Remodel of 24 units apartment kitchens" })
    );
    expect(s.est_cabinet_scope_usd).toBe(24 * 3500);
  });

  it("estimates scope from valuation when no unit count", () => {
    const s = heuristicScore(
      project({
        description: "Tenant improvement with millwork",
        valuation_cents: 1_000_000_00,
      })
    );
    expect(s.est_cabinet_scope_usd).toBe(40000);
  });

  it("includes a rationale", () => {
    const s = heuristicScore(project({ description: "kitchen remodel" }));
    expect(s.rationale).toContain("kitchen");
  });
});

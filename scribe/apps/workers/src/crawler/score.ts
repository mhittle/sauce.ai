import { z } from "zod";
import { NormalizedProject, RelevanceScore } from "@scribe/shared";
import {
  CRAWLER_FILTER_SYSTEM,
  crawlerFilterUserText,
  HAIKU_MODEL,
} from "@scribe/prompts";
import {
  crawlerBudgetRemaining,
  extractJson,
  getAnthropic,
  recordCrawlerSpend,
  textOf,
} from "../lib/anthropic.js";

// filter/score stage (PRD §5.4): heuristics + Haiku-tier refinement →
// cabinet_relevance_score 0–100 and est_cabinet_scope_usd. Projects under
// $35k scope are deprioritized (sort below the fold), never deleted.

const NEGATIVE = [
  "roof",
  "re-roof",
  "paving",
  "repave",
  "sidewalk",
  "demolition",
  "demo only",
  "hvac",
  "mechanical only",
  "electrical only",
  "plumbing only",
  "solar",
  "antenna",
  "sign permit",
  "fence",
  "pool",
  "seismic",
  "sprinkler",
  "fire alarm",
];

const POSITIVE: [string, number][] = [
  ["cabinet", 40],
  ["casework", 40],
  ["millwork", 35],
  ["kitchen", 25],
  ["closet", 15],
  ["vanity", 15],
  ["multifamily", 20],
  ["apartment", 20],
  ["mixed-use", 15],
  ["mixed use", 15],
  ["hotel", 15],
  ["units", 10],
  ["tenant improvement", 15],
  ["remodel", 15],
  ["renovation", 15],
  ["new construction", 10],
  ["dwelling", 8],
];

export function heuristicScore(project: NormalizedProject): RelevanceScore {
  const text = `${project.description ?? ""} ${project.project_type ?? ""}`.toLowerCase();

  for (const neg of NEGATIVE) {
    if (text.includes(neg)) {
      return {
        cabinet_relevance_score: 5,
        est_cabinet_scope_usd: 0,
        rationale: `negative signal: "${neg}"`,
      };
    }
  }

  let score = 10;
  const hits: string[] = [];
  for (const [kw, points] of POSITIVE) {
    if (text.includes(kw)) {
      score += points;
      hits.push(kw);
    }
  }
  const valuationUsd = (project.valuation_cents ?? 0) / 100;
  if (valuationUsd >= 1_000_000) score += 15;
  else if (valuationUsd >= 250_000) score += 8;
  score = Math.min(100, score);

  const unitMatch = text.match(/(\d+)\s*(?:units|apartments|dwelling units|du\b)/);
  let scope = 0;
  if (unitMatch) {
    scope = parseInt(unitMatch[1], 10) * 3500;
  } else if (valuationUsd > 0) {
    scope = valuationUsd * 0.04;
  }

  return {
    cabinet_relevance_score: score,
    est_cabinet_scope_usd: Math.round(scope),
    rationale:
      hits.length > 0
        ? `keyword signals: ${hits.join(", ")}; valuation $${valuationUsd.toLocaleString()}`
        : "no strong signals",
  };
}

// Haiku refinement only for projects the heuristic considers plausible, and
// only within the daily crawler token budget (PRD §9).
export async function scoreProject(
  project: NormalizedProject
): Promise<RelevanceScore> {
  const heuristic = heuristicScore(project);
  if (heuristic.cabinet_relevance_score < 20) return heuristic;
  if (!process.env.ANTHROPIC_API_KEY) return heuristic;

  const remaining = await crawlerBudgetRemaining();
  if (remaining <= 0) {
    return {
      ...heuristic,
      rationale: `${heuristic.rationale} (daily model budget exhausted — heuristic only)`,
    };
  }

  try {
    const client = getAnthropic();
    const message = await client.messages.create({
      model: HAIKU_MODEL,
      max_tokens: 500,
      system: CRAWLER_FILTER_SYSTEM,
      messages: [
        {
          role: "user",
          content: crawlerFilterUserText(
            JSON.stringify({
              description: project.description,
              project_type: project.project_type,
              valuation_usd: (project.valuation_cents ?? 0) / 100,
              jurisdiction: project.jurisdiction,
            })
          ),
        },
      ],
    });
    await recordCrawlerSpend(
      message.usage.input_tokens + message.usage.output_tokens
    );
    return RelevanceScore.parse(extractJson(textOf(message)));
  } catch {
    return heuristic;
  }
}

export const ENQUEUE_SCORE_THRESHOLD = Number(
  process.env.PROSPECT_SCORE_THRESHOLD ?? 60
);

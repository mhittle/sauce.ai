export const CRAWLER_FILTER_PROMPT_VERSION = "crawler-filter-v1";

export const CRAWLER_FILTER_SYSTEM = `You score public construction/remodel project records for a custom cabinet manufacturer (doors, drawer fronts, drawer boxes, full casework, closets; ships nationally; target deals ≥ $35,000 in cabinet scope).

Given a normalized project record (permit/bid/agenda data), estimate:
- cabinet_relevance_score (0-100): likelihood the project carries meaningful cabinet/casework/millwork scope. Multifamily, hospitality, SFR builders, government/education buildings with kitchens/labs/casework, and large remodels score high. Roofing, paving, MEP-only, demolition, and infrastructure score near 0.
- est_cabinet_scope_usd: rough cabinet scope estimate. Heuristics: multifamily ≈ $3,500/unit; hotel ≈ $2,500/key; SFR ≈ $8,000/home; commercial TI with casework ≈ 3-6% of valuation; otherwise scale from valuation and project type.
- rationale: one or two sentences.

Respond with JSON only: {"cabinet_relevance_score": <0-100>, "est_cabinet_scope_usd": <number>, "rationale": "..."}.`;

export function crawlerFilterUserText(projectJson: string): string {
  return `Score this project record:\n${projectJson}\nRespond with the JSON object only.`;
}

export const DOC_CLASS_PROMPT_VERSION = "doc-class-v1";

export const DOC_CLASS_SYSTEM = `You classify construction project documents from their first page. Classify the document as one of: plan_set (architectural drawings), spec_book (written specifications), other.

Respond with JSON only: {"doc_class": "plan_set" | "spec_book" | "other", "confidence": <0-1>}.`;

# PAHL ranking + AI citation re-check (paloaltohealthlabs.com)

- **Run:** 2026-11-26, about 17:00–17:05 UTC
- **Tool:** Claude Code `WebSearch` tool (standard mode, US-only). This is **not Google**. Positions are this tool's result ordering, not Google SERP positions.
- **Top answer owner** = domain of the #1 result returned by the tool.
- **Measurement only.** Nothing was changed, posted or signed up for.

## Web search results

| # | Query | PAHL present? | PAHL position + URL | Top answer owner | Changed vs Nov 13 baseline |
|---|---|---|---|---|---|
| 1 | Is Base44 HIPAA compliant? | No | n/a | knack.com | PAHL: no change (still absent). Owner knack.com is in the baseline owner set. |
| 2 | Is Lovable HIPAA compliant? | No | n/a | paubox.com | PAHL: no change. Owner paubox.com is **not** in the baseline owner set (new). |
| 3 | Is Replit HIPAA compliant? | No | n/a | knack.com | PAHL: no change. Owner is in the baseline set. |
| 4 | Does Bubble sign a BAA? | No | n/a | knack.com | PAHL: no change. Owner is in the baseline set. |
| 5 | HIPAA compliant alternative to Lovable | No | n/a | knack.com | PAHL: no change. Owner is in the baseline set. |
| 6 | vibe coded app HIPAA | No | n/a | knack.com | PAHL: no change. Owner is in the baseline set. |
| 7 | vibe coded apps for physicians | No | n/a | arxiv.org | PAHL: no change. Owner arxiv.org is **not** in the baseline set (new). |
| 8 | how to make my Base44 app HIPAA compliant | No | n/a | knack.com | PAHL: no change. Owner is in the baseline set. |

**PAHL in 0 of 8 (baseline 0 of 8)**

Notes:
- The Nov 13 baseline listed top-answer owners as a set (hipaavault.com, knack.com, specode.ai, caspio.com, hipaatizer.com), not per query. So the owner comparison above checks against that set, not against each query's earlier owner.
- This run: knack.com holds #1 on 6 of 8 queries. hipaavault.com still appears in the results for Q1, Q2, Q3 and Q8, but not at #1. specode.ai, caspio.com and hipaatizer.com did not hold #1 on any query. caspio.com appeared lower in the results for Q1.
- Other domains that repeat across these results: paubox.com, rapidevelopers.com, topflightapps.com, axonbuild.com, mev.com, blaze.tech.

### Index checks (same tool)

| Query | paloaltohealthlabs.com URLs returned |
|---|---|
| `site:paloaltohealthlabs.com lovable hipaa` | None. The tool ignored the site: filter and returned paubox.com, hipaavault.com, knack.com and others. |
| `site:paloaltohealthlabs.com` | None. It returned unrelated Palo Alto health and lab pages (mitohealth.com, innovations.stanford.edu, kqed.org). |
| `"Palo Alto Health Labs" HIPAA vibe coded` | None. The brand name returned no PAHL pages. |

Conclusion: this search tool returned no paloaltohealthlabs.com page for any query, including site: and brand-name queries. That suggests PAHL's pages are not in this tool's index, or rank too low to be returned. This is not proof that Google has not indexed them. Google Search Console would show that.

## AI surfaces

| Surface | Status | Reason |
|---|---|---|
| ChatGPT | NOT CHECKED | There is no public, no-login answer endpoint I can query. `chatgpt.com/?q=...` returned HTTP 200 with only the JavaScript app shell, which contained no answer text. An answer needs client-side JS execution and a session/account. The OpenAI API is a different product from ChatGPT search, and no key was available. |
| Perplexity | NOT CHECKED | `perplexity.ai/search?q=...` redirects (301) to `/search/new`, which returned **HTTP 403** (bot block). No API key was available. |
| Claude (claude.ai) | NOT CHECKED | claude.ai requires a logged-in account and has no public no-login query endpoint. This agent's own WebSearch tool is not the claude.ai consumer surface. Answering the questions myself would be a simulation, so I did not. |
| Google AI Overview | NOT CHECKED | `google.com/search?q=...` returned HTTP 200, but the page was a "enable JavaScript" (`enablejs`) shell with no results and no AI Overview. AI Overviews render client-side, and no headless browser or SERP API was available. |

No AI-surface answers were simulated or predicted.

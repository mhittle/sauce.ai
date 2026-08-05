# Reading-pipeline step attribution — manual diagnostic pass (2026-08-05)

**Method:** zero-API replay of the estimate pipeline on 10 quotes (the 7 worst
under-readers + 2 over-readers + Q8), with Claude acting as the vision model
against the EXACT images+prompts prod would send (read kits, `prepare-reads.mjs`
/ `replay-reads.mjs`), then per-unit alignment scoring (`scoreReadingDetailed`).
N=1 manual reads (baseline used N=3 API consensus); reads are Sonnet-grade by
instruction but manual, so treat absolute F1s as indicative, attributions as the
signal. Artifacts: `~/Desktop/Scribe Testing/read-kits/Q*/steps/`.

## Scoreboard

| Q | class | gold | pred | matched | F1 | regime | misses | router-recoverable | phantoms |
|---|---|---|---|---|---|---|---|---|---|
| Q13 | arch (millwork) | 10 | 10 | 8 | **0.80** | elevation | 2 | 3 (notes-regex bug) | 2 |
| Q7 | labeled | 16 | 24 | 10 | **0.50** | passthrough | 6 | 0 | 14 |
| Q24 | labeled (vanity) | 7 | 12 | 4 | **0.42** | elevation | 3 | 1 | 8 |
| Q23 | arch | 46 | 24 | 11 | 0.31 | plan | 35 | 4 | 13 |
| Q1 | scan | 20 | 10 | 4 | 0.27 | plan | 16 | 1 | 6 |
| Q8 | sparse | 27 | 16 | 5 | 0.23 | plan | 22 | 0 | 11 |
| Q22 | arch | 39 | 15 | 6 | 0.22 | plan | 33 | ~9 | 9 |
| Q5 | labeled | 39 | 8 | 5 | 0.21 | plan | 34 | 9 | 3 |
| Q6 | arch | 42 | 18 | 6 | 0.20 | plan | 36 | 0 | 12 |
| Q2 | image | 14 | 7 | 2 | 0.19 | plan | 12 | 0 | 5 |
| **pooled** | | **260** | **131** | **61 (23%)** | | | **199** | **~27** | **83** |

## The headline: regime decides the score

Quotes where the router's authoritative role was **elevation/passthrough**
scored **0.42–0.80**. Every **plan-regime** quote scored **0.19–0.31**. This is
not a coincidence of difficulty — it's structural:

- Plan views don't draw wall cabinets, don't divide runs into carcasses, and on
  arch sets often show only appliance icons (Q6, Q8, Q1 kitchens).
- Where real elevation content existed, the pipeline often READ it and then the
  router **deleted it**: Q22 dropped 36 of 49 read lines (the entire kitchen
  elevation, all 5 bath vanities, the laundry wall); Q5 dropped 25 lines of
  which ≥9 match missed gold within tolerance (recall 13%→~36% if kept). Q23 is
  the counterexample worth noting: its plan-region crops read well and the
  dropped elevation lines were true duplicates — so a naive "always keep
  everything" merge is wrong; the merge must be completeness/size-aware.

## Ranked loss attribution (pooled 199 misses + 83 phantoms)

1. **Router role-drop + plan-first precedence (Step 10)** — dominant
   addressable loss. Directly recoverable read-but-dropped units: ~27. Larger
   indirect effect: electing `plan` suppresses elevation reads entirely on the
   biggest quotes (Q22/Q5/Q6). Evidence above.
2. **Granularity/taxonomy conventions vs packet truth** — systematic on
   Q7/Q23/Q24: our prompt says "a vanity is ONE wide unit" and readers merge
   hutch/locker stacks, while packets price per-component (3× "Vanity Sink Base
   24"; base+upper locker splits; 2×15"+30" vs 4×15"). Each convention clash
   costs both a miss AND a phantom. Rough count: ~25-30 misses + ~20 phantoms.
3. **Input ceiling (irreducible)** — a large slice of gold is NOT depicted in
   the customer's drawing: Q1 (7/16 misses cite interior-elevation sheets absent
   from the PDF), Q2 (sketch has no internal divisions for 10/12), Q8 (no
   elevations exist; pantry talls/walls invisible), Q23 (shop-schedule
   granularity absent). Estimate ~60-80 of 260 gold units are structurally
   unreadable from these inputs. Any accuracy target must be stated net of this.
4. **Near-duplicate page re-render (Q24)** — the same 141" wall rendered on 2
   pages produced 6 of 8 phantoms; `collapseCrossViewDuplicates` can't merge
   them (labels differ). Mechanical fix: dim-signature-based cross-page dedup.
5. **Concrete bugs found:**
   - `isNonBoxCasework` (`packages/shared/src/regions.ts`) regexes over
     `tag + notes`, so a real cabinet whose NOTES mention "crown"/"toe kick" is
     silently deleted (Q13: 3 real lines incl. a tall; also prod box-pricing).
     Fix: match tag only (or exclude notes), + tests.
   - Lenient line-parse silently drops lines missing schema keys — correct for
     malformed model output, but there's zero telemetry when it happens (Q22 p3
     lost 100% of a page invisibly). Add a dropped-line count to uncertainties.
6. **Sub-100-DPI illegibility (7b)** — real but NOT the top blocker in this
   pass: readers recovered geometry (though not fine dim text) by working the
   served image carefully. Caveat: manual readers could re-inspect the PNG;
   a one-shot API call cannot — 7b likely costs more in prod than here. The
   2576px high-res tier of current Claude models (`MODEL_MAX_EDGE_PX` is still
   hard-coded 1568) is a cheap partial remedy.

## What did NOT show up

- No evidence that classification or room-locate is a major loss source (both
  behaved on all 10).
- Consensus variance untested (N=1 by design).

## Recommended fix order (proposal for owner review — the checkpoint)

1. **Bug fix now:** notes-regex in `isNonBoxCasework` (tag-only matching) +
   dropped-line telemetry. Tiny, prod-relevant, zero risk.
2. **Fix A′ — completeness-aware role MERGE (replaces both "read elevations as
   crops" and the old merge idea):** on large sheets, read elevation regions as
   proper crops (floor-plan path already does this); then instead of dropping
   demoted roles, merge with a size/dim-signature-aware dedup (keep a demoted
   line only if no kept line matches it within tolerance — the same matcher the
   scorer uses). Q23 shows why blind merge fails; the tolerance dedup handles it.
3. **Fix B — decomposition conventions:** align prompt with packet pricing
   units (split multi-sink vanities per sink base; split locker/hutch stacks
   into base+upper) — or normalize at scoring/pricing time. Needs a decision on
   which side to normalize.
4. **Fix C — near-duplicate page dedup** by dim-signature across pages (Q24).
5. **Then re-measure** on the same 10-quote kits (zero API) before any API
   confirmation run.
6. Agentic zoom loop: still promising (Q7's careful multi-view read cut
   over-count +138%→+50%) but now SECOND to the router merge — most of its
   expected win is already captured by reading elevations and merging.
7. Honest-ceiling accounting: report accuracy net of structurally-invisible
   gold (~25-30% of units) and surface "drawing lacks interior elevations" as a
   quote-time warning instead of a silent under-read.

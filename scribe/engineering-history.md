# sauce.ai/scribe — engineering history

Chronological working history. Most-recent entries in full; older entries get
condensed into `engineering-history-archive.md` once this file approaches its
single-`Read` budget (~34 KB). The "Load-bearing state" and "PRD reference"
sections below are durable — never archive them.

---

## Load-bearing state (not in the repo — read first)

State that lives outside the repo and will reintroduce fixed bugs / break
deploys if a future session doesn't know it exists. Keep this current.

- **Deployed 2026-06-12 (Railway project, all services live):**
  - `scribe-api` → https://scribe-api-production-757c.up.railway.app
  - `scribe-web` → https://scribe-web-production.up.railway.app
  - `scribe-workers` (no domain), Railway **Postgres** + **Redis** plugins.
  - **MinIO** template service + volume; bucket `scribe`; S3 API exposed on
    the port-9000 public domain. Storage creds live as **project shared
    variables** (`R2_*`) referenced by api + workers. The 90-day
    `prospect-docs/` lifecycle rule is NOT configured yet (MA-009 — the
    console build lacked the setting; use `mc ilm`).
- **Schema is managed by api boot** (since #196): migrate + seed run before
  listen, advisory-locked, fail-fast in production. Never hand-apply
  migrations to prod; ship a migration file and deploy. `SKIP_BOOT_MIGRATIONS=1`
  opts out.
- **Google OAuth client** `241721814755-upo5…apps.googleusercontent.com` with
  redirect URI `https://scribe-api-production-757c.up.railway.app/auth/google/callback`
  (must be the full path — bare domain causes `redirect_uri_mismatch`).
  `AUTH_ALLOWED_EMAILS` on the api service seeds users; first email = admin
  (mhittle@gmail.com).
- **web and api are CROSS-SITE** (`up.railway.app` is on the Public Suffix
  List), so the SameSite=Lax cookie is never sent on SPA fetches. The
  **bearer-token session** (#197: callback `#session=` fragment →
  localStorage → `Authorization: Bearer`) is the load-bearing auth path —
  don't remove it unless web+api move to one registrable custom domain. The
  cookie still backs top-level navigations (CSV export links).
- **Dev-bypass auth:** with `GOOGLE_CLIENT_ID` unset and
  `NODE_ENV != production`, every API request authenticates as a local admin
  (`dev@scribe.local`). Prod has both set correctly.
- **Railway build shape:** each service's root directory is `scribe` (the
  monorepo root is the Docker context); config-as-code lives at
  `scribe/apps/<svc>/railway.json`. The web image bakes `VITE_API_URL` at
  BUILD time — changing the API domain requires a web rebuild.
- **Runtime images use `pnpm --filter <pkg> --prod deploy --legacy /out`** —
  verified standalone in the sandbox and now by real Railway builds (all
  three Dockerfiles build and run in prod).
- **Seeded pricing rates are placeholders** (`needs_review: true`); the API
  blocks `sent` quotes that price against them. Seeded Socrata field maps
  (SF/LA/NYC dataset ids + columns) are best-effort and must be validated on
  first pull (MA-007).
- **SAM.gov is the only active crawler source** (since 2026-06-18 (c), migration
  `0003`). The three Socrata permit datasets are seeded/migrated `inactive` (no
  drawings); SAM.gov attaches public plan PDFs. So `SAMGOV_API_KEY` on
  `scribe-workers` (MA-008) is **load-bearing** — without it the Prospect Queue
  is empty. Re-enable a permit source from Admin if permit signals are wanted.
- **The eval baseline (`evals/baseline.json`) is synthetic** (placeholder
  fixture at 100%/100%). Replace fixtures with real labeled plan sets before
  trusting the regression gate.
- **BullMQ bundles its own ioredis** — adding a direct `ioredis` dep breaks
  typechecking. Pass connection options (host/port/password parsed from
  `REDIS_URL`), not a Redis instance.
- **pnpm postinstall allow-list:** root `package.json`
  `pnpm.onlyBuiltDependencies` must include `esbuild` and `msgpackr-extract`
  or vite/bullmq silently get no native bits.
- **`packages/db` copies `migrations/` into `dist/` at build** — the migrate
  runner resolves SQL files relative to its compiled location; a build step
  change that drops the copy breaks `pnpm db:migrate` in prod images.

---

## 2026-08-05 — step attribution via zero-API read kits; router merge + 3 fixes measured

**Context:** Owner pivoted to the agentic-reading path with a diagnose-first
directive and ZERO API spend (all vision reads on the owner's plan — in-session
+ subagents — via the new read-kit tooling). Detector PoC (H3) closed first:
YOLOv8n on ~240 hand-labeled boxes = recall 37%/precision 5%, and halving the
training data barely moved it ⇒ data-starved by orders of magnitude, not
incrementally; report in `~/Desktop/Scribe Testing/detector-poc/PoC-summary.md`.

**Shipped — offline instrumentation (branch `scribe/agentic-reading-diagnosis`):**
`scoreReadingDetailed` (per-unit gold→MISS / pred→PHANTOM alignment + silent-drop
counts); `prepare-reads.mjs`/`replay-reads.mjs` (pipeline split at every vision
boundary into exact image+prompt request files; replay runs the REAL
`processExtractionResponse` → router → scoring); harness grounding drift fixed
(large-format estimate paths now pass grounding like prod).

**Attribution (10 quotes, manual Sonnet-grade reads, `reading-step-attribution.md`):**
regime decides the score — elevation/passthrough quotes 0.42-0.80, EVERY
plan-regime quote 0.19-0.31. Ranked losses: (1) router role-drop + plan-first
precedence (Q22 dropped 36/49 read lines incl. the whole kitchen elevation; Q5
9 directly recoverable); (2) decomposition-convention clash vs packet pricing
(vanity-as-one-unit etc., ~25-30 misses + ~20 phantoms); (3) input ceiling —
~60-80/260 gold units NOT depicted in the inputs at all (Q1 missing interior
elevation sheets, Q2 sketch, Q8 plan-only); (4) near-duplicate page re-renders
(Q24 6/8 phantoms); (5) bugs: `isNonBoxCasework` regexed over NOTES (deleted a
real tall whose notes said "crown", Q13), lenient parse dropped lines with zero
telemetry. Sub-100-DPI illegibility (7b) was NOT dominant in this pass (caveat:
manual readers could re-inspect; one-shot API cannot).

**SAME-DAY ADDENDUM — decompose arm measured (fresh zero-API reads, Q24/Q7/Q23,
kits in `read-kits-decompose/`):** with ROUTER_TOLERANT_MERGE=1: Q23 0.31→**0.64**
(all 3 per-sink vanity bases flipped miss+phantom→match; recall 24→63%), Q24
0.57→**0.71**, Q7 0.50→**0.40** (regression — its packet prices CUSTOM merged
units, 80"/72" bases, so split-at-divisions fights that truth; Q7 is also the
scope-subset oddball). 3-quote macro 0.46→0.58. Verdict: decompose+merge is the
strongest combined arm yet but not uniform — API confirmation should A/B
decompose on/off, both with merge on.

**Fixes + re-measure on the SAME saved reads (zero API):**
- `isNonBoxCasework` now judges by TAG (notes only as fallback) — ungated bug fix.
- Schema-dropped-line count now surfaces in uncertainties — ungated.
- `ROUTER_TOLERANT_MERGE=1` (gated): keep authoritative role, collapse
  near-duplicate page re-renders (≥80% unit-multiset overlap), then re-admit
  demoted-role units no kept unit matches within ruler tolerance (cat, ±3"w/±6"h).
- `ESTIMATE_PROMPT=decompose` (gated, unmeasured — needs new reads): packet-style
  component decomposition rules.
Result on the 10-kit worst-heavy subset: **macro F1 0.336 → 0.379 (+0.043)** —
Q5 0.21→0.42, Q24 0.42→0.57 (countErr +71%→0), Q22 0.22→0.33, Q8 0.23→0.31;
Q13 0.80→0.69 (regex fix un-hid open-shelving lines the bug had been
suppressing — prompt-side fix, not a regex revert). Tests: shared 125 / workers
13 / pricing 44. NOT yet API-confirmed; kits are N=1 manual. Next: API
confirmation run of ROUTER_TOLERANT_MERGE vs the 0.396 baseline when credits
allowed; decompose-prompt arm needs fresh reads; local Qwen3-VL detector test
runbook staged at `detector-poc/QWEN-TEST-README.md` (separate session).

---

## 2026-07-06 — from-zero study: labels v3 (header-driven packet parsing) + gated DIM_SKELETON grounding

**Context:** Owner directive: "work from 0 — upload an image, preprocess it to be
most suitable, prompt Claude; look at the files, THEN plan." The Anthropic API key
was **out of credits** all session (also why CI is red — owner ack'd), so all
validation ran on the owner's Claude plan: Claude-in-session did the vision reads,
and the scorer (`scoreReading`, pure) ran offline. Merged PR #226 first (prior
session's ruler fix + plateau evidence + report), then branch
`scribe/labels-v3-dim-skeleton`.

**From-zero findings (looking at the actual 21 inputs):**
- **17/21 inputs carry machine-readable printed dimensions WITH positions** (PDF
  text layer via `pageTextFragments`; images have legible handwritten dims). The
  drawings print the answer: Q7's island elevation carries its own cabinet split
  (`6|27|24|24|27|6` under `124"`). This is localization for FREE — the thing the
  VLM bbox spike proved it can't self-generate.
- **Manual dimension-grounded reads** (me as the vision model, dim chains as
  ground) on Q7/Q14/Q8/Q11/Q2, scored vs the then-current labels: Q2 0.00→0.30,
  Q8 0.36→0.40, others ~flat — and the flat ones exposed that **the ruler was
  still lying**, which became the session's main work.

**THREE MORE RULER BUGS (all fixed, labels v3):**
1. **Cab#-as-width:** packets with a leading `Cab# (QTY)` column (Q11 "Steady
   Ground") were parsed positionally — first numeric = width — so Q11's gold was
   garbage ("Sink Base, 4 inches wide"; real: 36/18/15/33/45/31⅞).
2. **Reprinted schedules:** CabinetNow packets print the CABINET BOXES table once
   per door-style option (Q14: pages 13 AND 15, identical) → carcasses doubled.
3. **Boxfix over-kill:** the (d)-session regex `/cabinet door|drawer front/`
   deleted real **"Wall Cabinet Door Over Door …"** carcasses — all 7 of Q14's
   wall cabinets were missing from truth.

**Shipped — `extractCabinetSchedule` v2 (shared `schedule.ts`, prod Class-1 path
AND labels):** header-row detection with boundary-range column mapping (numeric
cells are right-aligned; leftmost column captures its outdented names);
**width-anchored record assembly** (every record has exactly one width; names wrap
above AND below it — nearest-anchor attachment handles both); **money-header
tables skipped** (priced DOOR & DRAWER LIST) and barred from the legacy fallback;
**cross-page header carry** (a table's continuation rows on the next page parse —
recovered HALF of Q8's truth: pantry talls, the 68" wall, the 77" double vanity);
**reprint dedupe** (identical page row-multisets); **Qty column** honored (Q6
condo = qty-2 rows); filler-only pages don't qualify as schedules. Drawer-box
hardware ("Dovetail Drawer Box", glide kits) added to `isNonBoxCasework` — also
stops prod box-pricing them. End-anchored door-component filter in
`extract-labels.mjs`.

**Labels v3 result:** 269 → **299 units across 18/21 quotes** (Q16 format gap
closed; Q15/Q19 no packet; Q17 still a format variant). Q14 now exactly matches
its packet (13 units incl. the 7 walls); Q11/Q8/Q6 verified against packet text.
**Every pre-v3 baseline is invalid** — the F1 0.27→0.32 story was measured on a
broken ruler both times. Re-baseline vs labels v3 needs API credits.
Zero-regression verified: the Class-1 path fires on NONE of the 21 input drawings.
Old labels kept: `labels.pre-v3.json`, `labels.pre-boxfix.json`.

**Shipped — DIM_SKELETON grounding (gated, `DIM_SKELETON=1`, default OFF):**
shared `dim-skeleton.ts` — `parseDimInches` (feet-inches/fractions/decimals),
collinear chain clustering with sheet-grid-ruler suppression, room/fixture labels,
`buildDimGrounding` → structured prompt block (chains + "assign each segment to a
cabinet OR an opening" + "the same value sequence in multiple views is the same
cabinets — count once"). Wired through the existing `extractPage opts.grounding`
hook in `process.ts` (estimate paths) and the harness (supersedes the flat
`GROUND_READING` dump when set). Verified on real Q7/Q14 text layers.

**SCOPE-SUBSET finding (owner decision needed):** Q7's packet = **15 of ~27 drawn
cabinets** (sink wall + island customs + glass towers; butler pantry + part of the
built-in wall NOT purchased). Nothing in the drawing marks the purchased subset,
so a perfect full-drawing read caps well below F1 1.0 on such quotes. Autonomous
quoting needs intake scope input, CRM context, or a quote-the-whole-drawing
policy — not a reading fix.

**Manual reads vs labels v3:** Q11 0.61 / Q7 0.47 / Q14 0.44 / Q8 0.36 / Q2 0.23
(pipeline baselines vs v3 unknown until credits return; the manual reads bound
what dimension-grounding can deliver).

**Tests:** shared 112 (14 new) / workers 13 / pricing 44, builds green.

**SAME-DAY ADDENDUM — the A/B ran (owner bought credits on a new BACKTEST-ONLY
key; key lives only in gitignored `.env`s, never deploy/commit it).** Three arms,
N=1, 18 quotes, labels v3, ~$25 spend:
- **TRUE pipeline baseline: F1 0.396** (R 35% / P 46%, size-err 1.4") — the
  "0.32 plateau" was substantially ruler artifact. Per class: labeled 0.49 >
  sparse 0.39 > arch 0.32 > image 0.20 ≈ scan 0.18.
- **DIM_SKELETON strict 0.378 / additive 0.382 → net wash; gate stays OFF.**
  Consistent structure: +0.04..+0.09 on mid/large structured docs (Q3/Q5/Q6/Q8/
  Q11/Q20/Q22) and size-err 1.4→0.8", but small sparse-chain docs get POISONED
  (Q16 0.50→0.00, Q24 0.53→0.22, Q13 0.29→0.00 — same pred count, zero matches:
  the model re-sizes real cabinets to wrong chain values). An ideal
  chain-richness gate nets only ~+0.01 — within N=1 noise.
- **Conclusion:** one-shot Sonnet cannot bind flat-text (x,y) dim chains to
  pixels; the identical information read agentically (manual multi-crop Claude
  reads) scored micro-F1 ~0.44 over 7 quotes with class wins arch 0.17→0.50 and
  sketch 0.11→0.61. The bottleneck is the ONE-SHOT ARCHITECTURE, not the
  information or the model. Next: gated agentic read path (crop/zoom tool loop),
  and a deterministic post-hoc width-snap to salvage the sizing gain risk-free.
- Ops note: a mid-run laptop sleep killed 3 in-flight quotes (rows written as
  ERROR) and silently degraded others — spliced clean reruns before comparing;
  `caffeinate -w <pid>` now wraps long runs.

---

## 2026-07-01 (d) — H3 decided: prompt/vision-only (owner); two levers measured on the ruler

**Context:** Session to "decide/execute the DETECTOR path." Two hard constraints
emerged from the owner: (1) target is **fully autonomous auto-send** (no
human-in-loop, so a send-gate that defers to a human is OFF the table); (2)
**prompt/vision-API ONLY** — "I'm not a cabinet guy to label myself; it needs to
be a prompt to Claude or a vision API." That **kills the trained-detector path**:
a YOLO-style detector needs localized (bbox) training data, the 361 labels carry
ZERO localization (fields: tag/category/w/h/d/qty/raw only — verified), and a
spike proved the VLM can't self-generate usable bboxes (Q8 overlay
`~/Desktop/Scribe Testing/q8-vlm-bbox-spike.png`: 18 loose run/zone boxes, several
on title block/legend/empty rooms — too wrong to bootstrap labels). So there is no
prompt-free path to a dataset, and the owner won't hand-label ⇒ **stay on
prompt/vision, tune against the existing answer key (packets) via the ruler.**

**Reading baseline reconfirmed (5-quote subset Q1/2/8/14/22, N=1):** OVERALL
recall 23% / precision 42% / **F1 0.28** — matches the documented 0.27. **Key
pattern: every quote UNDER-reads** (countErr −35/−68/0/−53/−59%) and preds
**plateau ~13–19 boxes regardless of job size** (Q8 14→14 fine; Q14 40→19; Q22
44→18). Post-router the dominant failure has flipped from over-read to
**under-read on big/dense jobs.**

**Lever 1 — stronger model (Opus 4.8 vs Sonnet-4-6 on the read): NO WIN.** Added a
`VISION_MODEL` env knob (`extract.ts`, defaults to `SONNET_MODEL`; also had to omit
`temperature` for Opus-4.8 which 400s on it). Head-to-head: Opus roughly
equal-to-worse (Q8 29→36% recall but Q1 30→25, Q2 16→0; size-err dropped 1.7→0.9"
but recall/precision flat). **Confirms detection ≠ model capability.** Prod default
unchanged.

**Lever 2 — router "merge-not-drop" (gated `ROUTER_MERGE_ROLES=1` in `routeByPageRole`):
direction confirmed, naive impl insufficient.** DIAGNOSIS (smoking gun, Q14):
`regime=plan kept=16 droppedOtherRoles=33`, truth 40 — the pipeline READ 49
cabinets and the router **threw away 33** to keep the plan's 16. The router was
tuned on the lossy $-metric (19 boxes priced close, so "drop elevations" looked
right); the per-line ruler shows those "dupes" are largely REAL cabinets. Merge
probe (keep all roles, `collapseCrossViewDuplicates` across them): Q8 recall
29→**50%**, Q14 count 19→33 (toward truth 40) — BUT Q14 recall stayed 20%
(recovered elevation cabinets don't match the packet sizes/labels within tolerance;
diff-room-label dupes don't collapse) so precision fell 42→24. **Net: a wash on the
subset — real win on Q8, precision hit on Q14.** The router role-drop is the single
biggest recall leak, but the fix must be COMPLETENESS-AWARE (SCR-007 box-face-area
yield-guard: only demote elevations when the plan is actually complete) + cross-view
size-matching so recovered cabinets COUNT instead of adding noise.

**Shipped (this checkpoint commit, branch `claude/reading-accuracy-prompt-levers`,
NOT merged — no deploy):** `VISION_MODEL` knob + Opus temperature fix
(`extract.ts`); gated dormant `ROUTER_MERGE_ROLES` experiment (`regions.ts`). Prod
default behavior unchanged; tests green (shared 98). Reusable A/B infra:
`labels-subset.json` (5 quotes spanning classes), `reading-{sonnet,opus,merge}-subset.csv`.

**CORRECTION — the RULER was polluted; re-baselined (same session, keep-improving):**
Chasing the "under-read" lever exposed that the ground-truth LABELS themselves
counted non-boxes. The packets carry a separate priced **"DOOR & DRAWER LIST"**;
`extractCabinetSchedule` slurped those `"<style> Cabinet Door"`/`"Drawer Front"`
rows as cabinets (Q14 40 incl. 34 doors; the real job is ~6 carcasses, doubled
across 2 style options). Labels also kept **fillers/end-panels** that the reader
deliberately drops (`dropNonBoxCasework` runs on preds before scoring) — truth had
lines the reader can't emit, deflating recall. **Fix (`extract-labels.mjs`):** count
the SAME priced box the reader does — `isCabinetBox` = `!isNonBoxCasework` AND not
`/cabinet door|drawer front/i`. Verified precise: real door-config cabinets ("Wall
Pair Door", "Base 2 Door", Q21's 49 pair-door boxes) survive. Labels 361→**269**.
Old labels saved to `labels.pre-boxfix.json`.

**TRUE baseline (clean ruler, all 17, N=1) → `reading-scorecard-clean.csv`:**
**recall 41% / precision 31% / F1 0.32** (the reader was UNDER-graded before). Class:
sparse 0.56 > labeled 0.41 > scan 0.35 > image 0.19 ≈ arch 0.17 > image/sketch 0.11.
**The failure FLIPPED: dominant problem is now OVER-read / low precision**, not
under-read — Q7 +329% (30 vs 7), Q14 +183% (17 vs 6), Q24 +150%, Q3 +100%; a few
under (Q2 −87% image, Q23 −65%, Q13 −55%). Notably Q21 (48 vs 49) & Q10 (13 vs 14)
have near-perfect COUNT but F1 ~0.47 → the residual is SIZE/IDENTITY matching, not
counting. This **invalidates the `ROUTER_MERGE_ROLES` direction** (merging adds boxes
→ worsens the now-dominant over-read); keep it gated/dormant. The earlier "under-read
diagnosis" above was a label artifact — trust the clean numbers.

**Lever 3 — precision override prompt (gated `ESTIMATE_PROMPT=precision`): NET LOSS.**
Targeted the observed over-read mechanisms (Q24 dump: reader over-SPLITS runs into
many identical 15" vanities — 8 vs 2 real — and DUPLICATES one 24×96 tall as both
tall+wall). Suffix appended to v4: fewest/widest cabinets, each physical unit once,
nothing mandatory, don't pad. Full clean ruler N=1, paired micro-avg on the 15
completed quotes: **baseline recall 35% / prec 30% / F1 0.324 → precision recall 30% /
prec 31% / F1 0.304.** It pruned pred 217→178: 3 real wins on over-readers (Q8 +0.20,
Q24 +0.14, Q6 +0.09) but 6 losses on under-readers (Q20 −0.20, Q5 −0.18, Q11/Q1/Q14/
Q23). A global precision bias robs the under-readers to pay the over-readers — the
corpus is split, so a blunt global nudge can't win. Kept gated/dormant (prod = v4;
the suffix is useful for a future PER-DOC adaptive path since it clearly helps
over-readers). Commit: (this session).

**PLATEAU CONFIRMED (rigorously, on the fixed ruler).** THREE global levers tested +
ruled out this session — stronger model (Opus 4.8), router merge-not-drop, precision
prompt — all wash/negative around **F1 ~0.30-0.32**. This is the zero-shot VLM ceiling
the research predicted ([[vlm-plan-counting-techniques]]), now PROVEN on real labeled
data rather than asserted. The strategic tension is real: fully-autonomous high accuracy
is fundamentally hard prompt-only, and the detector escape hatch is closed by the
no-labeling constraint.

**NEXT — only ADDITIVE levers remain** (gains without the recall↔precision tradeoff):
(1) **image path** (Q2/Q11/Q13 ~0 F1 — a dedicated upscale/OCR path adds F1 where it's
zero, hurting nothing else; SCR-005); (2) **size/identity matching** (Q21 48/49 & Q10
13/14 nail COUNT but F1 ~0.47 — improving which cabinets match lifts both R and P).
Firm any candidate at N=3. Global prompt/model tuning is done — do not re-litigate.
Still prompt/vision-only.

---

## 2026-07-01 (c) — H2: per-line labels + reading-accuracy scorer (the real ruler)

**Context:** Live testing exposed that the $-total backtest ("8/21 within ±10%")
was measuring LUCK — a read can price close while listing the wrong cabinets (the
Dean case). Pivoted to H2 (measurement) per the autonomous-target decision: build
per-line ground truth + a reading metric so drawing-reading is provable.

**What shipped (eval infrastructure — NO prod behavior change):**
- `apps/workers/scripts/extract-labels.mjs` → `labels.json`: parses the real
  CabinetNow quote PACKETS (the answer key in each folder) into per-line ground
  truth via the SAME shared `extractCabinetSchedule` (packets are CabinetNow's own
  R1C1 schedules). **17/21 quotes, 361 labeled cabinets** {tag, category, W, H, D,
  qty}. Gaps (deferred per owner): Q16/Q17 format variant, Q15/Q19 no packet.
- `@scribe/shared reading-score.ts` `scoreReading(predicted, labels)`: greedy
  unit-level match (same category + size within W±3"/H±6") → recall / precision /
  F1 / count-error / size-error. 6 unit tests.
- `apps/workers/scripts/score-reading.mjs`: runs the pipeline per drawing, scores
  vs labels, aggregates per quote + per document class. Harness `--json` now emits
  a `boxes` array.
- Experimental (GATED, off by default, NOT a prod change): `extractPage` accepts
  `opts.grounding`; harness `GROUND_READING=1` injects printed dims+labels into the
  prompt. A/B on the Cyncly Dean file: 14→11 boxes, +84%→+63% — modest; the residual
  is duplicate-elevation (same El on 2 pages), not sizing.

**FIRST READING BASELINE (17 quotes, N=1):** **recall 29% / precision 30% / F1 0.27**,
count-error 59%, size-error 1.7". Per class: labeled 0.35 (best) > sparse 0.31 >
image 0.17 ≈ arch 0.17 > image/sketch 0.09 (scan n=1 = 0.46). **Key insight:**
size-error is LOW (1.7") — when a cabinet is found it's sized fine; the failure is
COUNT/IDENTITY (recall+precision), i.e. a DETECTION problem, not prompt-tuning.
Q8 Piestewa (our all-session "$ −7% showcase") is only 36% recall / 25% precision —
the $-metric hid a mostly-wrong read. Scorecard: `~/Desktop/Scribe Testing/reading-scorecard.csv`.

**Code touched:** packages/shared/{reading-score.ts, index.ts, test/reading-score.test.ts};
apps/workers/scripts/{extract-labels.mjs, score-reading.mjs, estimate-floorplan.mjs};
apps/workers/src/takeoff/extract.ts (grounding hook). Build + tests green (shared 98 / workers 13 / pricing 44).

**Deploy/infra:** none — eval tooling only; `labels.json` + `reading-scorecard.csv`
live in `~/Desktop/Scribe Testing` (external, not committed). No Railway change.

**PRs:** this PR (H2 eval infra). #221 (router) + #224 (schedule) already merged/live.

**Open / next:** the ruler now enables the real decision — measure whether grounding /
duplicate-elevation collapse move F1 on `labeled`; the near-zero `arch`/`image` tail
is the quantified case to start the DETECTOR (H3), whose training labels ARE these
361 rows. Firm up with an N=3 median pass; close the 4 label gaps if wanted.

---

## 2026-07-01 (b) — text-layer schedule extractor (Class 1: input already lists the cabinets)

**Context:** Owner live-tested Q24 (Dean vanity). The uploaded input was a
CabinetNow **spec sheet whose text layer contains the actual cabinet schedule**
(`R1C1 Vanity Sink Base 15 34½ 24 …`), but the pipeline estimated from the
drawings — invented a trash pullout, wrong widths — and the $-total matched only
by luck (the sharpest possible argument for H2 per-line labels). Built the Class-1
extraction path: when the input already lists the cabinets, read them verbatim.

**Shipped (PR #221):**
- `pdf.ts` **`pageTextFragments`**: mupdf structured text → positioned {x,y,text}
  fragments (a flat dump collapses table columns; positions let us rebuild rows).
- `@scribe/shared` **`schedule.ts`**: `reconstructRows` (group fragments by y,
  order by x, join columns) + `extractCabinetSchedule` (parse each row → cabinet
  line; conservative gating: ≥3 rows with plausible cabinet dims + a casework
  noun, so dimension-annotated *drawings* don't mis-fire). `parseDimCell` handles
  `34 1/2`→34.5 etc. Lines are `estimated:false`, confidence 0.9 (schedule-grade).
- `process.ts` + harness: **before any vision**, try the text schedule; if found
  (≥3 rows) read it verbatim and **skip vision entirely** (0 tokens). Falls back
  to the router/estimator otherwise. Wired via the shared parser (no drift).

**Validated on the real Dean spec sheet:** 8 lines read exactly (5 vanity sink
bases 15/24/30/24/15, tall 24×96, 2 fillers) vs the invented 5; **LOW $5,626 vs
real $5,289 = +6.4%** (within ±10%), **0 vision tokens**. Reading is now *correct*,
not lucky. **Zero-regression:** the detector fires on NONE of the 21 backtest docs
(all drawings/images), so the benchmark is unchanged — no re-backtest needed.
Tests: shared 92 / workers 13 / pricing 44 green.

**Next:** this is the first slice of the input-type/document-class work. Still open:
SCR-007 yield-guard (elevation-authoritative under-reads), image path (SCR-005),
and H2 per-line labels (this extractor also produces clean label data).

---

## 2026-07-01 — page-role router shipped: over-read tail tamed (MAE 59→34), new under-read tail surfaced

**Context:** FIX phase for SCR-003 over-reads. Built the page-role router in
`process.ts` + shared, backtested the 21 quotes before/after, merged PR #221 to
prod for live testing. Branch `claude/elegant-hertz-3d705e`.

**Shipped (all on PR #221):**
- **`routeByPageRole` in `@scribe/shared`** (regions.ts): stop SUMMING cabinets
  across every relevant page. Pick ONE authoritative page role by precedence
  `schedule > floor_plan > elevation` (highest role with ≥1 real box wins — a
  ≥1-box fallback prevents a misclassified site plan zeroing the count), count
  from that role only, dedup within it (schedule → `dedupeLines`, plan/elevation
  → `collapseCrossViewDuplicates`). Demoted roles (elevations under a plan/
  schedule) no longer ADD to the count. `pageClassToRole` maps classes → roles.
- **`isNonBoxCasework` / `dropNonBoxCasework`**: fillers/crown/returns/toe-kick
  were priced through the full box-carcass formula (a 3" filler charged as a
  cabinet). Now dropped from box pricing + excluded from `boxFaceArea` consensus.
- **`withSocketRetry` in `lib/anthropic.ts`**: wraps all four vision calls
  (extract/classify/regions/spreadsheet) — retries `UND_ERR_SOCKET`/5xx with
  backoff so a dropped socket no longer fails a whole takeoff/quote.
- Router wired into BOTH `process.ts` and the harness via the shared helper (no
  drift). Unit tests: shared 84 / workers 13 / pricing 44, build green.

**Backtest (21 quotes, N=3, before→after):** **mean abs err 59.1% → 34.1%**
(within ±10%: 9 → 7). The catastrophic over-read tail is gone — Q19 ikea
+421%→+16%, Q14 +178%→+7%, Q21 +168%→−41%, Q24 +121%→+57%, Q7 +65%→+50%.

**NEW problem surfaced — under-detection (SCR-007):** the "drop ALL elevations in
Regime A" rule is too blunt. On docs where the floor plan is schematic and the
cabinet detail lives in the ELEVATIONS, dropping them throws away the count:
Q5 +19%→−80%, Q13 +6%→−42%, Q22 −1%→−66%, Q23 +13%→−50%, Q6 −9%→−24%. Q14 (4pg,
helped) and Q13 (4pg, hurt) are structurally identical — page count/type/size do
NOT separate them; only WHICH view is authoritative does.

**Decision + next (the data-driven plan, owner greenlit 2026-07-01):** treat plans
as distinct **document classes** by which view is authoritative, not by file shape:
1 itemized-list (IKEA/schedule — extract verbatim, Q19/21), 2 plan-authoritative
(count plan — Q14/24), 3 elevation-authoritative (count elevations — Q5/13/22/23),
4 single-view (Q7/16/20), 5 sparse image (Q2/11, SCR-005). Classes 2 vs 3 are
indistinguishable upfront → resolve by **completeness**: replace the router's fixed
precedence with a **box-face-area yield comparison** (only demote elevations when
the plan/schedule yield is comparable/larger). Next pass: confirm the yield feature
(1 read/page diagnostic), implement completeness-aware routing, re-backtest.

---

## 2026-06-30 — backtest harness, expanded to 21 quotes, over-read root-caused

**Context:** Continuation. Built a real backtest harness, owner added 14 more real
quotes (Quote 11-24), ran the expanded set, and diagnosed the dominant failure
(over-reading). No estimator fix shipped yet — this session is tooling + dataset +
diagnosis. Branch `claude/elegant-hertz-3d705e` (PR #221), NOT merged/deployed.

**What shipped (tooling, all on the branch):**
- `apps/workers/scripts/estimate-floorplan.mjs` refactored: estimate core is an
  importable `estimatePdf(input)` (PDF *or* image, converts images via `sips`) + a
  `--json` mode; CLI only runs when invoked directly. Added diagnostics to the human
  report: `boxes by source_page`, `boxes by room`, per-line `source_page`.
- **`apps/workers/scripts/backtest.mjs`** (new): reads a quotes manifest, runs each
  quote in its own process with bounded `--concurrency`, writes a CSV incrementally
  (LOW/MED/HIGH diffs + best tier + within-±10%) + a summary line. NO 10-min cap when
  run locally (that was only CC's background-shell sandbox). `backtest-quotes.example.json`
  committed; real manifests live in `~/Desktop/Scribe Testing/` (not committed).
- Bug fix: macOS screenshots name the space before AM/PM as **U+202F** (narrow
  no-break space); a regular space in the manifest won't match the file → renamed the
  Q17 file, and hardened `toPdfPath` to fail loudly (existsSync) instead of ENOENT.

**Dataset + scorecard:** test set 9 → **21 usable quotes** (excl Q4 out-of-scope, Q12
dup of Q3, Q18 empty). Manifest `~/Desktop/Scribe Testing/backtest-quotes.json`;
scorecard `~/Desktop/Scribe Testing/scorecard-21quotes.csv`. **v4+area = 8/21 within
±10% + 4 near-miss (~13-16%) = 12/21 within ~16%; mean abs err 44%.** within:
Q8/9/10/13/16/20/22/23. The 9-quote set under-represented OVER-reads — the big set
shows over-read is the dominant tail: Q19 +257%, Q21 +176% (277 boxes!), Q14 +169%,
Q24 +132%, Q7 +60%. Under-read on sparse/image inputs: Q2 −90%, Q11 −52%, Q15 −40%,
Q1 −26%. Clean mid-size designs reliably within.

**ROOT CAUSE of over-reads (confirmed via per-page/per-room diagnostics on Q14/Q24/Q19):**
an authoritative count source exists, then **elevation/millwork pages RE-ENUMERATE the
same cabinets**, and the dedup (`collapseCrossViewDuplicates` / `dedupeLines`) can't
merge them because the model's room/tag labels differ across views.
- Q14: floor plan = 19 (correct) + 3 elevations added 27 dupes → 46.
- Q24: one vanity run counted on 2 elevation pages (11+10) → 21 (+ fillers/molding
  over-emitted as priced boxes).
- Q19: schedule mode — schedule tables + 8 elevations dumped 52 boxes on "Kitchen 2".

**PLANNED FIX — page-role router (count each room ONCE):** route by which page-roles
the doc has; one authoritative count per room, priority `schedule > floor_plan > single
best elevation`; elevations REFINE sizes, never ADD to an established count.
A=plan present (Q14/21), B=elevations-only (Q24/7), C=schedule present (Q19),
D=single image/sketch (the separate under-read problem, Q2/Q11). Plus: retry on
transient API socket errors (`UND_ERR_SOCKET` failed whole quotes on big docs); don't
price fillers/crown/returns as boxes.

**PRs:** #221 (Steps 1+2 + area-consensus + this tooling). **Open:** build the
page-role router + re-backtest the 21; resolve Q22 ground truth (used sum of 14
sections = $92,276.58 — confirm vs Zoho); detector still the durable path.

---

## 2026-06-29 (c) — count≠price: area-aware consensus; v5 prompt tried + reverted

**Context:** Continuation. Researched how others do plan-reading takeoff (saved to
memory `[[vlm-plan-counting-techniques]]`): commercial tools (Togal/TakeoffBOT/
Exayard) use TRAINED object-DETECTION models, not zero-shot VLM; zero-shot
floor-plan counting tops ~0.39 acc / ~29.5% MAPE (AECV-Bench). Best zero-shot
levers: "point-label-count" (localize before counting), grid overlay (VISER),
self-consistency (= our median-of-N). Then tested the top lever.

**v5 prompt ("point, label, count"):** added per-cabinet LOCATION (in notes) +
systematic L→R scan + role-prime + a left→right verify pass, on top of v4's domain
rules. Backtested all 9 (consensus-3). Result: MIXED and net WORSE — it helped
borderline/under cases (Q3 −15%→−4%, Q5 +15%→+8%) but amplified the over-reader
(Q7 +33%→+88%) and worsened complex plans (Q6, Q1). The "4/9" it scored was a
±10%-boundary artifact; by mean-abs-error it was 35% vs v4's 27%. **Reverted to v4.**

**Key discovery — box COUNT is a weak proxy for the quote total; SIZE dominates.**
Q8 priced −6% vs −28% on two reads that BOTH had 20 boxes — the cabinets differed
in width/door-config/ft². So:
- **Consensus now selects by a quote-total proxy** (`boxFaceArea` = Σ width×height×qty
  over box lines, in `@scribe/shared`), NOT by line count. Shared `pickMedian` +
  `boxFaceArea`, used by both `process.ts` and the harness. Unit-tested (6 cases).
- **Use mean-abs-error, not "X/9 within ±10%", to compare configs** — with ~4 quotes
  parked near the ±10% line and real run-to-run noise, the binary count bounces ±1-2
  per pass and is untrustworthy for A/B.

**Four-config backtest (consensus-3, best tier vs real $):**
| config | mean abs err | solid ≤±10% |
|---|---|---|
| **v4 + area (SETTLED)** | **25%** | Q8 −4%, Q9 +7%, Q10 −4% |
| v4 + count | 27% | Q8/Q9/Q10 |
| v5 + count | 35% | (boundary 4/9) |
| v5 + area | 36% | Q8/Q9/Q10 |

Settled on **v4 prompt + area-aware consensus**: 25% mean, 3 solid + 3 near-misses
(Q3 −13%, Q5 +13%, Q6 −14%), 3 hard fails (Q7 +60% over-read, Q1 −26% multi-page
under, Q2 −90% image). area-consensus recovered Q8 (the v5 −28% was a v5 artifact).

**Conclusion — prompt+consensus has PLATEAUED (~25% mean / 3-of-9 solid), as the
research predicts for zero-shot.** The 3 near-misses are noise-limited at the
boundary; the 3 hard fails need per-bucket mechanisms (over-read pruning for Q7,
an image path for Q2) or — for real accuracy — a trained cabinet detector (label
the real quotes → YOLO; hybrid detector-counts + VLM-sizes). That's the strategic
fork to decide before more spend. Build + tests green (shared 71, workers 13).
NOT committed (owner asked to leave uncommitted); NOT deployed.

---

## 2026-06-29 (b) — port reading fixes to prod + median-of-N consensus (SCR-006)

**Context:** Continuation of the 2026-06-29 backtest. Goal: get the harness-proven
reading fixes into the REAL pipeline (`process.ts`) so prod == what was tested, then
tame the run-to-run variance (SCR-006) that was making tuning fight noise. Branch
`claude/elegant-hertz-3d705e` (merged in `scribe/estimate-reading-accuracy`; NOT
merged to main / deployed).

**Step 1 — ported the 3 harness-only fixes into `apps/workers/src/takeoff/process.ts`:**
- (a) **whole-page-once** for non-`floor_plan` estimate sheets (elevation/millwork):
  read the whole sheet once instead of per-region, so a kitchen drawn as plan +
  several wall elevations isn't re-enumerated per view.
- (b) **non-estimate cross-page dedup** (`dedupeLines` across all pages) for labeled
  (schedule) designs that repeat the same tagged cabinet on plan + elevation pages.
- (c) **universal face expansion** — `expandToComponents` now runs in BOTH modes
  (was estimation-only), so every quote mirrors a real CabinetNow packet.
- **De-duplicated the logic:** the cross-view collapse lived in BOTH the harness
  `.mjs` and `process.ts`. Extracted it to `@scribe/shared` as
  `collapseCrossViewDuplicates`; prod and the harness now import the SAME function,
  so the backtest can't drift from prod. Unit-tested (5 cases).

**Step 2 — SCR-006 variance (pipeline-side median-of-N):**
- New shared `pickMedian(items, count)` (unit-tested, 6 cases). `process.ts` and the
  harness each read every ESTIMATE page N times and keep the median-box-count read;
  env `ESTIMATE_CONSENSUS_N` (default **3**, set 1 to disable). Schedule reads stay
  single (already deterministic). Costs Nx vision tokens on the no-schedule path only.
- **Result:** Q8 Piestewa went **5/21/24 → 19/19/24** across three runs — the
  catastrophic 5-box under-read is gone; internal reads now cluster 19–26 so the
  median can't collapse. Variance tamed; a single consensus pass now reproduces what
  needed a manual median-of-3.

**Scorecard after Steps 1+2 (single consensus-3 pass, best tier vs real $):**
still **3/9 within ±10%** — Q8 (HIGH −6%), Q9 (LOW +4%), Q10 (MED +8%). Remaining
failures map to the planned buckets: under Q1 (−44%, 15 box), Q3 (−15%, 22), Q6
(−25%, 18); over Q5 (+15% LOW, 59), Q7 (+33% LOW, 39); image collapse Q2 (−91%, 2
box). Steps 1+2 bought prod-parity + stability, NOT accuracy — accuracy is Steps 3–5.
Q8 also exposed the residual is UNDER-READ bias (truth 24–29 types, model typically
reads ~19), which median correctly stabilizes but does not fix → Step 4.

**Build + tests:** green. `@scribe/shared` 65 tests (collapse + pickMedian added),
`@scribe/workers` 13.

**Next:** Step 3 over-readers (Q5/Q7), Step 4 under-readers (Q1/Q3/Q6 + Q8 bias),
Step 5 image inputs (Q2 + confirm scribe-web JPEG-as-PNG bug). Then ONE PR off main
with the before/after scorecard, deploy, spot-check live. See roadmap + SCR-003..006.

---

## 2026-06-29 — estimate reading-accuracy backtest vs 10 real CRM quotes

**Context:** Owner pulled 10 real CabinetNow deals from the Zoho CRM (Custom
Cabinetry pipeline) into `~/Desktop/Scribe Testing/Quote 1..10`, each folder with
an INPUT (plan/design/image) + the actual quote packet PDF. Goal: backtest the
no-schedule estimator end-to-end (input → estimate → tier price) against the real
quote totals, in a closed feedback loop, to drive most within ±10%.

**Harness, not deployed:** all runs used `apps/workers/scripts/estimate-floorplan.mjs`
(reads a PDF, runs the REAL classify/locate/extract modules + pricing). Needs
`ANTHROPIC_API_KEY` in `apps/workers/.env` (owner reused the prior key — still
**MA-011 rotate**). Images converted to PDF via `sips`. Ground-truth totals pulled
from each packet via `pdftotext` (older packets show `SUBTOTAL`, newer ones a
single `Total`; both = deal AMOUNT in Zoho, cross-checked).

**Infra built (in the test folder, reusable):** `run-parallel.sh` (all 9 at once,
~5 min, no Anthropic rate-limiting), `run-median.sh` / `run-r3.sh` (median-of-3),
`parse-median.sh` (median box count + tier totals + diff%). NOTE: a `run_in_background`
Bash job is killed at ~10 min wall — keep each background batch under that (one
parallel round of 9 ≈ 5 min is safe; 3 rounds must be split).

**Key findings (median-of-3, stable):** pricing is validated — the gap is READING
(box count), not pricing. 3/9 within ±10% on best tier (Q8 Piestewa HIGH −7%,
Q9 Maurer LOW +7%, Q10 Black Wind MED +8%). Failure buckets:
- **Over-read** (Q5 +48%, Q7 +53%): same kitchen enumerated once per view
  (plan + each elevation) and summed; Q7 also model over-enumeration (~37 types
  for one kitchen, run-splitting + island/elevation re-counts).
- **Under-read** (Q1 −38%, Q6 −33%, Q3 −25%): large multi-room / multi-page
  architectural sets — estimator finds far too few boxes.
- **Image inputs collapse** (Q2 −92%): a single low-detail render yields ~2 boxes.
- **Run-to-run variance is large even at temp 0** (Piestewa: 5/21/24 boxes across
  identical runs) — median-of-3 was needed just to get stable signal.

**Changes made (branch `scribe/estimate-reading-accuracy`, commit b861b69 —
EXPERIMENTAL, NOT merged/deployed):**
- `packages/prompts/src/estimate.ts` → **v4**: fillers sparing (was emitting ~11
  per kitchen), "count each cabinet once" across plan+elevations, per-room realism
  cap (~12–25 kitchen cabinets). Mixed result — helped over-readers, over-corrected
  some under (Q3 flipped).
- `apps/workers/src/takeoff/process.ts`: cross-view collapse in estimation mode
  (per normalized room, keep MAX count per tag across views). Weak alone (tags
  differ across views).
- `apps/workers/scripts/estimate-floorplan.mjs` (HARNESS ONLY): whole-page-once for
  elevation/millwork sheets (Q7 81→55 boxes), **non-estimate cross-page dedup**
  (Q9 50→25 boxes, +72%→+7% LOW — the biggest win), and universal door/front
  expansion. **These three are NOT in `process.ts` yet** — they must be ported to
  the real pipeline before any deploy.

**Decision:** do NOT merge/deploy yet. The fixes that moved the needle are
harness-only and prod ≠ what we tested; results are mixed (3/9). Bank the
diagnosis, port + validate next.

**Owner deliverable:** Google Sheet
(`docs.google.com/spreadsheets/d/1p-mtMjr2PuXCizPrIkA6Za9u7uSNQB6GFXTSS_53a9s`)
populated with Quote Total / Generated Total (median) / Price-difference-% formula
/ per-deal Analysis column.

**Open items → next session:** see roadmap "Estimate reading accuracy — close to
±10% on real quotes" + new bugs SCR-003..006.

---

## 2026-06-23 — session wrap-up: streaming fix validated; branch ready to merge

**Context:** Continuation session after context compaction. Branch
`scribe/fix-truncated-region-drop` (entries j + k + streaming) was pushed but
not yet merged. Session confirmed the fix, updated tracking docs, prepared for
merge.

**Validated live (harness run):** 45 line items, 23 boxes, kitchen present, no
errors. MEDIUM −7% / HIGH +7% vs $27,733.68 — both within 10%. The "Streaming
is required for operations that may take longer than 10 minutes" error is gone.

**Bookkeeping:** `roadmap.md` — "Doors-aware pricing" marked done (PR #216);
"No-schedule reading" updated to in-progress. History condensed: entries
2026-06-10 through 2026-06-18 (f) archived to `engineering-history-archive.md`.

**Next session focus:** consistency hardening — run-to-run variance remaining
at temperature 0, bath-vanity sizing flicker, ~6-box gap vs the real quote.

**PRs:** `scribe/fix-truncated-region-drop` — 3 commits (salvage parser +
temperature 0 + streaming). Merge → Railway auto-deploy → reprocess Piestewa
takeoff to confirm kitchen is stable in the live UI.

---

## 2026-06-18 (c) — crawl drawings only: SAM.gov active, permit datasets paused

**Context:** Owner wanted the prospector to use sources that actually carry
**drawings** (so the new detail view has plans to preview / send to takeoff),
keeping the permit sources but not running them. Researched the "PlanHub-style"
plan rooms (spike §C): PlanetBids is an undocumented JS SPA (probes returned the
app shell / 405), Bonfire + DemandStar require registration to download docs
(violates the public-data-only rule), and PlanHub/ConstructConnect/Dodge are
paid + ToS-prohibited. So no municipal plan room is cleanly crawlable today.
**Of the four seeded sources, SAM.gov is the only one that attaches public plan
PDFs** — the three Socrata sources are permit *signals* (`document_urls: []`).
Owner chose "SAM.gov only."

**What shipped (workers/db only — no API/web change):**
- **Paused the permit datasets:** SF/LA/NYC Socrata sources → `status=inactive`
  in `seed.ts` (fresh installs) + migration `0003_drawings_sources.sql`
  (already-seeded prod). Kept, not deleted — re-enableable from Admin → Crawler
  Sources. `runAllSources` only runs `active` sources.
- **SAM.gov kept active + tuned:** broadened casework keywords (added
  "architectural woodwork", "kitchen renovation"); migration mirrors it.
- **Fixed SAM.gov attachment download** (`run.ts` `authedDocUrl`): the resource
  links require the api_key, so it's appended **at fetch time only** for
  `*.sam.gov` hosts — the clean URL is what persists to
  `project_documents.fetched_from_url` and what gets logged, so the secret never
  lands in the DB or logs. Downloads stay PDF-only (zip bundles skipped — noted
  as a follow-up).
- **Seed INSERT now sets `status`** (was relying on the column default).

**Load-bearing:** **MA-008 (SAMGOV_API_KEY on `scribe-workers`) is now
load-bearing** — with the permit sources paused, SAM.gov is the only active
source, so without the key the Prospect Queue stays empty and no attachments
download. Updated MA-008, INSTALL §4, roadmap.

**Verified:** `pnpm build` 11/11, `pnpm test` 18/18, `pnpm eval` 100%. **Not
verified live** (no local SAM.gov key / Railway worker): after merge, set
`SAMGOV_API_KEY`, run the SAM.gov source from Admin, and confirm prospects with
downloaded plan PDFs appear in the detail view.

**PRs:** this PR (draft) — rides with the prospect-detail-view branch.

---

## 2026-06-18 (b) — C shipped: prospect detail view + send any plan to takeoff

**Context:** Task C (UI). The Prospect Queue only let you Triage/Ignore and (when
a doc was filename-classified `plan_set`) Run Takeoff — no way to open a
prospect, read its details, or see/preview the discovered drawings.

**What shipped (web-only — no API/DB/migration; all endpoints already existed):**
- **`View` button** on each Prospect Queue row → new route `/prospects/$projectId`.
- **`apps/web/src/pages/ProspectDetail.tsx`** (new): fetches `GET /projects/:id`
  and renders all project fields (address, jurisdiction, permit #, parcel, type,
  valuation, GC, score + rationale, description) plus the full **documents list**.
  Each doc shows its doc-class badge + page count, an **inline PDF preview**
  (presigned URL from `GET /project-documents/:id/url` in an iframe, fetched on
  demand + open-in-new-tab), and a **`Send to Takeoff`** button. Triage/Ignore
  mirrored in the header.
- **Send any document**, not only `plan_set` — `POST /takeoffs
  {project_document_id}` already accepts any doc, and the crawler's filename
  classifier (`run.ts` `classifyByFilename`) is rough, so a real plan can land as
  `other`. The queue's existing `plan_set`-gated Run Takeoff button is unchanged.
- **Source link** on the detail page: renders the prospect's `sourceRefs[].url`
  (the crawl origin — Socrata/SAM.gov listing) as external links, labelled by
  `external_id`.

**Verified:** `pnpm build` 11/11, `pnpm test` 18/18, `pnpm eval` 100%. **Not yet
verified live** — the presigned-URL iframe preview + takeoff-from-prospect only
fully exercise on Railway (no local API/MinIO). Confirm on deployed `scribe-web`
after merge: open a prospect with a discovered doc, preview it, send to takeoff.

**PRs:** this PR (draft).

---

## Condensed history

### 2026-06-18 (g-k) — estimate pricing + reading hardening (archived verbatim)
Drawer-box hardware (3rd CabinetNow list, one rolled-up line); branded tier-priced quote PDF; estimate prompt v3 (mandatory corners, specialty bases, fillers/end-panels, run-sized vanities, no invented cabinets); salvage parser + 32k max_tokens + streaming to stop silent kitchen drop on truncation; temperature 0 pinned on all four vision calls. Full text in the archive.

### 2026-06-10 — v1 framework (PR #192) + MinIO storage (PR #194) + boot migrate (PR #196)
Full monorepo scaffold (pnpm/Turborepo, 3 apps, 8 packages); takeoff pipeline;
Mozaik/KCD export; Socrata+SAM.gov crawler; evals harness; Railway/Docker configs.
MinIO path-style storage via Railway service + volume; boot-time migrate+seed
(advisory lock, `SKIP_BOOT_MIGRATIONS=1` opt-out). **Server state:** all captured
in "Load-bearing state" above.

### 2026-06-12 — SCR-001: login loop (PR #197); first prod deploy
Bearer-token session (OAuth fragment → localStorage → Bearer header) to work around
cross-site Railway subdomains (SameSite=Lax cookie refused on SPA fetches).
Railway services live (api/web/workers + Postgres + Redis + MinIO); Google OAuth
client; boot migrate+seed confirmed on prod. MA-001…MA-005 completed.

### 2026-06-16 — AI cross-validation toggle; SCR-002: CORS fix (PR #201)
Cross-validation: `org_settings.cross_validation_enabled` (migration 0002); OpenAI
secondary extraction; confidence lowered on disagreement; MA-010 completed
(OPENAI_API_KEY set, toggle confirmed live). CORS: `@fastify/cors` was missing
PUT/PATCH/DELETE from `methods`; fixed in PR #201 — all SPA saves now work.
SCR-002 resolved.

### 2026-06-17 — research spike (§A/B/C); A shipped: region-crop + tiling (PR #203)
Spike confirmed Sonnet downscales past 1568px (E-sheet → ~4px text); no-schedule
residential sets need estimation; public plan rooms not cleanly crawlable.
**A shipped:** `@scribe/shared/regions.ts` (18 unit tests), `locateRegions`, mupdf
clip render, large-format legible-read path in `process.ts`. Confirmed live 2026-06-18.

### 2026-06-18 (early) — B shipped (PR #204) + pricing model (doors + boxes + unify)
Estimation mode + ESTIMATE_SYSTEM + markEstimated. Reading overhaul: v2 prompt,
per-room segmentation, lenient parse. Box→door/front expansion (expandToComponents,
8 tests). Door/front $/ft² tiers anchored on Shaker Airtable rates. Cabinet-box
pricing (port of pricing.js, 0.3% vs live item). Totals unified with selected tier.
Combined result on real items: LOW −5% / MEDIUM +7% vs $27,733.68 (within 10%).

---

## PRD reference

The full product spec is `scribe/PRD.md` (v1.2, June 2026 — final). Key
invariants enforced in code: integer-cents money; immutable pricing-config
versions pinned per quote; freight-verification gate (≥ $35k or assembled
casework); NEEDS-REVIEW rate send block; unmatched lines never dropped;
ambiguous unit counts flag rather than assume; per-takeoff and daily-crawler
token budgets; crawler politeness rules (1 req/sec/host, honest UA, public
data only).

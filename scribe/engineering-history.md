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

## 2026-06-18 (k) — pin temperature 0 on takeoff vision calls (reproducible reads)

**Context:** Reprocessing the same plan gave a DIFFERENT cabinet list each run.
None of the worker vision calls set `temperature`, so they ran at the API
default 1.0 — both extraction AND the `locateRooms` region split resample every
time, compounding the drift.

**Shipped:** `temperature: 0` on the four takeoff calls — extract.ts (extract/
estimate), regions.ts (locate rooms/regions), classify.ts (page class),
spreadsheet.ts (header inference). Reads are now near-deterministic for a given
plan. (Vision isn't bit-identical even at temp 0, but variance drops sharply.)
Crawler `score.ts` left as-is (not in the takeoff path).

**PRs:** branch `scribe/fix-truncated-region-drop` (with (j)).

---

## 2026-06-18 (j) — fix silent whole-region drop on truncated extraction

**Context:** A deployed (v3) takeoff returned ONLY the bathroom + laundry
cabinets — the entire New Kitchen was missing. Cause: `extractPage` sends the
cabinet-dense kitchen crop, the model's JSON response exceeds `max_tokens`
(16000) and is truncated; `extractJson` does a hard `JSON.parse` → throws;
`readRelevantPage` catches it and `continue`s, dropping the whole region (only a
warning, easily missed). Kitchen is always the biggest region → always the one
that truncates → reproduces on every reprocess. Smaller rooms parse fine.

**Shipped (apps/workers extract.ts):**
- `salvageLineObjects(text)` — string-aware brace scanner that recovers every
  complete `{...}` from the `"lines"` array when the top-level parse fails
  (truncation only loses the last, incomplete cabinet). Used as a fallback when
  parse throws or yields zero lines, so a region is never silently emptied.
- Raised `max_tokens` 16000 → **32000** (billed only for tokens used) to avoid
  truncation in the first place. At that ceiling the SDK refuses a non-streaming
  request ("Streaming is required for operations that may take longer than 10
  minutes"), so the extract call now uses `messages.stream(...).finalMessage()`
  — same Message shape, same per-token cost. Re-validated live after the switch:
  no error, kitchen present, 23 boxes, MEDIUM −7% / HIGH +7% (within 10%).
- Surface a visible "response truncated (max_tokens) — verify" uncertainty when
  `stop_reason === max_tokens`, so a partial read is never silent again.

Tests: workers 13 pass incl. 3 new salvage cases (truncated mid-array; braces
inside strings; no-array). The earlier verbose `[ESTIMATED] …` notes inflate
output length and were the practical trigger.

**PRs:** branch `scribe/fix-truncated-region-drop`.

---

## 2026-06-18 (i) — estimate prompt v3: corners, specialty bases, fillers, vanity sizing

**Context:** Comparing our reprocessed takeoff to the real Piestewa quote
(pages 27-28) showed the reading under-detects: ~17 boxes vs the quote's 29. It
missed corners (Easy-Reach / Blind), specialty bases (Oven/Trash/Microwave),
fillers + end panels, Base Full-Height fridge surrounds, deep/wide wall runs;
rounded odd widths to standard; undersized the double-sink vanity (read 36" vs
77"); and invented Island/Bev-Fridge/Optional-Wall units not on the plan.

**Shipped:** `@scribe/prompts` estimate prompt → **v3** (`estimate-v3`):
- CORNERS MANDATORY — one corner cabinet at every inside corner where runs meet
  (Easy-Reach Corner Base/Wall, or Blind Corner when runs are unequal).
- Explicit specialty bases listed individually: Oven Base, Trash Pullout Base,
  Microwave Over Drawer Base.
- Fillers (1-3") + End Panels (~1.5") to make runs sum — emitted as
  casework_base with "Filler"/"End Panel" in the tag so expand.ts skips
  faces (no phantom doors) but they still box-price.
- Fridge surround modelled as Base Full-Height end panels + deep wall/bridge.
- Vanity sized to the FULL run; double-sink = one wide 4-drawer unit, not 36".
- Keep the odd width a run requires (37.25", 49.375"); don't force round numbers.
- Don't INVENT cabinets that aren't drawn (no "optional"/"beverage fridge").

Tests: shared 54 pass incl. new filler/end-panel & "cubbies" → no-faces coverage.

**Validated live** (estimate-floorplan.mjs on the 2440 E Piestewa plan):
box count **25 units / 24 types** (was ~17; quote = 29/24), and full tier
pricing **MEDIUM $27,721 = −0%** vs the $27,733.68 subtotal (LOW −11%, HIGH
+14%). v3 now emits the corners (Easy-Reach Corner Base/Wall), Oven Base, fridge
full-height surround panels, and run-sized vanities (38.5/30/27) it used to
miss. Follow-on fix: expand.ts no-faces regex now also catches "cubbies"
(plural) + appliance/range slots (was spawning ~$360 of phantom doors on the
open CUBBIES unit). Residual: still a few boxes short of 29 (no Trash Base /
Blind Corner / multi Base-Full-Height — partly plan-specific), and a "Range
Base" appliance-slot is still emitted as a box.

**PRs:** branch `scribe/drawer-box-hardware`.

---

## 2026-06-18 (h) — branded quote PDF + tier-priced itemized list

**Context:** The "Generate PDF" output was barebones — rows OVERLAPPED (a
long Tag wrapped but the row only advanced one line, so the next row crashed
into it), no branding, and it showed the OLD product-line subtotal ($10,962)
instead of the tier estimate the web UI shows.

**Shipped:**
- Rewrote `apps/api/src/lib/quote-pdf.ts`: per-row height = max cell height
  (`heightOfString`) so nothing overlaps; CabinetNow maroon header/title band +
  quote meta; room-grouped rows (subheaders) with zebra striping; right-aligned
  money; totals box; tier label. Verified with a render preview.
- New `priceQuoteLineItems(lines, tier)` in `@scribe/pricing` (single source of
  truth): prices each read line for the tier (boxes per unit, doors/fronts by
  ft²) + ONE rolled-up hardware row; items sum to subtotal. Exported
  `TIER_BOX_SPECIES`.
- `POST /quotes/:id/pdf?tier=` now prices via the tier model (was product-line
  `run`); web passes the selected tier. PDF + web now show the same number.

**Confirmed against the real quote (pages 27-28):** CabinetNow's quote IS three
lists — Doors/Fronts, CABINET BOXES (incl. a Toe Kick Skin line), DRAWER BOXES &
HARDWARE (Dovetail boxes + Blum 563H glide kits ×9 + Bulk Shelf Pins ×3) —
SUBTOTAL $27,733.68 − 10% = $24,960.31. Exactly the reverse-engineered model.

**Open (reading, next):** extraction under-detects/mis-sizes vs the real 29-box
list — misses corners (Easy Reach / Blind Corner), specialty bases (Oven/Trash/
Microwave), fillers/end-panels/toe-kick, Base Full Height, Deep Wall, big wall
runs; rounds widths (37.25→36, 49.375→40, 77→36) and undersizes the double-sink
vanity; invents Island/Bev-Fridge/Optional-Wall. Glides/pins/toe-kick still
unpriced. Persist tier server-side (currently query param, default medium).

**PRs:** branch `scribe/drawer-box-hardware`.

---

## 2026-06-18 (g) — drawer-box hardware: CabinetNow's 3rd list (one rolled-up line)

**Context:** The tier estimate priced only CabinetNow's first two lists (doors/
fronts by ft², cabinet boxes per unit). The third list — drawer boxes + hardware
— was missing, so the estimate ran ~9% light.

**Shipped:** ported the live store's `pricing.js` `drawerBoxes()` formula into
`@scribe/pricing` `hardware.ts` (per box: perimeter = 2·W+2·D; a tier line
`slope·perimeter+intercept` picked by drawer-front HEIGHT; then
`((tier×materialMult)+$10.06)×1.5`). `priceHardware(lines)` makes **one dovetail
drawer box per `drawer_front` face** (the expand step already emits those) and
sums to a **single rolled-up "Hardware" subtotal** (not a line per piece, per
owner). Wired into `priceQuoteTiers` as a constant across tiers (drawer-box
species isn't the rep's door-style choice — matches how CabinetNow's lists #2/#3
stay flat). QuoteBuilder shows boxes + doors/fronts + hardware in the breakdown
and Totals. Back-test on the Piestewa quote: 18 boxes add ~$2,387, LOW now
**+3%** vs $27,733.68 (was −5% without hardware).

**Open:** glides, shelf pins & toe-kick skin are option SKUs (not formulas in
pricing.js) — still not modelled, but they're the small remainder. The live
under-count (~20 vs ~29 boxes, reading completeness) still applies.

**PRs:** branch `scribe/drawer-box-hardware`.

---

## Condensed history

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

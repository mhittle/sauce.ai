# sauce.ai/scribe — bug log

Log every owner-reported bug here with a new sequential ID and status `open`
BEFORE doing anything else with it (even a 30-second fix). Statuses: `open` ·
`in-progress` · `attempted` (tried, not fully fixed — note the live
workaround) · `resolved`.

Format:
```
### SCR-NNN — <short title>
- **Status:** open
- **Reported:** YYYY-MM-DD by <user|session>
- **Description:** …
- **Notes / fix:** …
- **PR:** #NNN
```

---

## Open

### SCR-014 — Raw pipeline errors and read notes shown to customers
- **Status:** resolved (this PR; prod verify after deploy)
- **Reported:** 2026-09-15 by owner (Jobs list showing the SQL of the SCR-011 failure in red; review notes showing "measurements response was not valid JSON — 22 complete cabinet answers salvaged, nothing defaulted")
- **Description:** `takeoffs.error`, `docSummary.warnings` and `takeoff_detections.error` are written by the worker in developer language (SQL, model-answer diagnostics) and rendered verbatim on the Jobs list, the wizard, the review's "notes from the read" panel and the failed screen. This is a customer-facing app: the copy must be short and calm for the customer, while the developer still needs to see what happened.
- **Notes / fix:** `apps/web/src/messages.ts` maps every known error/note pattern to one plain sentence (`friendlyError`, `friendlyNote`, `friendlyNotes`; unknown notes get a generic line, developer-only notes such as a salvage that changed nothing or a cross-validation skip are hidden from customers). `TechnicalDetail` shows the raw text under a "Technical details (admin)" toggle for `role === "admin"` only. The worker keeps writing the technical sentence — it is the evidence. 11 web tests.
- **PR:** this PR

### SCR-013 — Measuring step fails in prod; wizard does not land on the review
- **Status:** in-progress (#274 merged → owner verifies on prod, then resolved)
- **Reported:** 2026-09-15 by owner (MOLLY_CHARLEY_KITCHEN, 24 cabinets / 3 elevation areas)
- **Description:** First report: Build ran ~2 min, then every cabinet came
  back 30" @ 50% with the note "measurements response was not parseable JSON
  — sizes defaulted". After #272 deployed the owner reports Build and
  "Measure again…" STILL error on the measuring step and they end up back on
  the wizard, not the review page.
- **Notes / fix:** #272 raised the measure call to 32k tokens, checks
  `stop_reason`, salvages complete cabinet objects from an unparseable
  answer, retries once, and throws (with rollback) when no usable sizes come
  back twice; raw answers persist as `takeoffs/{id}/beta/measure/response-N.txt`.
  **Evidence (2026-09-15, prod DB via the API + Railway worker logs, 7-day
  window):** no `beta build failed` after #270 (18:45 UTC 09-13) and no
  BullMQ `job failed` at all; the two rows on the Jobs list still showing
  `build takeoff failed: … = ANY((…))` are the pre-#270 jobs (18:41 UTC),
  parked at `awaiting_boxes` by design. Post-#272 builds: 40f9cb79
  (end_turn, 16.6k chars, 24/24, clean JSON) and 0a26eb66 (end_turn, 7.4k
  chars, 25/25 recovered by salvage, 3 estimated) — both reached `review`,
  and lines on 0a26eb66 carry `reviewerEdited` at 19:13 UTC, so the wizard
  did forward. No `remeasure` was ever queued. The reported symptom is not
  reproducible from the data; what is real is that 2 of the last 3 prod
  answers were not parseable as a whole (all 18 kits are), and the review
  said "the rest defaulted" when nothing had. #274: balanced-scan
  `extractJson` (prose/fences before and after, trailing commas), parse
  path + defaulted count in the warning, head/tail of any non-clean answer
  in the worker log, and a failed re-measure now shows on the review with
  a Measure again button. Routing untouched (evidence says it works).
  The stored `response-0.txt` for 0a26eb66 and 8a8e3914 were NOT pulled
  (no API route exposes them) — owner can read them from the MinIO console
  if the exact wrapper matters.
  **2026-09-15, cause found (Railway `measure answer was not clean JSON`
  warn line from #274, takeoff 99656b83, 22/22 cabinets salvaged):** the model
  wrote a markdown work-through of every marker BEFORE the JSON ("**Marker
  1:** … width 14" (from chain [y≈149]: 14) …") and the JSON object at the
  end. `extractJson` tried at most 8 candidate brackets, and the preamble
  had more than 8 `[y≈…]` brackets, so it gave up before reaching
  `{"cabinets"` and the salvage path ran. Fixed: every candidate is tried
  (this PR); the answer now takes the `json` path. The model reasoning out
  loud is not itself a fault — "JSON only" is a request the model ignores on
  a hard 4-page task — the parser has to accept it. Structured outputs (SDK
  bump) would make it moot; in the measurement plan.
- **PR:** #272 (partial), #274 (parse + visibility), this PR (preamble with >8 brackets)

### SCR-010 — Door swings priced as cabinets on plan reads
- **Status:** resolved (prompt fix; existing takeoffs need a re-run)
- **Reported:** 2026-08-18 by owner (takeoff a6e317a3, Piestewa floor plan)
- **Description:** The review screen showed a "bath vanity NEW 2668" line whose
  box looked slightly off the vanity. It is not an offset: the box sits exactly
  on the DOOR SWING (arc + leaf) tagged `NEW 2668` — a 2'-6" x 6'-8" door — in
  Bath 3. The real vanity is the sink to its left. The rendering is fine; on the
  same page the sink base, dishwasher, range and microwave boxes all land dead
  on their objects. The detector was counting a door as a cabinet and inheriting
  the door's schedule tag as the cabinet's name.
- **Notes / fix:** detect-v5 forbids boxing a door swing, its leaf, its callout,
  a lone plumbing fixture, stairs, or a dimension string — in any view. Shared
  `stripDoorCallout` scrubs a door tag out of any name that still arrives
  ("bath vanity NEW 2668" → "bath vanity", raw text kept as note provenance).
  Takeoffs already in review keep the bad line until re-run.
- **PR:** this PR

### SCR-006 — Estimate reads vary wildly run-to-run (same plan, temp 0)
- **Status:** attempted (variance tamed; under-read bias remains → SCR-004)
- **Reported:** 2026-06-29 by session (CRM backtest)
- **Description:** The same floor plan gives very different box counts across
  identical runs even at temperature 0 — e.g. Piestewa returned 5, 21, and 24
  boxes on three runs. Makes any single-run estimate unreliable and makes prompt
  tuning fight noise.
- **Notes / fix:** 2026-06-29 (b) — pipeline-side **median-of-N consensus** added
  to `process.ts` (estimate pages read N times) via shared `pickMedian`; env
  `ESTIMATE_CONSENSUS_N` (default 3). Mirrored in the harness so a single run is
  prod-equivalent. Q8 went 5/21/24 → 19/19/24 — the catastrophic outlier is gone.
  2026-06-29 (c) — consensus now selects the median by `boxFaceArea` (a quote-total
  proxy = Σ width×height), NOT box count: two reads with the same count can price
  −6% vs −28% by size. NOT yet deployed. Residual spread is sizing/under-read bias
  (SCR-004), not selectable noise.

### SCR-005 — Single-image inputs estimate almost nothing
- **Status:** open
- **Reported:** 2026-06-29 by session (CRM backtest, Q2/Q10)
- **Description:** A single low-detail render/photo (e.g. `image_(2).png`) yields
  ~2 boxes → −92% vs the real quote. The estimator needs a plan-like layout; one
  marketing render isn't enough. (Q10's cleaner image did land +8%, so it's
  image-quality dependent.)
- **Notes / fix:** needs a distinct path for image/sketch inputs, or a prompt that
  extracts more from a single elevation/render. Also: scribe-web rejects JPEG
  uploaded as PNG (media-type mismatch) — separate intake bug to confirm.
  2026-07-01 (c) — **quantified by the reading scorer:** image class F1 0.17
  (Q2 recall 0%), image/sketch 0.09 (Q11) — the worst classes. Fix likely rides
  the detector (H3) + an OCR/upscale front-end, not prompt tuning.

### SCR-004 — Estimator under-reads large multi-room / multi-page plans
- **Status:** open
- **Reported:** 2026-06-29 by session (CRM backtest, Q1/Q3/Q6)
- **Description:** Whole-house / multi-page architectural sets return far too few
  boxes (Q1 7-pg → ~18 boxes, −38%; Q6 6-pg → ~20, −33%; Q3 −25%). The estimate
  prompt v4 "realism cap" may also over-suppress on these.
- **Notes / fix:** likely per-room locate + read each room thoroughly; balance
  against over-reading. Carefully — pushing "find more" risks hallucination.

### SCR-003 — Estimator over-reads kitchens shown as plan + elevations
- **Status:** attempted (page-role router shipped in PR #221 2026-07-01 —
  over-read tail fixed, MAE 59→34; introduced the SCR-007 under-read tail, refine next)
- **Reported:** 2026-06-29 by session (CRM backtest, Q5/Q7/Q9)
- **Description:** A kitchen drawn as a plan AND several wall elevations gets
  enumerated once per view and summed → 2–4× over-count (Q7 81 boxes for one
  kitchen, +114%). Two sub-causes: (a) per-view re-enumeration with no cross-view
  dedup, (b) model over-splitting one sheet into ~37 cabinet "types".
- **Notes / fix:** cross-view collapse + whole-page-once + cross-page dedup ported to
  `process.ts` (2026-06-29 b). 2026-06-30 — **ROOT-CAUSED on the 21-quote set** (over-read
  is the dominant failure: Q19 +257%, Q21 +176%/277 box, Q14 +169%, Q24 +132%, Q7 +60%).
  Per-page/per-room diagnostics show: an authoritative count source exists (plan /
  schedule / one elevation), then **elevation pages RE-ENUMERATE the same cabinets** and
  the dedup can't merge them because the model's room/tag labels differ across views
  (Q14: plan 19 + 3 elevations +27; Q24: one vanity run on 2 pages 11+10; Q19: schedule
  + 8 elevations +52). **Planned fix = page-role router: one authoritative count per room
  (`schedule > floor_plan > single best elevation`), elevations refine sizes only.** The
  label-based `collapseCrossViewDuplicates` is too fragile and is being superseded.

## In progress

_None._

## Attempted (live workarounds / ongoing risk)

_None._

## Resolved

### SCR-011 — Build fails in prod with `… = ANY(($2, $3, …))`
- **Status:** resolved
- **Reported:** 2026-09-15 by owner (MOLLY_CHARLEY_KITCHEN; Find found 8 cabinets, Build errored)
- **Description:** Scoped deletes used `sql\`… = ANY(${ids})\``; drizzle
  expands a JS array into a parameter LIST, which Postgres rejects. It failed
  AFTER lines were inserted and `built_at` stamped, so the area read "in
  takeoff" with unpriced lines and Build had nothing to do.
- **Notes / fix:** `inArray()` at all three sites; `built_at` stamped only
  after pricing; rollback of inserted lines/faces on failure; self-repair of
  never-priced lines in build-takeoff; live progress during builds; jobs
  `attempts: 2`.
- **PR:** #270

### SCR-012 — Wizard parks on "Update 0 areas" after a successful build
- **Status:** resolved
- **Reported:** 2026-09-15 by owner
- **Description:** After Build finished the wizard stayed on the Build step
  instead of opening the review.
- **Notes / fix:** wizard forwards to `/takeoffs/:id` when status goes
  `processing → review`; "Open the review →" when nothing is unbuilt.
- **PR:** #271

### SCR-007 — Router under-reads elevation-authoritative plans
- **Status:** resolved (via `ROUTER_TOLERANT_MERGE=1`, LIVE on scribe-workers
  since 2026-08-12; kit macro F1 0.328 → 0.379; live Braun read went 5 → 23
  cabinets)
- **Reported:** 2026-07-01 by session (page-role router backtest)
- **Description:** The SCR-003 page-role router counts the floor plan and DROPS
  elevations. On docs where the cabinet detail lives in the elevations this
  throws away the real count (Q5, Q13, Q22, Q23, Q6 severe under-reads).
- **Notes / fix:** tolerant merge (PR #232, gated) keeps the authoritative
  role and RE-ADMITS demoted-role units no kept unit matches (cat, ±3"w/±6"h).
  Elevation-primary ordering also built + measured (PR #236) — ≈ equal on the
  kits (0.376), left gated. The planned document-class routing was superseded.
  Residual: cross-view SIZE-disagreement duplicates survive the merge (Wantoch
  island: plan 3×36" + elevation 21"/15" of the same island) → room-keyed
  reconciliation on the roadmap.
- **PR:** #232 (merge, gated), #236 (elevation-primary A/B); env flip by owner.

### SCR-008 — Sideways plan pages render rotated and garble label reads
- **Status:** resolved
- **Reported:** 2026-08-11 by owner (Braun webdownload elevations)
- **Description:** Landscape sheets drawn ROTATED on portrait pages with no
  /Rotate flag rendered sideways; the model read rotated label text and
  garbled sizes ("Oven Fridge Tall 18" for "36\" OVER FRIDGE"). mupdf honors
  /Rotate — these pages simply have sideways content.
- **Notes / fix:** `openPdf` detects dominant text orientation (bbox aspect +
  baseline-anchor direction) and serves dims/renders/crops/fragments in
  normalized upright space; 8 tests pin the empirically-probed mupdf
  conventions (rotate(90)=raster CW; region bboxes shift −rawH/−rawW).
- **PR:** #237

### SCR-009 — Quotes list total ≠ Quote Builder tier price
- **Status:** resolved
- **Reported:** 2026-08-13 by owner ($34,141 list vs $49.8k–$65.3k builder)
- **Description:** Stored quote totals came from the legacy per-line engine
  while the builder displayed the validated tier estimate with tier choice in
  client state only — two numbers for one quote (and the stored one was −53%
  vs the real Wantoch quote; the tier engine was within 6.3%).
- **Notes / fix:** `quotes.pricing_tier` persisted (migration 0005); stored
  subtotal/total derive from the tier at create + patch; tier click PATCHes;
  PDF defaults to the persisted tier. Pre-existing quotes re-price on first
  PATCH.
- **PR:** #238

### SCR-002 — All SPA "save" actions (PUT/PATCH/DELETE) blocked by CORS
- **Status:** resolved (fix deployed; owner confirmed the AI cross-validation
  toggle persists 2026-06-16)
- **Reported:** 2026-06-16 by owner (found while testing the AI cross-validation toggle)
- **Description:** Flipping the admin "AI Cross Validation" toggle did nothing
  with no error. Confirmed via the browser: clicking only fired the `OPTIONS`
  preflight (204) — no `PUT` followed. The API's CORS response advertised
  `Access-Control-Allow-Methods: GET,HEAD,POST`, so the browser refused to
  send the actual `PUT`. web and api are cross-site (different
  `*.up.railway.app` subdomains), so this affected EVERY mutating call from the
  SPA (org-settings, pricing edits, line PATCH/DELETE, export templates,
  sources) — it was just latent because no PUT had been exercised in prod yet.
- **Notes / fix:** `@fastify/cors` was registered without an explicit
  `methods` list; set it to include PUT/PATCH/DELETE (+OPTIONS) in
  `apps/api/src/app.ts`. Deployed via `scribe-api` redeploy.
- **PR:** #201

### SCR-001 — Login loops back to the sign-in screen on Railway domains
- **Status:** resolved (owner logging in and using the app normally as of
  2026-06-16)
- **Reported:** 2026-06-12 by owner
- **Description:** Google sign-in completes but the app returns to the login
  screen. Root cause: web and api run on different `*.up.railway.app`
  subdomains, and `up.railway.app` is on the Public Suffix List, so the
  browser treats them as cross-site and refuses to send the API's
  SameSite=Lax session cookie on the web app's fetches → `/auth/me` 401s.
- **Notes / fix:** bearer-token session path: OAuth callback passes the
  session token to the web app in the URL fragment; web stores it in
  localStorage and sends `Authorization: Bearer`. Cookie path kept for
  top-level navigations (CSV export) and a future same-site custom domain.
  New web bundle verified live in prod 2026-06-12.
- **PR:** #197

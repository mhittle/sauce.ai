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

### SCR-004 — Estimator under-reads large multi-room / multi-page plans
- **Status:** open
- **Reported:** 2026-06-29 by session (CRM backtest, Q1/Q3/Q6)
- **Description:** Whole-house / multi-page architectural sets return far too few
  boxes (Q1 7-pg → ~18 boxes, −38%; Q6 6-pg → ~20, −33%; Q3 −25%). The estimate
  prompt v4 "realism cap" may also over-suppress on these.
- **Notes / fix:** likely per-room locate + read each room thoroughly; balance
  against over-reading. Carefully — pushing "find more" risks hallucination.

### SCR-003 — Estimator over-reads kitchens shown as plan + elevations
- **Status:** attempted (partial)
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

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
- **Status:** open
- **Reported:** 2026-06-29 by session (CRM backtest)
- **Description:** The same floor plan gives very different box counts across
  identical runs even at temperature 0 — e.g. Piestewa returned 5, 21, and 24
  boxes on three runs. Makes any single-run estimate unreliable and makes prompt
  tuning fight noise.
- **Notes / fix:** worked around in testing with median-of-3 (`run-median.sh`).
  Real fix TBD: pipeline-side median-of-N, or stronger determinism in
  locate/extract. Top priority for the reading-accuracy work.

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
- **Notes / fix:** partial fixes on branch `scribe/estimate-reading-accuracy`:
  cross-view collapse + whole-page-once (Q7 81→55), non-estimate cross-page dedup
  (Q9 +72%→+7%). Harness-only fixes must be ported to `process.ts`. The model
  over-splitting (Q7) is prompt/model-quality — not fully solved.

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

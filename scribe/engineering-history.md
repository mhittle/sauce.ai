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
- **Size limits are Admin-set only (2026-10-20):** `product_lines.size_limits`
  (empty = none) is enforced; the seed `dim_bounds` in price lists v1–v3 are
  ignored on purpose — don't re-enable them.
- **Seeded pricing rates were placeholders**; real rates entered by the owner
  (MA-006, confirmed 2026-10-20). Quotes pin their pricing config — a quote
  built on the old placeholder config stays unsendable; build a new one. Seeded Socrata field maps
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
- **Stacked PRs: delete the base branch on merge, or the stack never reaches
  main.** 2026-09-13: #255/#256/#257 were each based on the PR below them;
  GitHub only retargets a stacked PR to `main` when its base branch is
  DELETED, so each one merged into the feature branch below it and `main`
  got PR 1 only while all four showed "merged". Fixed by #260 (the PR 3
  branch, which contained all the merges, opened against `main`). Either
  base every PR on `main`, or merge bottom-up and delete each branch.
- **Email sends via SMTP once MA-013's variables are set (2026-10-21).**
  `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASS`/`EMAIL_FROM` on
  `scribe-api` (Gmail, ridadarwish12@gmail.com, app password). Unset → every
  invite, magic link and receipt is only LOGGED and the admin copies links
  from Admin → Users. Gmail caps ~500/day.
- **Migration 0014 created the platform org "CabinetNow"** and backfilled
  every pre-existing user, takeoff, quote, customer and eval_fixture into
  it. `orgs.is_platform` marks it; machine users (dev bypass,
  signal-connector) are created there by `getPlatformOrgId()`. Only users
  who had `role = 'admin'` were promoted to `is_platform_admin` — anyone
  else needs the Admin → Users checkbox (MA-014) or they see no Admin tab.
- **The Google OAuth consent screen is still in TESTING mode** (external
  publishing is MA-015), so Google sign-in is capped at 100 hand-listed
  test users. Invited users can still sign up and sign in by email link
  once MA-013 is done — the cap only binds the Google button.
- **`org_settings.sample_takeoff_id` is unset**, so new sign-ups land on an
  empty Jobs list and the tutorial's sample step is skipped (MA-016). The
  sample must be a plan set we may show strangers; the test kits are
  customers' drawings.
- **Local dev recipe (verified 2026-09-22, no new services installed):**
  brew Postgres 14 already on 5432 (`createdb scribe_dev`) and the
  already-running Docker Redis on 6379; api on **3011**, web on **5174**
  (3001 and 5173 are the owner's other servers — never take them). From
  `scribe/`, after `pnpm build`:
  ```
  DATABASE_URL=postgres://localhost:5432/scribe_dev REDIS_URL=redis://localhost:6379 \
  NODE_ENV=development PORT=3011 API_PUBLIC_URL=http://localhost:3011 \
  WEB_PUBLIC_URL=http://localhost:5174 SESSION_SECRET=local-dev-secret \
  AUTH_ALLOWED_EMAILS=mhittle@gmail.com,ridadarwish12@gmail.com \
  node apps/api/dist/server.js
  (cd apps/web && VITE_API_URL=http://localhost:3011 npx vite --port 5174 --strictPort)
  ```
  Migrations apply at boot. Dev-bypass signs you in as the local admin
  (`GOOGLE_CLIENT_ID` unset); object storage is NOT configured, so plan and
  logo uploads fail locally by design — the invite → sign-up → account flow
  does not need them.
- **Usage ledger needs a rate per model (2026-10-02, #309).** Every model
  call writes a `usage_events` row costed from `model_rates`; a model id with
  no rate row (exact or alias prefix) is skipped with a log line. Before
  changing `VISION_MODEL` / `OPENAI_VISION_MODEL`, add its rate in a
  migration. Rates are never updated — a price change is a new row.
- **Billing state (2026-10-19):** usage ledger (#309, 0017) and credits
  (#310, 0018) live; Stripe page packs (#323) merged code but OFF until
  `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET` are set on `scribe-api`
  (MA-017). The webhook credits only `checkout.session.completed`, paid,
  amount == the pack price in `PAGE_PACKS` — changing a pack price means a
  code change, not a Stripe dashboard change.
- **Credits are RECORD-ONLY (2026-10-02, #310).** `platform_settings.
  credits_enforced = false`: holds/settles happen and balances can go
  negative, nothing is blocked. Prerequisites for ticking "Block jobs the
  balance can't cover" (Admin → Credits): Stripe live (MA-017) and the
  hourly hold sweep (2026-10-20, `credits.sweep` queue on scribe-workers,
  `CREDIT_HOLD_SWEEP_HOURS` default 24) — both now in code.
- **`ROUTER_TOLERANT_MERGE=1` is SET on `scribe-workers`** (owner, 2026-08-12)
  — the demoted-role re-admit merge is LIVE prod behavior (kit-measured 0.379
  vs 0.328 baseline). Removing the var reverts to the plan-only router and
  silently re-breaks elevation-heavy docs. `ROUTER_ELEVATION_PRIMARY` exists
  gated but is NOT set (measured ≈ equal; don't set without new evidence).

---

## 2026-10-22 — redeploy trigger (Railway deploys were paused)

#330 (SMTP + CSV invites) merged 2026-10-21 but never deployed: Railway's
`scribe api` page showed "Limited Access — Deploys have been paused
temporarily" and prod stayed on #329; the owner's new `SMTP_*` variables
were staged but not live either. This docs-only PR exists to give Railway a
fresh `main` commit under `scribe/` to build once deploys are allowed again.
Verify after it lands: `/admin/invites/import` answers 400/401 (not 404),
Admin › Users shows "Invite from a CSV", and `emailConfigured` is true.

---

## 2026-10-21 — SMTP email (nodemailer) + invites by CSV; placeholder invite copy

**Owner asks.** Send email through SMTP (Gmail, ridadarwish12@gmail.com)
instead of waiting on Resend; an "Import CSV" for bulk invites with a
downloadable one-row template; invite text "This is a test invitation"
while the real wording is written.

**Shipped.** `packages/email`: nodemailer SMTP transport when `SMTP_HOST`
+ `SMTP_USER` + `SMTP_PASS` + `EMAIL_FROM` are set (465 = TLS, else
STARTTLS); Resend REST next; else log-only. A failed SMTP send logs
`email send failed (smtp)` with the code and returns `sent: false` — the
invite still exists and its link is shown. Invite wording lives in
`INVITE_SUBJECT` / `INVITE_INTRO` (templates.ts) — placeholder now.
`@scribe/shared` `parseInviteCsv` / `INVITE_CSV_TEMPLATE` (columns email,
name, company, pages_included, note; header variants; quotes/BOM/CRLF;
per-row errors; dedupe; 500 rows). `POST /admin/invites/import {csv}`
re-parses server-side, skips existing accounts and live invites, returns a
per-row result. Admin › Users: "Invite from a CSV" card — Download template,
Import CSV, preview with row errors, Send N invites, results with copy links.

**Verified locally.** Import: 2 created with links, existing user skipped,
bad email + duplicate reported by row, re-import skipped as already invited;
unreachable SMTP logged and did not fail the invite; UI preview rendered.
NOT exercised: a real Gmail send (owner sets the vars — MA-013).

---

## 2026-10-20 (f) — size limits are an Admin setting (owner: "something I can control")

After #328 removed the hard-coded limits, the owner asked for limits they
control. **Shipped:** `size_limits` per product (`SizeLimits` in
`@scribe/shared`, min/max per width/height/depth, each end optional, empty
by default) — a NEW field, so the old seed `dim_bounds` placeholders (9–48"
etc., still in v1–v3) never come back. Migration `0019_size_limits.sql`
(`product_lines.size_limits jsonb DEFAULT '{}'`). `checkSizeLimits`:
`priceLine` refuses with reason `size_limit` and a plain detail ("width 58"
is over the 48" max set for Framed Casework"); `matchLine` skips a product
whose limit the cabinet breaks so another can take it; an unmeasured
dimension is not judged. Admin › Pricing: "Size limits (inches)" row per
product; saving creates a new price-list version like any rate change, so
existing quotes keep theirs. Verified locally: set a 48" max in the UI →
v2 snapshot carries it → hand-pick of a 58" cabinet refused with that text;
a product without a limit accepts it.

---

## 2026-10-20 (e) — no size limits in pricing (owner: "let the measurements do the work")

**Context.** The 48" Framed Casework max that blocked the Albert Boyle quote
was a placeholder from the v1 seed (Claude, 2026-06-10, `seed.ts`), carried
into prod's price list v1–v3; not a CabinetNow rule. Owner: don't set limits.

**Shipped.** `@scribe/pricing`: `priceLine` no longer checks `dim_bounds`
(removed `checkDimBounds` / the `out_of_bounds` reason) and `matchLine` no
longer drops candidates by size. `dim_bounds` stays in the schema, the DB
and Admin data, but nothing enforces it. Pricing defaults an empty material
to the product's first material (the matcher's existing rule) — the two prod
lines carried `material: ""` from the old hand-pick. Applies to every price
list, including ones old quotes are pinned to, so quote `a98845a0` prices
its 58" cabinets on deploy (at the default material — check it).

**Gotcha.** Size is now never a reason a line can't be priced; a cabinet
read at a wrong size is priced at that size — the review is the check.

---

## 2026-10-20 (d) — old-rates quotes say "build a new quote" (owner ask)

`GET /quotes/:id` returns `newer_rates` (a price list newer than the
quote's pinned one exists). When the quote prices on placeholder rates and
`newer_rates` is true, the blocker reads "This quote was built with the old
placeholder rates — build a new quote to use the current rates" and a
"Build a new quote" button posts `/quotes` for the same takeoff (same name)
and opens it; the send 409 says the same. Only when the newest list is
itself placeholder does it still point admins at Admin › Pricing. Copy in
`messages.ts`. Verified locally: both branches, and the button opens a new
quote on the newest list.

---

## 2026-10-20 (c) — SCR-016: hand-picked products must be priceable (#326)

**Bug.** Quote `a98845a0` kept "2 lines could not be priced" after the owner
fixed them in the takeoff; Send disabled. **Cause (prod evidence):** the
quote re-prices live — not stale. Both lines were 58" base cabinets that no
product accepts (Framed Casework 9–48"); the "fix" was a hand-pick in the
review's unmatched bucket, which `PATCH /takeoff-lines` saved unchecked and
the review then counted as resolved. Send was blocked only by those lines
(rates real — MA-006 closed; freight not required).

**Fix.** `@scribe/pricing` `resolveForProductLine` (matcher-style
material/finish resolution + `priceLine`) and `priceIssue`; API refuses an
unpriceable hand-pick with a 422 + reason and adds `priceIssue` to every
line on `GET /takeoffs/:id` (latest price list); quote `unpriced` entries
carry the tag; review treats `priceIssue` lines as unmatched with the plain
reason; quote lists each unpriced cabinet. Copy in `messages.ts`
(`friendlyPriceIssue`, `lineSaveErrorText`).

**Gotcha (unchanged, worth knowing).** A quote pins the pricing config it
was created with; new rates never reach an old quote — build a new quote.
The Admin blocker text "enter real rates in Admin › Pricing" was
misleading for an existing quote — fixed the same day (see (d)).

---

## 2026-10-20 (b) — Stripe verified live in sandbox; custom page amounts

**Stripe sandbox round trip (prod, 2026-10-20).** Owner set test-mode
`STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET` (MA-017 steps 1–3, sandbox)
and bought 25 pages with card 4242: Railway logs show `checkout session
created` → `purchase credited` (25) → receipt `email not configured — not
sent` (MA-013); the ledger has exactly one `purchase` +25 row with the
`cs_test_…` session id. Unsigned POSTs to the webhook now return 400.

**First prod usage numbers (2026-10-20).** One real job
(Albert_Boyle_Office_CAD_16.pdf, 4 pages, the free first job — hold then
settle in the ledger): 10.8¢ total, 2.7¢/page; measure 58%, detect 33%,
classify 10%. The kit estimate for the same set was 8.4¢ (output tokens
are a floor there), so real ≈ 1.3× the kit numbers.

**Shipped.** Custom amounts (owner): `findPack("custom", pages)` prices any
5–5,000 pages at `PAGE_PRICE_CENTS` (100); checkout takes `{pack, pages}`;
the webhook re-derives the price from `metadata.pages` and still requires
amount == price. Account → Pages: "Or buy [N] pages — Buy for $N" with the
limits explained. Min 5 keeps Stripe's fixed fee from eating tiny buys.

---

## 2026-10-20 — open-hold sweep + "charge again" (#324, credits, before enforcement)

**Owner:** release holds on jobs left unfinished; a swept job that is picked
back up is charged again ("charge again", 2026-10-20).

**Shipped.** `@scribe/db` `sweepStaleHolds(db, hours)`: holds with no
settle/release whose takeoff is `processing` / `awaiting_pages` /
`awaiting_boxes` and has had no activity (hold, takeoff `updated_at`, newest
area) for `CREDIT_HOLD_SWEEP_HOURS` (default 24) are released with a note.
Workers run it hourly on a new `credits.sweep` BullMQ queue
(`upsertJobScheduler`). `reholdIfReleased` + the API's `reholdOrRefuse`:
Find (`/detections/run`) and Build (`/build-takeoff`) on a job whose hold
was released open a fresh hold (402 when enforced and short); an open or
settled hold is never charged again, and a swept free first job comes back
free. Ledger label "Pages returned" (note says failed / not finished).

**Verified locally (`scribe_dev`).** Stale abandoned job released; a job
with an area drawn within the hour kept; settled and fresh jobs untouched;
second sweep a no-op; resuming charged 3 pages once; resuming the free job
stayed free; balance = sum of deltas. Not exercised: the hourly scheduler
(local Redis down).

**Gotcha.** Image jobs are released by the sweep but only Find/Build re-hold,
and those are PDF routes — an image job abandoned and finished later another
way is not re-charged.

---

## 2026-10-19 — Stripe page packs (#323); Task 0: prod usage is empty

**Task 0 (read prod Usage, 2026-10-19).** Admin → Usage: 0 jobs / $0 since
2026-10-01 (and all-time). Not a bug: prod has ONE org (CabinetNow) and its
newest job is 2026-09-14 — nobody has run a job since the ledger shipped.
Railway (last 7 d): no `usage event insert failed`, no worker activity.
The kit estimate (4.1¢/page median) is still the only cost evidence; the
ledger is unproven end-to-end in prod until one real job runs.

**Shipped (#323).** Owner: packs 25 pages $25 · 100 $90 · 500 $400;
receipts log-only until MA-013. No Stripe SDK: `lib/stripe.ts`
(`checkoutForm` with inline `price_data`, `createCheckoutSession`,
`verifyStripeSignature` HMAC + 5-min tolerance); `routes/billing.ts`
(`POST /billing/checkout` any member, 503 when unconfigured;
`POST /billing/webhook` in its own raw-body plugin → paid +
amount == pack price → `writeLedger` `purchase`, external_ref = session id,
pre-check + 0018 unique index); `receiptEmail`; `PAGE_PACKS` in
`@scribe/shared`; `/credits` returns `packs` + `billing`; Account → Pages
buy buttons, `?purchased=1` banner polls until the row lands.

**Verified locally** with signed fake events: credited once, redelivery and
two simultaneous deliveries → one row, bad signature 400, wrong amount /
unpaid / other events ignored, receipt logged. NOT exercised: a real Stripe
round trip (MA-017 step 5).

**Manual:** MA-017 (Stripe account, `STRIPE_SECRET_KEY`,
`STRIPE_WEBHOOK_SECRET`, webhook endpoint; test mode first).

**Open.** Open-hold sweep (before enforcement); one real prod job to prove
usage + hold/settle; then live keys + enforcement.
## 2026-10-05 — session wrap-up: usage ledger + credits merged and live; Stripe next

**Context.** Session 2026-10-02→05 from the 2026-09-23 prompt: Task 1 usage
ledger, report costs, ask pricing, Task 2 credits. Task 3 (Stripe) not
started — pack prices unconfirmed.

**Shipped (both merged 2026-10-02).** #309 usage ledger (0017, Admin →
Usage, `scripts/kit-cost.mjs`); #310 credits (0018, $1/page, no minimum,
first job free, record-only, Admin → Credits). #310 was rebased onto #309
(conflicts were add/add only; both tabs and both route sets kept).

**Prod verification (2026-10-05).** All #309/#310 files on `origin/main`
(`git cat-file`); `/health/db` ok; `/admin/usage`, `/credits`,
`/admin/credits` answer 401 (route exists) — the api boots only after
migrating, so 0017 + 0018 applied. Live bundle `index-BA6beBJh.js`
contains "Model cost per job, stage, page", "First job free",
"Balances, grants, rules". Prod usage numbers NOT yet read (no session in
the app this time) — Admin → Usage is the first thing to look at next.

**Owner decisions.** $1 per page read; no per-job minimum; first job free
(any size) replaces the page grant; packs 25 / 100 / 500 pages (prices
not yet confirmed — proposal $25 / $90 / $400); enforcement stays off until
Stripe.

**Open.** Stripe (Task 3); open-hold sweep before enforcement; read prod
Usage vs the kit estimate (4.1¢/page median); MA-006/013/014/015/016 and
older MA-007/008/009/011 unconfirmed; measurement Option A/B/C; SCR-015;
SCR-013 live spot-check.

---

## Condensed history

### 2026-10-02 (b) — credits, step 3b (#310, archived verbatim)
Migration 0018 `credit_ledger` / `orgs.credit_balance` / `platform_settings`;
$1/page, first job free, hold on submit → settle on review / release on
failure; record-only until enforcement (see Load-bearing state).

### 2026-10-02 — usage ledger, step 3a (#309, archived verbatim)
Migration 0017 `model_rates` + `usage_events` (microcents); `TakeoffBudget`
writes every model call; Admin → Usage; `scripts/kit-cost.mjs` (18 kits:
4.1¢/page median by count_tokens; first real job 2.7¢/page).

### 2026-09-23 — wrap-up: accounts + tutorial live (archived verbatim)
#279–#283 merged 2026-09-21 and verified on prod; billing then unbuilt;
pricing + MA-006/013/014/015/016 left for the owner.

### 2026-09-15 (o) — onboarding tutorial (archived verbatim)
Migration 0016: sample-job clone per new org (`storage_id` shares the
original's images; writes refused on samples) + coachmark tours, progress
in `users.onboarding`. Sample is unset in prod (MA-016).

### 2026-09-15 (n) — PR D: account screens (archived verbatim)
`/account` (profile, company name/logo, team roles, teammate invites),
`requireOrgOwner`; org logo wins on that org's quote PDFs.

### 2026-09-15 (m) — PR B: sign-up + magic link (archived verbatim)
`POST /signup` (org + owner + invite consumed in one transaction, session in
the body), `/signup?token=` page, email magic link (0015 `login_tokens`).

### 2026-09-15 (l) — PR C: tenancy (archived verbatim)
Migration 0014 `orgs` + `org_id` on takeoffs/quotes/customers/eval_fixtures,
`is_platform_admin`, `req.orgId` (+ `X-Org-Id` for platform admins),
`lib/scope.ts` on every id lookup, per-org lists. Closed the cross-org leak.

### 2026-09-15 (k) — PR A: email provider + invites API (archived verbatim)
`packages/email` (Resend REST, logs without the key), migration 0013
`invites` (hashed token, 14-day expiry, credits_granted), admin invite API +
Admin → Users panel. A lost link means Resend, which rotates the token.

### 2026-09-15 (j) — accounts/credits/Stripe plan written (archived verbatim)
`accounts-plan.md`: sign-in = Google + magic link, PR order A → C → B → D,
credits schema + $1/page proposal. No code.

### 2026-09-15 (i) — wrap-up: SCR-013/014 shipped (archived verbatim)
#274/#276/#275 merged; prod `tokens_used` put reading at 1–5¢/page.

### 2026-09-15 (h) — customer-facing copy for pipeline errors and notes (archived verbatim)
`apps/web/src/messages.ts` (`friendlyError`, `friendlyNote(s)`, `friendlyAreaError`)
maps every known error/note to one plain sentence; developer-only notes are hidden
from customers; `TechnicalDetail` shows the raw text to admins only (#276). Cause of
the salvage: the model writes a markdown preamble with one `[y≈…]` per marker and
`extractJson` capped candidates at 8. **Gotcha:** a new pipeline warning string needs
a `NOTE_RULES` entry or customers see the generic line.

### 2026-09-15 (g) — measurement-accuracy plan written (archived verbatim)
`measurement-accuracy-plan.md` from the 18 kits + prod Charley builds: F1 0.47
is a COUNT problem, text-layer `nearbyDims` cap at 26% coverage, legibility
(not the printed-dim shortlist) is the gap. Options A (areas + Find count gate
+ per-area measuring, recommended, LOE 7), B (mark every cabinet), C (reviewer
pass); Step 0 is a ~$4 live per-area A/B. Awaiting the owner.

### 2026-09-15 (f) — SCR-013 evidence + #274 parse hardening (archived verbatim)
Prod DB + Railway logs showed no build failure after #270 and the wizard DID
forward; what was real is that 2 of 3 prod measure answers were not parseable
whole. #274: balanced-scan `extractJson` (prose/fences/trailing commas, every
candidate tried), `parseMeasureResponse` → `json|salvage|none` with an honest
defaulted count, a `measure answer was not clean JSON` warn carrying 400-char
head/tail, and a review-screen error banner + "Measure again".

### 2026-09-15 (d) — unparseable measuring answer → salvage, retry, re-measure (archived verbatim)
`max_tokens` 32k on the measure call with a `stop_reason` note; `parseMeasureResponse`
salvages complete cabinet objects; zero usable → one retry, then the build throws
and rolls back; `POST /takeoffs/:id/remeasure` ("Measure again…" in Review's More
menu). Each attempt persists as `response-{attempt}.txt`.

### 2026-09-15 (c) — `= ANY($list)` build failure; builds roll back (archived verbatim)
Drizzle `sql\`= ANY(${ids})\`` expands to an invalid list — use `inArray`.
`buildFromDetections` stamps `built_at` only after pricing and deletes
inserted lines on failure; self-repair for stamped-but-unpriced areas;
build progress stages; `beta_build` retries once (30 s). Full text in the archive.

### 2026-09-15 (b) — Mark step PR 2: areas own their cabinets (archived verbatim)
Migration 0012 (`takeoff_lines.detection_id`, `takeoff_detections.built_at`);
`buildFromDetections` scoped to unbuilt areas with per-area line replacement
and `priceAndExpand(..., {lineIds})`; PATCH/DELETE detection resets and
deletes its lines; `POST /takeoffs/:id/reopen`; movable/resizable areas.
Gotchas: hand-drawn review lines have NULL `detection_id`; legacy takeoffs
would double on rebuild.

### 2026-09-15 — Mark step PR 1: side panel, no pre-selection, kind + scale (archived verbatim)
Extract stage no longer locates/seeds — renders page images and parks at
`awaiting_boxes`; area kind (plan|elevation) from the Pages page type with a
per-area override (`areaKindForPage`, `PATCH …/detections/:id {kind}`); scale
computed at scan time; wizard layout rail/drawing/panel with two-way selection.

### 2026-09-14 (d) — V0 PR C measured and DROPPED (archived verbatim)
Geometry-first size merge replayed on the 18 kits: F1 0.465 → 0.465, size
error 1.64" → 1.66"; printed dims beat box×scale (0.64" vs 1.16" mean error);
the size-mismatch flag catches 3 of 18 wrong sizes at 3 false alarms. PR A/B
stay gated on main; geometry is a fallback for reviewer-drawn boxes only.

### 2026-09-14 (c) — Mark step: marked areas unmistakable; overlap guard (archived verbatim)
`BoxOverlay` areas became solid redline rectangles with label chips and ×;
a new box overlapping ≥50% of an existing area is refused with a toast
(`overlapFraction` in `BetaDetect.tsx`) so cabinets are never scanned twice.

### 2026-09-14 (b) — one flow: the wizard is the pipeline (archived verbatim)
Two PDF paths (auto staged read vs wizard) collapsed into one: after Pages the
worker locates drawings, seeds `drawn` boxes, renders wizard page images and
parks at `awaiting_boxes`; Mark → Find → Build lands on review. Quotes got a
name (migration 0011, `quotes.name`). Gotchas: a build failure restores
`awaiting_boxes`; `docSummary.seeded` tells the build which warnings to carry;
`STAGED_READS=0` is the emergency classic reader. Full text in the archive.

### 2026-09-15 (e) — session wrap-up after #272 (archived verbatim)
Session 2026-09-10→15 recap: Stage 1 UI, one flow, V0 A+B, Mark step, three
prod fixes on MOLLY_CHARLEY (#270–#272). Logged SCR-013 for the next session
with "evidence first"; owed the measurement-accuracy plan. Both done in (f)–(h).

### 2026-09-13 (c) → 2026-09-14 — V0 PR A (scale sources) + PR B (vector snap), gated (archived verbatim)
PR A: `scale.ts` (`parseScaleNote`, `chainCalibration` = densest ±10% cluster,
≥3 members; `reconcileScale` manual > chain > note > model), migration `0010`,
`PUT …/detections/:id/scale`; text-layer coverage is the ceiling. PR B:
`pdf.ts pageSegments` + `snap.ts snapBox` (window max(6 pt, 10%), ≥50%
overlap, 15% cap) under `DRAWING_SCALE=1`; 204/246 kit boxes touched, mean
move 4.3%. Gotchas: `page.run(device, Matrix.identity)`; `addPage()` needs
`insertPage`. Nothing consumes scale/snap for SIZE (PR C dropped). Archive.

### 2026-09-10 → 2026-09-13 (b) — Stage 1 UI rework, PRs 1–4 (archived verbatim)
Product pivot agreed (product-plan.md, #253). PR 1 design system (tokens via
`@theme inline`, `components/ui/`, `labels.ts`, shell Jobs/Quotes/Admin); PR 2
Jobs list + `takeoffs.progress` (migration 0009) + ReadingProgress + quotes
named by file; PR 3 Pages step + Review rework (60/40, rooms, inline product
picker, batch accept); PR 4 Quote step (tiers, gated Send, Done) + Admin port.
Stacked PRs #254–#257 never reached main until #260 (see Load-bearing state).
Full text in the archive.

### 2026-08-05 → 2026-08-18 — two-stage review → staged reads default → run decomposition (archived verbatim)
Zero-API read kits + step attribution (router role-drop was the top loss;
`ROUTER_TOLERANT_MERGE` 0.336→0.379). Two-stage human review (migration 0004,
prepare/extract/finalize jobs, bbox provenance), then the box gate removed
(review = interactive editor, faces keyed by `raw_model_output.parent`),
sideways-page normalization in pdf.ts, quote tier persisted (migration 0005).
Beta detect wizard (`takeoff_detections`, migrations 0006/0007) → staged reads
DEFAULT (#247; `STAGED_READS=0` reverts); fontconfig incident fixed by
fonts-dejavu-core in the workers image. measure-v6/detect-v5: plan runs
decompose into units via legible region crops (plan-kind kits 0.13→0.32, set
0.42→0.47), door swings excluded (SCR-010), review zoom/pan + dots. Full text
in the archive.

### 2026-06-18 (c)–2026-07-06 — reading-accuracy campaign (archived verbatim)
Prospect detail view (#218); drawings-only crawl (SAM.gov active, migration 0003).
CRM backtest vs 10→21 real quotes: pricing validated, READING is the gap; over-read
root-caused to cross-view re-enumeration. Median-of-N consensus (SCR-006), area-aware
pick, page-role router (over-read MAE 59→34; #226), text-layer schedule extractor
(Class 1), per-line reading ruler (scoreReadingDetailed, labels v1→v3), owner decision
H3: prompt/vision-only. Gated levers: ESTIMATE_PROMPT=precision, DIM_SKELETON
grounding, header-driven packet parsing. Full text in the archive.

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

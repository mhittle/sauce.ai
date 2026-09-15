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
- **Stacked PRs: delete the base branch on merge, or the stack never reaches
  main.** 2026-09-13: #255/#256/#257 were each based on the PR below them;
  GitHub only retargets a stacked PR to `main` when its base branch is
  DELETED, so each one merged into the feature branch below it and `main`
  got PR 1 only while all four showed "merged". Fixed by #260 (the PR 3
  branch, which contained all the merges, opened against `main`). Either
  base every PR on `main`, or merge bottom-up and delete each branch.
- **`ROUTER_TOLERANT_MERGE=1` is SET on `scribe-workers`** (owner, 2026-08-12)
  — the demoted-role re-admit merge is LIVE prod behavior (kit-measured 0.379
  vs 0.328 baseline). Removing the var reverts to the plan-only router and
  silently re-breaks elevation-heavy docs. `ROUTER_ELEVATION_PRIMARY` exists
  gated but is NOT set (measured ≈ equal; don't set without new evidence).

---

## 2026-09-15 (n) — PR D: account screens (profile, company, team, teammate invites)

**Shipped.** `routes/account.ts` (`requireUser`; owner writes behind the
new `requireOrgOwner`, which platform admins also pass): `PATCH /me
{name, phone}`; `GET /account` (me, org with signed logo URL, members,
pending invites for this org); `PATCH /account/org {name}`; `POST
/account/org/logo` (PNG/JPEG → `orgs/{org}/logo-*.{ext}`,
`orgs.logo_s3_key`); `PATCH /account/members/:id {org_role}` (no
self-demotion); `POST /account/invites {email, name?}` → an invite with
`org_id` set (joins the org, no new org, no credits) via the shared
`createInvite` in `routes/invites.ts`; `DELETE /account/invites/:id`.
Quote PDF uses the org's logo when set, else the platform logo. Web:
`pages/Account.tsx` at `/account` (You / Company / Team cards; members see
read-only), "Account & team" in the account menu above Sign out.

**Gotchas.** (1) An admin's platform-level invite (Admin → Users) with no
company name makes an org named after the person; owners rename it here.
(2) Members cannot be removed yet (users carry FKs from takeoffs/quotes);
demote to member instead — removal is a follow-up. (3) `orgSettings`
quote terms/footer stay platform-wide.

---

## 2026-09-15 (m) — PR B: sign-up page + email magic link

**Shipped.**
- `POST /signup {token, name, phone?}` (public): pending invite → one
  transaction creates the org (`invite.org_name ?? name`; or joins
  `invite.org_id`), the user (`estimator`, org `owner` for a new org,
  `terms_accepted_at/version/ip`, `last_sign_in_at`) and consumes the
  invite; the session token is set as the cookie AND returned in the body
  (`session`) — the SPA stores it (`setSession`) and goes to Jobs. 409 with
  `state` when the invite is used/revoked/expired or the email already has
  an account.
- Web `/signup?token=…` (`pages/Signup.tsx`, renders without a session):
  looks the token up, shows plain copy for invalid/used/revoked/expired,
  else the form — email read-only, name (prefilled from the invite),
  phone optional, "By continuing you agree to the Terms and Privacy
  Policy" (links from `TERMS_URL` / `PRIVACY_URL` on the api, plain text
  when unset).
- Magic link: migration `0015_login_tokens.sql`; `POST /auth/magic-link
  {email}` always answers `{ok: true}` (no account enumeration), emails
  `GET /auth/magic/:token` (15 min, single use) which redirects with
  `#session=` like the Google callback; expired/used → `?auth_error=
  link_expired`. Sign-in screen: "Email me a sign-in link" under the
  Google button; `not_allowed` copy now says sign-ups are by invitation.
  `magicLinkEmail` template.
- Google sign-in for an invited user needs nothing new: the callback
  already accepts any existing `users` row, and sign-up creates it.

**Not done.** No welcome email (the invite email is the welcome). No
password (decision). The tutorial's sample job is not seeded yet — a new
org lands on an empty Jobs list.

**Manual:** MA-015 (consent screen external + published, Terms/Privacy
pages and `TERMS_URL` / `PRIVACY_URL` on `scribe-api`). Without
MA-013 the magic link is only in the api log (`magic link not emailed`).

---

## 2026-09-15 (l) — PR C: tenancy — orgs, org_id on every customer table, platform admins

**Shipped (migration `0014_orgs.sql`, applies at boot).** `orgs` (name,
`is_platform`, logo); the platform org "CabinetNow" is created and every
existing user/takeoff/quote/customer/eval_fixture is backfilled into it,
then `org_id` goes NOT NULL. `users.org_id / org_role (owner|member) /
is_platform_admin` (backfilled from `role = 'admin'`). Seed puts
`AUTH_ALLOWED_EMAILS` users in the platform org (first = platform admin).
- **Request context:** `SessionUser` carries `orgId`, `orgRole`,
  `isPlatformAdmin`; `req.orgId` is the org the request acts in — the
  user's own, or for platform admins the `X-Org-Id` header (support view).
  `requireAdmin` now means **platform admin** (pricing, sources, users,
  invites, prospects, org-settings). `/auth/me` returns `orgId`,
  `orgName`, `orgRole`, `isPlatformAdmin`.
- **Scoping (`lib/scope.ts`):** `takeoffInOrg` / `quoteInOrg` replace every
  `eq(takeoffs.id, …)` / `eq(quotes.id, …)` (18 + 6 sites); a preHandler
  404s any `/takeoffs/:id/…` route whose takeoff is outside the org (covers
  detections, page images, exports); `/takeoff-lines/:id` PATCH/DELETE
  filter by `inArray(takeoff_id, <org's takeoffs>)`; `/takeoffs`, `/jobs`,
  `/quotes`, `/customers` list per org; inserts stamp `org_id`; dashboard
  SQL is per org (prospect counts platform-admin only); `/projects` is
  platform-admin only. Workers copy `takeoffs.org_id` onto eval fixtures.
- **Admin → Users:** org column, role select, platform-admin checkbox
  (`PATCH /admin/users/:id`; you cannot un-admin yourself), last sign-in.
  Web nav/operator menu and `TechnicalDetail` key off `isPlatformAdmin`.

**Not changed (deliberate).** `org_settings` stays the single platform row
(freight, handling, quote terms/logo, cross-validation) — per-org branding
comes with the account screens (PR D). Pricing configs, product lines,
export templates, sources and projects are platform-level.

**Gotchas.** (1) A new tenant org has no takeoffs, so `/jobs` is empty
until they upload — the sample job (tutorial) fills it later. (2) Machine
users (dev bypass, signal connector) are created in the platform org via
`getPlatformOrgId()`. (3) `X-Org-Id` is honoured only when
`isPlatformAdmin`; the web app does not send it yet.

**Manual:** MA-014 — after deploy, tick "Platform admin" for
ridadarwish12@gmail.com in Admin → Users (the migration promotes only
`role = 'admin'`, i.e. mhittle@gmail.com).

---

## 2026-09-15 (k) — PR A: email provider + invites API + Admin invite panel

**Owner:** sign-up form = email, name, phone only; "ok go" on the plan's
recommendations (A → C → B → D, Google OAuth + magic link, no password).

**Shipped.**
- `packages/email`: `sendEmail` posts to Resend's REST endpoint (no SDK);
  with `RESEND_API_KEY`/`EMAIL_FROM` unset it logs and returns
  `sent: false` so dev/tests/prod-before-DNS all work. `inviteEmail`
  template (text + html, escaped; tests).
- Migration `0013_invites.sql`: `invites` (token_hash sha256, email, name,
  org_name, org_id for PR C/D, credits_granted, invited_by, note,
  expires_at 14 d, used_at/used_by, revoked_at, last_sent_at) and
  `users.phone / terms_accepted_at / terms_version / terms_ip /
  last_sign_in_at`.
- API `routes/invites.ts`: public `GET /signup/:token` (state only for
  non-pending; email/name/inviter/credits for pending; never the token);
  admin `GET /admin/invites` (+ `emailConfigured`), `POST /admin/invites`
  (409 if the email has an account; emails; returns the link once),
  `POST /admin/invites/:id/resend` (new token, new expiry — also revives
  expired), `DELETE /admin/invites/:id` (revoke). `lib/tokens.ts`
  (`newToken`, `hashToken`, `inviteState`; tests).
- Web Admin → Users: "Invite someone" (email, name, company, pages
  included, note), copyable last link, invites list (pending by default,
  toggle for used/expired/revoked, Resend/Revoke), warning when email is
  not configured.

**Gotchas.** (1) The raw token exists only in the email and the create/
resend response; the DB holds the hash — a lost link means Resend, which
rotates it. (2) `org_id`/`org_name` on invites are stored but unused until
PR C/B. (3) `POST /signup` (creating the user) is PR B, deliberately not
here — a pending invite cannot yet be redeemed.

**Manual:** MA-013 (Resend account, `mail.` subdomain DNS, `RESEND_API_KEY`
+ `EMAIL_FROM` on `scribe-api`).

---

## 2026-09-15 (j) — accounts / onboarding / credits / Stripe plan written (no code)

**Owner ask** (`next-session-prompt.md`): plan the invite → sign-up →
profile flow, the onboarding tutorial, the credits data model and pricing,
and confirm the Stripe row — then stop for decisions. **Shipped:**
`accounts-plan.md`. Key recommendations: sign-up submit issues the session
directly (the emailed token proves the mailbox), later sign-ins are Google
OAuth or an email magic link, no password; Google consent screen goes
external + published (non-sensitive scopes → no review, but terms/privacy
URLs are required); Resend on a `mail.` subdomain with SPF/DKIM/DMARC as
manual actions; tenancy = `orgs` + `org_id` on takeoffs/quotes/customers/
eval_fixtures, `is_platform_admin`, `requirePlatformAdmin` /
`requireOrgOwner`, 54 routes audited; PR order **A → C → B → D** (tenancy
before any sign-up). Credits: `model_rates` / `usage_events` (microcents)
/ `credit_ledger` (hold → settle | release) / `platform_settings`; hook is
`TakeoffBudget.record` plus the two hand-summed sites in `detect.ts`;
pricing proposal $1/page, 5-page minimum, 20-page grant, re-runs included,
`credits_enforced=false` until Stripe. **Open:** the six decisions in
`accounts-plan.md` §5. Nothing built; no prod state touched.

---

## 2026-09-15 (i) — session wrap-up: SCR-013/014 shipped, plan awaiting decision, next = sign-up + credits

**Shipped:** #274 (parse hardening, salvage evidence, review error banner),
#276 (customer-facing copy, admin technical toggle, parser accepts the
markdown preamble), #275 (measurement plan, docs). Prod verification of
#274/#276 on MOLLY_CHARLEY is still the owner's to click (steps in (f)/(h)).
**Owner decided:** accept the current measuring behaviour as is; the
measurement plan's Option A/B/C choice stays open, nothing built.
**New roadmap rows:** sign-up flow + tutorial (next session, prompt in
`next-session-prompt.md`), credits ledger + pricing, Stripe payments, door/
drawer-front counts (SCR-015 open). **Cost evidence for pricing:** prod
`tokens_used` = 13k–23k per 4-page kitchen set, 66k for a 4-page office set
→ 1–5¢ per page at Sonnet rates; $1/page is margin-safe, needs a per-job
minimum. **Manual actions:** MA-006/007/008/009/011 still open (not asked).

---

## 2026-09-15 (h) — customer-facing copy for pipeline errors and read notes; the "not clean JSON" cause

**Owner:** the Jobs list showed the SCR-011 SQL in red and the review's
notes said "measurements response was not valid JSON — 22 complete cabinet
answers salvaged, nothing defaulted". Customer-facing app: calm plain copy
for the customer, the technical text for the developer only (SCR-014).

**Cause of the salvage, from #274's new warn line** (takeoff 99656b83,
2026-09-14 01:45 PDT, 22/22 salvaged): the model answers with a markdown
work-through of every marker before the JSON ("**Marker 1:** … (from chain
[y≈149]: 14)"), then the object. `extractJson` capped candidate brackets at
8; the preamble has one `[y≈…]` per marker, so the real `{"cabinets"` was
never reached. Now every candidate is tried (test with 22 bracketed
markers). The preamble itself is harmless — arguably useful reasoning — the
parser has to accept it. A strict output contract (structured outputs, SDK
bump) is in `measurement-accuracy-plan.md`.

**Shipped.** `apps/web/src/messages.ts`: `friendlyError` (build failed →
"We couldn't finish building this takeoff. Please try Build again."; billing
/ 429 / 529 → "The reading service isn't available right now…"; media type →
"upload as PNG or JPEG"; default generic), `friendlyNote` / `friendlyNotes`
(schedule missing, N defaulted, N estimated, cut off, page cap, plan-run
arithmetic, unread page type, failed page part; developer-only notes —
salvage with nothing defaulted, cross-validation — hidden from customers;
unknown → one generic line; duplicates merged), `friendlyAreaError`.
`components/TechnicalDetail.tsx`: raw text under "Technical details (admin)"
for `role === "admin"` (same `["me"]` query as the shell). Wired into the
Jobs list, the wizard (takeoff error + failed areas), the review banner,
the review notes panel and the failed screen. The worker's strings are
unchanged — they are the evidence.

**Gotcha.** New pipeline warning strings need a `NOTE_RULES` entry or they
render as the generic line for customers (admins still see the raw text).

---

## 2026-09-15 (g) — measurement-accuracy plan written (no code)

`measurement-accuracy-plan.md`, from the 18 kits (zero API) + the prod
Charley builds. Findings: F1 0.47 is a COUNT problem (158/382 gold matched;
sizes on matched are 62% exact width, 53% within 1"); fixing Find's count
after the fact costs about as many touches as marking each cabinet
(elevation sets ~15 vs 17.6 gold per kit); the text-layer `nearbyDims`
hold the gold width for 26% of matched cabinets and for 2 of the 60 the
model got wrong — the printed-dim shortlist is not the missing information,
legibility is (elevation areas get no high-res crop; plan areas do). Owner
batch-accepted 16/24 lines on prod and typed no size. Options A (areas +
Find count gate + per-area measuring, recommended, LOE 7 in 3 PRs + an
optional reviewer PR), B (mark every cabinet), C (reviewer pass). Step 0 =
a ~$4 live per-area A/B on the kits before PR 2. Awaiting the owner.

---

## 2026-09-15 (f) — SCR-013 evidence: no build failed after #270; prose-wrapped answers now parse; failed re-measure visible

**Context.** Owner report (via the wrap-up): Build and "Measure again…"
still error on the measuring step after #272 and land on the wizard.
Evidence pulled before any code: prod DB through the API (`/jobs`,
`/takeoffs/:id`, `/detections`) and the Railway `scribe workers` log
(7-day window, filters `"measure response"`, `"beta build"`, `"job failed"`).

**What the data says.** All beta builds 09-13 UTC: 247913a4 done (20);
f876cac2 + 9018debb FAILED 18:41 with the pre-#270 `= ANY((…))` query —
still on the Jobs list as "build takeoff failed", parked at `awaiting_boxes`
by design; 8a8e3914 done 18:49 pre-#272 (24/24 defaulted at 0.5 — the first
report); 40f9cb79 done 19:07 (`end_turn`, 16.6k chars, 24/24 clean JSON);
0a26eb66 done 19:12 (`end_turn`, 7.4k chars, **25/25 via salvage**, 3
estimated) → `review`, lines carry `reviewerEdited` at 19:13. No
`beta build failed` after #270, no BullMQ `job failed`, no `remeasure` ever
queued. So: the measuring step does not fail post-#272, and the wizard did
forward. What IS real: 2 of the last 3 prod answers were not parseable as a
whole though every cabinet object was complete (all 18 kits parse), and the
review said "25 salvaged, the rest defaulted" when nothing defaulted. The
stored `response-0.txt` were not pulled (no API route; MinIO console only).

**Shipped (#274).**
- `extractJson`: outermost JSON value by a balanced string-aware scan,
  prose/fences before and after ignored, trailing commas forgiven, a value
  that never closes still throws (salvage path). Tried candidates in order,
  so `{kitchen}` in a preamble no longer poisons the parse.
- `parseMeasureResponse(text, markerCount)` → `parse: json|salvage|none`;
  warning counts the defaulted markers ("nothing defaulted" / "4 of 5
  defaulted"); salvages when the first complete value was an inner object.
- Worker: `parse` on the `measure response` log line; a `measure answer was
  not clean JSON` warn with 400-char head/tail — the next occurrence is
  diagnosable from Railway without MinIO.
- Review page: `takeoffs.error` banner + **Measure again** button in
  `review` (a failed re-measure or a failed area update on a reviewed
  takeoff restores `review`; the error was invisible there).
- 9 tests; 18-kit zero-API replay identical to `summary.csv` per kit.

**Not changed.** Routing (`BetaDetect.tsx` forward, review forward) — the
evidence says both work. Measure prompt (measure-v6) and call shape.

**Open.** Owner verifies on prod after deploy (Build on a fresh
MOLLY_CHARLEY_KITCHEN job → review; Measure again from the review's More
menu → review). If a non-clean answer recurs, the warn line has the edges.
Strict JSON via structured outputs needs an SDK bump (0.70.1 has no
`output_config`) — in the measurement-accuracy plan, not this PR.
## 2026-09-15 (d) — measuring answer unparseable → every size defaulted; salvage + retry + re-measure

**Owner's live job (MOLLY_CHARLEY, 24 cabinets on 3 elevation areas):**
Build ran ~2 min, then every cabinet came back 30" wide at 50% — the
review's notes said "measurements response was not parseable JSON — sizes
defaulted". The measure call had `max_tokens: 16000`, no `stop_reason`
check and no salvage; the page-reading path has had 32k + salvage since
June. Whether this answer was cut off or malformed is in
`takeoffs/{id}/beta/measure/response-0.txt` (not pulled).

**Fixed.**
- `max_tokens: 32000` on the measure call; `stop_reason === "max_tokens"`
  is logged and surfaces as a note ("cut off at the token limit; N of M
  cabinets salvaged").
- `parseMeasureResponse` salvages every COMPLETE cabinet object from an
  unparseable answer (`salvageArrayObjects(text, "cabinets")`, the same
  string-aware brace scanner as `salvageLineObjects`); note says how many.
- An answer with zero usable cabinets gets ONE fresh model call; still
  zero → the build throws ("the measuring step returned no usable sizes
  twice — click Build again"), rolls back (2026-09-15 (c)), and the
  wizard shows the error — instead of silently producing a takeoff of
  defaults that LOOKS finished.
- `POST /takeoffs/:id/remeasure` (review or awaiting_boxes): clears
  `built_at` on every scanned area, keeps the found cabinets, queues a
  build — "Measure again…" in the review's More menu (confirms; edits on
  those cabinets are replaced). This is the recovery for the live job.

**Gotchas.** (1) Each measuring attempt persists as `response-{attempt}.txt`.
(2) Re-measure re-prices only the rebuilt lines like any area build; hand-
drawn review lines (no area) are untouched. (3) The user's proposal
("read the printed dimensions near each box across every page") is what
the measure pass already does — `nearbyDims` per marker from the whole
page's text layer + every page sent as context; the failure was purely
the answer format.

---

## 2026-09-15 (c) — build failed in prod: `= ANY($list)` bug; builds now roll back and report progress

**Owner report (live, MOLLY_CHARLEY_KITCHEN):** Find found 8 cabinets;
Build errored `delete from takeoff_lines where … raw_model_output->>'parent'
= ANY(($2, $3, …))`. Root cause: PR 2's scoped deletes used
`sql\`… = ANY(${ids})\`` — drizzle expands a JS array into a parameter
LIST, so Postgres got `ANY((…,…))`, which is invalid (ANY wants an array).
It failed at the scoped pricing step, AFTER the lines had been inserted and
`built_at` stamped: the area read "in takeoff" with 8 unpriced lines and
Build then had "nothing new to build".

**Fixed.**
- All three sites (`replaceLinesForDetections`, scoped `priceAndExpand`,
  API `deleteLinesForDetection`) use `inArray(sql\`…->>'parent'\`, ids)`
  → `IN ($2, $3, …)`.
- `buildFromDetections` stamps `built_at` only AFTER pricing succeeds; on
  any failure after insert it deletes the inserted lines (+ faces) and
  clears `built_at`, so the areas read as scanned-but-unbuilt and Build is
  simply clickable again.
- `build-takeoff` self-repairs the state this bug left behind: an area
  stamped built whose lines were never priced (`product_line_id IS NULL AND
  unmatched_reason IS NULL` on every line) is reset to unbuilt.
- Progress during a build: the API writes `{stage: "measure", "Queued for
  measuring"}` when Build is clicked; the worker writes "Measuring N
  cabinets" before the model call; pricing writes "price". The Reading card
  picks its title and stage list from the real stage (Preparing your pages /
  Building your takeoff / Reading your drawings) instead of a client flag —
  the "went back to Preparing" confusion.
- `beta_build` jobs get `attempts: 2` (30 s fixed backoff) so a worker
  restart mid-build (a deploy) recovers on its own.

**Second live symptom, same day:** a job sat 25 min in `processing` showing
the stale hand-off line — consistent with the PR 1/PR 2 deploys restarting
the workers mid-build (unverified without the Railway log). The retry +
progress changes cover it; if it recurs, the worker log for that job is the
evidence to pull.

**Gotcha.** Never write `= ANY(${jsArray})` in drizzle `sql` — use
`inArray()`. Grep `= ANY(` in a review.

---

---

## Condensed history

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

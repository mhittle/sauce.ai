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
- **Accounts are LIVE but email is NOT configured (2026-09-21, #279–#283).**
  `RESEND_API_KEY` / `EMAIL_FROM` are unset on `scribe-api`, so every invite
  and magic link is created and then only LOGGED (`email not configured`);
  the admin copies the link out of Admin → Users by hand. Setting the two
  vars switches sending on with no code change (MA-013).
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
- **`ROUTER_TOLERANT_MERGE=1` is SET on `scribe-workers`** (owner, 2026-08-12)
  — the demoted-role re-admit merge is LIVE prod behavior (kit-measured 0.379
  vs 0.328 baseline). Removing the var reverts to the plan-only router and
  silently re-breaks elevation-heavy docs. `ROUTER_ELEVATION_PRIMARY` exists
  gated but is NOT set (measured ≈ equal; don't set without new evidence).

---

## 2026-09-23 — session wrap-up: accounts + tutorial merged and live; billing still unbuilt

**Context.** Session 2026-09-15→23. The owner's four tasks were: plan the
invite → sign-up → profile flow, plan the onboarding tutorial, specify what
credits need (plan only), and confirm the Stripe row. After the plan came an
"ok go", so tasks 1 and 2 were built; 3 and 4 remain plan-only by decision.

**What shipped (all merged to `main` 2026-09-21).**
- **#278** `accounts-plan.md` — state diagram, schemas, Google/Resend manual
  steps, tenancy route audit, PR split, credits schema + pricing proposal.
- **#279 PR A** `packages/email` (Resend REST, log-only without the key) +
  migration 0013 `invites` + admin invite API + Admin → Users invite panel.
- **#280 PR C** tenancy: migration 0014 `orgs`, `org_id` on takeoffs/quotes/
  customers/eval_fixtures, `is_platform_admin`, `req.orgId` (+ `X-Org-Id`
  for platform admins), `lib/scope.ts` on ~24 id lookups, per-org lists and
  dashboard, `/projects` platform-only. **This closed the security item** —
  before it, any signed-in user saw every takeoff.
- **#281 PR B** `POST /signup` (org + owner user + invite consumed in one
  transaction, session in the body) + `/signup?token=` page + email magic
  link (migration 0015 `login_tokens`).
- **#282 PR D** `/account`: profile, company name/logo (org logo now wins on
  that org's quote PDFs), team roles, teammate invites; `requireOrgOwner`.
- **#283** onboarding tutorial: migration 0016, sample-job clone
  (`storage_id` shares the original's images; non-GET writes on a sample are
  refused), `Tour`/`Coachmark` with a sequence per screen, progress in
  `users.onboarding`, "Show me around" in the account menu.

**Owner decisions this session.** Sign-up form is email + name + phone only
(no company, no how-heard, no checkbox — a terms LINE). PR order A → C → B
→ D, so tenancy landed before any outside user could exist. Sign-in is
Google OAuth or an email magic link; no password.

**Prod verification (2026-09-23).** `/health/db` ok; `GET /signup/<bogus>`
returns the route's own `{"error":"invite not found"}` (not route-not-found),
so PR B's routes are deployed and migrations 0013–0016 applied at boot. Live
web bundle `index-CDvzjuQb.js` contains "Create my account", "Email me a
sign-in link", "Show me around", "Sample job for new accounts", "Invite
someone", "Skip tour". Every merged file confirmed present on `origin/main`
by `git cat-file` (the 2026-09-13 stacked-PR trap did not recur).

**Also run locally (2026-09-22)** on a throwaway `scribe_dev` DB: invite →
copy link → sign-up → new org → Account page, end to end, green. Recipe in
Load-bearing state.

**NOT built, by decision.** Credits and Stripe. There is no `usage_events`,
`credit_ledger`, `model_rates`, `platform_settings` or Stripe code on main.
**Gotcha:** the invite form's "Pages included" is stored on the invite and
shown to the invitee at sign-up, but nothing reads or decrements it — every
account today reads without limit at our API cost.

**Owner decision 2026-09-23: measurement accuracy is CLOSED.** None of
Option A/B/C taken; the current measuring behaviour is accepted and the
reviewer correcting sizes on Review is the product's answer. The $4 Step 0
experiment was never run. `measurement-accuracy-plan.md` keeps a CLOSED
banner and stays as the evidence base — the study is not to be re-proposed
or re-run on the same 18 kits. SCR-015 (door/drawer-front counts) is a
separate item and stays open.

**Open for the owner.** Pricing shape (per page + minimum, or per job),
signup grant, pack sizes — `accounts-plan.md` §3.4. Manual actions MA-006
(real rates; the send gate blocks every quote until done), MA-013, MA-014,
MA-015, MA-016.

---

## 2026-09-15 (o) — onboarding tutorial: seeded sample job + coachmarks

**Shipped (migration `0016_onboarding.sql`).**
- **Sample job.** `org_settings.sample_takeoff_id` (Admin → Users →
  "Sample job for new accounts"; must be review/approved and not itself a
  clone). `lib/sample.ts cloneSampleTakeoff(orgId, userId)`: copies the
  takeoff row (`is_sample`, `storage_id` = original, status `review`,
  name "Sample — <file>"), its detections and lines with ids remapped
  (faces' `raw_model_output.parent`, `detection_id`); idempotent per org;
  called after sign-up (best-effort) and by `POST /account/sample`. Image
  routes (`pages`, `thumbs`, `reads`, `beta/pages`) read from
  `storage_id`; a preHandler refuses non-GET `/takeoffs/:id/…` on a sample
  except accept-lines / approve / reopen (409 "this is the sample job —
  upload your own plan set"), so reviewing, approving and quoting it works
  and nothing re-reads it. `/jobs` carries `isSample`; the row shows a
  "sample" badge.
- **Coachmarks.** `ui/Coachmark.tsx` (fixed popover pinned to
  `[data-tour=…]`, never blocks input, Next / Skip tour, N/M) and
  `components/Tour.tsx` (`TOURS` copy per screen; steps whose anchor is
  absent are skipped; progress `users.onboarding {seen, dismissed}` via
  `PATCH /me`; `/auth/me` returns it). Anchors: Jobs upload zone + sample
  row; Pages continue button; Mark step action; Review accept button +
  estimate bar; Quote tiers + send. "Show me around" in the account menu
  clears progress, re-seeds the sample and goes to Jobs.

**Gotchas.** (1) `storage_id` is only honoured by the four image routes;
worker key helpers still use the takeoff id — hence the write block on
samples. (2) Deleting the original sample takeoff is blocked by the FK
from `org_settings`; clear the sample first. (3) The tour reads `["me"]`
from the query cache — a page that renders before `/auth/me` resolves
simply shows nothing until it does.

**Manual:** MA-016 (choose a sample plan set we may show to strangers).

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

---

## Condensed history

### 2026-09-15 (i) — session wrap-up, superseded by 2026-09-23 (archived verbatim)
Shipped #274/#275/#276; owner accepted the measuring behaviour as is (the study
was formally CLOSED on 2026-09-23). Recorded the prod cost evidence that still
drives pricing: 13k–23k tokens for a 4-page kitchen set, 66k for a 4-page office
set, i.e. 1–5¢ per page at Sonnet rates. Queued the sign-up/credits/Stripe rows.

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

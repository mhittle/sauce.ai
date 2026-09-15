# Starting prompt for the next engineering session (written 2026-09-15)

Paste everything below the line into a fresh session.

---

Working in `scribe/` of mhittle/sauce.ai. Start by reading
`scribe/new-engineering-session-instructions.md`, then
`scribe/engineering-history.md` (Load-bearing state + entries 2026-09-15
(f)–(i)), `scribe/product-plan.md` §4 and §5, `scribe/roadmap.md` (the
"Sign-up flow", "Credits", "Stripe payments" rows), `scribe/bugs.md`
(open items), `scribe/manual-actions.md`. Skip the "pick from the roadmap"
question — the work is below.

## Setup rules (non-negotiable)
- `git fetch origin && git checkout main && git pull` first; confirm
  `git log origin/main -1` is at or after the merge of #276.
- Never edit on main. Branch off `origin/main`, base every PR on `main`,
  merge with `--delete-branch` (the auto-mode classifier blocks `gh pr
  merge` — open the PR, gate it, hand the merge to me). Railway
  auto-deploys `main`; verify a web deploy by grepping the live JS bundle
  for a string unique to the merge AND a changed bundle hash. API health:
  `https://scribe-api-production-757c.up.railway.app/health/db`.
- No Docker/brew services locally; `pnpm build && pnpm test && pnpm eval`
  from `scribe/` is the offline gate. Port 3001 is my unrelated Next.js
  server — don't kill it.
- Drizzle: never `sql\`col = ANY(${jsArray})\``; use `inArray`. Never
  hand-apply migrations — ship a migration file, the API applies it at
  boot.
- Verify evidence before diagnosing. Prod evidence is reachable from my
  Chrome (logged into the web app and Railway) — see history (f) for how.
- Customer-facing app: every new error or note the pipeline can show goes
  through `apps/web/src/messages.ts` (plain copy for customers, raw text
  for admins via `TechnicalDetail`).
- Bookkeeping for every PR: history entry, roadmap row, bugs.md status,
  manual-actions entry for anything I must do on Railway/Google/DNS — all
  in the same PR, per `engineering-session-wrapup.md`.

## Task 1 — sign-up flow (invite email → sign-up link → details → profile)

The flow I want: I send a prospect an email with a sign-up link. The link
opens a page that asks for their details (name, company, phone, how they
heard about us, terms acceptance — propose the exact fields). Submitting
creates their user profile and signs them in. They land on Jobs.

Today auth is Google OAuth with an allow-list only (`routes/auth.ts`: "No
self-signup", `AUTH_ALLOWED_EMAILS` seeds users, admins add the rest).
Product-plan §4 has the agreed shape: email provider first (Resend), then
tenancy (`orgs`, `users.org_id`, every list scoped by org — the security
item), then self-signup with single-use invite codes, then account screens.

Plan first, then build in PRs on `main`:
1. **Plan (docs, ask me before coding):** the invite → sign-up → profile
   sequence as a state diagram; the `invites` table (token, email, expiry,
   granted credits, invited_by, used_at); what "sign in" means for an
   invited user — Google OAuth (their Google account must match the
   invited email) vs email magic link vs password; what changes on the
   Google side (OAuth consent screen: internal/testing → external +
   published, verification if scopes beyond email/profile, the 100-test-
   user cap in testing mode, redirect URIs for a custom domain); the email
   provider setup as manual actions (Resend account, sending domain, SPF/
   DKIM/DMARC DNS records, `RESEND_API_KEY` on `scribe-api`); tenancy
   scope (which routes/queries change). Give LOE per PR.
2. **PR A — email provider + invites API:** `invites` migration, `POST
   /admin/invites` (sends the email), `GET /signup/:token` (validates),
   Admin → Users gets "Invite" with the pending list.
3. **PR B — sign-up page:** `/signup?token=…` in the web app: details
   form, terms, create user (+ org), sign in, land on Jobs. Google OAuth
   path accepts an invited email on first sign-in.
4. **PR C — tenancy:** `orgs`, `org_id` on takeoffs/quotes/customers/
   eval_fixtures, every list/detail scoped; platform-admin flag for me and
   Mike. This is the one that touches every route — do it before any
   outside user.
5. **PR D — account screens:** profile, org name/logo, members + invite,
   sign out.

## Task 2 — onboarding tutorial

A first-run walkthrough that shows a new user how the product works:
Jobs (upload) → Pages (pick the sheets) → Mark (draw the cabinet areas,
Find, Build) → Review (correct the breakdown, live estimate) → Quote.
Propose the form before building: a seeded sample job already read
(product-plan §6 "first-run job with a sample plan set") plus step
callouts on each screen, dismissable, re-openable from the account menu.
Keep it in the design system (`components/ui/`), no third-party tour
library unless it is tiny. Ship after Task 1's PR B so a new sign-up
lands in it.

## Task 3 — credits: what data is needed (plan only, then ask)

Answer with a schema and a short doc, not code:
- `usage_events` per model call: org, takeoff, stage (classify / locate /
  detect / measure / spreadsheet / cross_validate / verify), model,
  input/output/cache tokens, image count, cost_cents computed from a
  versioned `model_rates` table. Hook point: `TakeoffBudget.record()`
  already sees every call's usage.
- `credit_ledger`: org, delta, reason (grant / hold / settle / refund /
  purchase), takeoff, balance_after; org balance; signup grant setting in
  Admin. Hold N credits when Pages is submitted, settle on completion,
  refund on failure. Decide what a re-run costs.
- Admin "Usage" view: cost per takeoff, per page, per stage.
- **Pricing:** measured prod cost (history (i)) is 1–5¢ per page at Sonnet
  rates (a 4-page kitchen set = 13k–23k tokens end to end; a 4-page office
  set 66k). $1/page is margin-safe by 20–50×; the question is perceived
  value: a 4-page kitchen job would cost $4, which reads as free. Propose
  the unit (per page vs per job vs packs), a per-job minimum, a signup
  grant, and what a human takeoff service charges for comparison. Stop for
  my decision before building.

## Task 4 — Stripe (roadmap only this session)

Do not build. Confirm the roadmap row and note the dependencies: credits
ledger first, Stripe Checkout for packs, webhook → ledger, receipts by
email from the same provider as Task 1.

## Also open (don't start unless I say)
- Measurement-accuracy plan (`measurement-accuracy-plan.md`): Option
  A/B/C undecided.
- SCR-015 door/drawer-front counts: evidence first.
- Prod verification of #274/#276 on MOLLY_CHARLEY (history (f)/(h)).
- Manual actions MA-006/007/008/009/011 still open.

# Starting prompt for the next engineering session (written 2026-09-23)

Paste everything below the line into a fresh session.

---

Working in `scribe/` of mhittle/sauce.ai. Start by reading
`scribe/new-engineering-session-instructions.md`, then
`scribe/engineering-history.md` (**Load-bearing state** in full — it now
carries the prod state of the accounts work — plus the 2026-09-23 wrap-up
entry), `scribe/accounts-plan.md` §3 (credits) and §5 (open decisions),
`scribe/product-plan.md` §5, `scribe/roadmap.md` (the "Credits" and "Stripe
payments" rows), `scribe/bugs.md` (open items), `scribe/manual-actions.md`
(the 2026-09-23 status note at the top). Skip the "pick from the roadmap"
question — the work is below.

## Where things stand (do not re-derive)

Accounts, tenancy, sign-up, account screens and the onboarding tutorial are
**merged and live** (#279–#283, 2026-09-21; verified on prod 2026-09-23).
Invite → sign-up → profile → Jobs works end to end. There is **no billing of
any kind**: no `usage_events`, no `credit_ledger`, no `model_rates`, no
Stripe. The invite form's "Pages included" is stored and shown to the
invitee but nothing reads or decrements it, so every account currently reads
without limit at our API cost.

## Setup rules (non-negotiable)
- `git fetch origin && git checkout main && git pull` first; confirm
  `git log origin/main -1` is at or after the merge of #283.
- Never edit on main. Branch off `origin/main`, base every PR on `main`.
  The auto-mode classifier blocks `gh pr merge` — open the PR, gate it, and
  hand the merge to me. If you ever stack PRs, base each on `main` or merge
  bottom-up and delete the branch (see Load-bearing state).
- Railway auto-deploys `main`. Verify a web deploy by grepping the live JS
  bundle for a string unique to the merge AND a changed bundle hash; API
  health: `https://scribe-api-production-757c.up.railway.app/health/db`.
  After merging, confirm the files are actually on `origin/main`
  (`git cat-file -e origin/main:<path>`), not just that the PR says merged.
- No Docker/brew services beyond what is already running. `pnpm build &&
  pnpm test && pnpm eval` from `scribe/` is the offline gate. Ports 3001 and
  5173 are my other servers — the local recipe uses **3011 / 5174** and a
  `scribe_dev` database; the exact two commands are in Load-bearing state.
- Drizzle: never `sql\`col = ANY(${jsArray})\``; use `inArray`. Never
  hand-apply migrations — ship a migration file, the API applies it at boot.
  Next migration number is **0017**.
- Every new user-visible error or note goes through `apps/web/src/messages.ts`
  (plain copy for customers, raw text for admins via `TechnicalDetail`).
- Everything customer-scoped is now per org: new tables get `org_id`, new
  routes go through `lib/scope.ts`, and lists filter on `req.orgId`.
- Verify evidence before diagnosing. Prod evidence is reachable from my
  Chrome (logged into the web app and Railway).
- Bookkeeping rides in the same PR: history entry, roadmap row, bugs.md
  status, manual-actions entry for anything I must do — per
  `engineering-session-wrapup.md`.

## Task 1 — usage ledger (build this first; no decision needed)

`accounts-plan.md` §3.1/§3.2 has the schema. This is 3a only — instrument,
do not charge. It needs no pricing decision and it produces the measured
cost distribution I want to price against.

- Migration `0017`: `model_rates` (versioned, never updated; seed Sonnet
  4.6 / Haiku 4.5 / Opus and the OpenAI cross-validation model at list
  price) and `usage_events` (org, takeoff, stage, model, `model_rate_id`,
  input/output/cache tokens, image count, page number, `cost_microcents`,
  created_at — microcents because a 1k-token Haiku call rounds to 0 cents).
- Hook: `TakeoffBudget` (`apps/workers/src/lib/anthropic.ts`) already sees
  every call's usage — give it `{orgId, takeoffId}` context and a
  `record(usage, {stage, model, images, page})` that also inserts a row. A
  failed insert must log and never fail a build. Existing `budget.record`
  call sites: `classify.ts`, `regions.ts`, `extract.ts`, `spreadsheet.ts`;
  `detect.ts` sums `message.usage` by hand in TWO places (~lines 231 and
  989) and needs the same call.
- Admin → "Usage" tab (platform admin): cost per takeoff, per stage, per
  page, with a date range and an org filter.
- Then **report the numbers to me**: median and p90 cost per page and per
  job, plan pages vs elevation pages, and what the 18-quote test set costs.
  That is the input to the pricing decision below.

LOE ~3. One PR.

## Task 2 — credits (only after I answer the pricing question)

Ask me this before writing any of it, with your recommendation:

1. **Unit:** $1 per page with a 5-page job minimum, or $10 per job covering
   10 pages then $1 per page after?
2. **Signup grant:** 20 pages?
3. **Packs:** 25 / 100 / 500 pages?

Then build §3.1's `credit_ledger` + `orgs.credit_balance` +
`platform_settings` (grant, minimum, `credits_enforced`), the hold on Pages
submit → settle on completion → release on failure, the balance in the top
bar, the cost preview on Pages, and the signup grant applied from
`invites.credits_granted` (which is already stored and already promised to
the invitee). Keep `credits_enforced = false` until Stripe exists — record
and show, never block. LOE ~4.

## Task 3 — Stripe (only after credits)

`accounts-plan.md` §4. Checkout for packs, signature-verified idempotent
webhook → a `purchase` ledger row, receipts from the same Resend domain.
Do not start before credits work.

## Waiting on me — nudge me for these, they block real usage
- **MA-006** real pricing rates. Until entered, the send gate blocks EVERY
  quote, so a customer could sign up, run a takeoff and hit a wall.
- **MA-013** Resend account + `mail.` subdomain DNS + `RESEND_API_KEY` /
  `EMAIL_FROM` on `scribe-api`. Blocked on choosing the product domain.
  Until then invites are created and I copy the link by hand.
- **MA-015** Google consent screen → External + published; needs Terms and
  Privacy pages to exist, then `TERMS_URL` / `PRIVACY_URL` / `TERMS_VERSION`.
- **MA-014** tick Platform admin for ridadarwish12@gmail.com.
- **MA-016** choose the tutorial's sample plan set (must be one we may show
  strangers — the test kits are customers' drawings).
- Older: MA-007, MA-008, MA-009, MA-011.

## Also open (don't start unless I say)
- Measurement-accuracy plan (`measurement-accuracy-plan.md`): Option A/B/C
  undecided. This is the product's known weak spot — the count, not the
  sizes — and it matters more than billing if outside users are coming.
- SCR-015 door/drawer-front counts: evidence first.
- SCR-013: #274 is deployed; I still owe a live Build / "Measure again"
  spot-check before it can be closed.

# Starting prompt for the next engineering session (written 2026-10-05)

Paste everything below the line into a fresh session.

---

Working in `scribe/` of mhittle/sauce.ai. Start by reading
`scribe/new-engineering-session-instructions.md`, then
`scribe/engineering-history.md` (**Load-bearing state** in full, plus the
2026-10-05 wrap-up and the two 2026-10-02 entries), `scribe/accounts-plan.md`
§3.4 (pricing — decided) and §4 (Stripe), `scribe/roadmap.md` (the "Stripe
payments" and "Open-hold sweep" rows), `scribe/bugs.md` (open items),
`scribe/manual-actions.md` (the status notes at the top). Skip the "pick
from the roadmap" question — the work is below.

## Where things stand (do not re-derive)

Usage ledger (#309, migration 0017) and credits (#310, migration 0018) are
**merged and live** (2026-10-02; verified on prod 2026-10-05). Every model
call writes a `usage_events` row (Admin → Usage). Credits are **record-only**:
$1 per page read, no per-job minimum, each org's first job free (a 0-page
hold), invites' "Pages included" honoured as a signup grant. A job holds its
pages on Pages submit (or at upload for an image/sheet), settles when it
reaches review, releases if it fails. `platform_settings.credits_enforced`
is **false** — balances can go negative and nothing is blocked. There is
**no Stripe code** and no way for a customer to buy pages.

Measured cost (18-quote kit set via `apps/workers/scripts/kit-cost.mjs`,
Sonnet list): $1.75 total; per job median 8.7¢ / p90 20¢; per selected page
median 4.1¢ / p90 12.5¢; measure is 52% of cost. Prod numbers have not been
read yet.

## Setup rules (non-negotiable)
- `git fetch origin && git checkout main && git pull` first; confirm
  `git log origin/main` contains the merge of #310.
- Never edit on main. Branch off `origin/main`, base every PR on `main`.
  The auto-mode classifier blocks `gh pr merge` — open the PR, gate it, and
  hand the merge to me. Don't stack PRs; if two PRs touch the same files,
  tell me the merge order and rebase the second after the first lands.
- Railway auto-deploys `main`. Verify a web deploy by grepping the live JS
  bundle for a string unique to the merge AND a changed bundle hash; API
  health: `https://scribe-api-production-757c.up.railway.app/health/db`; a
  new route answering 401 (not 404) proves the api deployed. After merging,
  confirm the files are on `origin/main` (`git cat-file -e origin/main:<path>`).
- No Docker/brew services beyond what is already running (local Redis is
  often down — queue adds hang; test ledger logic through `@scribe/db`
  directly). `pnpm build && pnpm test && pnpm eval` from `scribe/` is the
  offline gate. Ports 3001 and 5173 are mine — local recipe uses
  **3011 / 5174** and `scribe_dev` (commands in Load-bearing state). Clean
  up any test rows you add.
- Drizzle: never `sql\`col = ANY(${jsArray})\``; use `inArray`. Never
  hand-apply migrations. Next migration number is **0019**.
- Every new user-visible error or note goes through `apps/web/src/messages.ts`.
- Everything customer-scoped is per org (`org_id`, `lib/scope.ts`,
  `req.orgId`). Ledger writes go through `writeLedger` (org row lock) —
  never update `orgs.credit_balance` directly.
- Verify evidence before diagnosing. Prod evidence is reachable from my
  Chrome (logged into the web app and Railway).
- Bookkeeping rides in the same PR, per `engineering-session-wrapup.md`.
  Keep `engineering-history.md` under ~34 KB (archive oldest entries).

## Task 0 — read prod usage (10 minutes, no code)

In my Chrome, open Admin → Usage on prod (last 30 days, all companies) and
report: jobs, median/p90 per job and per page, stage shares, plan vs
elevation, and how it compares with the kit estimate above. If there are no
rows, say so and check whether any takeoff ran since 2026-10-02 before
assuming the hook is broken (a model with no `model_rates` row is skipped
with a log line — check the worker logs for `usage event insert failed`).

## Task 1 — Stripe (accounts-plan.md §4)

Ask me first, with your recommendation: **pack prices** for 25 / 100 / 500
pages (proposal $25 / $90 / $400) and whether receipts wait for Resend
(MA-013) or ship log-only like invites.

Then build: `POST /billing/checkout {pack}` → Stripe hosted Checkout
(`success_url` → `/account?purchased=1`); `POST /billing/webhook`
(`checkout.session.completed`, signature-verified with the raw body,
idempotent on `external_ref = session id` — 0018 already has a unique index
for `purchase` rows) → `writeLedger` `purchase`; a "Buy pages" action on
Account and wherever `CREDITS_INSUFFICIENT` shows; receipt email via
`packages/email`. Stripe test mode only; no live keys in the repo or chat.
Manual actions to add (full steps): Stripe account, products/prices,
`STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET` on `scribe-api`, webhook
endpoint registered. LOE ~4. One PR.

## Task 2 — open-hold sweep (small, can ride with Task 1 or its own PR)

Release holds on jobs that never reached review (no settle/release, takeoff
not processing, >24 h since the hold) via `closeHold(…, "release")`, run on
a schedule in workers. Required before `credits_enforced` is turned on.
Then tell me when it is safe to tick "Block jobs the balance can't cover".

## Waiting on me — nudge me for these, they block real usage
- **MA-006** real pricing rates — until entered, the send gate blocks EVERY
  quote.
- **MA-013** Resend + `mail.` subdomain DNS + `RESEND_API_KEY` / `EMAIL_FROM`
  — blocked on choosing the product domain; invites are copied by hand.
- **MA-015** Google consent screen → External + published; needs Terms and
  Privacy pages first (`TERMS_URL` / `PRIVACY_URL` / `TERMS_VERSION`).
- **MA-014** tick Platform admin for ridadarwish12@gmail.com.
- **MA-016** choose the tutorial's sample plan set (one we may show strangers).
- Older: MA-007, MA-008, MA-009, MA-011.

## Also open (don't start unless I say)
- Measurement-accuracy plan (`measurement-accuracy-plan.md`): Option A/B/C
  undecided — the count is the product's known weak spot and matters more
  than billing once outside users arrive.
- SCR-015 door/drawer-front counts: evidence first.
- SCR-013: #274 deployed; I still owe a live Build / "Measure again"
  spot-check before it can be closed.

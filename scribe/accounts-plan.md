# Accounts, onboarding, credits, Stripe — plan (2026-09-15)

Owner-requested plan for the four items in `next-session-prompt.md`. Docs
only; nothing here is built. Sections marked **DECIDE** stop for the owner.
Facts about the current code are from `apps/api/src/auth.ts`,
`apps/api/src/routes/auth.ts`, `packages/db/migrations/0001_init.sql`,
`apps/workers/src/lib/anthropic.ts` and `packages/prompts/src/index.ts`.

---

## 1. Sign-up flow — invite email → sign-up link → details → profile

### 1.1 What exists

- Auth is Google OAuth only. `/auth/google/callback` looks the Google email
  up in `users`; unknown email → `?auth_error=not_allowed` ("No self-signup").
  `AUTH_ALLOWED_EMAILS` seeds users at boot; Admin → Users adds the rest.
- Sessions are HMAC tokens (`signSession(userId)`, 14 days), carried as a
  cookie AND as `Authorization: Bearer` from localStorage (cross-site
  Railway domains — load-bearing, see history "Load-bearing state").
- `users` = id, email, name, role (`estimator | sales | admin`), created_at.
  No orgs. `org_settings` is a singleton row (`id = 1`). Every list query is
  global: any signed-in user sees every takeoff and quote.
- No email provider anywhere in the stack.

### 1.2 State diagram

```
                 admin: POST /admin/invites {email, credits, note}
                                  |
                                  v
          +---------------- invite: pending -----------------+
          |  token emailed (Resend), expires_at = now + 14d   |
          +------+---------------------+---------------------+
                 |                     |                     |
        link opened            admin revokes          expiry passes
   GET /signup/:token           (revoked_at)          (no row change)
                 |                     |                     |
                 v                     v                     v
     signup page: form         invite: revoked        invite: expired
   (email read-only from       link → "This          link → "This invite
    the invite; name,           invite was            has expired — ask
    company, phone,             withdrawn")           <inviter> for a new
    heard-from, terms)                                 one"
                 |
        POST /signup {token, ...}
                 |
                 v
   in ONE transaction:
     users.insert (email, name, phone, heard_from, terms_accepted_at,
                   terms_version, role 'estimator', org_role 'owner')
     orgs.insert (name = company)             [PR C shape; see 1.6]
     invites.used_at = now, used_by = user.id
     credit_ledger grant of invite.credits   [after credits ship; else noop]
                 |
                 v
     session token issued exactly as the OAuth callback does
     (cookie + `#session=` fragment → localStorage) → redirect to Jobs
                 |
                 v
   later sign-ins: Google OAuth (email must equal the invited email,
   case-insensitive) OR email magic link (see 1.4). Both land on Jobs.
```

Guards: a used token → "This invite was already used — sign in"; an
invite whose email already has a user → same message; token compared by
sha256 hash, single use, never logged.

### 1.3 Sign-up form fields (proposed)

| Field | Required | Storage |
|---|---|---|
| Email | read-only, from the invite | `users.email` |
| Full name | yes | `users.name` |
| Company | yes | `orgs.name` (until PR C: `users.company`) |
| Phone | no | `users.phone` |
| How did you hear about us | select: referral / search / trade show / social / other + free text when "other" | `users.heard_from` |
| I agree to the Terms and Privacy Policy | required checkbox, links open in a new tab | `users.terms_accepted_at`, `users.terms_version`, `users.terms_ip` |

Not asked: password (see 1.4), role (everyone is `estimator`; org role
`owner` for the first user of an org), logo (account screens, PR D).

**DECIDE:** the Terms and Privacy Policy pages must exist (public URLs)
before the first invite goes out — they are also required fields on the
Google consent screen (1.5). Who writes them, and at which URL?

### 1.4 What "sign in" means for an invited user — **DECIDE**

Recommendation: **the invite link itself signs the user in at sign-up; after
that, Google OAuth or an email magic link. No password.**

| Option | Pros | Cons |
|---|---|---|
| **A. Google OAuth (matching email) + email magic link** (recommended) | Google path already works; magic link reuses PR A's email provider and the existing session token; no password storage, no reset flow; works for Outlook/Yahoo shops | A user with neither Google nor mailbox access at the desk can't sign in (rare for the buyer persona) |
| B. Google OAuth only | zero new auth code | invitees without a Google account are locked out; sign-up would need a Google step, and the invited email must equal the Google email (common mismatch: `me@company.com` vs `me@gmail.com`) |
| C. Add a password | works everywhere | argon2 + reset flow + breach surface; every reset is the magic link anyway |

Mechanics for A:
- Sign-up submit proves mailbox ownership (the token was emailed there), so
  the API issues a session directly — no OAuth round trip on day one.
- `POST /auth/magic-link {email}` → if a user exists, email a 15-minute
  single-use token (`login_tokens` table: token_hash, user_id, expires_at,
  used_at). Always answers 200 (no account enumeration).
  `GET /auth/magic/:token` → session, same redirect as the OAuth callback.
- Google callback change: unknown email stays refused (invites are the only
  door); a known email whose Google name is set fills `users.name` as today.
  Google sign-in for an invited user works the moment the user row exists,
  which is at sign-up — no separate "accept on first Google sign-in" state.
- Login screen gets an email field + "Email me a sign-in link" under the
  Google button.

### 1.5 Google side (manual actions, before external users)

Scopes are `openid email profile` only (non-sensitive), which keeps this
simple:

1. **OAuth consent screen → External, publish to production.** Testing
   mode caps the app at 100 listed test users and every invitee would have
   to be added by hand in the Google console — that alone blocks self-serve.
   With non-sensitive scopes only, publishing needs **no Google
   verification review**; the consent screen just needs app name, support
   email, developer contact, homepage, privacy-policy and terms URLs
   (hence 1.3's DECIDE), and an authorized domain that those URLs live on.
   Users will see the normal Google account chooser, no "unverified app"
   interstitial. (Brand verification of the logo becomes a review only if
   a logo is uploaded — skip the logo until a custom domain exists.)
2. **Redirect URIs.** Today: `https://scribe-api-production-757c.up.railway.app/auth/google/callback`.
   When the custom domain lands (product-plan §4 item 5) add
   `https://api.<domain>/auth/google/callback` BEFORE switching
   `API_PUBLIC_URL`; keep both during the cutover. Full path, not bare host
   (MA-004 gotcha).
3. **Authorized JavaScript origins** are not needed (server-side code flow).
4. If any Google scope beyond email/profile is ever added (Drive, Gmail),
   verification review + a demo video become mandatory — don't.

### 1.6 Email provider (manual actions)

Resend, transactional only (marketing sends stay on a separate domain per
product-plan §6). Manual actions, in order (become MA-013…MA-015 in PR A):

1. Create the Resend account; add the sending domain — recommend a
   subdomain such as `mail.<domain>` so the root domain's reputation is
   untouched and DMARC can be strict.
2. DNS at the registrar: the two DKIM CNAME/TXT records and the SPF TXT
   Resend shows on the domain page; optional MX for bounce handling;
   DMARC `v=DMARC1; p=quarantine; rua=mailto:dmarc@<domain>` on
   `_dmarc.mail.<domain>` (start `p=none` for a week if unsure).
3. Wait for Resend to show "Verified"; send the test email from the
   dashboard.
4. Railway `scribe-api`: `RESEND_API_KEY`, `EMAIL_FROM="Scribe <no-reply@mail.<domain>>"`,
   `EMAIL_REPLY_TO` (a real inbox). Without `RESEND_API_KEY` the API logs
   the invite link instead of sending (dev + tests keep working).
5. Templates in PR A: invite; PR B: magic link, welcome; later: takeoff
   ready, quote to customer.

**DECIDE:** which domain sends. There is no custom domain yet (web/api live
on `up.railway.app`, which cannot send mail). Cheapest path: buy/choose the
product domain now, use it for mail first, move web/api to it later.

### 1.7 Tenancy scope (PR C)

Schema (migration `0014_orgs.sql`):

```sql
CREATE TABLE orgs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  logo_s3_key text,
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE users
  ADD COLUMN org_id uuid REFERENCES orgs(id),
  ADD COLUMN org_role text NOT NULL DEFAULT 'member' CHECK (org_role IN ('owner','member')),
  ADD COLUMN is_platform_admin boolean NOT NULL DEFAULT false;
ALTER TABLE takeoffs      ADD COLUMN org_id uuid REFERENCES orgs(id);
ALTER TABLE quotes        ADD COLUMN org_id uuid REFERENCES orgs(id);
ALTER TABLE customers     ADD COLUMN org_id uuid REFERENCES orgs(id);
ALTER TABLE eval_fixtures ADD COLUMN org_id uuid REFERENCES orgs(id);
-- backfill: one org "CabinetNow"; every existing row → that org;
-- mhittle@gmail.com + ridadarwish12@gmail.com → owner + is_platform_admin;
-- dev@scribe.local and signal-connector@scribe.local → that org.
-- then SET NOT NULL on the four org_id columns + indexes.
ALTER TABLE org_settings DROP CONSTRAINT org_settings_id_check;  -- singleton → per org
ALTER TABLE org_settings ADD COLUMN org_id uuid UNIQUE REFERENCES orgs(id);
```

Platform-level (no org): `pricing_configs`, `product_lines`,
`export_templates`, `sources`, `projects`, `project_documents`,
`token_spend`. Pricing is CabinetNow's price book — every org quotes
against it.

Request context: `SessionUser` gains `orgId`, `orgRole`,
`isPlatformAdmin`. `requireAdmin` today means `role === 'admin'`; split it
into `requirePlatformAdmin` (pricing editor, sources, prospects, usage
across orgs, invites for new orgs) and `requireOrgOwner` (org settings,
members). The existing `role` column stays for estimator/sales semantics.

Routes that change (every list/detail/mutation adds `where org_id =
req.user.orgId`, or 404 on a cross-org id):

| File | Routes | Change |
|---|---|---|
| `routes/takeoffs.ts` | 26 of 27 (`/product-lines` is global) | `POST /takeoffs` stamps `org_id`; `GET /takeoffs`, `GET /jobs` filter; every `:id` route loads with org check via one `loadTakeoff(id, orgId)` helper |
| `routes/quotes.ts` | 9 | same pattern; `customers` scoped |
| `routes/dashboard.ts` | 1 | counts per org |
| `routes/projects.ts` | 4 | platform admin only (prospector is internal) |
| `routes/admin.ts` | 14 | org-settings/logo → per org (owner); users → org members (owner) + platform view; pricing/templates/sources → platform admin |
| `routes/auth.ts` | `/auth/me` | returns org + flags |
| workers | `process.ts`, `staged.ts`, `detect.ts` | copy `takeoff.org_id` onto `eval_fixtures` and `quotes` they create; no other change |
| signal connector | service user | belongs to the CabinetNow org; unchanged externally |

Web: `Me` type gains org; Admin tab visibility keys off `isPlatformAdmin`
vs `orgRole === 'owner'`. Tests: one route test per file asserting a
cross-org id returns 404 (the security regression gate).

### 1.8 `invites` table (PR A, migration `0013_invites.sql`)

```sql
CREATE TABLE invites (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  token_hash text NOT NULL UNIQUE,           -- sha256(token); token is 32 random bytes base64url, shown once
  email text NOT NULL,
  name text,                                  -- optional prefill
  credits_granted integer NOT NULL DEFAULT 0, -- pages; applied when credits ship
  org_id uuid,                                -- NULL = sign-up creates a new org; set = join this org (PR D members)
  invited_by uuid NOT NULL REFERENCES users(id),
  note text,                                  -- admin-only ("met at KBIS")
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  used_by uuid REFERENCES users(id),
  revoked_at timestamptz,
  last_sent_at timestamptz,                   -- "Resend email" button
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX invites_email_idx ON invites (lower(email));
```

`users` additions (same migration): `phone`, `company` (dropped into
`orgs.name` by PR C), `heard_from`, `terms_accepted_at`, `terms_version`,
`terms_ip`, `last_sign_in_at`.

### 1.9 PR plan, order and LOE (roadmap scale 1–10)

Recommended order is **A → C → B → D**, not A → B → C → D: a sign-up
before tenancy would create a user who sees every CabinetNow job, and
nothing about B is testable safely until C. B is also smaller once `orgs`
exists (the transaction in 1.2 needs the table).

| PR | Contents | LOE | Manual actions |
|---|---|---|---|
| **A. Email provider + invites API** | `packages/email` (Resend client, `sendInvite`, log-only fallback), migration 0013, `POST /admin/invites` (platform admin; creates + emails; returns the link too), `GET /admin/invites` (pending / used / revoked), `POST /admin/invites/:id/resend`, `DELETE /admin/invites/:id` (revoke), `GET /signup/:token` (public; returns email/name/state, never the token), Admin → Users "Invite" dialog + pending list, `.env.example`, INSTALL.md | 3 | Resend account, domain, DNS, `RESEND_API_KEY`, `EMAIL_FROM` on `scribe-api` |
| **C. Tenancy** | migration 0014 + backfill, `SessionUser` org fields, `requirePlatformAdmin` / `requireOrgOwner`, every route in 1.7, worker org stamping, cross-org 404 tests, Admin gating in web | 5 | none (migration applies at boot); confirm both owner emails are platform admins after deploy via `/auth/me` |
| **B. Sign-up page** | `POST /signup` (transaction in 1.2, creates org), `/signup?token=` route in the web app (form, terms, error states), session hand-off identical to OAuth (`#session=`), lands on Jobs; magic link (`login_tokens`, `POST /auth/magic-link`, `GET /auth/magic/:token`, login-screen email field); welcome email; `messages.ts` copy for every error | 3 | Google consent screen → external + published (1.5); terms + privacy URLs |
| **D. Account screens** | `/account`: profile (name, phone), org (name, logo — reuse the org_settings logo upload), members list (owner: remove, change role), "Invite a teammate" (an invite with `org_id` set), sign out; account menu in the top bar (also hosts "Show me around", §2) | 3 | none |

Total LOE 14 across four PRs; A and C can be built in parallel (disjoint
files except `schema.ts` and the migration numbers 0013/0014).

---

## 2. Onboarding tutorial (build after PR B)

### 2.1 Form — **DECIDE**

Two parts, both in the design system, no tour library:

1. **A seeded sample job.** On sign-up (inside PR B's transaction, or the
   first `GET /jobs` of an org with zero takeoffs) the API clones a
   platform-owned template takeoff into the new org: `takeoffs` row (status
   `review`), its `takeoff_detections`, `takeoff_lines` and derived faces,
   all pointing at the SAME storage keys (the sample PDF and page renders
   are read-only shared objects under `samples/`). Named "Sample kitchen —
   try it", flagged `takeoffs.is_sample = true` so it is excluded from
   usage/credits and can be deleted or re-seeded from the account menu. The
   template itself is built once by a platform admin from a normal job and
   marked as the template in Admin (`org_settings` → `sample_takeoff_id`
   on the platform row). Cost: one real read, once.
2. **Step callouts.** `components/ui/Coachmark.tsx`: a small anchored
   popover (title, one sentence, "Next" / "Skip tour", step N of M)
   attached to elements tagged `data-tour="jobs-upload"` etc. One short
   sequence per screen: Jobs (upload zone, the sample job row) → Pages (the
   sheet picker, the Continue button) → Mark (draw an area, Find, Build) →
   Review (a line's size fields, batch accept, the live estimate) → Quote
   (tier, Send gate). Progress in `users.onboarding` jsonb
   (`{seen: {jobs: true, …}, dismissed_at}`) via `PATCH /me` so it follows
   the user across devices; "Show me around" in the account menu resets it.
   The sequence never blocks input — it points, the user acts.

Sample plan set: **DECIDE** which PDF. The 18 test kits and the CRM quotes
are customers' drawings (client info — product-plan §4 says plan PDFs
carry client info); a sample needs one we own or one with permission.
MOLLY_CHARLEY_KITCHEN is the owner's test set — usable if it is ours.

LOE 4 (seed clone 2, coachmarks + copy 2). Ships as its own PR after B.

---

## 3. Credits — data model and pricing (plan only)

### 3.1 Schema (migration `0015_usage_credits.sql`)

```sql
CREATE TABLE model_rates (               -- versioned; rows are never updated
  id serial PRIMARY KEY,
  model text NOT NULL,                   -- exact model id, e.g. 'claude-sonnet-4-6'
  input_cents_per_mtok integer NOT NULL, -- $3.00 → 300
  output_cents_per_mtok integer NOT NULL,
  cache_write_cents_per_mtok integer NOT NULL,
  cache_read_cents_per_mtok integer NOT NULL,
  effective_from timestamptz NOT NULL DEFAULT now()
);
-- seed (Anthropic list, 2026-09): sonnet-4-6 300/1500/375/30; haiku-4-5 100/500/125/10;
-- opus-4-8 500/2500/625/50; openai gpt-4.1 (cross-validate) per its list price.

CREATE TABLE usage_events (
  id bigserial PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES orgs(id),
  takeoff_id uuid REFERENCES takeoffs(id),
  stage text NOT NULL CHECK (stage IN ('classify','locate','detect','measure','spreadsheet','cross_validate','verify','extract')),
  model text NOT NULL,
  model_rate_id integer NOT NULL REFERENCES model_rates(id),
  input_tokens integer NOT NULL,
  output_tokens integer NOT NULL,
  cache_write_tokens integer NOT NULL DEFAULT 0,
  cache_read_tokens integer NOT NULL DEFAULT 0,
  image_count integer NOT NULL DEFAULT 0,
  page_number integer,                   -- when the call is about one page
  cost_microcents bigint NOT NULL,       -- cents × 1e6 (a 1k-token Haiku call is 0.1¢ — cents would round to 0)
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX usage_events_takeoff_idx ON usage_events (takeoff_id);
CREATE INDEX usage_events_org_day_idx ON usage_events (org_id, created_at);

CREATE TABLE credit_ledger (
  id bigserial PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES orgs(id),
  delta integer NOT NULL,                -- pages; + grant/purchase/refund/release, − hold/settle
  reason text NOT NULL CHECK (reason IN ('signup_grant','admin_grant','purchase','hold','settle','release','refund','adjust')),
  takeoff_id uuid REFERENCES takeoffs(id),
  hold_id bigint REFERENCES credit_ledger(id),  -- settle/release/refund point at their hold
  balance_after integer NOT NULL,
  actor_user_id uuid REFERENCES users(id),
  external_ref text,                     -- Stripe checkout session id, invite id
  note text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX credit_ledger_org_idx ON credit_ledger (org_id, id DESC);
ALTER TABLE orgs ADD COLUMN credit_balance integer NOT NULL DEFAULT 0;  -- cache; = sum(delta), asserted by a test and a nightly check
ALTER TABLE takeoffs ADD COLUMN credit_hold_id bigint REFERENCES credit_ledger(id), ADD COLUMN pages_charged integer;

CREATE TABLE platform_settings (         -- one row
  id integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  signup_grant_pages integer NOT NULL DEFAULT 20,
  min_pages_per_job integer NOT NULL DEFAULT 5,
  credits_enforced boolean NOT NULL DEFAULT false,  -- off = record only; on = block at zero balance
  sample_takeoff_id uuid REFERENCES takeoffs(id)
);
```

Writes are serialized per org with `SELECT … FROM orgs WHERE id = $1 FOR
UPDATE` inside the ledger transaction; `balance_after` is computed there,
never in JS.

### 3.2 Hook points

- `TakeoffBudget` gets a context (`{orgId, takeoffId}`) and
  `record(usage, {stage, model, images, page})`. It keeps the in-memory cap
  and additionally inserts a `usage_events` row (awaited, but a failed
  insert is logged and never fails the build). Usage objects already carry
  `cache_creation_input_tokens` / `cache_read_input_tokens` when caching is
  on (it is not, today — recorded as 0). Call sites: `classify.ts`,
  `regions.ts`, `extract.ts`, `spreadsheet.ts` already call
  `budget.record`; `detect.ts` sums `message.usage` by hand in two places
  (lines ~231 and ~989) and needs the same call. OpenAI cross-validation
  usage is recorded under its own model id.
- Credits: `POST /takeoffs/:id/pages` (Pages submit) opens a **hold** of
  `max(selectedPages, min_pages_per_job)`; the build's final state
  transition to `review` writes **settle** (same amount — the hold IS the
  price, see 3.4); `failed` writes **release**. A hold that outlives a
  takeoff by 24 h with no terminal state is released by a sweep. Images and
  spreadsheets are one page each at upload.

### 3.3 Admin "Usage" view

Platform admin tab. Three tables from `usage_events`, all with a date
range and org filter: per takeoff (pages, tokens by stage, cost, credits
charged, cost per page), per stage (calls, tokens, cost, share), per page
class (plan vs elevation — plan pages carry crops + decomposition and
should cost more; verify). Plus the org's `credit_ledger` and an "Adjust
credits" action (writes `adjust` with a note). The 18-kit corpus can be
replayed into `usage_events` for a first distribution before any customer.

### 3.4 Pricing — **DECIDE**

Measured cost (history (i), Sonnet 4.6 at $3/$15 per MTok, mostly input):
a 4-page kitchen set is 13k–23k tokens → 5–9¢; a 4-page office set 66k →
~25¢. So **1–6¢ per page**. A human takeoff for comparison: outsourced
estimating services and freelance takeoff shops typically charge roughly
$150–$400 for a residential kitchen/bath cabinet takeoff and $500–$2,000+
for a commercial casework package, or $50–$90 per hour (market knowledge,
not measured — worth one phone call before we print a price). The
customer's alternative therefore costs 50–500× what our reading costs.

Proposal:

| Item | Proposal | Why |
|---|---|---|
| Unit | **1 credit = 1 page read** (a selected PDF sheet, an image, a spreadsheet) | matches what the user chose on Pages; cost preview is exact |
| Price | **$1 / page** list, sold in packs | 20–50× margin; simple to say |
| Per-job minimum | **5 pages** ($5) | a 1–2 page sketch job still costs something; avoids the "$1 job" |
| Packs | 25 pages $25 · 100 pages $90 · 500 pages $400 | pack discounts sell volume without touching the per-page story |
| Sign-up grant | **20 pages** | 3–5 typical jobs; enough to reach a quote, not enough to run a business on |
| Re-runs | **included**: Find, Build, Measure again, area edits, cross-validation cost nothing extra; re-uploading the same file is a new job and charges again | corrections are cents; charging for them punishes exactly the behaviour we want (fixing the draft) |
| Enforcement | `credits_enforced=false` until Stripe lands: record and show, never block | invite-only beta gets grants; nobody should hit a paywall before there is a way to pay |

The perceived-value problem the owner raised ($4 for a kitchen "reads as
free") is real, and the fix is the framing, not the number: price the
**job** ("from $5 per job, $1 per additional page") and put the human
comparison ("a takeoff service charges $150+") on the pricing page. An
alternative worth considering is **per job, $10 flat up to 10 pages, then
$1/page** — simpler to understand, closer to how buyers think about a
takeoff, same revenue on typical jobs. Pick one; the ledger supports both
(the hold amount is the only formula that changes).

LOE: 3a usage ledger + Admin view 3; 3b credits (hold/settle/release, balance in
the top bar, cost preview on Pages, grant on sign-up) 4. Depends on PR C.

---

## 4. Stripe (roadmap only — not built)

Roadmap row stands ("Stripe payments", Pri 7, LOE 4). Dependencies, in
order: credits ledger (3.1) → Stripe account + Checkout for the packs in
3.4 (`POST /billing/checkout {pack}` → hosted Checkout, `success_url` back
to `/account?purchased=1`) → `POST /billing/webhook`
(`checkout.session.completed`, signature-verified, idempotent on
`external_ref = session id`) writes a `purchase` ledger row → receipt email
from the same Resend domain as Task 1 (Stripe's own receipts can stay off
so all mail comes from one sender). Manual actions when built: Stripe
account, products/prices for the packs, `STRIPE_SECRET_KEY` +
`STRIPE_WEBHOOK_SECRET` on `scribe-api`, the webhook endpoint registered.
Sales tax / invoices for net-30 customers are out of scope until asked.

---

## 5. Decisions needed before coding

1. PR order A → C → B → D (recommended) or the original A → B → C → D.
2. Sign-in method: A (Google + magic link, no password) recommended.
3. Sending domain for Resend, and whether to buy the product domain now.
4. Terms + Privacy Policy pages: author and URL.
5. Tutorial form (seeded sample job + coachmarks) and which sample PDF.
6. Pricing: per page with a 5-page minimum, or $10 per job up to 10 pages;
   the sign-up grant; pack sizes.

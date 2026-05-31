# sauce.ai/news — Roadmap

Backlog of future sprints, features, and projects. **At the start of every
engineering session, ask the user whether to work off this roadmap or
something else** (per `new-engineering-session-instructions.md`).

## Conventions

Each item is rated on three axes:

- **Priority** (1–10): how much this matters. 10 = drop-everything, 1 = nice to have someday.
- **LOE** (1–10): rough effort estimate. 1 = under an hour, 10 = multi-week project.
- **Category**: one or more of `infra`, `new-feature`, `ui`, `backend`, `algo`, `security`, `ops`, `skunkworks`, `docs`. Add new categories as needed; document them here.

Status values: `backlog` (default), `proposed` (PM agent suggestion;
not yet authorized for dev), `ready-for-agent` (queued for the
unattended dev workflow), `in-progress`, `done`, `dropped`.

Add new items at the bottom of the appropriate section. When you move an item
to `done`, also append a section to `engineering-history.md` describing what
shipped.

---

## At-a-glance

| Pri | LOE | Category | Title | Status |
| --- | --- | --- | --- | --- |
| 6 | 1 | ui, ops, docs | Root sauce.ai/ landing page (product lab positioning + coming-soon product cards) | done |
| 6 | 3 | ui, new-feature, backend | Lab landing expansion: 10 more radical concepts + anon up/down voting | in-progress |
| 9 | 8 | backend, new-feature | Sandboxed Python algorithm execution | backlog |
| 6 | 4 | backend, algo, ops | Demand-driven feed classification — keep a ~400 buffer, page 40, background top-up | done |
| 9 | 6 | backend, ui, new-feature, algo | Story dossier (multi-source view of a single story) | done |
| 8 | 7 | ops, backend, new-feature | Automated source discovery (Reddit/HN + LLM agent) | done |
| 7 | 7 | ops, new-feature | Automated source discovery — social firehoses (Mastodon, Bluesky, X/Twitter) | backlog |
| 8 | 7 | algo, backend, new-feature | Signal Learning (implicit + explicit reader signals → per-user adjustments) | backlog |
| 7 | 4 | security | CSRF tokens + auth rate limiting | done |
| 7 | 4 | algo | Fold internal clicks into popularity (superseded by Signal Learning) | backlog |
| 7 | 4 | ui | Mobile / responsive polish | done |
| 7 | 4 | new-feature, ui | Article summary (3-bullet TL;DR via Haiku) | done |
| 7 | 4 | ui, new-feature, algo | Reading diet meter | backlog |
| 7 | 5 | new-feature, algo | Trending topics view (upgraded post-dedup) | done |
| 7 | 4 | algo, backend, ui | External trending sort (Google News/Trends) — BUG-015 | done |
| 7 | 3 | ui | Why This Article (ranking explainer popover) | done |
| 7 | 3 | ui, algo | Across-the-spectrum in-feed (mini-dossier on multi-source cards) | done |
| 7 | 3 | new-feature, ui, algo | Discussion links (Techmeme-style Reddit/HN threads) | done |
| 6 | 4 | new-feature, ui | Article save / bookmark | done |
| 6 | 4 | new-feature, ui | TTS audio mode (Read-me-my-queue) | backlog |
| 6 | 2 | ui, backend | Feed sort selector (Relevance / Newest / Popularity) | done |
| 6 | 4 | new-feature, ui | User-added RSS feed subscriptions | done |
| 6 | 6 | new-feature, ui | Search across articles | done |
| 5 | 5 | infra | Test coverage expansion | backlog |
| 5 | 3 | security | Email verification on signup | backlog |
| 5 | 1 | ops | CloudLinux/GoDaddy support ticket re: shim | backlog |
| 4 | 7 | infra, skunkworks | Migrate to VPS (gunicorn + nginx) | backlog |
| 3 | 2 | ui | Dark mode | done |
| 8 | 5 | ui, algo, new-feature | Natural-language algorithm builder | done |
| 8 | 4 | algo, ui | Keyword / topic mute & boost | done |
| 7 | 3 | algo, ui | Per-algorithm keyword mute & boost (in the algo builder) | done |
| 6 | 3 | algo, ui, new-feature | Keywords-on-algo only (drop /terms; travel with gallery publish/adopt) | done |
| 6 | 2 | ui | Fold per-algorithm Keywords into the Your Algorithm feature list | done |
| 7 | 4 | backend, ui | Multiple saved algorithms / profiles | in-progress |
| 6 | 5 | ui, algo | A/B split feed | backlog |
| 6 | 2 | ui | Compact / density toggle (Techmeme-style) | in-progress |
| 6 | 2 | ui, algo, backend | Unique sources toggle — one article per source (Your Algorithm) | in-progress |
| 7 | 3 | ops, new-feature | Source catalog expansion (+1000 high-quality sources, incl. Substack / Medium) | done |
| 7 | 4 | ui, new-feature | Onboarding interview / cold-start | done |
| 7 | 4 | algo, ui | Tune from this article (Signal-Learning wedge) | done |
| 6 | 3 | ui, ops | Periodic "is your feed working?" check-in | backlog |
| 8 | 6 | new-feature, ui | Shareable algorithm gallery | in-progress |
| 7 | 5 | algo, backend | Community source-quality overlay | backlog |
| 6 | 5 | new-feature | Community "add a source" on dossiers | backlog |
| 7 | 5 | algo, backend | Perceptual feature expansion (12 new ranking features) | done |
| 8 | 3 | infra, ops, skunkworks | Agent infra: Unattended dev-agent dispatcher | done |
| 9 | 2 | infra, security | Agent infra: Pre-merge QA + BUG-007 gate | done |
| 8 | 4 | infra, ops | Agent infra: Post-deploy verification | done |
| 10 | 5 | infra, ops, backend | Agent infra: Migration / restart executor | done |
| 6 | 2 | infra, ops | Agent infra: Bug auto-triage | done |
| 5 | 3 | infra, skunkworks | Agent infra: PM agent (weekly proposals) | done |
| 6 | 3 | infra, ops | Agent fleet observability — weekly cost + activity rollup | done |
| 7 | 6 | new-feature, backend, ops, algo | Breaking-news email alerts (major-event detection → opt-in email) | ready-for-agent |
| 7 | 3 | ui, algo, new-feature | Steel-man — strongest opposing-view coverage of a story | in-progress |

---

## Items in detail

### Breaking-news email alerts (major-event detection → opt-in email)
**Priority:** 7 · **LOE:** 6 · **Category:** new-feature, backend, ops, algo · **Status:** ready-for-agent

**User value / why now.** Today sauce.ai only reaches a reader when they
come to us (the home feed) or once a day (the digest). When something
genuinely major breaks, an engaged reader wants to *hear about it* — that
is the single highest-value re-engagement moment a news product has, and
we're currently silent in it. This is a retention/habit lever, and it
leans on the one thing our multi-source backend uniquely owns:
**distinct-outlet counting** (the same signal that powers `/trending`).
"A story that suddenly hits many independent outlets at once" is the
textbook breaking-news signature — no dependency on Google's noisy
token-match. We also already own the entire email path (digest), so this
is mostly assembly + one detection job, not new infrastructure.

**Product decisions already made with the owner:**
- **Detection = outlet-burst + a cheap LLM confirmation gate.** A bad
  push email is worse than no email, so a deterministic threshold alone
  isn't enough — one Haiku call confirms the event is genuinely major and
  writes the push headline/blurb.
- **Targeting = broad, minus mute keywords.** A major event is major for
  everyone, so every opted-in user gets it — *except* we suppress an
  alert whose topic matches that user's active-profile mute keywords.
- **Opt-in = a new toggle, default off**, independent of the daily
  digest (different intrusiveness level; the two must not be conflated).

**How detection works (new cron `news/jobs/breaking_alerts.py`, every
~15 min).** Mirrors the structure of `jobs/popularity_poll.py` /
`jobs/trending_poll.py`: `from _bootstrap import Config, get_conn,
setup_logging, db_log, job_lock, AlreadyRunning`; `JOB =
"breaking_alerts"`; `with job_lock(JOB): _run()`; `conn.ping(reconnect=
True)` before the send block (BUG-009 idle-socket lesson). Master
kill-switch env `BREAKING_ENABLED` (default on); fast no-op when off.
1. **Candidate query** — distinct global outlets per recent story
   cluster:
   ```sql
   SELECT a.story_id,
          COUNT(DISTINCT a.source_id) AS outlet_count,
          MAX(a.published_at)         AS latest
   FROM articles a
   JOIN sources s ON s.id = a.source_id
   WHERE a.story_id IS NOT NULL
     AND a.published_at >= UTC_TIMESTAMP() - INTERVAL %s HOUR  -- BREAKING_WINDOW_HOURS, default 6
     AND s.owner_id IS NULL                                    -- global pool only, not personal feeds
   GROUP BY a.story_id
   HAVING outlet_count >= %s                                   -- BREAKING_MIN_OUTLETS, default 12
   ORDER BY outlet_count DESC;
   ```
2. **Dedup** — skip any `story_id` already in `breaking_news_alerts`
   (UNIQUE on `story_id`), so each story alerts at most once.
3. **LLM gate** — for each survivor, fetch the canonical article
   (title + summary; optionally a few member headlines) and make one
   call via the existing Haiku client (`app/classifier/llm.py` pattern;
   reuse the configured model + `LLMUnavailable` + `llm_usage` cost
   logging). Prompt returns strict JSON: `{is_major: bool, headline:
   str, blurb: str}`. Record the verdict in `breaking_news_alerts`
   (`status` = `sent` or `rejected`) so a rejected story is **not**
   re-judged every 15-min tick. On `LLMUnavailable`, **record nothing
   and skip** (fail-closed — a confirmation-less push is the risk we're
   avoiding) so a later tick retries while the story is still in window.
4. **Send** — for a `sent` event, email every opted-in, under-cap,
   non-suppressed user (see below), then write the event row with
   `recipients`.

**Opt-in + per-user state (new table `user_alert_prefs`, deliberately
SEPARATE from `users` so it is migrate-after-deploy safe / NOT BUG-007
class):**
```sql
CREATE TABLE IF NOT EXISTS user_alert_prefs (
  user_id          INT UNSIGNED NOT NULL,
  breaking_enabled TINYINT(1) NOT NULL DEFAULT 0,
  unsub_token      CHAR(40) NOT NULL DEFAULT '',
  alerts_day       DATE DEFAULT NULL,
  alerts_today     INT UNSIGNED NOT NULL DEFAULT 0,
  last_alert_at    DATETIME DEFAULT NULL,
  updated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id),
  CONSTRAINT fk_uap_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
A per-user **daily cap** `BREAKING_MAX_PER_DAY` (default 3) uses
`alerts_day`/`alerts_today` (reset when the UTC date rolls) so a busy
news day can never spam one inbox. **Mute suppression:** for each
recipient, load their active-profile mute terms (`SELECT term FROM
algorithm_term_prefs WHERE algorithm_id = <active> AND mode = 'mute'`)
and skip the send if the event headline/title matches, using the **same
case-insensitive substring semantics** as the feed's keyword mute.
⚠️ **Correction (verified against code 2026-05-31):** `app/term_prefs.py`
`build_term_clauses` is **SQL-clause-building only — there is no pure
Python matcher to reuse today.** So *extract* one: add a pure
`term_matches(text, term) -> bool` to `app/term_prefs.py` that lower-cases
`text` and does the escaped-`LIKE`-equivalent substring test (mirror the
existing `_MATCH_EXPR` `LOWER(CONCAT(title,' ',summary))` + `escape_like`
semantics), refactor `build_term_clauses` to be expressed in terms of the
same matching rule, and call `term_matches` from `breaking.is_suppressed`.
One matcher, two callers — so the alert-suppression rule can never drift
from the feed's mute rule.

**Sketch (files/surfaces to touch):**
- `news/seed/migrations/2026-05-31-breaking-alerts.sql` (new) +
  `news/seed/schema.sql` (+`user_alert_prefs` and `breaking_news_alerts`
  CREATE TABLEs, near the trending/`llm_usage` tables).
  `breaking_news_alerts(id, story_id UNIQUE, outlet_count, status
  ENUM('sent','rejected'), headline, blurb, recipients, detected_at)`.
- `news/app/breaking.py` (new, pure / Flask-free, mirrors
  `app/feed_diversify.py` / `app/trending.py`): `select_candidates(rows,
  min_outlets)`, `is_suppressed(event_text, mute_terms)`,
  `daily_cap_ok(prefs_row, max_per_day, today)`, and a `parse_llm_verdict`
  clamp/validate helper. This is where the unit tests live — no
  Flask/DB/SMTP/Haiku needed.
- `news/app/term_prefs.py` (edit) — add the pure
  `term_matches(text, term) -> bool` helper described above and refactor
  `build_term_clauses` to share its matching rule; `breaking.is_suppressed`
  delegates to it. Pure, already unit-tested module — extend
  `tests/test_term_prefs.py` with `term_matches` cases.
- `news/jobs/breaking_alerts.py` (new cron) — orchestrates query → dedup
  → LLM gate → send, using the pure helpers above.
- `news/app/mailer.py` (new, small) — extract the inline smtplib +
  `MIMEMultipart("alternative")` + `List-Unsubscribe` /
  `List-Unsubscribe-Post` block currently duplicated in
  `jobs/send_digest.py` into one `send_email(to, subject, html, text,
  list_unsub_url)` helper, and **refactor `send_digest.py` to call it**
  (behavior-preserving) so the two senders can't diverge. (If extraction
  proves risky, duplicating the ~15 lines is an acceptable fallback —
  justify in the PR.)
- `news/app/templates/breaking_email.html` + `breaking_email.txt` (new) —
  single-event push layout: headline, blurb, "N outlets covering this",
  a link to the story dossier (`/story/<story_id>` — our killer demo, the
  perfect landing surface), and the one-click unsubscribe footer.
- `news/app/routes/account.py` — add a **"Breaking news alerts"** checkbox
  to `settings()` + `account_settings.html` (next to the digest toggle,
  clearly labeled as more intrusive/rarer), reading/writing
  `user_alert_prefs.breaking_enabled` and minting `unsub_token` on enable
  (mirror `_ensure_unsub_token`). Add a dedicated one-click route
  `/account/alerts/unsubscribe/<token>` (GET+POST, RFC 8058, CSRF-exempt
  like the digest unsubscribe) that flips `breaking_enabled = 0` and
  rotates the token.
- `news/app/config.py` — `BREAKING_ENABLED`, `BREAKING_WINDOW_HOURS`,
  `BREAKING_MIN_OUTLETS`, `BREAKING_MAX_PER_DAY` (env-defaulted).
- `news/INSTALL.txt` — document the new env knobs, the new every-15-min
  cron line, and the migration (touches `jobs/*` + `config.py`, so the
  BUG-007 gate expects an INSTALL.txt update in the same PR).

**Preserve / must-not-break:**
- The daily digest is untouched in behavior (only refactored to share
  `mailer.py`). The two opt-ins are independent.
- App code must **tolerate both new tables being absent** (migrate-after-
  deploy): `settings()` wraps the `user_alert_prefs` read in try/except
  and renders the toggle as "off" if the table is missing; the
  unsubscribe route shows "already unsubscribed"; the cron no-ops on a
  missing table. So this is **NOT BUG-007 class** — a missing migration
  never 500s a user route. Label the PR `has-migration` (not
  `needs-migration`); the executor applies it post-deploy per
  `agent-fleet.md`.

**Constraints / watch-outs:**
- **No synchronous LLM and no process spawn on any request path** — the
  Haiku gate runs only in the cron; the web app only reads/writes the
  toggle. nproc ceiling untouched.
- **Fail-closed on the LLM gate** (don't send if unconfirmed) and
  **per-story dedup + per-user daily cap** are the three guards against a
  spammy or embarrassing send. With `min_outlets >= 12` + dedup, expect
  ~1–5 alerts/day; the Haiku gate is a handful of calls/tick at most
  (sub-cent/day). Email volume = alerts/day × opted-in users.
- Reuse the existing `SMTP_*` config and localhost-MTA default; no new
  pip dependency, no new secret. One new cron entry (manual-actions Open).

**Rollout (owner decision 2026-05-31 — go live on deploy, NO shadow/dry-run
mode):** the first qualifying event will email real opted-in users as soon
as the cron + migration are live, so the three guards must be airtight and
`BREAKING_MIN_OUTLETS`/`BREAKING_WINDOW_HOURS`/`BREAKING_MAX_PER_DAY` MUST be
env-tunable (read from `config.py`, never hard-coded) — the catalog is now
**1,919 feeds** (up from 768 when first spec'd), so "12 outlets in 6h" is a
looser bar than it was and the owner will tune `BREAKING_MIN_OUTLETS` after
watching the real firing rate. `BREAKING_ENABLED` (master kill-switch,
default on) is the instant-stop if a send misbehaves: a single env flip +
no restart needed (it's a cron, fresh process each tick). The cron MUST log
one structured line per tick — candidates considered, LLM verdicts
(sent/rejected), recipients emailed — so the owner can audit firing rate and
quality from `logs/cron.log` / `/admin/cron-health` without a DB query.
Default opt-in is **off**, so day-one blast radius = only users who actively
enabled the toggle.

**Manual-actions the dev agent must file (Open, full inline SQL/commands per
`manual-actions.md` conventions, account `lt1ih6uyy2z6` substituted):** (1)
the two-table migration (`has-migration` label — applied post-deploy by the
executor, NOT BUG-007 class since both tables are tolerated-absent); (2) the
new every-~15-min `breaking_alerts.py` cron line; (3) a note that the new
`BREAKING_*` knobs are env-defaulted (no action required to ship, but listed
so the owner knows where to tune them). Restart the Python App on deploy
(new `/account/alerts/unsubscribe/<token>` route).

**Test expectation:** `pytest news/tests/` stays green. New
`tests/test_breaking.py` covers the pure helpers without Haiku/DB/SMTP:
candidate threshold (≥ min_outlets selected, below skipped), mute
suppression (matching term → suppressed; non-match → sent), daily-cap
rollover, and `parse_llm_verdict` clamping/`is_major=false`/malformed-JSON
→ no send. The LLM call is stubbed; no test requires a live DB, MTA, or
browser. Add `term_matches` cases to `tests/test_term_prefs.py` (case-fold,
substring hit/miss, LIKE-metacharacter escaping) and a parity assertion that
`is_suppressed` agrees with `term_matches` so the alert-suppression rule
can't drift from the feed mute rule.

**v2 (out of scope):** per-user relevance personalization of which events
qualify; "follow this story/topic" granular alerts; SMS / Web Push
channels; a frequency/quiet-hours control; an end-of-day "what you
missed" recap for users who weren't around.

### Demand-driven feed classification — keep a ~400 buffer, page 40, background top-up
**Priority:** 6 · **LOE:** 4 · **Category:** backend, algo, ops · **Status:** done (PR #121; new 1-min cron pending in manual-actions Open)

Today classification is a 5-minute cron (`jobs/classify_pending.py`,
rules + Haiku); the feed shows only `status='classified'` rows
(`feed.py`, 30/page). An active reader can outpace the cron and hit the
end of the classified set — the feed runs dry until the next tick. Make
**feed activity drive classification** so the feed stays effectively
endless, **without ever blocking on Haiku at request time**.

Decisions already made with the maintainer:
- **Background top-up, never synchronous.** The HTTP response must never
  wait on classification — serve already-classified rows immediately and
  trigger classification out-of-band.
- **~400 = classified buffer depth to maintain**, global/shared (an
  article is classified once for everyone; only *ranking* is per-user).
- **40 = "load more" page size** (currently 30).

**Behavior:**
- Feed page size 30 → 40 (`feed.py:90`).
- On feed load and each "load more": if the classified depth available
  ahead of the reader is below ~400, **fire a background classification
  top-up** and return the page immediately.
- Repeated top-ups keep extending the classified set as the reader pages,
  until the pending pool is exhausted ("keeps going like that").

**The crux is HOW to classify out-of-band on THIS host — it has a known
foot-gun.** CloudLinux/Passenger here has a **tight nproc/EP limit
(~115); a fork storm fork-bombs Passenger** (see
`new-engineering-session-instructions.md` Step 10). Therefore:
- **Never fork/spawn a classifier per request.** Debounce hard.
- Reuse `classify_pending.py`'s existing **single-run `job_lock(JOB)`**
  (raises `AlreadyRunning`) and **`CLASSIFY_BUDGET_SECONDS` walltime
  budget** — a trigger must be a no-op while a run is in progress, and two
  concurrent feed loads must never launch two runs.
- Prefer the safest mechanism for this host. **Recommended:** a
  lightweight "classify-now" flag the existing cron honors on its next
  tick (bounded, no new process); or — only if justified and gated behind
  the lock + a cooldown — a single detached, walltime-bounded
  `classify_pending` run. Pick one and justify it in the PR.

**Pointers:** `feed.py` (page size; post-page depth check + debounced
trigger; never block) · `jobs/classify_pending.py` (a small "triggered /
top-up" entrypoint or honor the classify-now flag; keep lock + budget
intact) · `feed.html` ("load more" exists; adjust for 40 + keep-going).

**Constraints:** no synchronous LLM on the request path; respect the
single-run lock and walltime budget; **no per-request process spawning**
(nproc safety); classification stays global; keep `pytest news/tests/`
green and unit-test the trigger decision (buffer-low → trigger,
run-in-progress → skip) without invoking Haiku. Likely no migration — but
if you add a "classify-now" flag table, that's a migration: label the PR
`has-migration` and let it apply post-deploy per `agent-fleet.md`.

### Lab landing expansion: 10 more radical concepts + anon up/down voting
**Priority:** 6 · **LOE:** 3 · **Category:** ui, new-feature, backend · **Status:** in-progress

Follow-on to PR #101 (root `index.html`). User feedback on the first
7 coming-soon concepts: "kind of mid — add more radical, high-leverage
tools like jar.ai." Two coupled changes:

- **+10 concepts on the lab landing page.** Total card grid is now
  1 live + 17 coming-soon. New: `jar` (AI memory jar / second brain),
  `negotiate` (success-fee bill negotiator), `clone` (your voice +
  reasoning, trained), `doctor` (calibrated health triage and second
  opinions), `legal` (contracts / leases / small claims), `tax`
  (year-round agent, file the return), `estate` (wills, beneficiaries,
  digital legacy), `decide` (big-call structurer with simulated
  outcomes), `friend` (relationship-maintenance nudger), `mirror`
  (weekly self-debrief synthesized from digital exhaust).
- **Anonymous up/down voting** on each coming-soon card so visitors
  can rank what we should build next. Aggregate counts visible to
  all (HN-style net score in the middle, ▲/▼ on the sides). Anon
  identity is a 40-hex token in a `lab_voter_token` cookie, scoped
  `Path=/` so the static root page and the news app at
  `sauce.ai/news` share it. Backend: new pure
  `app/lab_concepts.py` (concept-key allowlist + vote validation +
  `tally_with_you`; 12 pure tests), new `app/routes/lab.py` blueprint
  (`GET /labvotes/tally`, `POST /labvotes/vote`), new
  `lab_concept_votes` table (BUG-007 class? **No** — only the
  `/labvotes/*` endpoints touch it; the rest of the news app and the
  static landing page are unaffected if the table is missing; the
  landing page's JS catches a tally fetch error and hides the vote UI
  silently). `lab.vote` added to the CSRF-exempt set
  (anon endpoint, low-stakes, `(concept_key, voter_token)` UNIQUE
  index caps abuse from any one cookie).

*Server-side state:* one new migration
(`2026-05-20-lab-votes.sql` — `CREATE TABLE lab_concept_votes`). No
new cron, no env var, no pip dep, no symlink. Python App restart on
deploy so the new blueprint registers.

v2 ideas (out of scope here): sort cards by net score on load, vote
log / brigading mitigation beyond the per-cookie unique key,
"trending concept" callout above the grid, share buttons per card.

### Root sauce.ai/ landing page
**Priority:** 6 · **LOE:** 1 · **Category:** ui, ops, docs · **Status:** in-progress

Static `index.html` at the repo root (FTP-deployed to
`~/public_html/sauce.ai/index.html` by the existing GitHub Actions
workflow — `local-dir: ./`, `server-dir: /`, incremental sync). Until
now the root domain had no in-repo content; this stakes out the
positioning. Hero states the thesis: **"sauce.ai is an autonomous AI
product development and engineering lab. Agent systems —
semi-autonomously and autonomously — design, build, and ship consumer
products you'll love."** Card grid of 8 products: `sauce.ai/news`
(live, links to `/news`) + 7 "Coming soon" concepts brainstormed as
plausible next agent-built consumer surfaces — Recipes, Travel, Money,
Fit, Learn, Inbox, Stage. Self-contained file (inline CSS, no
framework, no build step); matches the news app's editorial-serif
wordmark and warm-neutral palette; `prefers-color-scheme: dark` for
the dark theme (no JS toggle in v1 — news has its own). No server-side
state, no migration, no cron, no env var, no pip dep.

v2 ideas (not in scope here): per-product "notify me" email capture,
in-flight progress meter per coming-soon product, a /lab page that
shows real-time agent activity / the GitHub PR stream.

### Sandboxed Python algorithm execution
**Priority:** 9 · **LOE:** 8 · **Category:** backend, new-feature · **Status:** backlog

The original spec called for users to write their own ranking algorithms in
Python. v1 ships the "Code" tab on `/algo` as read-only — it renders the
Python equivalent of the UI-chosen weights but doesn't execute user-supplied
code. This is the single biggest feature gap vs the spec.

Approach: needs a sandbox (RestrictedPython, subprocess + seccomp, or
WebAssembly). Must enforce CPU/memory/wallclock limits. User code receives a
fixed input shape (article features) and returns a score. Result is used at
query time the same way the SQL expression is today.

Open questions:
- Sandbox choice. RestrictedPython is easiest to integrate but porous;
  subprocess + resource limits is safer but slower.
- How to handle errors in user code (default back to weighted SQL? show
  warning in UI?).
- Caching of computed scores to avoid running user code per article per
  request.

### Story dossier
**Priority:** 9 · **LOE:** 6 · **Category:** backend, ui, new-feature, algo · **Status:** done (v1, PR #43)

`sauce.ai/news/story/<story_id>` aggregates every article in a
deduplicated story group and presents them across the political-lean
spectrum — three columns (left / center / right) on desktop, vertical
bands on mobile. Each column shows source headline, lead paragraph,
and a small lean badge.

Sticky element at top: a Claude-generated **framing summary** — *"Left-
leaning sources emphasized the demographic impact; right-leaning
emphasized the procedural concerns; AP and Reuters stuck to the
announcement itself."* Cached per story group, recomputed only when
new articles join.

Optional power feature: word-level diff highlights between headlines
and lead paragraphs so coverage divergence is *visible* ("the suspect"
vs "the gunman" vs "the alleged shooter"). This is the screenshot
that gets shared.

This is the **killer demo**. No other aggregator does this — and it's
the feature that requires our opinionated multi-source backend. Without
it, sauce.ai is a slightly nicer Google News; with it, a category of
one.

Cost gating: only run framing summaries for story groups with 3+
articles spanning 2+ lean buckets. Single-source stories don't get a
dossier — their card just links to the source.

Hard dependency on **Article deduplication** (Pri 8) — story_id must
exist first.

### Automated source discovery — social firehoses
**Priority:** 7 · **LOE:** 7 · **Category:** ops, new-feature · **Status:** backlog

Phase 3 of source discovery. Adds three more signal sources to the
candidate pipeline shipped in the Reddit/HN + LLM PR:

- **Mastodon** — public timeline streaming per instance. Easiest, no
  API key needed. Start with a curated list of journalism-heavy
  instances (mastodon.social, journa.host, newsie.social).
- **Bluesky** — the jetstream firehose is a public WebSocket and
  doesn't fit the cron model cleanly; either a long-running worker
  process (new infra pattern) or a periodic batch pull of recent
  `app.bsky.feed.post` records with URLs.
- **Twitter/X** — only viable with a paid API tier ($100/mo Basic
  minimum for usable volume); gated on whether the catalog growth
  justifies the spend.

All three feed the same `candidate_sources` table; the only new code per
platform is a poll/stream worker. Hard-depends on the candidate_sources
schema landing first.

### Signal Learning
**Priority:** 8 · **LOE:** 7 · **Category:** algo, backend, new-feature · **Status:** backlog

Capture every reader signal in a uniform `user_signals` table — `click`,
`dwell_ms`, `scroll_pct`, `thumb_up`, `thumb_down`, `save`, `share`,
`hide`, `return_click`. Nightly job in `maintenance.py` regresses signals
against feature values per user, producing a hidden per-user adjustment
vector that rides alongside the explicit `/algo` weights.

Forward-compatibility (key design constraint): when a new ranking
feature lands later, `maintenance.py` back-classifies historical
articles within a rolling window so the user's accumulated signal
history informs the new dimension immediately. Same pattern as the
obscurity-score backfill, generalized via a `features.added_at` column
+ rescore queue. This means future features instantly benefit from
months of past reader behavior instead of needing fresh data to be
useful.

Two UX modes, staged:
- **Suggest (v1)** — "You read 3x more high-objectivity articles than
  the median. Bump objectivity weight to 1.5? [accept / dismiss]". User
  stays in control; learning is a recommender, not a silent rewriter.
- **Auto-tune (v2)** — hidden adjustment applied silently to ranking,
  exposed on `/algo` as a "Learned tweaks" panel the user can audit and
  reset to zero.

Absorbs the older Pri-7 "Fold internal clicks into popularity" item —
click signal becomes one input among many in the unified signal table.
Also absorbs the principled follow-on to BUG-012's score-jitter
patch: a **per-user seen-recently downrank** (impression tracking on
card render, downweight for N hours after impression) so refresh
shuffle is informed by what the user has actually seen rather than a
uniform random nudge.

Ship after Thumbs Up/Down so explicit signals are flowing first.

### Reading diet meter
**Priority:** 7 · **LOE:** 4 · **Category:** ui, new-feature, algo · **Status:** backlog

Personal-stats page at `/me/diet` showing the user a mirror of their
own reading over rolling 7-day and 30-day windows. Metrics:

- Political lean distribution ("68% center-left, 22% center, 10% right")
- Source diversity (unique sources, unique categories)
- Source reputation mix (mean / median)
- Reading level + info density distribution
- Paywall exposure ("47% of your reading was behind paywalls")
- Category breakdown
- Comparative deltas vs. the user's prior week

v2: weekly in-app card or email *"Your reading week in numbers"* —
Spotify-Wrapped energy, but truthful rather than gamified. v3:
comparative ("vs. the median sauce.ai reader") if presentable without
turning into a leaderboard.

Why it's sticky: gives the user a literal feedback loop on whether
their news diet matches their intent. Pairs naturally with Signal
Learning — "we noticed you only read center-left this week; here are
3 center-right pieces you might find worth your time".

Depends on signal capture (user_clicks today; user_signals once Signal
Learning lands).

### Trending topics view
**Priority:** 7 · **LOE:** 5 · **Category:** new-feature, algo · **Status:** done (v1, PR #71)

> **Implementation note (2026-05-17):** the original plan piggybacked
> topic extraction on the `classify_pending` LLM call. That file is being
> rewritten by a parallel session (PR #56, BUG-016..019), so this session
> took the conflict-free route: reuse the Google Trends/News topic index
> `trending_poll` already builds every 30 min (PR #53), persist topic →
> article matches, and rank topics by distinct-outlet count. No
> `classify_pending` edit, no added LLM cost. Trade-off: only surfaces
> topics that are also externally trending (Google), not purely-internal
> ones — the LLM-entity upgrade remains the documented follow-on (pairs
> with Signal Learning entity extraction).

`/trending` groups today's stories by topic/entity with source count.
Big upgrade post-dedup: trending becomes "topics that hit N outlets"
rather than "topics with N raw articles", so wire-syndicated noise
stops dominating. A topic that 20 outlets cover ranks above one that
one outlet covered 20 times.

Topic/entity extraction piggybacks on the existing `classify_pending`
LLM call (same body, additional output field — negligible incremental
cost given the call is already batching). Store as
`article_topics(article_id, topic)` many-to-many. `/trending` SQL
aggregates by recent article count and unique-source count.

Pairs with story dossier — each trending topic links to the
dossier(s) under it. Pairs with diet meter — "trending in your top
categories".

Bumped from Pri 5 to Pri 7 because the dedup-enabled version is much
stronger than the v1 version, and because it feeds the dossier theme.

### Why This Article
**Priority:** 7 · **LOE:** 3 · **Category:** ui · **Status:** done (v1, PR #79)

Small "i" icon on each card → popover showing the top 3 feature
contributions to that article's score, plus learned-model influence
when present: "high objectivity (+0.34), low paywall (+0.12), your
reading history (+0.08)".

Implementation: `/article/<id>/explain` endpoint fetches the article's
feature row, computes weighted contributions against the user's algo,
returns JSON. Frontend renders in a popover. Doubles as an admin debug
tool for tuning the ranking function.

Trust + transparency feature — also makes thumbs-down decisions more
informed ("oh, it ranked high because of X, but I don't actually care
about X").

### Article summary
**Priority:** 7 · **LOE:** 4 · **Category:** new-feature, ui · **Status:** done (PR #145, 2026-05-31)

> **Shipped 2026-05-31 (PR #145):** owner chose the separate-pass-from-body
> design — an isolated Haiku pass in `classify_pending` after body extraction
> over a gated subset (rep > 0.4, paywall < 0.5, real body), cached in the new
> `article_summaries` table; surfaces via a lazy "TL;DR" toggle on feed cards
> and a box atop the reader view. Decoupled from the judgments call so it can't
> degrade ranking; table-existence probe + defensive read so a missing
> migration degrades gracefully (BUG-025 lesson). Migration applied
> post-deploy. v2 follow-ons below remain backlog.

3-bullet TL;DR per article, generated by Claude Haiku at classification
time and cached on the row. Surfaces on card hover/expand (preview
without commitment) and at the top of the reader view (decide whether
to keep reading).

Batches with the existing political_lean / objectivity LLM call — same
body, one prompt, three judgments returned together. Cheaper than a
separate call. Gate to control cost: only summarize articles passing a
threshold (e.g. `source_reputation > 0.4` AND `paywall < 0.5`). At
~$0.001-0.002 per article with Haiku, ~$1-3/day at expected volume.

v2: "Summarize today's brief" — meta-summary across the day's 10
articles for a 3-minute orientation read at the top of the home feed.

Depends on reader view body extraction (RSS blurbs make poor input).

### Fold internal clicks into popularity
**Priority:** 7 · **LOE:** 4 · **Category:** algo · **Status:** backlog

`user_clicks` is being recorded but isn't used in the ranking. Popularity
today is only Reddit + HN. Internal clicks are a stronger signal for our
users — fold them in.

Approach: per-article click-rate (clicks per impression over rolling 24h)
normalized to 0..1, max'd with the external signal so unpopular-on-Reddit-but-
popular-here articles still rank.

### TTS audio mode
**Priority:** 6 · **LOE:** 4 (v1) / 6 (v2) · **Category:** new-feature, ui · **Status:** backlog

"Play" button on the reader page and on each card.

- **v1:** browser `window.speechSynthesis` — free, zero infra. Decent
  on Chrome/Safari, mediocre elsewhere. Ship first to validate the use
  case before paying for quality.
- **v2:** server-side TTS (ElevenLabs / OpenAI `gpt-4o-mini-tts` /
  Google) generating MP3 cached per-article. High quality, ~$0.005-0.02
  per article — gate behind a "premium" tier or "top-rated articles
  only" before turning on broadly.

The sticky pattern: a **"Read me my queue"** button on `/saved` that
plays the Read Later queue back-to-back, podcast-style. Commute /
exercise / dishes use case — earbuds in, sauce.ai becomes the source
for 20 minutes. Podcast-mode listening is habit-forming in a way visual
reading isn't.

v2+ extras: per-article duration estimate ("~4 min read · ~5 min
listen"), lock-screen media controls via Media Session API, skip-to-
next, playback speed.

Depends on reader view body extraction.

### Test coverage expansion
**Priority:** 5 · **LOE:** 5 · **Category:** infra · **Status:** backlog

20 tests today, mostly classifier rules and ranking. No tests for routes,
auth, admin pages, or cron pipeline end-to-end. Add Flask test-client
coverage for the top-level routes and a SQLite-backed integration test for
the classify pipeline.

### Email verification on signup
**Priority:** 5 · **LOE:** 3 · **Category:** security · **Status:** backlog

Confirmation email on signup, gate is_active until clicked. Easy once the
email infra for the digest exists, so probably do it alongside.

### CloudLinux/GoDaddy support ticket re: shim
**Priority:** 5 · **LOE:** 1 · **Category:** ops · **Status:** backlog

The venv shim's `BASH_SOURCE[0]` resolution fails when Passenger invokes
with a relative argv[0]. Three load-bearing symlinks (`activate`,
`set_env_vars.py`, `python3.11_bin`) in the app root work around it. File
a ticket asking CloudLinux/GoDaddy to fix the shim so we can remove the
workaround.

### Migrate to VPS (gunicorn + nginx)
**Priority:** 4 · **LOE:** 7 · **Category:** infra, skunkworks · **Status:** backlog

GoDaddy shared cPanel is a constant fight: nproc limits, hostile cPanel
scaffolds, immutable venv shims, fork-bombs on respawn. A $6–10/month VPS
(Hetzner, Linode, DO) removes 90% of the failure modes. Code transfers
cleanly: Flask + gunicorn behind nginx, MySQL local, system cron.

Defer until shared hosting actively breaks something the customer notices.

### Steel-man — strongest opposing-view coverage of a story
**Priority:** 7 · **LOE:** 3 · **Category:** ui, algo, new-feature · **Status:** in-progress

**User value / why now.** sauce.ai already owns the one thing that makes a
credible "see the other side" feature possible: a deduplicated story cluster
with every covering outlet's political lean (`articles.story_id` +
`article_features.political_lean` — the same data behind the `/story/<id>`
dossier and the in-feed "+N angles" peek). This turns that latent asset into
a single deliberate action: on any multi-source card, one click surfaces the
**strongest** coverage of the same story from the **opposite** side of the
spectrum. The emphasis on *strongest* (highest-quality, not a cherry-picked
strawman) is the whole point and the differentiator — it's a steel-man, not a
dunk. Most on-thesis ("transparent, my-rules news") and the most shareable of
the bubble-breaking cluster.

**What it is.** A new "⚖ Steel-man" pill on multi-source `/` feed cards (next
to the existing "+N angles" pill) and a highlighted callout on the
`/story/<id>` dossier. Clicking expands inline (HTMX, exactly like the
spectrum peek) to show the 1–2 best opposing-side articles for that story:
source, headline, lean badge, lead paragraph, and a link into the full
dossier.

**How "the other side" is defined (v1 — deterministic, no per-user state):**
relative to the **anchor article's own lean bucket** (the card you're looking
at), not the user's politics:
- anchor in `left` bucket → opposing = `right` members;
- anchor in `right` → opposing = `left`;
- anchor in `center` → best of *both* flanks (left + right).

Buckets use the existing ±0.2 thresholds already shared by `app/spectrum.py`
and `app/routes/story.py` (keep all three in sync — `spectrum.py` already
carries a sync note).

**How "strongest" is defined.** Within the opposing bucket, rank candidates by
a **quality key** built from columns we already compute —
`source_reputation` and `objectivity` (e.g. their product), tie-broken by
recency — and take the top 1–2, **at most one per source**. This deliberately
surfaces the most reputable, most objective version of the other side, which
is what makes it a steel-man rather than an outrage-bait counterexample.

**Sketch (files/surfaces to touch):**
- `news/app/spectrum.py` — new pure, Flask/DB-free helper
  `pick_steelman(members, anchor_lean, limit=2)` reusing `lean_bucket`:
  resolve the opposing bucket(s) from `anchor_lean`, drop the anchor and
  same-source dupes, rank by the quality key, return the top `limit`. This is
  where the unit tests live (no Flask/DB/LLM needed).
- `news/app/routes/story.py` — new thin `GET /story/<id>/steelman` route that
  reuses `_fetch_cluster(story_id)` (so visibility / personal-source
  filtering is identical to peek/dossier), computes the anchor lean from the
  canonical member, calls `pick_steelman`, and renders a small partial. Also
  add a "Strongest opposing coverage" callout to the `view()` dossier render
  when the cluster spans both flanks.
- `news/app/templates/partials/feed_cards.html` — add the "⚖ Steel-man" pill
  (mirrors the "+N angles" `hx-get` / `hx-target="#spectrum-<id>"` pattern;
  reuse the existing `.spectrum-peek` slot or add a sibling slot), shown only
  when `a.cluster_size > 1` AND the cluster has an opposing-side member.
- `news/app/templates/partials/steelman.html` (new) + the dossier callout
  markup; `news/app/static/style.css` — a small block reusing the
  spectrum-peek / lean-badge classes.

**Gating (when the pill shows).** Only when the cluster genuinely spans ≥2
lean buckets *and* has at least one opposing-side member relative to the
anchor — otherwise there's nothing to steel-man and the pill is hidden
(single-source / single-bucket clusters never show it). Mirrors the dossier's
`FRAMING_MIN_BUCKETS` spirit.

**Preserve / must-not-break:**
- The in-feed "+N angles" spectrum peek (`story.peek` /
  `pick_spectrum_sample`) is unchanged — steel-man is a *sibling* selection,
  not a replacement.
- Lean-bucket thresholds stay shared across `spectrum.py` / `story.py` / the
  new helper (the existing sync note governs).
- Scope to `/` feed cards + `/story/<id>` only — `/firehose`, `/search`,
  `/saved`, and the digest are untouched (same scoping as the spectrum peek).

**Constraints / watch-outs:**
- **No synchronous LLM, no process spawn** — v1 selection is pure SQL-fetched
  rows + a Python ranking, the same cost profile as the existing peek. (A
  one-line Haiku "here's the strongest argument the other side is making"
  framing, cached like `story_dossiers`, is the explicit v2 — keep v1
  LLM-free so it's cheap and request-path-safe.)
- **NOT BUG-007 class** — purely additive read path over columns/tables
  already on prod; if there's no opposing member the partial renders empty.
  Anonymous-safe. **No DB migration, no cron, no env var, no new dep, no
  symlink** — new pure helper + thin route + template/CSS; Passenger restart
  on deploy so the new `story` route registers.

**Test expectation:** `pytest news/tests/` stays green. New pure tests for
`pick_steelman` (in `tests/test_spectrum.py` or a new `test_steelman.py`):
anchor-left → returns right-bucket members; anchor-right → left; anchor-center
→ best of both flanks; ranks by the quality key (a high-reputation/objective
opposing article beats a low one); one-per-source dedupe; empty result when
the cluster has no opposing-side member. No test requires Haiku, a live DB, or
a browser.

**v2 (out of scope):** an optional cached Haiku one-liner steel-manning the
opposing argument; anchoring "the other side" to the *user's* reading-lean
diet instead of the article's bucket (Signal-Learning territory — needs the
per-user lean profile); a "strongest agreeing coverage" inverse for finding
corroboration.

---

## User-empowerment cluster (added 2026-05-17)

Themes A/B/C from the "empower the user to help us build the perfect
newsfeed" brainstorm. A = direct algorithm expressiveness; B = closing
the feedback loop; C = crowdsourcing the feed for everyone.

### Natural-language algorithm builder
**Priority:** 8 · **LOE:** 5 · **Category:** ui, algo, new-feature · **Status:** done (v1, PR #59)

User describes the feed they want in plain English ("more local tech and
science, less political outrage, prefer long objective reads, hide
paywalls"); a single Claude Haiku call maps that onto the existing
`FEATURES` catalog (direction / weight / threshold per feature, plus
recency) and the `/algo` UI is pre-filled with the proposed settings for
the user to review, tweak, and apply — never applied silently.

Reuses the Haiku client already wired for `political_lean` /
`objectivity` classification and dossier framing. The model returns
strict JSON constrained to the known feature names and the 3-axis
schema; out-of-range values are clamped, unknown keys dropped, and a
parse failure falls back to "couldn't parse that — editor unchanged"
rather than erroring. No per-request LLM cost (fires only on explicit
submit).

Biggest single unlock for non-technical users: turns the core "build
your own algorithm" thesis from a slider grid into a sentence. Pairs
with the read-only Code tab and is a natural precursor to Sandboxed
Python exec (Pri 9).

### Keyword / topic mute & boost
**Priority:** 8 · **LOE:** 4 · **Category:** algo, ui · **Status:** done (v1, PR #77)

Per-user mute and boost term lists ("mute: crypto, royal family; boost:
climate policy, local elections") applied at the feed-query layer as a
hard filter (mute) and a score multiplier (boost). Distinct from
`user_source_prefs` (which weight whole sources) — this is
content/topic-level and the highest-perceived-control lever users ask
for first. New `user_term_prefs(user_id, term, mode, weight)` table;
matched against title + summary (+ body once extracted). v2: phrase /
entity-aware matching once topic extraction (Trending) lands.

Shipped v1 (PR #77, merged 2026-05-17; migration applied on prod
same day). v2 = phrase/entity-aware matching (shared with topic
extraction); also fold in `article_bodies` text (`_MATCH_EXPR` is the
single point to change).

### Per-algorithm keyword mute & boost (in the algo builder)
**Priority:** 7 · **LOE:** 3 · **Category:** algo, ui · **Status:** done (v1, PR #82)

Extension of the shipped per-user keyword mute & boost (PR #77). Today
keywords live at `/terms` and are scoped to the user — they apply to
every saved profile equally. This adds a parallel surface inside the
`/algo` builder where keywords attach to a specific `user_algorithms`
row, so different profiles can carry different keyword intent (e.g.
"Morning brief" boosts AI/local tech; "Weekend deep-dive" mutes
politics). New `algorithm_term_prefs(algorithm_id, term, mode, weight)`
table; new `/algo/keywords/add` and `/algo/keywords/<id>/delete`
routes; new "Keywords" tab on the algo builder. `routes/feed.py`
unions `user_term_prefs` + the active algorithm's
`algorithm_term_prefs` and feeds the combined list into the existing
pure `app/term_prefs.build_term_clauses` builder — the builder's
dedupe + mute-wins rules carry the merge semantics, so no new helper.
`/terms` stays as the power-user account-wide surface.

### Fold per-algorithm Keywords into the Your Algorithm feature list
**Priority:** 6 · **LOE:** 2 · **Category:** ui · **Status:** done (PR #119)

Follow-on UI polish to "Per-algorithm keyword mute & boost" (PR #82).
Today `/algo` (the Your Algorithm editor) is an Alpine tabbed view with
five top tabs — UI, Code, Presets, Profiles, **Keywords** — and the
per-algorithm mute/boost terms live in their own **Keywords** tab,
separate from the feature sliders. That siloes keywords from the rest of
the algorithm definition and is easy to miss; keywords shape ranking just
like the feature weights and belong in the same place.

**Goal:** drop the standalone "Keywords" tab and fold its content into
the regular feature list on the **UI** tab, so an algorithm's full
definition (sliders + filters + keywords) is visible and editable in one
view.

**Sketch (template/UI reorg — no DB change, no route change):**
- In `news/app/templates/algo.html`: move the keyword block currently
  under `<section x-show="tab==='keywords'">` (the add-keyword form plus
  the muted/boosted term lists) into the UI tab's `<div class="features">`
  feature list — e.g. as a "Keywords" section/feature-row after the
  existing rows (Category/Country filter, Near a place). Remove the
  `Keywords` `<button>` from `<nav class="tabs">` and the now-empty
  `tab==='keywords'` section. Keep the existing count inline.
- The add/delete forms keep posting to the unchanged
  `/algo/keywords/add` and `/algo/keywords/<id>/delete` routes; the
  `_render_editor` context (`algo_muted`, `algo_boosted`,
  `max_keywords`) is unchanged. CSRF fields stay on the forms.
- Style the folded block to match `.features` / `.feature-row` in
  `news/app/static/style.css`; keep it usable on mobile.

**Preserve:** the 100-keyword cap (`MAX_KEYWORDS_PER_ALGO`), mute-wins +
dedupe semantics, the "save an algorithm first" guard, keywords attaching
to the **active** profile, and the Profiles-tab interplay (switch profile
to edit a different one's keywords). `routes/feed.py`'s per-algorithm
keyword union is unchanged.

**Constraints:** no migration, no new endpoint, no ranking behavior
change — purely where the controls render. Keep `pytest news/tests/`
green; update any template-render test that asserts the Keywords tab.

### Multiple saved algorithms / profiles
**Priority:** 7 · **LOE:** 4 · **Category:** backend, ui · **Status:** in-progress

Named algorithm profiles ("Morning brief", "Weekend deep-dive", "Work
mode") switchable from a dropdown on `/`. Today there is exactly one
active `user_algorithms` row per user; this generalizes to many with an
`is_active` flag + `name` and a profile switcher. Pairs with the NL
builder (each generated algo can be saved as a profile) and time-of-day
auto-switching as a v2 follow-on.

### Compact / density toggle (Techmeme-style)
**Priority:** 6 · **LOE:** 2 · **Category:** ui · **Status:** in-progress

Topnav toggle (next to dark-mode) that strips the home feed down to a
dense Techmeme-style list: no thumbnails, no feature bars, no lead
paragraph, single column, tight padding — title + source + lean dot +
"+N angles" + discussion line + thumbs/save controls only. Persisted in
`localStorage` (mirrors the dark-mode pattern, PR #63 — client-only, no
DB migration). Scoped via `#feed-cards` so `/`, `/search`, `/saved`,
`/firehose` keep their current layouts; firehose is already dense and
search/saved would be cheap follow-ons by removing the scope.

### Unique sources toggle — one article per source (Your Algorithm)
**Priority:** 6 · **LOE:** 2 · **Category:** ui, algo, backend · **Status:** in-progress

A checkbox on the **Your Algorithm** editor (`/algo`, the UI tab) that,
when on, guarantees the home feed shows **at most one article per
source** — no outlet appears twice. User framing: "let me see a wider
spread of sources, not three Inquirer stories in a row." This is the
user-controllable version of the BUG-021 fix: the feed already enforces
a per-source cap (`FEED_MAX_PER_SOURCE`, default 3) globally via
`app/feed_diversify.py`; this exposes a per-profile lever that tightens
that cap to **1** for the user who wants maximum source diversity.

**Why now / user value:** source diversity is a top-perceived expression
of "my algorithm, my rules," and the plumbing is already shipped — this
is a thin, high-clarity control over machinery that exists and is
unit-tested. It pairs naturally with the existing diversification cap and
the transparent-ranking thesis.

**Where it lives & how it persists (no DB migration):**
- The flag is a per-profile setting stored as a new key `unique_sources`
  (boolean) inside the existing free-form `user_algorithms.weights_json`
  dict. **No schema change, no migration, not BUG-007 class** — the
  ranking layer (`ranking.build_score_sql` / `build_filters_sql`) only
  reads known feature keys and ignores unknown keys, and
  `parse_weights_json` / `resolved_weights_for_view` round-trip the dict
  as-is. An older profile without the key simply reads as "off."

**Sketch (files/surfaces to touch):**
- `news/app/routes/algo.py` — in `_parse_form_weights(form)`, add
  `weights["unique_sources"] = bool(form.get("unique_sources"))`.
  (Unchecked HTML checkboxes don't submit, so set it explicitly every
  save rather than relying on the key's presence.)
- `news/app/templates/algo.html` — add the checkbox on the **UI** tab as
  a feed-shaping control near the recency / category / country controls
  (it is a feed-shaping toggle, not a per-feature slider, so it doesn't
  belong inside the `.feature-row` weight grid). `name="unique_sources"`,
  `value="1"`, `checked` when `weights.get('unique_sources')`. Include
  the existing `csrf_field()` (the form already posts it). Short helper
  caption: "Show at most one article per source."
- `news/app/routes/feed.py` — in `index()`, resolve the **effective**
  per-source cap: when the active profile's `weights.get("unique_sources")`
  is truthy, use `cap = 1`; otherwise keep the existing
  `FEED_MAX_PER_SOURCE` config value. Feed this cap into the existing
  `fetch_budget(...)` / `cap_per_source(..., cap=...)` / `page_slice(...)`
  calls — no new query, no new join. Keep the over-fetch + cap + slice
  pagination contract intact (page N+1 must agree with page N).
- Prefer a tiny pure helper (e.g. `effective_source_cap(weights,
  default_cap)` in `app/feed_diversify.py`) so the decision is
  unit-testable without Flask/DB and `feed.index()` stays thin.

**Preserve:**
- Anonymous visitors and signed-in users with no saved profile keep the
  default behavior (balanced default weights → no `unique_sources` key →
  existing `FEED_MAX_PER_SOURCE` cap). The toggle is per-profile, so it
  only affects the active profile and travels with profile switching.
- The toggle **overrides** the global cap toward 1; it must not weaken an
  already-tighter setting and must work even if `FEED_MAX_PER_SOURCE` is
  configured to 0 (disabled) — `unique_sources` still yields cap 1.
- The cap is applied AFTER the SQL `ORDER BY` (as today), so the one
  surviving article per source is the highest-ranked one for that
  source under the user's algorithm. Story-cluster dedup, jitter,
  source/keyword prefs, category/sort, and the 7-day window are all
  unchanged. Scope to `/` only — `/firehose`, `/search`, `/saved`, and
  the digest are untouched (same scoping decision as BUG-021).

**Constraints / watch-outs:**
- **No synchronous LLM, no new process** — pure SQL-fetch + Python cap.
- **Over-fetch ceiling:** `fetch_budget` with `cap=1` and `page_size=30`
  multiplies the row budget ~31x (≈930 rows for page 1, growing per
  page). The active catalog has hundreds of sources so the page still
  fills, but cap the fetch at a sane ceiling (e.g. a `max_fetch` constant)
  so deep "Load more" paging can't issue an unbounded `LIMIT`. Justify
  the ceiling in the PR; a short page near the end of the window is
  acceptable, an unbounded fetch is not.
- No migration, no cron, no env var, no new dependency, no symlink. A
  template-only + thin-route change; Passenger restart on deploy as usual.

**Test expectation:** `pytest news/tests/` stays green. Add pure unit
tests for `effective_source_cap` (unique_sources on → 1; off/absent →
default; default 0 + on → 1) and a `cap_per_source(..., cap=1)`
regression asserting no duplicate `source_id` survives. No test should
require Haiku, a live DB, or a browser.

### A/B split feed
**Priority:** 6 · **LOE:** 5 · **Category:** ui, algo · **Status:** backlog

Two algorithms rendered side by side over the same article pool so the
user can see concretely which tuning surfaces a better feed and promote
the winner to active in one click. Makes algorithm tuning empirical
instead of guesswork. Depends on Multiple saved algorithms for the
"promote winner" half; the compare view itself can ship first against
"current vs. a scratch algo".

### Tune from this article
**Priority:** 7 · **LOE:** 4 · **Category:** algo, ui · **Status:** done (PR #143, 2026-05-31)

Inline "more like this / less like this" on any feed card that, instead
of silently learning, *shows which feature weights it would nudge and by
how much* with accept / undo. Effectively the "Suggest" mode of the
larger **Signal Learning** item (Pri 8) but article-anchored and
immediate — can ship as the cheap standalone wedge for that theme and
later be absorbed into the full Signal Learning regression. Keep the two
in sync; don't double-implement the adjustment-vector storage.

**In progress (2026-05-31, PR pending).** Implemented as a pure
`app/tune.py` (nudge = `±LEARNING_RATE·(2·alignment − 1)` per weighted
feature, where `alignment = 1 − |value − direction| / scale` is the
scorer's own per-feature factor — reused from `ranking`/`explain` for
parity, so no second adjustment representation). Preview→Accept→Undo via
three thin `feed.py` routes that mutate the active profile's existing
`weights_json` (no new adjustment-vector table — stays absorbable into
the Signal Learning regression). Only already-weighted features are
nudged; directions/thresholds/filters untouched. **No migration / cron /
env / dep.** **Done — merged PR #143, 2026-05-31.**

### Periodic "is your feed working?" check-in
**Priority:** 6 · **LOE:** 3 · **Category:** ui, ops · **Status:** backlog

Lightweight in-feed card surfaced every N days: a 1–5 rating plus an
optional "what's missing / what's too much?" free-text box. Per-user it
feeds tuning suggestions; in aggregate it's the cheapest product-quality
signal (trend the mean, read the free-text for themes). Dismissible,
rate-limited per user so it never nags. New
`feed_feedback(user_id, score, note, created_at)` table.

### Shareable algorithm gallery
**Priority:** 8 · **LOE:** 6 · **Category:** new-feature, ui · **Status:** in-progress

Users publish an algorithm with a name + short description; others
browse a gallery and one-click **adopt** or **fork** it. Network effect
(good feeds spread), a viral/marketing surface, and a corpus of what
users consider a good feed that can inform future default presets. The
code already has internal `PRESETS`; this exposes user-authored ones.
Needs a `shared_algorithms` table, a moderation/abuse story (report +
admin takedown), and adopt = clone into the user's own `user_algorithms`
(pairs with Multiple saved algorithms, which it depends on for clean
adopt/fork semantics).

**v1 status (PR #88, 2026-05-20):** minimal scope landed — publish
snapshot, browse, adopt = clone-into-a-new-active-profile, three usage
stats (total adoptions / last 7d / currently active) usable as sort
axes plus a substring search. Moderation/reporting is deliberately
**out of scope** for v1 (takedowns are admin-only via DB). v2 = report
button + `/admin/gallery` moderation queue. New `shared_algorithms` +
`algorithm_adoptions` tables (migration applied on prod 2026-05-20;
`manual-actions.md` → Completed); the page lives at `/gallery`.

### Community source-quality overlay
**Priority:** 7 · **LOE:** 5 · **Category:** algo, backend · **Status:** backlog

Aggregate the per-user trust/distrust + thumb signals already captured
in `user_signals` / `user_source_prefs` into a community bias /
reputation badge shown on cards, and (opt-in) fold it into the default
ranking so individual signal becomes a collective good. Main risk is
brigading: weight contributions by account age / activity, cap per-user
influence, and keep the community overlay separate from the editorial
`source_reputation` so it can be audited and disabled. Absorbs part of
the "Fold internal clicks into popularity" intent at the source level.

### Community "add a source" on dossiers
**Priority:** 6 · **LOE:** 5 · **Category:** new-feature · **Status:** backlog

On the story dossier (the killer-demo page), signed-in users can submit
a missing source/article URL for that story. Submissions flow into the
existing `candidate_sources` admin review queue (and, if the domain is
already a known source, just attach the article to the cluster).
Crowdsources coverage breadth exactly where missing perspectives are
most visible. Depends on Story dossier (done) and the discovery
pipeline's `candidate_sources` table (done).

---

## Agent infrastructure cluster (added 2026-05-21)

Six-phase build-out that replaces the "5 Claude Code terminals open at
once" workflow with an unattended agent fleet triggered by GitHub
Actions. Each phase is its own feature branch + draft PR; the human
merges between phases so each lands cleanly and is tested in prod
before the next starts. All workflows are gated by the repo variable
`AGENTS_ENABLED` (boolean string) and share a fine-grained PAT
`AGENT_PUSH_TOKEN` (contents:write + pull-requests:write) plus
`ANTHROPIC_API_KEY`. Dev/PM agents run on Opus 4.7
(`claude-opus-4-7`), QA/review on Sonnet 4.6 (`claude-sonnet-4-6`),
triage on Haiku 4.5 (`claude-haiku-4-5`).

### Agent infra: Unattended dev-agent dispatcher
**Priority:** 8 · **LOE:** 3 · **Category:** infra, ops, skunkworks · **Status:** done (PR #103)

Phase 1. Marking a roadmap item's status `ready-for-agent` triggers
an unattended Claude Code session via GitHub Actions that produces a
draft PR — replacing the habit of manually launching terminals. New
`.github/agents/dev-warmup.md` system prompt (near-copy of the
standard manual warmup, adapted: assignment passed in an ASSIGNMENT
block; manual-actions.md Open entries treated as untouched and never
moved to Completed; output is always a DRAFT PR; hard budget $8 /
45 min wallclock; PARTIAL: ... draft commit if approaching either;
matrix max-parallel 3 with rebase-before-PR; blocked-by-dependency
and blocked-by-open-action escape hatches). New
`.github/scripts/pick_ready_items.py` (pure stdlib) scans roadmap.md
for `ready-for-agent` items, flips them to `in-progress` in both the
at-a-glance row and the detail-section Status line, commits with
`[skip ci]`, and emits the picked titles to GITHUB_OUTPUT. New
`.github/workflows/dev-agent.yml` (push-to-main on `roadmap.md` or
workflow_dispatch with `title` input) gated by
`vars.AGENTS_ENABLED == 'true'`, concurrency group
`dev-agent-picker`, three jobs (pick / manual / implement), implement
matrix invokes `anthropics/claude-code-action@v1` with
`--model claude-opus-4-7 --max-turns 80 --max-budget-usd 8`.

### Agent infra: Pre-merge QA + BUG-007 gate
**Priority:** 9 · **LOE:** 2 · **Category:** infra, security · **Status:** done (PR #104)

Phase 2. Every PR runs tests + a Claude-Sonnet BUG-007 reviewer
before merge. The single most expensive recurring failure mode in
this repo is "PR merged before migration applied → signed-in feed
500s" (BUG-007 + 2026-05-17 recurrence on PR #64); this gate
prevents it. New `.github/workflows/qa-code.yml` on pull_request
{opened, synchronize, ready_for_review}: a `tests` job (pip install,
boot check, `python -m pytest news/tests/ -q`) and a `bug007-gate`
Sonnet job that diffs against main and flags (a) new SQL table/
column refs in app/jobs code without seed/schema.sql + matching Open
manual-actions.md entry, (b) modifications to passenger_wsgi.py /
app/__init__.py / app/config.py / jobs/*.py / requirements.txt
without a same-PR INSTALL.txt update, (c) `dangerous-clean-slate: true`
anywhere (HARD FAIL). Inline comments + BUG007_OK / BUG007_BLOCK
status + `blocked-pre-merge` label on block. Budget $1. New
`.github/agents/qa-reviewer.md` system prompt. Branch protection
update (require both checks) called out in the PR description as a
manual step.

### Agent infra: Post-deploy verification
**Priority:** 8 · **LOE:** 4 · **Category:** infra, ops · **Status:** done (PR #105)

Phase 3. After each deploy, smoke-test prod and file bugs if
anything regressed. Two new admin endpoints in
`news/app/routes/admin_ops.py` (admin-auth required) feed the
verifier: `GET /admin/cron-health` returns last 200 lines of
`logs/cron.log`; `GET /admin/usage-summary` returns 14-day signup /
DAU / signal counts JSON. New
`.github/workflows/post-deploy.yml` triggers on push-to-main (120s
sleep so the FTP deploy finishes) + cron `*/30 * * * *` safety net.
Two steps: curl smoke (/, /firehose, /algo, /trending,
/search?q=test, /gallery — fail on any 5xx), then a Sonnet Playwright
MCP agent (budget $2) that signs in with SMOKE_TEST_USER /
SMOKE_TEST_PASS, toggles a thumb, reloads, checks persistence;
inspects /admin/cron-health for known bad patterns; for each new
issue appends a BUG-NNN to bugs.md and opens a draft PR labeled
`agent:qa-filed`. New `.github/agents/post-deploy-qa.md` prompt.
**One-time exception to "infra-only" before Phase 4:** ships the
two admin endpoints (with unit tests) so the agent has something to
query; admin blueprint adds a `manual-actions.md` Open entry (new
blueprint needs a Python App restart).

### Agent infra: Migration / restart executor
**Priority:** 10 · **LOE:** 5 · **Category:** infra, ops, backend · **Status:** done (PR #106)

Phase 4. Highest-blast-radius phase. New
`news/app/routes/agent_ops.py` blueprint at `/agent-ops/*` runs
HMAC-SHA256-signed whitelisted operations from GitHub Actions:
`POST /agent-ops/run-migration` (filename whitelist under
`news/seed/migrations/`, single transaction, rollback on failure),
`POST /agent-ops/restart-app` (Passenger `tmp/restart.txt` touch),
`POST /agent-ops/verify-schema` (read-only SELECT against
information_schema). New
`.github/workflows/migration-executor.yml` triggers on PRs labeled
`needs-migration`: discovers migration files in the diff, signs +
POSTs each to /agent-ops/run-migration, then /agent-ops/restart-app,
then a small Haiku agent (budget $0.50) moves the matching
manual-actions.md entry from Open to Completed, comments on the PR,
swaps the `needs-migration` label for `migration-applied`. Phase 1's
dev-warmup updated so dev-agent draft PRs that include a migration
self-label `needs-migration` after opening. New secret
`AGENT_OPS_SECRET` (32+ random hex bytes) added to .htaccess on
prod with quarterly rotation policy; matching `manual-actions.md`
Open entry. PR description includes threat model, prod test plan
(throwaway create-then-drop dummy table end-to-end), and a manual
rollback procedure.

### Agent infra: Bug auto-triage
**Priority:** 6 · **LOE:** 2 · **Category:** infra, ops · **Status:** done (PR #107)

Phase 5. Bugs filed by the Phase 3 post-deploy QA agent get a
suitability assessment for the unattended dev fleet — but a human
still decides whether to promote to `ready-for-agent`. New
`.github/workflows/bug-triage.yml` on pull_request labeled
`agent:qa-filed`: a single Sonnet job (budget $1) reads bugs.md,
finds the new BUG-NNN, estimates scope, and verdicts
`AUTO_FIX_ELIGIBLE` (touches <3 files, clear repro, NOT in
sharp-edge areas: passenger_wsgi.py, symlinks, .htaccess, cPanel
infra) or `NEEDS_HUMAN`. Posts the verdict as a PR comment; never
labels the bug ready or spawns a dev agent on its own. New
`.github/agents/bug-triage.md` prompt.

### Agent infra: PM agent (weekly proposals)
**Priority:** 5 · **LOE:** 3 · **Category:** infra, skunkworks · **Status:** done (PR #108)

Phase 6. Weekly cadence Opus agent reads production signals and
proposes new roadmap items as `status: proposed`. Adds `proposed`
to the roadmap.md Conventions ("PM agent suggestion; not yet
authorized for dev"). New `.github/workflows/pm-agent.yml` on cron
`0 14 * * 1` + workflow_dispatch: single Opus job (budget $4) reads
engineering-history.md (last 14 days) + bugs.md + roadmap.md (Done
last 14d + backlog), fetches /admin/cron-health and
/admin/usage-summary, proposes AT MOST 3 new items each with
Priority / LOE / Category / Status `proposed` + a Rationale
paragraph citing specific data. Opens one PR titled
"PM proposals: <date>" that touches only the detail sections (not
the at-a-glance table — human folds in when promoting). Empty weeks
are fine; if nothing meaningful surfaces, no PR is opened. New
`.github/agents/pm-agent.md` prompt.

---

## PM proposals (2026-05-21)

PM-agent suggestions from the 2026-05-21 cycle (run manually). Each is
`status: proposed` — not yet authorized for dev. The human promotes a
proposal to `ready-for-agent` (and folds its row into the at-a-glance
table) to dispatch it. This cycle ran on repo-doc signals only;
production telemetry (`/admin/cron-health`, `/admin/usage-summary`) was
unavailable, so rationales cite history/bugs/roadmap data.

### Schema-drift sentinel (clear failure instead of a 500 storm)
**Priority:** 7 · **LOE:** 3 · **Category:** backend, infra, ops · **Status:** proposed

**Rationale:** BUG-007 is the most expensive recurring failure mode in
this repo — it fired twice (original PRs #30/#31, 2026-05-13; recurrence
on PR #64, 2026-05-17). The symptom each time: a migration lagging the
deploy makes *every* signed-in request 500 with an opaque PyMySQL
"Unknown column" error until a human notices. Phase 2's pre-merge gate
(PR #104) now blocks merge-before-migration and Phase 4's executor
(PR #106) applies migrations — but there is still **no runtime guard**:
if a column is missing at request time, the failure is a silent 500
storm, not a diagnosable signal.

Propose a schema-drift sentinel: on app start (and on demand via a new
`GET /admin/schema-health`), diff the expected columns — derivable from
`seed/schema.sql`, or a tracked schema-version — against
`information_schema`, reusing the Phase 4 `agent_ops.verify_schema`
building block. Surface one clear readout plus a logged warning naming
the missing table/column, instead of per-request 500s. Turns the worst
recurring outage into an immediately actionable banner. Scope: one
read-only admin route + an init-time check; no sharp-edge infra, no new
dependency.

### Agent fleet observability — weekly cost + activity rollup
**Priority:** 6 · **LOE:** 3 · **Category:** infra, ops · **Status:** done (PR #114, migration applied to prod)

**Rationale:** The six-phase agent fleet shipped 2026-05-21 (PRs
#103–#108), each workflow carrying a per-run budget cap ($8 dev / $1 QA
/ $2 post-deploy / $0.50 executor-finalize / $1 triage / $4 PM). But
nothing aggregates what the fleet actually *did*: there is no record of
weekly spend, run counts, success/failure rates, or how many post-deploy
auto-filed bugs turned out to be real. A per-run cap bounds a single run
but does not catch a workflow that fails or loops repeatedly, nor tell
you whether the fleet earns its cost.

Propose a lightweight agent-activity log (an append-only `agent_runs`
row per workflow run, mirroring the existing `llm_usage` table pattern)
plus a read-only `GET /admin/agent-activity` 14-day summary, fed by a
final reporting step each agent workflow appends. The Phase 6 PM agent
can then cite real fleet telemetry instead of inferring from PRs. Scope:
one small table + one admin route + a per-workflow reporting step; no
app-behavior change.

---

## Done

Reverse chronological. Each entry links to the merged PR; the matching
narrative lives in `engineering-history.md` under the same date.

### 2026-05-31

- **Tune from this article — article-anchored weight nudges** (Pri 7,
  LOE 4). "More / less like this" on feed cards previews which feature
  weights it would nudge, with Accept / Undo; mutates the active profile's
  existing `weights_json` (no new adjustment store). Also fixed BUG-028
  (the Why? explainer 500). PR #143.
- **Article summary — 3-bullet TL;DR** (Pri 7, LOE 4). Cached Haiku summary
  per gated article; lazy "TL;DR" toggle on cards + reader box. PR #145.
  (Migration `2026-05-31-article-summaries.sql` still Open in
  manual-actions — apply post-deploy.)

### 2026-05-22

- **Agent fleet — operationalized + hardened.** Took the six-phase fleet
  from merged-but-dormant to fully running, and shipped the first two
  agent-built features. Fixes: headless tool permissions (PR #111),
  `repository_dispatch` event wiring for dev-agent (PR #113) and
  pm-agent/post-deploy + picker push hardening (PR #116),
  migrate-after-deploy model (PR #115), fleet onboarding doc
  `agent-fleet.md` (PR #117), PM-session doc (this PR).
- **Agent fleet observability — weekly cost + activity rollup** (Pri 6,
  LOE 3, PR #114). First fully autonomous dev-agent feature: `agent_runs`
  table + `/agent-ops/report-run` + `/admin/agent-activity` rollup;
  migration applied to prod via the executor.
- **Fold per-algorithm Keywords into the Your Algorithm feature list**
  (Pri 6, LOE 2, PR #119). Dropped the standalone Keywords tab; folded
  the keyword controls into the UI-tab feature list.
- **Demand-driven feed classification** (Pri 6, LOE 4, PR #121). Feed
  activity touches a signal file; a new every-1-min `classify_pending
  --triggered-only` cron tops up a ~400-article classified buffer (page
  size 30→40). No synchronous LLM / no per-request spawn. New cron entry
  is pending in `manual-actions.md` Open.

### 2026-05-21

- **Agent infrastructure cluster (six phases)** — infra/ops/security/
  skunkworks. The unattended agent fleet that replaces manually
  launching terminals. All six merged 2026-05-21; the loop goes live
  once the human sets the secrets/variable and does the prod restarts
  (see `manual-actions.md` Open). PRs:
  - **Phase 1 — Unattended dev-agent dispatcher** (Pri 8, LOE 3, PR
    #103). `ready-for-agent` roadmap item → unattended Opus dev session
    → draft PR. `dev-warmup.md` + `pick_ready_items.py` + `dev-agent.yml`.
  - **Phase 2 — Pre-merge QA + BUG-007 gate** (Pri 9, LOE 2, PR #104).
    pytest + Sonnet BUG-007 reviewer on every PR. `qa-code.yml` +
    `qa-reviewer.md`. (Also fixed a sgmllib3k CI install break + a
    stale CSRF test.)
  - **Phase 3 — Post-deploy verification** (Pri 8, LOE 4, PR #105).
    curl smoke + Sonnet Playwright check + cron-health scan →
    auto-files bugs. Ships the `admin_ops` blueprint
    (`/admin/cron-health`, `/admin/usage-summary`).
  - **Phase 4 — Migration / restart executor** (Pri 10, LOE 5, PR
    #106). HMAC-signed `/agent-ops/*` prod DDL + restart, label-driven.
  - **Phase 5 — Bug auto-triage** (Pri 6, LOE 2, PR #107). Sonnet
    verdict (`AUTO_FIX_ELIGIBLE`/`NEEDS_HUMAN`) on `agent:qa-filed`
    bug PRs; human keeps the promote decision.
  - **Phase 6 — PM agent** (Pri 5, LOE 3, PR #108). Weekly Opus reads
    signals → proposes ≤3 `proposed` roadmap items; human promotes.

### 2026-05-20

- **Keywords-on-algo only (drop /terms; travel with gallery publish/adopt)** —
  Pri 6, LOE 3, algo/ui/new-feature. PR drafted 2026-05-20 (migration
  pending on prod — see `manual-actions.md` Open). Account-wide
  `/terms` surface removed: keywords now live ONLY on each algorithm
  profile (`algorithm_term_prefs`). The deprecated `user_term_prefs`
  table is dropped; its rows are folded into each user's active
  profile by the migration so no work is lost. Gallery publish now
  snapshots the algorithm's keywords into a new
  `shared_algorithms.keywords_json` column; gallery adopt clones them
  into the cloned profile (sanitized via `parse_keywords` →
  `normalize_term` / `clamp_boost` so an untrusted listing can never
  poison the adopter's keyword table). New pure helpers
  `snapshot_keywords` / `parse_keywords` in `app/gallery.py` (8 tests
  + 7 union tests that no longer applied were removed from
  `test_term_prefs.py`). `routes/feed.py` reads only
  `algorithm_term_prefs` for the active profile. Blueprint
  `/terms` + `me_terms.html` deleted; "Your Keywords" nav link removed.
- **Source catalog expansion (+1151 sources)** — Pri 7, LOE 3, ops /
  new-feature. PR #91 (draft 2026-05-20; admin re-import pending on prod
  — see `manual-actions.md` Open). Appended 1151 hand-curated
  high-quality sources to `seed/source_lean.csv` (768 → 1919): ~630
  institutional outlets (US regional papers, state capital press, local
  investigative nonprofits, trade pubs, magazines, NPR affiliates; plus
  UK, EU, LATAM, Africa, MENA, Asia-Pacific outlets) and ~520
  individual writers / newsletters / Medium publications / engineering
  blogs (Stratechery, Platformer, Slow Boring, Heather Cox Richardson,
  Money Stuff via Bloomberg, Sinocism, ChinaTalk, Latent Space,
  Karpathy, Simon Willison, etc.). US share 69%, 47+ countries
  represented. Honest `source_lean` ratings spanning -0.5 to +0.5. No
  code change, no schema change; loads via the existing `/admin/feeds`
  Import button (idempotent upsert on `feed_url`). Dead feeds
  self-deactivate at `error_count=10`.
- **Per-algorithm keyword mute & boost (in the algo builder)** —
  Pri 7, LOE 3, algo/ui. PR #82 (merged 2026-05-20;
  `algorithm_term_prefs` migration applied on prod same day —
  `manual-actions.md` Completed). Extends PR #77's
  per-user `user_term_prefs` with a parallel **per-profile** surface
  on `/algo`: new `algorithm_term_prefs(algorithm_id, term, mode,
  weight)` table FK'd to `user_algorithms`; new
  `POST /algo/keywords/{add,<id>/delete}` routes (ownership-checked,
  100/profile cap, idempotent mode-move upsert); new "Keywords" tab
  in the algo builder (mute/boost lists, boost-default add form,
  profile-aware header, link to `/terms` for the account-wide
  list). `routes/feed.py` reads both tables for the active profile
  and concatenates the rows through the existing pure
  `build_term_clauses` builder — dedupe + mute-wins rules carry the
  union semantics so a mute at EITHER scope hides the article and
  the strongest matching boost wins. 5 new pure tests (22/22
  in-sandbox). Same v1 substring-match caveat as PR #77 (a muted
  "crypto" also hides "cryptography"); entity-aware matching is the
  shared v2. Same scoping: signed-in main feed only; anon /
  `/firehose` / digest are unaffected.
- **Perceptual feature expansion (12 new ranking features)** —
  Pri 7, LOE 5, algo/backend. PR #84 (draft 2026-05-20; migration
  pending on prod — see `manual-actions.md` Open). 6 LLM-judged
  perceptual signals (`tone_calmness`, `sensationalism`,
  `analysis_depth`, `emotional_charge`, `hedging`,
  `solution_orientation`) batched into the existing
  `classify_pending` Haiku call (one extra JSON object per article,
  ~3x prior per-article LLM cost — still sub-$0.001/article) plus
  6 rule-based structural signals (`headline_length`, `caps_ratio`,
  `punctuation_intensity`, `numeric_density`, `question_headline`,
  `quote_present`) in `app/classifier/rules.py` with no
  network/LLM. All 12 added to `FEATURES`, `article_features`,
  `feature_catalog`, and (via the existing template loop) the
  `/algo` editor. Existing user algorithms are unaffected — their
  saved `weights_json` doesn't reference the new keys, so
  `build_score_sql` ignores them until a user opts in.
  `_reclassify_nollm` extended to also heal the 6 LLM features.
  **Requires manual DB migration**
  (`2026-05-20-perception-features.sql`: 12 ADD COLUMN + 12
  feature_catalog rows).

### 2026-05-18

- **Why This Article** — Pri 7, LOE 3, ui. PR #79 (merged 2026-05-18).
  A "Why?" toggle on each feed card lazily expands an inline per-feature
  score breakdown for the viewer's active algorithm (anon → balanced
  default, matching the feed): top-3 weighted contributors with a match
  bar, the multiplicative recency gate, the final score, and an
  all-features expansion. New pure `app/explain.py` reproduces
  `build_score_sql`'s per-feature term + recency gate in Python and
  imports `_direction_from_weights`/`_scale_width` from `ranking.py` so
  it can't desync from the scorer (18 parity tests); `feed.explain`
  `GET /article/<id>/explain` partial with the feed's
  active-weights+visibility scoping; progressive-enhancement HTMX
  trigger; append-only dark-mode-aware CSS. No DB/cron/env/dep/symlink.
  v2 (deferred): the learned-model contribution line lands with Signal
  Learning; per-user source/term multipliers are not modeled.

### 2026-05-17

- **Keyword / topic mute & boost** — Pri 8, LOE 4, algo/ui. PR #77
  (merged 2026-05-17; `user_term_prefs` migration applied on prod same
  day). Per-user content-level lever distinct from `user_source_prefs`:
  **mute** hard-filters any article whose title+summary contains the
  term, **boost** multiplies a matching article's score (strongest
  match wins, mute beats boost). New Flask-free `app/term_prefs.py` SQL
  builder (escaped LIKE, `GREATEST` boost, injection-proof; 17 pure
  tests), `user_term_prefs` table + migration, `/terms` page (mirrors
  `/sources`) + "Your Keywords" nav, feed integration scoped to
  signed-in users on `/` only (anon/firehose/digest untouched). v1 =
  substring match; phrase/entity-aware + body-text are v2.
- **Across-the-spectrum in-feed** — Pri 7, LOE 3, ui/algo. PR #69
  (merged 2026-05-17). The `+N angles` pill on multi-source feed cards
  (shipped with the dossier, PR #43) now **expands inline** to a
  mini-dossier of a few sibling outlets' coverage (round-robined across
  the lean spectrum, one per source) with a "Full dossier →" deep-dive
  link, instead of navigating away. New pure `app/spectrum.py`
  (`pick_spectrum_sample`); new `GET /story/<id>/peek` partial reusing
  the dossier's canonical + visibility cluster fetch (extracted to
  `_fetch_cluster`); pill progressively enhanced (keeps its `href` so
  no-JS/no-HTMX falls back to the full dossier page). No DB migration,
  no LLM call, no new dependency, no manual prod action.
- **Search across articles** — Pri 6, LOE 6, new-feature/ui. PR #70
  (merged 2026-05-17). Full-text search: new `/search` route + nav
  box backed by a MySQL InnoDB FULLTEXT index on
  `articles(title, summary)`, NATURAL LANGUAGE MODE with the query
  bound as a parameter (no injection surface). Results deduped by
  story cluster and scoped by the feed's source-visibility +
  per-user mute rules; `ORDER BY relevance DESC, published_at DESC`.
  No new dependency. Required the `2026-05-17-search-fulltext.sql`
  FULLTEXT migration (applied on prod 2026-05-17). v2: body-text
  search, boolean/phrase mode, blended relevance×recency score.
- **Dark mode** — Pri 3, LOE 2, ui. PR #63 (merged 2026-05-17).
  Client-only theme: a nav toggle persisted in `localStorage` with a
  FOUC-free `<head>` init (falls back to `prefers-color-scheme`).
  `style.css` gains a `:root[data-theme="dark"]` palette via semantic
  surface vars; light-mode values unchanged. No DB/cron/env/pip/symlink
  — Python App restart on deploy.
- **Trending topics view** — Pri 7, LOE 5, new-feature/algo. PR #71
  (merged 2026-05-17). New `/trending` page ranking topics by
  distinct-outlet count ("20 outlets beat one outlet ×20"), each
  linking to the story dossier(s) under it. Reuses the Google
  Trends/News topic index `trending_poll` already builds (PR #53)
  instead of the roadmap's `classify_pending` LLM plan — chosen to
  avoid colliding with the in-flight `classify_pending` rewrite
  (PR #56) and add zero LLM cost. `trending_poll` now also rebuilds a
  `trending_topics` / `trending_topic_articles` snapshot each tick;
  new pure helpers in `app/trending.py` (`topic_key`, `topic_matches`
  — `score_article` refactored to its max, identical output —
  `build_persist_rows`, `group_topic_stories`). New blueprint +
  template + nav + additive CSS; env-defaulted `TRENDING_*` config.
  **Required one DB migration** (`2026-05-17-trending-topics.sql`,
  applied on prod 2026-05-17); **no new cron**. Limitation: only
  surfaces topics also trending on Google — the internal LLM-entity
  version is the documented follow-on (pairs with Signal Learning),
  deferred until PR #56 lands.
- **Article save / bookmark** — Pri 6, LOE 4, new-feature/ui. PR #64
  (merged 2026-05-17). Signed-in users star feed articles (☆/★ via
  the existing `cardSignals` Alpine component) into a new `/saved`
  page; new `saves` blueprint (`POST /save/<id>` toggle,
  `/save/<id>/read`, `GET /saved`). New `user_saves` table
  (`folder` default "Read Later"; `read_at` set on click-through).
  **Durable archive:** `jobs/maintenance.py` exempts saved articles
  (and their `article_bodies`) from both retention prunes, so the
  in-app reader copy stays readable indefinitely. v1 is a single
  implicit folder; folder UI / "N unread" prompt / export are v2.
  **Required a manual DB migration** (`2026-05-17-user-saves.sql`,
  load-bearing — see `manual-actions.md`).
- **Onboarding interview / cold-start** — Pri 7, LOE 4,
  ui/new-feature. PR #62. Theme A. Upgraded the bare `/algo/onboarding`
  preset picker into a real interview: topic categories (hard
  `category_filter`), a 5-point soft political-balance choice
  (`political_lean_direction`, no threshold so cross-spectrum exposure
  stays), and top-reputation trusted-source picks that get a
  `user_source_prefs` boost (weight 1.5, reuses the PR #19 feed
  multiplier). Answers layer on the `balanced` preset → one
  "My starting feed" `user_algorithms` row; signup now lands here;
  route is idempotent (re-visit after onboarding → editor). Pure logic
  in new Flask-free `app/onboarding.py`. **No** DB migration / cron /
  dep / env change.
- **Natural-language algorithm builder** — Pri 8, LOE 5,
  ui/algo/new-feature. PR #59. Plain-English feed description → one
  Claude Haiku call → the existing 3-axis `FEATURES` weight vector,
  pre-filling the `/algo` editor for review (never applied silently;
  reuses the existing `/save` path, so **no DB migration**). New
  Flask-free `app/algo_nl.py` (mirrors `classifier/framing.py`: lazy
  `anthropic`, `LLMUnavailable` on any failure, every value clamped
  into range, unknown keys dropped); `POST /algo/describe`
  re-renders the editor; "Describe your ideal feed" panel on the UI
  tab. Fails soft (no key / parse / API error → editor unchanged +
  inline note, never 500s); no per-request LLM cost. Shipped
  alongside a 10-item "user-empowerment" roadmap cluster (themes
  A/B/C). No new dep, no cron/env/symlink change.
- **Discussion links (Techmeme-style Reddit/HN)** — Pri 7, LOE 3,
  new-feature/ui/algo. PR #52. `popularity_poll` already matched
  Reddit/HN threads per article for the popularity score but
  discarded the permalink; now persists `permalink` + `subreddit` on
  `popularity_signals` and surfaces a compact
  `Discussion: Hacker News (142) · r/technology (89)` line on feed
  cards plus a panel on the story dossier (pure `app/discussion.py`
  helpers). Zero new API cost / no new dep; one nullable-column
  migration applied on prod. Follow-ons (user-gated): free Bluesky
  `searchPosts` harvest into the same surface; paid X/Twitter.
- **Engineering-history archive process** — ad-hoc, docs/infra. PR #51.
  `engineering-history.md` had grown to ~34.8K tokens, past the 25K
  single-`Read` ceiling, breaking the "read it end-to-end" onboarding
  step. Split into a condensed live file (~11K tokens: 3 newest entries
  full + a "Condensed history" digest + a durable "Load-bearing
  production state" section that never ages out) plus a byte-exact
  `engineering-history-archive.md` consulted on demand only. ~14K-token
  budget + the archive procedure documented in
  `engineering-session-wrapup.md` (Step 1b) and
  `new-engineering-session-instructions.md` (Step 1 + tl;dr). Docs-only;
  no DB/cron/symlink/env-var/pip change, no manual prod action.
- **External trending sort (Google News/Trends)** — Pri 7, LOE 4,
  algo/backend/ui. PR #53. Fixes BUG-015 (Popularity sort was
  HN-only). New `app/trending.py` (pure helpers) + `jobs/trending_poll.py`
  cron harvest Google Trends + Google News RSS into weighted topics and
  write a 0..1 `article_features.trending` column. The feed's
  `popularity` sort is renamed **Trending** and ordered
  `f.trending DESC, score DESC` — trending topics surface but the
  user's algorithm orders within them (relevance preserved). Opt-in
  `trending` feature in the catalog (default weight 0; existing user
  algos unchanged). Legacy `?sort=popularity` aliased to `trending`.
  No new pip dependency. **Requires manual DB migration**
  (`seed/migrations/2026-05-17-trending.sql`) + a new every-30-min
  cron entry. Does **not** supersede the separate "Trending topics
  view" item below (that's a dedicated `/trending` page).
- **CSRF tokens + auth rate limiting** — Pri 7, LOE 4, security. PR #58.
  Hand-rolled signed double-submit-cookie CSRF (stdlib `hmac`/`secrets`,
  zero new dependency) enforced on every unsafe-method route via an
  app-wide `before_request`. Token delivered to forms via a
  `csrf_field()` helper, to HTMX via an `htmx:configRequest` header
  hook, and to plain `fetch()` POSTs via a `<meta>` tag +
  `window.csrfToken`. RFC 8058 one-click `/account/unsubscribe`
  exempted (URL-token authenticated). `CSRF_ENABLED` config (default
  on; conftest disables suite-wide, `test_csrf.py` re-enables).
  Sliding-window in-process rate limit on `/auth/login` +
  `/auth/signup` (default 10 POSTs / 5 min per IP, env-tunable);
  per-worker caveat documented. No DB migration, no new dependency,
  no manual prod action — standard Python App restart on deploy.

### 2026-05-14

- **Feed sort selector (Relevance / Newest / Popularity)** — Pri 6, LOE 2,
  ui/backend. PR #48. Adds a `?sort=` query param to `/`: `relevance`
  (default — score DESC, current algo-driven order), `newest`
  (`a.published_at DESC, score DESC`), `popularity` (`f.popularity DESC,
  a.published_at DESC`). Threshold filters and the user's algorithm
  weights still apply to every sort — only the ORDER BY changes.
  Pure URL-param persistence (no DB migration). Selector preserves the
  active category and threads through HTMX "Load more". Unknown values
  fall back to `relevance`. No new dependency. CSS-only template edits
  (single `.feed-controls` flex row in `style.css`).

### 2026-05-13

- **English-only article filter at fetch time** — ad-hoc, ops/backend.
  PR #42. New `app/language.py` with pure-Python `is_english()` that
  trusts non-English RSS `<language>` tags and otherwise rejects on a
  >25% non-Latin letter ratio in title+summary. Wired into
  `fetch_feeds.py` before the INSERT; rejected entries surface as
  `skipped_lang=N` in the per-tick summary. No DB migration, no new
  dependency. Latin-script European content (FR/DE/ES/IT) still
  slips through unless the feed self-declares — limit documented in
  INSTALL.txt §10.
- **Mobile / responsive polish** — Pri 7, LOE 4, ui. PR #40. Single
  additive `@media (max-width: 640px)` block in `app/static/style.css`
  plus a `.table-scroll` utility — desktop layout untouched. Collapses
  `.topnav` to wrap, `.algo` two-column grid to single, `.feature-row`
  to stacked sliders; gives `#firehose-feed` `overflow-x: auto` with a
  `min-width: 640px` table; stacks `.admin` + `.admin-nav`; enlarges
  tap targets on `.cat-tab`, `.thumb-btn`, `.tabs button`; tightens
  `.auth-form`, `.onboarding`, `.preset-card`. CSS-only — no DB
  change, no cron, no pip dep.
- **Automated source discovery (Reddit/HN + LLM agent)** — Pri 8, LOE 7,
  ops/backend/new-feature. PR #38. New `candidate_sources` table; three
  cron jobs (`discover_harvest` hourly, `discover_promote` nightly,
  `discover_llm` weekly); `/admin/discovery` review queue with one-click
  approve / reject / blacklist. Pure helpers in `app/discovery.py`.
  Promotion gated behind admin review by default. Phase 3 (social
  firehoses) backlogged separately. **Requires manual DB migration**
  (`seed/migrations/2026-05-13-discovery.sql`) and three new cron entries.
- **Article deduplication across sources** — Pri 8, LOE 7, algo/backend. PR #24.
  `articles.story_id` + `articles.simhash` columns; `fetch_feeds` computes
  64-bit SimHash on title+summary lead; `classify_pending` per-article cluster
  assignment via title_hash exact match OR SimHash Hamming<=8 over 48h window;
  canonical = highest source_reputation, oldest tiebreak. Feed dedupes by
  story_id, firehose stays un-deduped. Heavy paraphrases left to a future
  embedding-based pass. **Requires manual DB migration**
  (`seed/migrations/2026-05-13-dedup.sql`).
- **User-added RSS feed subscriptions** — Pri 6, LOE 4, new-feature/ui.
  PR #29. New `/sources` page, signed-in users add personal feeds
  scoped via `sources.owner_id`; feed/firehose queries filter by
  visibility. **Requires manual DB migration**
  (`seed/migrations/2026-05-13-user-sources.sql`).
- **In-app reader view (body extraction + `/read/<id>`)** — Pri 8, LOE 6,
  backend/new-feature/ui. PR #21. New `article_bodies` table, trafilatura
  extractor wired into `classify_pending` (paywall-aware, shares the
  cron wallclock budget), `/read/<id>` blueprint + reader template,
  nightly `BODY_RETENTION_DAYS` prune in `maintenance.py`, single `Read →`
  link in `card-meta`. **Requires manual DB migration**
  (`seed/migrations/2026-05-13-article-bodies.sql`) and `pip install -r
  requirements.txt` (adds `trafilatura==1.12.2` + `lxml`) on cPanel,
  then Python App restart.
- **Daily personalized email digest** — Pri 6, LOE 7, new-feature/infra.
  PR #23. Opt-in toggle on `/account/settings`, `users.digest_enabled`
  + 40-hex unsub token, noon-UTC cron `jobs/send_digest.py` reusing the
  feed's ranking SQL, MIME alternative HTML+text via stdlib `smtplib`
  (localhost MTA by default). One-click List-Unsubscribe header wired.
  **Requires manual DB migration** (`seed/migrations/2026-05-13-digest.sql`)
  and a new noon-UTC cron entry.
- **Thumbs up/down on cards** — Pri 7, LOE 4, ui/algo. PR #19. Adds the
  generic `user_signals` table (forward-compat for Signal Learning) +
  `user_source_prefs`. Subtle hover-revealed chevrons, toggle semantics,
  3-downs-from-source prompt with Less / Hide / Reset actions, feed
  query splice that filters/multiplies by per-user-source weight.
  **Requires manual DB migration** (`seed/migrations/2026-05-13-signals.sql`).
- **Cron job hardening: timeouts + flock** — Pri 8, LOE 3, infra. PR #15.
  Per-job fcntl mutex, requests timeouts on RSS/Reddit/HN, HN wallclock
  budget, anthropic `timeout=30`, `FEED_FETCH_BATCH` 80→20.
- **PyMySQL connection timeouts** — Pri 8, LOE 2, backend. PR #15 (same
  PR). Web path `(5,15,10)`, cron path `(5,30,15)`.

### 2026-05-12

- **Paywall feature (per-article detection)** — Pri 7, LOE 4, algo/new-feature.
  PR #14. Active HTTP probe during `classify_pending` writes a 0..1 paywall
  score; opt-in catalog entry; admin /feeds gets a paywall column.
  **Requires manual DB migration** (`seed/migrations/2026-05-12-paywall.sql`).
- **Editorial serif wordmark in topnav** — ad-hoc, ui. PR #13. Subtle
  typographic personality: `sauce.ai` in system serif, `news` in italic.
- **3-axis feature config (Direction + Weight + Threshold)** — Pri 8, LOE 7,
  ui/backend/algo. PR #9.
- **Expand source catalog to ~635 sources** (shipped at 768) — Pri 8, LOE 5,
  ops/new-feature. PR #11. Includes auto-deactivate of dead feeds at
  error_count=10 + Refresh button in `/admin/feeds`.
- **Obscurity features (story + source)** — Pri 7, LOE 6, algo/new-feature.
  PR #10. Requires manual DB migration on existing installs
  (`seed/migrations/2026-05-12-obscurity.sql`).
- **Category tabs on `/` feed** — Pri 7, LOE 3, ui/new-feature. PR #8.
- **BUG-006 — article links don't open on click** (filed in `bugs.md`). PR #7.

### Earlier

- **Session-management doc framework** — `engineering-history.md`,
  `roadmap.md`, `bugs.md`, `engineering-session-wrapup.md`,
  `new-engineering-session-instructions.md`. PRs #4, #5, #6.
- **Anthropic SDK 0.39 → 0.101 (httpx 0.28 compat)** — PR #4.
- **First GoDaddy deploy bug-fix bundle**
  (`APPLICATION_ROOT` double-prefix, path mismatch, cron path/import
  hardening, `_selftest.py`) — PR #3.

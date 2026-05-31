# sauce.ai/news — Manual prod actions tracker

Outstanding server-side actions that must be performed manually on prod
(usually via phpMyAdmin or cPanel) before a feature works end-to-end.
**Reviewed at the start of every engineering session** per
`new-engineering-session-instructions.md` — the agent asks the user
whether each open item has been completed.

When a new manual action is required (e.g. DB migration, cron entry,
symlink, env-var change), the session that ships the feature must:

1. Append a new entry to the **Open** section below, with the **full
   command/SQL inline** (not just a path to a file), so it's
   copy-paste-ready straight from this doc. **Substitute the real prod
   account `lt1ih6uyy2z6` into every path** — do NOT leave `YOURACCOUNT`
   placeholders in this doc or in the chat paste. (`INSTALL.txt` keeps
   `YOURACCOUNT` because it's a generic fresh-install template; this
   tracker and the chat paste are operational and must be runnable
   verbatim.)
2. Also paste the same command/SQL into chat so the user can act on it
   immediately without opening any files.
3. After the user confirms completion, move the entry to **Completed**
   with the completion date.

If the migration also lives as a `news/seed/migrations/*.sql` file,
reference the filename in the entry — but the entry must still carry the
full SQL inline. The file is for fresh installs / replay; this doc is
for the live prod database.

## Conventions

Each entry: title, status, opened date, related PR, exact command,
where to run it, verification step, and (when done) completion date.

Status values: `open` (action required) · `completed` (verified done).

Sort **Open** newest-first. **Completed** newest-first.

---

## Open

(none currently)

---

## Completed
### 2026-05-31 — Cron entry: classify_pending --triggered-only (every 1 min)
**Status:** completed · **PR:** #121 · **Opened:** 2026-05-22 · **Completed:** 2026-05-31

Demand-driven classification top-up (the every-minute `classify_pending.py
--triggered-only` cron, a fast no-op unless `logs/classify_topup.signal` is
present AND fresh). This is also fix **(A)** for **BUG-023** (classification
re-stall): the cron was inert because this line had never been installed, so
PR #121's top-up never fired and classification ran only on the `*/5`
safety-net (a ~2,400 articles/hour ceiling that couldn't drain the backlog
under the 1,919-feed catalog). User confirmed the line is installed on prod
(2026-05-31; first reported applied 2026-05-27 per `bugs.md` BUG-023). The
existing `*/5 * * * * classify_pending.py` entry stays as the safety-net /
cold-start tick; `job_lock(classify_pending)` serializes the two so they
never run concurrently. No DB migration, no Python App restart, no new env
var, no new pip dep.

### 2026-05-31 — Python App restart: keywords-into-feature-list (PR #119)
**Status:** completed · **PR:** #119 (merged 2026-05-22) ·
**Opened:** 2026-05-22 · **Completed:** 2026-05-31

PR #119 folded the `/algo` Keywords tab into the UI-tab feature list
(`algo.html` + `style.css`). Template-only (no migration / cron / env /
dep). User confirmed (2026-05-31) the `sauce.ai/news` Python App was
restarted in cPanel and `/algo` now shows no Keywords tab, with the
keyword controls rendering under the algo form.

---

### 2026-05-27 — Cron entry: classify_pending --triggered-only (every 1 min) — BUG-023 fix (A)
**Status:** completed · **PR:** #121 (merged 2026-05-22) ·
**Opened:** 2026-05-22 · **Completed:** 2026-05-27

Demand-driven classification top-up. The feed (`/`) touches
`logs/classify_topup.signal` after each page load when the classified
buffer ahead of the reader drops below 400 (debounced ~60s); the new
every-minute cron runs `classify_pending.py --triggered-only`, a fast
no-op unless the signal is present AND fresh, otherwise it acquires the
existing `job_lock(classify_pending)` and runs normally (the lock
serializes it against the `*/5` safety-net tick). This entry was the
root cause of **BUG-023** (classification re-stall): PR #121's top-up
was inert because this line was never installed. User confirmed
(2026-05-27, per BUG-023 fix A) the line is now in the prod crontab;
demand-driven top-up is live. No DB migration, no Python App restart,
no new env var, no new pip dep.

**Cron line installed (cPanel → "Cron Jobs"):**

```
*    * * * *  source /home/lt1ih6uyy2z6/virtualenv/public_html/sauce.ai/news/3.11/bin/activate && cd /home/lt1ih6uyy2z6/public_html/sauce.ai/news/jobs && python classify_pending.py --triggered-only >> /home/lt1ih6uyy2z6/public_html/sauce.ai/news/logs/cron.log 2>&1
```

**Verify:**

```
crontab -l | grep -- '--triggered-only'      # the */1 line is present
tail -50 ~/public_html/sauce.ai/news/logs/cron.log | grep classify_pending
```

Expect one of: `--triggered-only: no fresh signal, exiting` (no demand) ·
`classified=N llm_articles=M ...` (ran) · `lock held … skipping` (5-min
cron mid-run). (BUG-023 itself stays `open` in `bugs.md` until prod
telemetry confirms the pending backlog fully drains.)

---

### 2026-05-31 — Python App restart: keywords-into-feature-list (PR #119)
**Status:** completed · **PR:** #119 (merged 2026-05-22) · **Opened:** 2026-05-22 · **Completed:** 2026-05-31

PR #119 folded the `/algo` Keywords tab into the UI-tab feature list
(`algo.html` + `style.css`). Template-only (Passenger picks it up on its
next worker cycle), so this was low-urgency, but the user confirmed a cPanel
"Restart" of the `sauce.ai/news` Python App was performed so it takes
immediately. `/algo` shows no Keywords tab; the keyword controls render
under the algo form. No DB migration, no env var, no pip dep.

---

### 2026-05-31 — Rotated: AGENT_PUSH_TOKEN (fine-grained PAT)
**Status:** completed · **PR:** (agent-fleet enablement) · **Opened:** 2026-05-22 · **Completed:** 2026-05-31

`AGENT_PUSH_TOKEN` is the fine-grained PAT that lets the agent fleet push
branches, open PRs, and fire `repository_dispatch` (the default
`GITHUB_TOKEN` can't trigger downstream workflows — see `agent-fleet.md`).
Fine-grained PATs **expire** and four workflows (`dev-agent`, `pm-agent`,
`post-deploy`, `migration-executor`) fail silently the day it lapses. User
confirmed the token was regenerated (scope `mhittle/sauce.ai`: Contents /
Pull requests / Workflows / Actions RW) and the `AGENT_PUSH_TOKEN` repo
secret updated. No code change; the fleet resumes immediately.

> **Standing reminder:** this is a recurring action — the new token will
> also expire. Re-file an **Open** entry before its expiry date so a future
> session rotates it ahead of the lapse.

---
crontab -l | grep -- '--triggered-only'   # the */1 line is present
tail -50 ~/public_html/sauce.ai/news/logs/cron.log | grep classify_pending
```

`classify_pending --triggered-only: no fresh signal, exiting` once a
minute confirms the cron is live (no demand); `classified=N ...` lines
appear when the signal is fresh.

---

### 2026-05-26 — Migration: article_features geo columns (geo_lat/geo_lng/geo_place) — BUG-025 fix
**Status:** completed · **PR:** (geo / "Near a place" feature, 2026-05-20; entry filed retroactively in #135) ·
**Opened:** 2026-05-26 · **Completed:** 2026-05-26 ·
**File reference:** `news/seed/migrations/2026-05-20-geo.sql`

The geo / "Near a place" feature shipped with `schema.sql` +
`classify_pending.py` writing `geo_lat`/`geo_lng`/`geo_place`, but this
migration was **never applied on prod and was never tracked here** — so
`classify_pending` crashed on every tick from ~May 20 with
`(1054, "Unknown column 'geo_lat' in 'INSERT INTO'")`. `fetch_feeds`
kept ingesting `pending` rows but none classified, so the feed (which
shows only `status='classified'`) froze at May 20. **BUG-007 class**,
on the cron write path rather than a user route (so it failed silently
— no user-facing 500). Root-caused and fixed during the 2026-05-26
session; see `bugs.md` BUG-025.

User applied the SQL via phpMyAdmin against `lt1ih6uyy2z6_news`
(2026-05-26) and confirmed `classify_pending` recovered (consecutive
clean classify ticks, feed freshening). No Python App restart was
needed — `classify_pending` is a fresh process each cron tick. In the
repo via `schema.sql` + the migration file so fresh installs replay it.

**SQL applied:**

```sql
ALTER TABLE article_features
  ADD COLUMN geo_lat   FLOAT DEFAULT NULL AFTER region,
  ADD COLUMN geo_lng   FLOAT DEFAULT NULL AFTER geo_lat,
  ADD COLUMN geo_place VARCHAR(120) DEFAULT NULL AFTER geo_lng,
  ADD KEY idx_feat_geo (geo_lat, geo_lng);
```

**Verify (confirmed):**

```sql
SHOW COLUMNS FROM article_features LIKE 'geo_%';        -- geo_lat, geo_lng, geo_place present
SELECT status, COUNT(*) FROM articles GROUP BY status;  -- pending falling over ticks
```

The ~57k `pending` backlog drains **oldest-first** at ~180/tick
(~50k/day), so the feed's newest date advances day-by-day over ~a day
— self-healing.

---

### 2026-05-22 — Migration: agent_runs (agent fleet observability)
**Status:** completed · **PR:** #114 (merged 2026-05-22) · **Opened:** 2026-05-22 · **Completed:** 2026-05-22 ·
**Applied:** by the migration-executor on the #114 `needs-migration` label (HMAC `/agent-ops/run-migration`), 2026-05-22.
**File reference:** `news/seed/migrations/2026-05-22-agent-runs.sql`

Adds a new append-only `agent_runs` table that each agent workflow
appends one row to via the HMAC `/agent-ops/report-run` endpoint after
its agent step finishes. Read by `GET /admin/agent-activity` for the
14-day cost + activity rollup, and (going forward) by the Phase 6 PM
agent so it can cite real fleet telemetry instead of inferring from PRs.

**NOT BUG-007 class:** only the new `/admin/agent-activity` (read) and
`/agent-ops/report-run` (write) endpoints touch this table; user traffic
paths do not. The admin endpoint also degrades to an empty rollup if
the table is missing (with a `table_missing: true` flag), so the page
never 500s.

Apply once on prod via phpMyAdmin → SQL tab (database `lt1ih6uyy2z6_news`):

```sql
CREATE TABLE IF NOT EXISTS agent_runs (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  ts               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  workflow         VARCHAR(64) NOT NULL,
  job              VARCHAR(64) NOT NULL DEFAULT '',
  run_id           BIGINT UNSIGNED NOT NULL DEFAULT 0,
  conclusion       VARCHAR(32) NOT NULL DEFAULT '',
  duration_seconds INT UNSIGNED NOT NULL DEFAULT 0,
  est_cost_usd     DECIMAL(10,5) NOT NULL DEFAULT 0,
  pr_number        INT UNSIGNED NOT NULL DEFAULT 0,
  notes            VARCHAR(255) NOT NULL DEFAULT '',
  PRIMARY KEY (id),
  KEY idx_agent_runs_ts (ts),
  KEY idx_agent_runs_workflow_ts (workflow, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Verify:**

```sql
SELECT COUNT(*) FROM agent_runs;       -- 0 immediately after apply
SHOW INDEX FROM agent_runs;            -- expects PRIMARY + idx_agent_runs_ts + idx_agent_runs_workflow_ts
```

Then a quick browser check (signed-in admin):
`https://sauce.ai/news/admin/agent-activity` → JSON, `table_missing: false`,
empty `per_workflow` until the first agent workflow runs after the
migration is applied.

No Python App restart required (no new blueprint — the routes were
added to the existing `admin_ops` / `agent_ops` blueprints in the same
PR, and the `agent_ops` blueprint was already registered).

**Auto-application:** the dev-agent should label this PR
`needs-migration` so the migration-executor workflow applies the file
above over HMAC and moves this entry to Completed automatically.

---

### 2026-05-21 — Secret: AGENT_OPS_SECRET for the HMAC migration executor
**Status:** completed · **PR:** #106 (merged 2026-05-21) ·
**Opened:** 2026-05-21 · **Completed:** 2026-05-21

Phase 4 adds the `agent_ops` blueprint (`/agent-ops/*`), which executes
whitelisted prod operations (run a migration, restart the app, verify a
column) authenticated by an HMAC-SHA256 signature over the request body
keyed by `AGENT_OPS_SECRET`. Until this secret is set on prod, every
`/agent-ops/*` endpoint returns **503** (fail-closed) — so the
migration-executor workflow simply can't act, which is the safe default.

**The same secret value must exist in TWO places, identical:**

1. **Prod app env** (so the Flask app can verify signatures). Secrets on
   this host live in cPanel "Setup Python App" env vars (canonical
   source of truth — cPanel materializes them into the app's
   `.htaccess` as Passenger env vars; see the load-bearing notes /
   INSTALL.txt §9). Add a new variable named `AGENT_OPS_SECRET`.
2. **GitHub Actions repo secret** named `AGENT_OPS_SECRET` (so the
   `migration-executor.yml` workflow can sign requests). Settings →
   Secrets and variables → Actions → New repository secret.

**Generate the value (32 random bytes hex) — do NOT paste it into chat,
a PR, or a commit:**

```bash
openssl rand -hex 32
```

**Set on prod (cPanel):** Setup Python App → the `sauce.ai/news` app →
Environment variables → add `AGENT_OPS_SECRET = <the hex value>` → Save
→ **Restart**. (If you edit the app's `.htaccess` directly instead, the
Passenger env line is:
`PassengerAppEnv AGENT_OPS_SECRET <the hex value>` in
`/home/lt1ih6uyy2z6/public_html/sauce.ai/news/.htaccess` — but the
cPanel UI is preferred since cPanel rewrites that file.)

**Set the matching GitHub secret:** paste the same hex value as the
`AGENT_OPS_SECRET` repository secret.

**Rotation policy: quarterly.** To rotate, generate a new value, update
both places (cPanel env + GitHub secret) in the same sitting, and
restart the Python App. There is no in-flight state to drain — the
executor signs each request fresh, so a brief mismatch only causes 401s
until both sides carry the new value.

**Verify (no secret needed — confirms fail-closed wiring):**

```bash
# 401 = blueprint live and rejecting unsigned requests (good once the
# secret is set); 503 = secret not yet configured; 404 = restart needed.
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://sauce.ai/news/agent-ops/verify-schema -d '{}'
```

After the secret is set on both sides, the Phase 4 PR description's
end-to-end test (a throwaway create-then-drop dummy-table migration)
confirms the full path.

---

### 2026-05-21 — Python App restart: admin_ops blueprint (post-deploy verification)
**Status:** completed · **PR:** #105 (merged 2026-05-21) ·
**Opened:** 2026-05-21 · **Completed:** 2026-05-21

Phase 3 adds a new Flask blueprint `admin_ops` (`news/app/routes/admin_ops.py`)
registered at `/admin`, exposing two **read-only, admin-only**
endpoints the post-deploy QA workflow hits:
`GET /admin/cron-health` (last 200 lines of `logs/cron.log` as
text/plain) and `GET /admin/usage-summary` (14-day signups / DAU /
signal-count JSON, read-only SELECTs against existing tables). **No DB
migration** — both endpoints only read tables already on prod
(`users`, `user_clicks`, `user_signals`) and the cron log file. **Not
BUG-007 class:** a missing restart just leaves the two new routes
404'ing until Passenger reloads; the rest of the app is unaffected.
After the deploy lands, restart the Python App so Passenger registers
the new blueprint.

**Action (cPanel):** Setup Python App → the `sauce.ai/news` app →
**Restart**. (This is the same restart used for every prior
blueprint/template deploy; Passenger caches imports until restart.)

**Verify (no admin creds needed — confirms the routes are registered):**

```bash
# 302 (redirect to login) = blueprint registered + auth-gated, good.
# 404 = restart didn't take; restart again.
curl -s -o /dev/null -w "%{http_code}\n" https://sauce.ai/news/admin/cron-health
curl -s -o /dev/null -w "%{http_code}\n" https://sauce.ai/news/admin/usage-summary
```

To exercise them fully, sign in as an admin and load each in a
browser: `/admin/cron-health` returns the tail of `logs/cron.log` as
plain text; `/admin/usage-summary` returns a JSON object with a
14-element `days` array.

---

---

### 2026-05-21 — Migration: lab_concept_votes (root-domain landing page voting)
**Status:** completed · **PR:** #102 (merged 2026-05-20) ·
**Opened:** 2026-05-20 · **Completed:** 2026-05-21 ·
**File reference:** `news/seed/migrations/2026-05-20-lab-votes.sql`

Backs the anonymous up/down voting controls on each "Coming soon"
card on the root-domain lab landing page (`https://sauce.ai/`). New
`/news/labvotes/tally` (GET) and `/news/labvotes/vote` (POST)
endpoints read/write this table; the static `index.html` JS calls
them. **NOT BUG-007 class:** only the new `/labvotes/*` endpoints
touch the table, and the landing page's JS catches a tally fetch
error and hides the vote UI silently — so the cards rendered
normally throughout the gap, just without scores. User confirmed
the `CREATE TABLE` was run via phpMyAdmin against `lt1ih6uyy2z6_news`
and the Python App restarted (2026-05-21), so the `lab_bp` blueprint
and the voting UI are now live.

**SQL applied:**

```sql
CREATE TABLE IF NOT EXISTS lab_concept_votes (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  concept_key  VARCHAR(64) NOT NULL,
  voter_token  CHAR(40) NOT NULL,
  vote         TINYINT NOT NULL,
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_concept_voter (concept_key, voter_token),
  KEY idx_concept (concept_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Verify:**
- `curl -s https://sauce.ai/news/labvotes/tally | head` returns JSON
  like `{"tally": {...17 keys...}, "voter_token": "<40 hex>"}` and
  sets a `lab_voter_token` cookie.
- Voting from the landing page in a browser updates the score and
  highlights the chosen ▲/▼; reloading preserves the vote.
- `SELECT COUNT(*) FROM lab_concept_votes;` ticks up as votes come in.

---

### 2026-05-21 — Migration: keywords-on-algo (drop user_term_prefs, add shared_algorithms.keywords_json)
**Status:** completed · **PR:** (drafted 2026-05-20) ·
**Opened:** 2026-05-20 · **Completed:** 2026-05-21 ·
**File reference:** `news/seed/migrations/2026-05-20-keywords-on-algo.sql`

Removes the account-wide `/terms` surface: keywords now live ONLY on
each algorithm profile (`algorithm_term_prefs`). Gallery publish
snapshots the algorithm's keywords into a new
`shared_algorithms.keywords_json` column; adopt clones them into the
new profile. **Load-bearing (BUG-007 class):** the merged code drops
the `user_term_prefs` SELECT in `routes/feed.py` and SELECTs
`keywords_json` in `routes/gallery.adopt()`. User confirmed the three
SQL steps were run via phpMyAdmin against `lt1ih6uyy2z6_news` and the
Python App restarted (2026-05-21), so signed-in feed + gallery adopt
are safe and the deprecated `/terms` route is gone.

**SQL applied (in order):**

```sql
-- 1. Preserve existing per-user keywords by copying them into each
-- user's currently-active algorithm. INSERT IGNORE keeps any
-- pre-existing per-algo term on a (algorithm_id, term) collision.
INSERT IGNORE INTO algorithm_term_prefs (algorithm_id, term, mode, weight)
SELECT ua.id, utp.term, utp.mode, utp.weight
FROM user_term_prefs utp
JOIN user_algorithms ua
  ON ua.user_id = utp.user_id
 AND ua.is_active = 1;

-- 2. Add the snapshot column on gallery listings. Added nullable +
-- backfilled + tightened so strict-mode MySQL doesn't reject a NOT NULL
-- TEXT ADD COLUMN on a populated table.
ALTER TABLE shared_algorithms
  ADD COLUMN keywords_json TEXT NULL AFTER weights_json;

UPDATE shared_algorithms SET keywords_json = '[]' WHERE keywords_json IS NULL;

ALTER TABLE shared_algorithms
  MODIFY COLUMN keywords_json TEXT NOT NULL;

-- 3. Drop the now-unused account-wide keywords table.
DROP TABLE user_term_prefs;
```

**Verify:**
- `/terms` returns 404 (route is removed).
- `/algo` Keywords tab still works on the active profile.
- Publishing an algorithm with keywords sets a non-`[]`
  `shared_algorithms.keywords_json`.
- Adopting that listing inserts rows into `algorithm_term_prefs`
  attached to the cloned profile.
- `SHOW TABLES LIKE 'user_term_prefs';` returns empty.

---

### 2026-05-20 — Source catalog import (+1151 new sources)
**Status:** completed · **PR:** #91 (merged 2026-05-20) ·
**Opened:** 2026-05-20 · **Completed:** 2026-05-20

`seed/source_lean.csv` grew 768 → 1919 sources (added 1151 hand-curated
outlets + Substacks + Medium pubs + engineering blogs). User confirmed
the admin re-import was run on prod (`/admin/feeds` → **Re-import seed
CSV** → POST `/admin/feeds/import`, idempotent upsert keyed on
`feed_url`). Dead feeds self-deactivate at `error_count=10` per the
existing cron worker. No DB migration, no cron change, no env var, no
pip install, no symlink, no Python App restart.

**Action that was run:** signed in as admin → `https://sauce.ai/news/admin/feeds`
→ clicked **Re-import seed CSV**.

**Verify:** `/admin/feeds` row count is now ~1919; `logs/cron.log`
shows `fetch_feeds` hitting the new feed URLs over the following ticks.

### 2026-05-20 — Migration: shared_algorithms + algorithm_adoptions (algorithm gallery)
**Status:** completed · **PR:** #88 (draft) ·
**Opened:** 2026-05-20 · **Completed:** 2026-05-20 ·
**File reference:** `news/seed/migrations/2026-05-20-shared-algorithms.sql`

Backs the new `/gallery` page (publish active algorithm + browse +
adopt + usage stats). Tables are read-only at feed time — only the
`/gallery` routes touch them — so a missing table did NOT risk the
signed-in feed (unlike BUG-007-class migrations); only `/gallery`
itself would have 500'd. User confirmed the SQL was run via phpMyAdmin
against `lt1ih6uyy2z6_news` and the Python App restarted (2026-05-20).
`/gallery` is now safe to load.

**SQL applied:**

```sql
CREATE TABLE IF NOT EXISTS shared_algorithms (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  owner_id      INT UNSIGNED NOT NULL,
  name          VARCHAR(120) NOT NULL,
  description   VARCHAR(500) NOT NULL DEFAULT '',
  weights_json  TEXT NOT NULL,
  is_public     TINYINT(1) NOT NULL DEFAULT 1,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_sa_owner (owner_id),
  KEY idx_sa_public_created (is_public, created_at),
  CONSTRAINT fk_sa_owner FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS algorithm_adoptions (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  shared_algorithm_id BIGINT UNSIGNED NOT NULL,
  user_id             INT UNSIGNED NOT NULL,
  user_algorithm_id   INT UNSIGNED DEFAULT NULL,
  created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_aa_shared_created (shared_algorithm_id, created_at),
  KEY idx_aa_user (user_id),
  KEY idx_aa_active (shared_algorithm_id, user_algorithm_id),
  CONSTRAINT fk_aa_shared FOREIGN KEY (shared_algorithm_id)
    REFERENCES shared_algorithms (id) ON DELETE CASCADE,
  CONSTRAINT fk_aa_user FOREIGN KEY (user_id)
    REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_aa_user_algo FOREIGN KEY (user_algorithm_id)
    REFERENCES user_algorithms (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Verify:** `/gallery` returns 200 (empty until someone publishes);
"Publish your active algorithm" inserts a row in `shared_algorithms`;
"Adopt as my feed" inserts a new active `user_algorithms` row +
one `algorithm_adoptions` event.

### 2026-05-20 — Migration: 12 perceptual feature columns + catalog rows
**Status:** completed · **PR:** #84 (merged 2026-05-20) ·
**Opened:** 2026-05-20 · **Completed:** 2026-05-20 ·
**File reference:** `news/seed/migrations/2026-05-20-perception-features.sql`

Added 6 LLM-judged perceptual columns (`tone_calmness`,
`sensationalism`, `analysis_depth`, `emotional_charge`, `hedging`,
`solution_orientation`, all DEFAULT 0.5) and 6 rule-based structural
columns (`headline_length`, `caps_ratio`, `punctuation_intensity`,
`numeric_density`, `question_headline`, `quote_present`, all DEFAULT
0) to `article_features`, plus the matching 12 `feature_catalog`
rows. Load-bearing (BUG-007 class): `jobs/classify_pending.py` INSERTs
into all 12 new columns on every tick after the deploy and would have
errored hard on the missing columns. User confirmed the ALTER + INSERT
were run via phpMyAdmin against `lt1ih6uyy2z6_news` and the Python App
restarted (2026-05-20), so `classify_pending` is now writing the new
columns and `/algo` exposes the 12 new sliders. In the repo via
`schema.sql` + `feature_catalog.sql` + the migration file so fresh
installs replay it. Folded into the load-bearing "Applied prod schema
migrations" line in `engineering-history.md`.

**SQL applied:**

```sql
ALTER TABLE article_features
  ADD COLUMN tone_calmness         FLOAT NOT NULL DEFAULT 0.5 AFTER trending,
  ADD COLUMN sensationalism        FLOAT NOT NULL DEFAULT 0.5 AFTER tone_calmness,
  ADD COLUMN analysis_depth        FLOAT NOT NULL DEFAULT 0.5 AFTER sensationalism,
  ADD COLUMN emotional_charge      FLOAT NOT NULL DEFAULT 0.5 AFTER analysis_depth,
  ADD COLUMN hedging               FLOAT NOT NULL DEFAULT 0.5 AFTER emotional_charge,
  ADD COLUMN solution_orientation  FLOAT NOT NULL DEFAULT 0.5 AFTER hedging,
  ADD COLUMN headline_length       FLOAT NOT NULL DEFAULT 0   AFTER solution_orientation,
  ADD COLUMN caps_ratio            FLOAT NOT NULL DEFAULT 0   AFTER headline_length,
  ADD COLUMN punctuation_intensity FLOAT NOT NULL DEFAULT 0   AFTER caps_ratio,
  ADD COLUMN numeric_density       FLOAT NOT NULL DEFAULT 0   AFTER punctuation_intensity,
  ADD COLUMN question_headline     FLOAT NOT NULL DEFAULT 0   AFTER numeric_density,
  ADD COLUMN quote_present         FLOAT NOT NULL DEFAULT 0   AFTER question_headline;

INSERT INTO feature_catalog (feature_key, label, type, range_min, range_max, description, is_active, sort_order) VALUES
  ('tone_calmness',        'Tone (calm)',           'scale', 0, 1, 'LLM judgment: 1 = calm, measured; 0 = alarmist, urgent.',          1, 120),
  ('sensationalism',       'Sensationalism',        'scale', 0, 1, 'LLM judgment: 1 = sensational/clickbait phrasing; 0 = plain.',     1, 125),
  ('analysis_depth',       'Analysis depth',        'scale', 0, 1, 'LLM judgment: 1 = analytical/explainer; 0 = breaking-news brief.', 1, 130),
  ('emotional_charge',     'Emotional charge',      'scale', 0, 1, 'LLM judgment: 1 = emotionally loaded language; 0 = neutral.',      1, 135),
  ('hedging',              'Hedging',               'scale', 0, 1, 'LLM judgment: 1 = heavy hedging ("may", "could"); 0 = confident assertion.', 1, 140),
  ('solution_orientation', 'Solution orientation',  'scale', 0, 1, 'LLM judgment: 1 = solution-focused; 0 = problem-focused.',         1, 145),
  ('headline_length',      'Headline length',       'scale', 0, 1, 'Rule-based: normalized title word count, capped at 24.',           1, 150),
  ('caps_ratio',           'ALL-CAPS shouting',     'scale', 0, 1, 'Rule-based: uppercase letter ratio in title (shoutiness proxy).',  1, 155),
  ('punctuation_intensity','Punctuation intensity', 'scale', 0, 1, 'Rule-based: !? density per word in title+summary.',                1, 160),
  ('numeric_density',      'Data density',          'scale', 0, 1, 'Rule-based: digit-run density per word.',                          1, 165),
  ('question_headline',    'Question headline',     'scale', 0, 1, 'Rule-based: 1 if title ends with `?`, else 0.',                    1, 170),
  ('quote_present',        'Direct quote',          'scale', 0, 1, 'Rule-based: 1 if a direct quoted span appears in title or summary.', 1, 175);
```

### 2026-05-20 — Migration: algorithm_term_prefs (per-algorithm keyword mute & boost)
**Status:** completed · **PR:** #82 (merged 2026-05-20) ·
**Opened:** 2026-05-20 · **Completed:** 2026-05-20 ·
**File reference:** `news/seed/migrations/2026-05-20-algorithm-term-prefs.sql`

Created `algorithm_term_prefs`, backing the new "Keywords" tab on
`/algo`. `routes/feed.py` reads it for the signed-in user's active
algorithm on every feed load and unions the rows with `user_term_prefs`
before scoring. **BUG-007 class** — the merged code 500'd the signed-in
feed on a missing table (anon / `/firehose` / digest unaffected) for
the gap between deploy and migration. User confirmed the `CREATE TABLE`
was run via phpMyAdmin against `lt1ih6uyy2z6_news` and the Python App
restarted (2026-05-20), so the signed-in feed + new Keywords tab are
safe. In the repo via `schema.sql` + the migration file so fresh
installs replay it. Folded into the load-bearing "Applied prod schema
migrations" line in `engineering-history.md`.

**SQL applied:**

```sql
CREATE TABLE IF NOT EXISTS algorithm_term_prefs (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  algorithm_id INT UNSIGNED NOT NULL,
  term         VARCHAR(128) NOT NULL,
  mode         ENUM('mute','boost') NOT NULL,
  weight       FLOAT NOT NULL DEFAULT 1.5,
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_algo_term (algorithm_id, term),
  KEY idx_algo_term_algo (algorithm_id),
  CONSTRAINT fk_algo_term_algo FOREIGN KEY (algorithm_id)
    REFERENCES user_algorithms (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Verify:** `/algo` Keywords tab renders for a signed-in user; adding a
mute term hides matching articles on `/`; adding a boost term raises
them. `SHOW CREATE TABLE algorithm_term_prefs\G` lists the FK to
`user_algorithms`.

### 2026-05-17 — Migration: user_term_prefs (keyword mute & boost)
**Status:** completed · **PR:** #77 (merged 2026-05-17) ·
**Opened:** 2026-05-17 · **Completed:** 2026-05-17 ·
**File reference:** `news/seed/migrations/2026-05-17-term-prefs.sql`

Created `user_term_prefs`, backing per-user keyword **mute**
(hard-filter) and **boost** (score multiplier) at `/terms`.
`routes/feed.py` reads it on every signed-in feed load (BUG-007 class
if absent). User confirmed the `CREATE TABLE` was run via phpMyAdmin
against `lt1ih6uyy2z6_news` and the Python App restarted (2026-05-17),
so the signed-in feed is safe. Anonymous feed / `/firehose` / digest
were unaffected throughout. In the repo via `schema.sql` + the
migration file so fresh installs replay it.

**SQL applied:**

```sql
CREATE TABLE IF NOT EXISTS user_term_prefs (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id    INT UNSIGNED NOT NULL,
  term       VARCHAR(128) NOT NULL,
  mode       ENUM('mute','boost') NOT NULL,
  weight     FLOAT NOT NULL DEFAULT 1.5,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_term_pref (user_id, term),
  KEY idx_term_pref_user (user_id),
  CONSTRAINT fk_term_pref_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Verify:** `/terms` returns 200 for a signed-in user; a muted term
drops matching articles from `/`; a boosted term raises them.

### 2026-05-17 — Migration: articles FULLTEXT index (article search)
**Status:** completed · **PR:** #70 · **Opened:** 2026-05-17 ·
**Completed:** 2026-05-17 ·
**File reference:** `news/seed/migrations/2026-05-17-search-fulltext.sql`

Added an InnoDB FULLTEXT index over `articles(title, summary)` backing
the new `/search` route + nav search box. User confirmed the ALTER was
run via phpMyAdmin against `lt1ih6uyy2z6_news` and the Python App
restarted (2026-05-17). `/search` is now safe to merge (the BUG-007-class
missing-index 500 is cleared). In the repo via `schema.sql` + the
migration file so fresh installs replay it.

**SQL applied:**

```sql
ALTER TABLE articles
  ADD FULLTEXT INDEX ft_articles_search (title, summary);
```

**Verify:** `https://sauce.ai/news/search?q=election` returns 200 with
ranked results (not a 500). `SHOW INDEX FROM articles WHERE Key_name =
'ft_articles_search';` lists the FULLTEXT index.

### 2026-05-17 — Migration: trending-topics snapshot tables (/trending page)
**Status:** completed · **PR:** #71 (Trending topics view, roadmap Pri 7) ·
**Opened:** 2026-05-17 · **Completed:** 2026-05-17 ·
**File reference:** `news/seed/migrations/2026-05-17-trending-topics.sql`

Added `trending_topics` + `trending_topic_articles`, the snapshot the
`/trending` page reads. The existing every-30-min `trending_poll` cron
fills both tables on its next tick — no new cron, no backfill. User
confirmed the SQL was run via phpMyAdmin against `lt1ih6uyy2z6_news`
and the Python App restarted (2026-05-17). The feed's Trending *sort*
(`article_features.trending`, a different column) was unaffected
throughout.

**SQL applied:**

```sql
CREATE TABLE IF NOT EXISTS trending_topics (
  topic_key   CHAR(40) NOT NULL,
  label       VARCHAR(255) NOT NULL,
  origin      VARCHAR(16) NOT NULL DEFAULT '',
  heat        FLOAT NOT NULL DEFAULT 0,
  captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (topic_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS trending_topic_articles (
  topic_key   CHAR(40) NOT NULL,
  article_id  BIGINT UNSIGNED NOT NULL,
  match_score FLOAT NOT NULL DEFAULT 0,
  PRIMARY KEY (topic_key, article_id),
  KEY idx_tta_article (article_id),
  CONSTRAINT fk_tta_article FOREIGN KEY (article_id)
    REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### 2026-05-17 — Migration: user_saves (article save / bookmark)
**Status:** completed · **PR:** #64 (merged 2026-05-17) ·
**Opened:** 2026-05-17 · **Completed:** 2026-05-17 ·
**File reference:** `news/seed/migrations/2026-05-17-user-saves.sql`

Created `user_saves`, backing the star/bookmark button on feed cards
and the `/saved` page. Load-bearing (BUG-007 class): the table was NOT
confirmed applied before PR #64 merged, so signed-in `/` 500'd and the
nightly `maintenance` job would have errored in the interval between
deploy and migration. User ran the `CREATE TABLE user_saves` SQL via
phpMyAdmin against `lt1ih6uyy2z6_news` and restarted the Python App
(2026-05-17) — signed-in feed recovered. **Process note:** recurrence
of the BUG-007 pattern (load-bearing migration not applied pre-merge);
the migration should have gated the PR merge, not trailed it.

### 2026-05-17 — Migration: popularity_signals discussion columns
**Status:** completed · **PR:** #52 · **Opened:** 2026-05-17 ·
**Completed:** 2026-05-17 ·
**File reference:** `news/seed/migrations/2026-05-17-discussion-links.sql`

Added nullable `permalink` + `subreddit` to `popularity_signals` so the
feed card and story dossier can render a Techmeme-style "Discussion:"
line linking to the Reddit/HN thread (`popularity_poll` already matched
those threads for the popularity score; it now also writes the
permalink). User confirmed the ALTER was run via phpMyAdmin against
`lt1ih6uyy2z6_news` and the Python App restarted (2026-05-17).

**SQL applied:**

```sql
ALTER TABLE popularity_signals
  ADD COLUMN permalink VARCHAR(1024) DEFAULT NULL AFTER comments,
  ADD COLUMN subreddit  VARCHAR(64) DEFAULT NULL AFTER permalink;
```

---

### 2026-05-17 — Migration + cron: external trending sort (BUG-015)
**Status:** completed · **PR:** #53 · **Opened:** 2026-05-17 ·
**Completed:** 2026-05-17 ·
**File reference:** `news/seed/migrations/2026-05-17-trending.sql`

Added `article_features.trending` (0..1, external trending-topic match)
and the new `trending_poll` cron that fills it from Google Trends +
Google News RSS. The renamed **Trending** feed sort orders by this
column. User confirmed the migration was applied, the every-30-min
cron added, and the Python App restarted.

**SQL applied (phpMyAdmin against `lt1ih6uyy2z6_news`):**

```sql
ALTER TABLE article_features
  ADD COLUMN trending FLOAT NOT NULL DEFAULT 0 AFTER paywall;
```

**Cron added (cPanel → "Cron Jobs"):**

```cron
# every 30 min: external trending poll (Google Trends + Google News RSS)
*/30 * * * *  source /home/lt1ih6uyy2z6/virtualenv/public_html/sauce.ai/news/3.11/bin/activate && cd /home/lt1ih6uyy2z6/public_html/sauce.ai/news/jobs && python trending_poll.py >> /home/lt1ih6uyy2z6/public_html/sauce.ai/news/logs/cron.log 2>&1
```

Python App restarted so the renamed sort + new column load. Verify on
prod: `/?sort=trending` returns 200 and is no longer HN-only;
`logs/cron.log` shows a `trending_poll` line like
`topics=T gnews=G articles=N matched=M` within ~30 min.

---

### 2026-05-17 — pip install -r requirements.txt (py3langid for BUG-013/BUG-014)
**Status:** completed · **PR:** #50 (BUG-013, BUG-014) · **Opened:** 2026-05-17 · **Completed:** 2026-05-17

User confirmed `pip install -r requirements.txt` was run on prod
(2026-05-17), installing `py3langid==0.3.0` (+ wheel-distributed
`numpy`). The European-language filter (stage 3 of `is_english`) is
now live: `jobs/fetch_feeds.py` is a fresh per-tick cron process so it
picks up py3langid on its next tick regardless of a Passenger restart
(web routes don't use the detector, so no site-facing restart was
strictly required). BUG-013/BUG-014 are now effective in production.

Expect `skipped_lang=N` to rise in `logs/cron.log` over the next few
`fetch_feeds` ticks, and German/Spanish/Finnish content to clear out
of the feed over ~7 days as pre-existing rows age out (the filter is
fetch-time only; it does not purge rows already in `articles`).

**Commands run (account `lt1ih6uyy2z6`):**

```bash
# In cPanel Terminal, paste cPanel's "Enter to the virtual environment"
# command for the news app, then:
source /home/lt1ih6uyy2z6/virtualenv/public_html/sauce.ai/news/3.11/bin/activate \
  && cd /home/lt1ih6uyy2z6/public_html/sauce.ai/news
pip install -r requirements.txt
```

**Verify:**

```bash
/home/lt1ih6uyy2z6/virtualenv/public_html/sauce.ai/news/3.11/bin/python \
  -c "from py3langid.langid import LanguageIdentifier, MODEL_FILE; LanguageIdentifier.from_pickled_model(MODEL_FILE, norm_probs=True); import numpy; print('py3langid ok, numpy', numpy.__version__)"
```

---

### 2026-05-13 — Migration: story_dossiers (framing-summary cache)
**Status:** completed · **PR:** #43 · **Opened:** 2026-05-13 ·
**Completed:** 2026-05-13 ·
**File reference:** `news/seed/migrations/2026-05-13-story-dossiers.sql`

Added the `story_dossiers` table that caches each story cluster's
LLM-generated framing summary keyed by canonical `articles.id` and
invalidated by `member_signature` (sha1 of sorted member ids). The
`/story/<id>` route writes to this table on the first uncached view per
signature. Ran via phpMyAdmin against `lt1ih6uyy2z6_news`; Python App
restarted post-migration so the new `story_bp` blueprint registers.

**SQL applied:**

```sql
CREATE TABLE IF NOT EXISTS story_dossiers (
  story_id         BIGINT UNSIGNED NOT NULL,
  member_signature CHAR(40) NOT NULL,
  summary_text     TEXT NOT NULL,
  article_count    INT UNSIGNED NOT NULL DEFAULT 0,
  lean_buckets     VARCHAR(16) NOT NULL DEFAULT '',
  model            VARCHAR(64) NOT NULL DEFAULT '',
  generated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (story_id),
  CONSTRAINT fk_dossier_story FOREIGN KEY (story_id) REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### 2026-05-13 — Cron entries: three discover_* jobs
**Status:** completed · **PR:** #38 · **Opened:** 2026-05-13 · **Completed:** 2026-05-13

Three new cron lines added in cPanel after the candidate_sources
migration ran. All three jobs are wrapped in `job_lock` and no-op
safely on an empty queue.

**Cron lines applied (account substituted):**

```cron
# hourly (15 past): source discovery harvest (Reddit/HN domain mining)
15  * * * *   source /home/lt1ih6uyy2z6/virtualenv/public_html/sauce.ai/news/3.11/bin/activate && cd /home/lt1ih6uyy2z6/public_html/sauce.ai/news/jobs && python discover_harvest.py >> /home/lt1ih6uyy2z6/public_html/sauce.ai/news/logs/cron.log 2>&1

# nightly 4:00am UTC: source discovery validation
0   4 * * *   source /home/lt1ih6uyy2z6/virtualenv/public_html/sauce.ai/news/3.11/bin/activate && cd /home/lt1ih6uyy2z6/public_html/sauce.ai/news/jobs && python discover_promote.py >> /home/lt1ih6uyy2z6/public_html/sauce.ai/news/logs/cron.log 2>&1

# weekly Monday 5:00am UTC: LLM-suggested source discovery
0   5 * * 1   source /home/lt1ih6uyy2z6/virtualenv/public_html/sauce.ai/news/3.11/bin/activate && cd /home/lt1ih6uyy2z6/public_html/sauce.ai/news/jobs && python discover_llm.py >> /home/lt1ih6uyy2z6/public_html/sauce.ai/news/logs/cron.log 2>&1
```

---

### 2026-05-13 — Migration: candidate_sources (automated source discovery)
**Status:** completed · **PR:** #38 · **Opened:** 2026-05-13 ·
**Completed:** 2026-05-13 ·
**File reference:** `news/seed/migrations/2026-05-13-discovery.sql`

Added the `candidate_sources` table that backs the new hourly Reddit/HN
harvest, weekly LLM-suggestion pass, and nightly RSS auto-discovery
jobs. Ran in phpMyAdmin against `lt1ih6uyy2z6_news`; Python App
restarted post-migration.

**SQL applied:**

```sql
CREATE TABLE IF NOT EXISTS candidate_sources (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  domain        VARCHAR(255) NOT NULL,
  feed_url      VARCHAR(1024) DEFAULT NULL,
  name          VARCHAR(255) DEFAULT NULL,
  homepage_url  VARCHAR(1024) DEFAULT NULL,
  category      VARCHAR(64) DEFAULT NULL,
  score         INT NOT NULL DEFAULT 0,
  first_seen_via VARCHAR(32) NOT NULL,
  last_seen_via  VARCHAR(32) NOT NULL,
  first_seen_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  state         ENUM('pending','validated','approved','rejected','blacklisted')
                NOT NULL DEFAULT 'pending',
  reject_reason VARCHAR(255) DEFAULT NULL,
  validation_attempted_at DATETIME DEFAULT NULL,
  validation_error VARCHAR(255) DEFAULT NULL,
  promoted_source_id INT UNSIGNED DEFAULT NULL,
  notes         TEXT,
  PRIMARY KEY (id),
  UNIQUE KEY uk_candidate_domain (domain),
  KEY idx_candidate_state_score (state, score),
  KEY idx_candidate_last_seen (last_seen_at),
  CONSTRAINT fk_candidate_source FOREIGN KEY (promoted_source_id)
    REFERENCES sources (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### 2026-05-13 — pip install -r requirements.txt (trafilatura for PR #21)
**Status:** completed · **PR:** #21 · **Opened:** 2026-05-13 ·
**Completed:** 2026-05-13

PR #21 added `trafilatura==1.12.2` (+ `lxml`) to `requirements.txt` for
the in-app reader's body extractor. The cPanel "Run Pip Install" button
in Setup Python App was greyed out, so the install was run manually
from cPanel Terminal after activating the venv. `classify_pending` is
the only consumer (lazy import in `app/extractor.py`); web routes were
unaffected, so the site itself stayed up while this was pending.

**Commands run:**

```bash
# In cPanel Terminal, after pasting cPanel's "Enter to the virtual
# environment" command for the news app:
source /home/YOURACCOUNT/virtualenv/public_html/sauce.ai/news/3.11/bin/activate \
  && cd /home/YOURACCOUNT/public_html/sauce.ai/news
pip install -r requirements.txt
```

**Post:** Python App restarted via cPanel.

---

### 2026-05-13 — Migration: sources.owner_id (user-added feeds)
**Status:** completed · **PR:** #29 · **Opened:** 2026-05-13 ·
**Completed:** 2026-05-13 ·
**File reference:** `news/seed/migrations/2026-05-13-user-sources.sql`

Added the `owner_id` column to `sources` so user-added RSS feeds can be
scoped to the user that added them. NULL = global pool (all existing
rows); non-null = personal source visible only to that user. Site was
500'ing on every reader route until this ran because `feed.py:65` and
`firehose.py:49` reference `s.owner_id` in the visibility WHERE clause
on every page load. Ran via phpMyAdmin against `lt1ih6uyy2z6_news`,
Python App restarted, site recovered. Filed as BUG-007 during recovery.

**SQL applied:**

```sql
ALTER TABLE sources
  ADD COLUMN owner_id INT UNSIGNED DEFAULT NULL AFTER region,
  ADD KEY idx_sources_owner (owner_id),
  ADD CONSTRAINT fk_sources_owner FOREIGN KEY (owner_id)
    REFERENCES users (id) ON DELETE CASCADE;
```

---

### 2026-05-13 — Migration: user_signals + user_source_prefs
**Status:** completed · **PR:** #19 · **Opened:** 2026-05-13 ·
**Completed:** 2026-05-13 ·
**File reference:** `news/seed/migrations/2026-05-13-signals.sql`

Added the two tables that back thumbs up/down: `user_signals` (generic
per-user signal stream, sized for the full Signal Learning vocabulary)
and `user_source_prefs` (per-user-source weight, 0 = hidden, 0.5 =
downweighted, default 1.0). `feed.py` LEFT JOINs `user_source_prefs` for
signed-in users so this also contributed to the BUG-007 outage. Ran in
the same phpMyAdmin session as the owner_id ALTER.

**SQL applied:**

```sql
CREATE TABLE IF NOT EXISTS user_signals (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id     INT UNSIGNED NOT NULL,
  article_id  BIGINT UNSIGNED NOT NULL,
  signal_type VARCHAR(32) NOT NULL,
  value       FLOAT DEFAULT NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_signal_binary (user_id, article_id, signal_type),
  KEY idx_signal_user_type_ts (user_id, signal_type, created_at),
  KEY idx_signal_article_type (article_id, signal_type),
  CONSTRAINT fk_signal_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_signal_article FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_source_prefs (
  user_id    INT UNSIGNED NOT NULL,
  source_id  INT UNSIGNED NOT NULL,
  weight     FLOAT NOT NULL DEFAULT 1.0,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, source_id),
  CONSTRAINT fk_usp_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_usp_source FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### 2026-05-13 — Migration: article dedup (story_id + simhash)
**Status:** completed · **PR:** #24 · **Opened:** 2026-05-13 ·
**Completed:** 2026-05-13 ·
**File reference:** `news/seed/migrations/2026-05-13-dedup.sql`

Added `articles.simhash`, `articles.story_id`, and the
`(story_id, published_at)` index; backfilled `story_id = id` for legacy
rows. User ran the SQL via phpMyAdmin; Python App restart still required
once the PR merges so the new code path picks up the columns.

**SQL applied:**

```sql
ALTER TABLE articles
  ADD COLUMN simhash  BIGINT UNSIGNED DEFAULT NULL AFTER title_hash,
  ADD COLUMN story_id BIGINT UNSIGNED DEFAULT NULL AFTER simhash,
  ADD KEY idx_articles_story (story_id, published_at);

UPDATE articles SET story_id = id WHERE story_id IS NULL;
```

---

### 2026-05-13 — Cron entry: daily email digest
**Status:** completed · **PR:** #23 · **Opened:** 2026-05-13 · **Completed:** 2026-05-13

Noon-UTC cron line for `jobs/send_digest.py` added in cPanel. Will fire
its first real run at the next noon UTC; until users opt in it exits as
a no-op.

---

### 2026-05-13 — Migration: users digest columns
**Status:** completed · **PR:** #23 · **Opened:** 2026-05-13 · **Completed:** 2026-05-13

`users.digest_enabled`, `digest_unsub_token`, `digest_last_sent_at` plus
`idx_users_digest` index added on prod (`lt1ih6uyy2z6_news`). Python App
restarted. `/account/settings` toggle is now safe to use.

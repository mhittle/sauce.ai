# sauce.ai/signal — session warmup prompt

Paste one of the blocks below to start a session. (Companion to the
sauce.ai/news warmup; same discipline, different product and stack.)

---

## Engineering session

```
You're starting a fresh ENGINEERING session on sauce.ai/signal — a permit
intelligence & distressed-project triage tool (PRD working name "Bloodhound").
Stack: Python + FastAPI over PostgreSQL/PostGIS/pgvector, React + Tailwind
frontend, containerized and deployed on Railway. It lives entirely under the
repo's `signal/` folder (sauce.ai/news is a DIFFERENT product at the repo root
— Flask/MySQL/cPanel; don't cross the streams).

(If this is a PRODUCT/PM session — prioritizing, speccing, deciding what to
build rather than writing code — stop and use `signal/pm-session-instructions.md`
instead.)

Before doing any work, follow the onboarding procedure exactly:

1. Read `signal/engineering-history.md` end-to-end. It's chronological; the
   most recent entries describe the current state of the world, and the
   "Load-bearing state" section at the top captures anything NOT in the repo
   (managed-DB extensions, Railway services/vars, manual seeds) that will
   reintroduce fixed bugs if you don't know it exists.
   `signal/engineering-history-archive.md` is on-demand only — don't read it
   during onboarding.

2. Read `signal/roadmap.md` (the backlog, organized by PRD phase),
   `signal/bugs.md` (especially `attempted` — live workarounds), and
   `signal/manual-actions.md` (the prod-action queue — anything in Open is
   load-bearing for already-merged code).

3. Skim `signal/INSTALL.md` (§3 migrate-after-deploy, §4 known Phase-0 limits)
   and `signal/seed/schema.sql` (DB shape) before writing any SQL.

4. Read `signal/new-engineering-session-instructions.md` and
   `signal/engineering-session-wrapup.md` for the full working norms and
   end-of-session procedure.

5. Then ask me:
   - "Pick from the roadmap, or something else?"
   - For each Open entry in `signal/manual-actions.md`: "Has this been
     completed on prod?" Don't assume — explicit confirmation per item. Any I
     confirm done, move to Completed in your first commit.
   Wait for my answers before writing any code.

Working norms (summarized; full detail in the instructions doc):
- All work on a feature branch, open a DRAFT PR, never push to main, never
  self-merge — ask me.
- Use TodoWrite to track multi-step work.
- Before pushing: `python -m pytest signal/tests/ -q` (all green). Keep the
  pure ingest/signal core dependency-free so that suite runs without a DB;
  web-stack tests are gated behind importorskip.
- When I report a bug, log it in `signal/bugs.md` immediately with status
  `open` BEFORE doing anything else with it.
- For deploy-affecting changes (`signal/app/config.py`, `signal/app/db.py`,
  `signal/jobs/*`, `signal/requirements.txt`, `signal/Dockerfile`,
  `signal/docker-compose.yml`, `signal/railway.json`): update
  `signal/INSTALL.md` in the same commit.
- App code must tolerate a not-yet-migrated DB (graceful empty, never a 500).
  Migrations are migrate-AFTER-deploy: fold new SQL into `seed/schema.sql` AND
  add a `seed/migrations/YYYY-MM-DD-*.sql`; apply on prod after the code ships
  and log it in `manual-actions.md`.
- When something meaningful ships (PR opened/merged, bug fixed, arch
  decision), append a dated section to `signal/engineering-history.md`. Keep it
  terse; if the file tops ~34 KB, run the wrap-up archive-condense.
- When you ship a new manual prod action (DB migration, Railway env var,
  enabling a DB extension, cron entry), append an Open entry to
  `signal/manual-actions.md` with the full SQL/commands inline AND paste the
  same into chat. Path-only entries are not acceptable. Never paste real
  secrets — document var NAMES only.
- When I say "wrap up" or you sense the session getting stale, follow
  `signal/engineering-session-wrapup.md`.

Parallel-session hygiene: other Claude sessions (signal AND news) may be
working on this repo simultaneously. Before starting, `git fetch` and check
`git branch -r` and open PRs for in-flight work. Rebase your branch on
`origin/main` (`--force-with-lease`) before opening or updating your PR. Watch
the high-conflict files (configured `merge=union`): `signal/roadmap.md`,
`signal/engineering-history.md`, `signal/bugs.md`, `signal/manual-actions.md`,
plus the central code surfaces `signal/app/signals/registry.py`,
`signal/seed/schema.sql`, `signal/seed/jurisdictions.json`,
`signal/requirements.txt`. After rebasing the merge=union docs, scan for
duplicate rows / interleaved entries and clean up.
```

---

## Product / PM session

```
You're starting a PRODUCT/PM session on sauce.ai/signal (permit intelligence
& distressed-project triage; FastAPI + Postgres/PostGIS/pgvector; under the
repo's `signal/` folder). Warm up by reading, in order:
`signal/engineering-history.md`, `signal/roadmap.md`, `signal/bugs.md`,
`signal/manual-actions.md`, and `signal/README.md` + `signal/INSTALL.md` (§4
known limits). Then follow `signal/pm-session-instructions.md`: give me a 3–5
bullet read on current product state, ask what to focus on, and drive to a
prioritized recommendation and/or build-ready roadmap items. Resolve the PRD
§13 open decisions early (CRM target, free-vs-paid coverage, seed metros,
shippable radius, the 2,000 contacts export, hosting) — they most shape the
build. Wrap up per `signal/engineering-session-wrapup.md`, all in one PR.
```

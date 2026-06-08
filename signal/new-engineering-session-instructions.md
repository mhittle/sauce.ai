# sauce.ai/signal — Instructions for new engineering sessions

For any agent (LLM or human) starting fresh work on **sauce.ai/signal**, the
permit-intelligence / distressed-project triage tool. Read this end-to-end
before touching anything.

> **Product-management session?** Use `pm-session-instructions.md` instead
> (same warmup, product focus).
>
> **Working on sauce.ai/news?** That's a different product with a different
> stack (Flask/MySQL/cPanel). Its docs live at the repo root. Don't cross the
> streams — signal is FastAPI/Postgres and lives entirely under `signal/`.

---

## Step 1 — Read `engineering-history.md` end-to-end

`signal/engineering-history.md` is the condensed working history. It's
chronological: most-recent entries in full, older ones condensed, and a
durable **"Load-bearing state"** section at the top capturing anything not in
the repo (managed-DB extensions, Railway services/vars, manual seeds) that
will reintroduce fixed bugs if you don't know it exists. Read that carefully.
Keep the live file under ~34 KB (single-`Read` budget); condense oldest-first
into `engineering-history-archive.md` when over (see the wrap-up doc).

## Step 2 — Read `roadmap.md`, `bugs.md`, `manual-actions.md`

- `roadmap.md` — backlog, each item rated Priority (1–10), LOE (1–10),
  Category (`infra`, `ingest`, `signals`, `ui`, `backend`, `algo`, `ops`,
  `security`, `docs`). Organized around PRD phases 0–4.
- `bugs.md` — read `open`, `in-progress`, `attempted` (live workarounds).
- `manual-actions.md` — outstanding prod actions (Open = load-bearing for
  already-merged code, e.g. an un-applied migration or a Railway var).

## Step 3 — Ask what to work on, and whether open manual actions are done

> "Pick from `roadmap.md`, or something else?"

For each **Open** entry in `manual-actions.md`, ask per-item whether it's been
done on prod. Move confirmed ones to **Completed** (today's date) in your
first commit. If they pick a roadmap item, flip it to `in-progress` in your
first commit and to `done` (with this PR's number) before requesting merge —
the wrap-up bookkeeping rides in the feature PR (see the wrap-up doc).

## Step 4 — Read the deploy docs

- `INSTALL.md` — local docker-compose + Railway deploy + migrate-after-deploy
  + §4 known Phase-0 limits.
- `README.md` — product description, stack, layout.
- `seed/schema.sql` — DB shape. Skim before writing SQL.

## Step 5 — Architecture in one paragraph

FastAPI (`app/main.py:create_app`) over PostgreSQL+PostGIS+pgvector via
SQLAlchemy 2. The ingest pipeline is the core: a `SourceAdapter`
(`app/adapters/`, generic **Socrata** adapter today; ArcGIS/portal scrapers
later) pulls per jurisdiction → `normalize_record` maps source columns onto
the canonical schema via the jurisdiction's `field_map` → `ingest/dedup.py`
collapses permits into **projects** (APN → address → permit) →
`signals/derived.py` computes the signal catalog (incl. distress) →
`signals/scoring.py` blends weighted **rules** into `lead_score`. Signals live
**EAV-style** in `project_signals` keyed by the in-code
`signals/registry.py`, so a new signal is a registry row, not a schema change,
and auto-appears as an API facet (`/api/signals`) and a rule input. Jobs
(`jobs/`) are standalone scripts (`init_db`, `daily_ingest`, `scheduler`);
there's no per-request heavy work. The React/Tailwind SPA (`web/`) reads
`/api/projects` (default sort `lead_score`).

## Step 6 — Session workflow

1. Work on a **feature branch**. Never push to `main` directly, never
   self-merge — open a **draft PR** and ask the owner.
2. Use TodoWrite for multi-step work.
3. Before pushing: `python -m pytest signal/tests/ -q` (green). Keep the pure
   logic (adapters/signals/ingest/scoring) **import-light** so that suite runs
   without a DB; gate web-stack tests behind `importorskip`.
4. For deploy-affecting changes (`app/config.py`, `app/db.py`, `jobs/*`,
   `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `railway.json`):
   update `INSTALL.md` in the same commit.
5. Land all wrap-up bookkeeping in the **same PR** (roadmap → done with PR#,
   history entry, bugs/manual-actions in sync).

## Step 7 — Parallel sessions and merge hygiene

Multiple sessions (and the news sessions) share this repo. Rebase your branch
on `origin/main` before opening/updating a PR
(`git fetch && git rebase origin/main && git push --force-with-lease`).
High-conflict files (configured `merge=union` in `.gitattributes`):
`signal/roadmap.md`, `signal/engineering-history.md`, `signal/bugs.md`,
`signal/manual-actions.md`. After a rebase, scan them for duplicate
at-a-glance rows / out-of-order dated headers and clean up in the same PR.
Central code surfaces that conflict easily: `app/signals/registry.py`
(the signal catalog), `seed/schema.sql`, `seed/jurisdictions.json`,
`requirements.txt`. If your task touches these and another session likely
does too, confirm scope with the owner first.

## Step 8 — When the owner reports a bug, log it in `bugs.md` immediately

Add an entry with a new sequential ID and status `open` BEFORE doing anything
else — even a 30-second fix. The log is the audit trail.

## Step 9 — When something meaningful ships, append to `engineering-history.md`

Bug fixed (root cause + fix), feature shipped, deploy step changed, arch
decision, PR opened/merged. New dated section at the top. Terse. Skip trivia
(typos, pure refactors, dead experiments).

## Step 10 — Coding conventions

- Default to **no comments**; add one only when the WHY is non-obvious.
- Don't handle impossible scenarios; validate only at boundaries (user input,
  external APIs/portals).
- Edit existing files; don't create new ones unless necessary.
- No emojis in code/docs unless asked.
- Keep the **pure ingest/signal core dependency-free** so it stays testable
  without a DB or network — that's a load-bearing property of the test suite.
- App code must **tolerate a not-yet-migrated DB** (graceful empty, never a
  500) — the API already does this; preserve it.
- **Never paste a real secret** (API key, DB URL with password) into chat or
  the repo. Use env vars; document var *names* only.

## Step 11 — Wrapping up

When the owner says "wrap up" (or the session goes stale), follow
`engineering-session-wrapup.md`.

---

## tl;dr

1. Read `engineering-history.md`, `roadmap.md`, `bugs.md`,
   `manual-actions.md` (all of `signal/`).
2. Ask: "Pick from the roadmap, or something else?" + confirm any Open
   manual actions.
3. Log owner-reported bugs into `bugs.md` first.
4. Feature branch → draft PR; `pytest signal/tests/ -q` green; rebase on
   `main` before opening/updating.
5. Ship wrap-up bookkeeping in the same PR. Follow the wrap-up doc.

# sauce.ai/news — Instructions for new engineering sessions

For any agent (LLM or human) starting fresh work on this codebase. Read this
end-to-end before touching anything.

---

## Step 1 — Read `engineering-history.md` end-to-end

This is **non-optional**. The history file is short and chronological. The
most recent entries describe the current state of the world; older entries
explain how we got there. Several load-bearing pieces of server-side state
(symlinks, manually-overwritten files, hostile cPanel scaffolds) are **not**
visible in the repo and will reintroduce bugs we already fixed if you don't
know they exist.

After reading you'll know:

- What sauce.ai/news is and what the original spec called for
- What v1 ships and what's deferred to v2
- The deploy bugs we've hit, their root causes, and the workarounds applied
- What's currently running in production and where the server-side artifacts
  live

## Step 2 — Read `roadmap.md`

The backlog of future sprints, features, and projects. Each item is rated
on Priority (1–10), LOE (1–10), and Category (`infra`, `new-feature`, `ui`,
`backend`, `algo`, `security`, `ops`, `skunkworks`, `docs`).

## Step 3 — Ask the user what to work on

Before doing anything else, ask:

> "Want to pick something off `roadmap.md`, or are we working on something
> else this session?"

If they pick from the roadmap, confirm the item and update its status to
`in-progress` in `roadmap.md` as part of your first commit. If they have
something else in mind, fine — but consider adding it to the roadmap with
appropriate ratings so future sessions inherit the context.

## Step 4 — Read the deploy docs

- `news/INSTALL.txt` — first-time setup on GoDaddy cPanel/CloudLinux.
  Especially §8 (troubleshooting) and §10 (known v1 limits).
- `news/README.md` — high-level project description and stack.
- `news/seed/schema.sql` — DB shape. Skim it before writing any SQL.

## Step 5 — Architecture in one paragraph

Flask 3 served by cPanel Passenger; MySQL via PyMySQL; Jinja2 + HTMX + Alpine
on the client (no build step). The pipeline is four cron-driven Python scripts
under `news/jobs/`: `fetch_feeds` (RSS), `classify_pending` (rules + Claude
Haiku for two judgment features), `popularity_poll` (Reddit + HN), and nightly
`maintenance`. Articles get ten feature columns in `article_features`. Per-user
ranking is a weighted SQL expression evaluated at query time — there is no
per-article Python at request time. The three user views are `/` (feed),
`/firehose` (live), and `/algo` (algorithm editor). Admin lives at `/admin/*`.

## Step 6 — Session workflow

1. Pick or confirm a feature branch. Never push to `main` directly. CI/CD
   deploys on push to `main`, so anything you push there is live within a
   minute.
2. Use TodoWrite to track multi-step work. Mark items done as you go.
3. Before pushing: run `python -m pytest news/tests/ -q`. All tests should
   pass.
4. For deploy-affecting changes (anything in `news/passenger_wsgi.py`,
   `news/app/__init__.py`, `news/app/config.py`, `news/jobs/*.py`, or
   `news/requirements.txt`): also update `news/INSTALL.txt` in the same
   commit if the install procedure changed.
5. Open a draft PR. Don't self-merge; ask the user.

## Step 7 — When you accomplish something meaningful, append to `engineering-history.md`

"Meaningful" means:

- A bug fixed (root cause + fix, not just "fixed bug")
- A feature shipped
- A deploy step changed (new env var, new cron job, new server-side state)
- An architectural decision made (new dependency, new layer, design pivot)
- A PR opened or merged

Add a **new dated section** at the top (under the heading row). Follow the
format of existing entries: Context, What changed, Why, Code touched, Server
state touched, PRs.

**Do not append for:**

- Trivial commits (typo fixes, variable renames)
- Failed experiments that left no trace in the repo or on the server
- Pure refactors that don't change behavior

Keep entries terse. The reader is a future agent who needs to come up to
speed fast.

## Step 8 — Known sharp edges to watch for

These are the foot-guns we've already hit. Don't re-discover them.

- **`passenger_wsgi.py` can get overwritten by cPanel** if the Python App is
  recreated or the Python version is changed. The cPanel scaffold is
  self-recursive and infinite-loops. Backup of the working file is at
  `~/passenger_wsgi.py.working` on the server. The repo's version is
  correct; restoring it on the server is a `cp` away.
- **Three symlinks in `~/public_html/sauce.ai/news/` are load-bearing.**
  Names: `activate`, `set_env_vars.py`, `python3.11_bin`. They point at the
  real venv `bin/` files. If they disappear, the CloudLinux venv shim
  fork-bombs Passenger. Re-create with `ln -sf` from the venv `bin/`.
- **Never set `dangerous-clean-slate: true`** in `.github/workflows/main.yml`.
  It wipes the symlinks above and any other server-side state. Incremental
  sync (the default `false`) is correct.
- **CloudLinux nproc/EP limit on this account is tight (~115).** A
  Passenger fork-bomb saturates it within seconds and the user's interactive
  shell stops working. If you see `fork: Resource temporarily unavailable`:
  STOP the Python App in cPanel first, then kill processes, then wait
  60 seconds before doing anything else.
- **Do NOT set `APPLICATION_ROOT` in cPanel env vars.** LiteSpeed already
  mounts the app at `/news`; setting this env var causes a double-prefix
  bug and every URL 404s.
- **The `.htaccess` in `~/public_html/sauce.ai/news/` contains secrets**
  (DB password, Anthropic API key). Treat it as sensitive. cPanel writes
  it; don't manually edit unless you know what you're doing.
- **Never paste a real API key, DB password, or other secret into chat.**
  Chat transcripts are logged. If you suspect a secret was exposed, rotate
  immediately — Anthropic console for API keys, cPanel MySQL for DB
  passwords.

## Step 9 — Coding conventions

- Default to **no comments**. Only add one when the WHY is non-obvious: a
  hidden constraint, a subtle invariant, a workaround for a specific bug.
  Don't explain WHAT the code does — names should carry that.
- **Don't add error handling for impossible scenarios.** Trust internal
  invariants and framework guarantees. Only validate at system boundaries
  (user input, external APIs).
- **Edit existing files; don't create new ones** unless necessary.
- **No emojis in code, comments, or docs** unless the user explicitly asks.
- **Test changes locally** before pushing. The Flask app builds and runs
  with `python -c "from app import create_app; create_app()"`. The cron
  scripts can be invoked directly: `python jobs/<script>.py`.

## Step 10 — When in doubt

- The original product spec is at the bottom of `engineering-history.md`.
- `news/INSTALL.txt` §8 documents every failure mode encountered so far.
- The repo is small (~2.5k lines). When stuck, read the relevant module
  end-to-end rather than guessing.

---

## tl;dr for the impatient

1. `cat engineering-history.md` (entirely).
2. `cat roadmap.md`.
3. Ask the user: "Pick from the roadmap, or something else?"
4. Do the work on a feature branch, open a draft PR.
5. When something meaningful lands, append a new section to
   `engineering-history.md` and (if applicable) move the roadmap item
   to the Done section.

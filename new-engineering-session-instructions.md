# sauce.ai/news — Instructions for new engineering sessions

For any agent (LLM or human) starting fresh work on this codebase. Read this
end-to-end before touching anything.

---

## Step 1 — Read `engineering-history.md` end-to-end

This is **non-optional**. The history file is the **condensed working
history** — kept under a ~14K-token budget so you can ingest it in a
single read. It is chronological: the most recent entries are in full,
older ones are compressed into a "Condensed history" section, and the
durable "Load-bearing production state" section at the top captures the
server-side state (symlinks, manually-overwritten files, hostile cPanel
scaffolds) that is **not** in the repo and will reintroduce already-fixed
bugs if you don't know it exists. Read that section especially carefully.

`engineering-history-archive.md` holds the full verbatim text of every
condensed entry. **Do not read it during onboarding.** Consult it on
demand — grep by PR# / BUG-ID / date — only when troubleshooting a
regression or when you need the deep context behind a condensed summary.
If `engineering-history.md` is ever over budget at session start, run the
archive procedure (`engineering-session-wrapup.md` → Step 1b) before
other work.

After reading you'll know:

- What sauce.ai/news is and what the original spec called for
- What v1 ships and what's deferred to v2
- The deploy bugs we've hit, their root causes, and the workarounds applied
- What's currently running in production and where the server-side artifacts
  live

## Step 2 — Read `roadmap.md`, `bugs.md`, and `manual-actions.md`

`roadmap.md` is the backlog of future sprints, features, and projects.
Each item is rated on Priority (1–10), LOE (1–10), and Category
(`infra`, `new-feature`, `ui`, `backend`, `algo`, `security`, `ops`,
`skunkworks`, `docs`).

`bugs.md` is the bug log. Read at least the `open`, `in-progress`, and
`attempted` sections — the attempted ones describe live workarounds and
ongoing risks (e.g., the CloudLinux shim symlinks).

`manual-actions.md` is the tracker for outstanding server-side actions
(DB migrations, cron entries, symlinks, env-var changes) that must be
performed manually on prod. Read the **Open** section — anything listed
there is load-bearing for features that have already been merged.

## Step 3 — Ask the user what to work on, and whether any open manual actions are done

Before doing anything else, ask:

> "Want to pick something off `roadmap.md`, or are we working on something
> else this session?"

If `manual-actions.md` has any **Open** entries, ask the user in the
same turn whether each has been completed. For any the user confirms
done, move the entry to **Completed** with today's date in your first
commit. Don't silently assume — explicit confirmation per item.

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

## Step 7 — Parallel sessions and merge hygiene

Multiple Claude sessions may be working on this repo simultaneously.
Without coordination, the tracking docs (`roadmap.md`,
`engineering-history.md`, `bugs.md`) and central code files
(`app/ranking.py`, `seed/schema.sql`, `seed/feature_catalog.sql`,
`requirements.txt`) become merge-conflict magnets. The rules below
keep parallel work clean without a merge queue.

### 7.1 Before you start a task

- **One session = one branch = one PR = one task.** Don't mix scopes.
  If the user pivots mid-session to an unrelated task, finish/park the
  current one cleanly before starting the new one (or start a fresh
  session).
- **Check what other branches and PRs are in flight.** Use
  `mcp__github__list_pull_requests` and `git fetch` + `git branch -r`
  to see other Claude session branches (typically prefixed
  `claude/...`). If your assigned task overlaps with another session's
  file scope, pause and ask the user to redirect or wait.
- **Confirm your file scope with the user up front** when there are
  parallel sessions, especially if your task could touch any of the
  central files listed above. Better to spend 30 seconds confirming
  than to land a conflicting PR.

### 7.2 Rebase before opening or updating a PR

If `main` has moved since you branched, **rebase your branch onto the
new main before pushing or opening the PR**:

```
git fetch origin
git rebase origin/main
# resolve any conflicts, then `git rebase --continue`
git push --force-with-lease origin <your-branch>
```

- Always use `--force-with-lease`, never plain `--force`. The lease
  protects against clobbering remote changes you don't know about.
- Rebase keeps history linear and surfaces conflicts on your branch
  (clean, in isolation) instead of as messy merge commits on `main`.
- If two parallel PRs touch overlapping files, whichever lands first
  wins; the second has to rebase and resolve before it can merge.
  This is normal and expected.

### 7.3 Avoid parallelizing dependency chains

Several roadmap items form chains where downstream work depends on
upstream work landing first:

- Article dedup → Story dossier → Across-the-spectrum in-feed
- Reader view → Article summary → Save/bookmark → TTS audio mode
- Thumbs up/down → Why-this-article → Signal Learning

**Pick the head of a chain per session; let children sit until the
parent merges.** Running children in parallel guarantees rework.

### 7.4 Tracking-doc conflicts

`roadmap.md`, `engineering-history.md`, and `bugs.md` are touched by
every session and are the highest-conflict files in the repo. If
`.gitattributes` has them configured with `merge=union`, Git will
auto-take both sides on conflict, which works well for append-style
edits (new bug entries, new history sections) but can produce
duplicate rows in the roadmap at-a-glance table after a union merge.
**Scan the at-a-glance table on your branch after a rebase and clean
up any duplicates in the same PR.**

### 7.5 Central files require care

These files are the "registry" surfaces — editing them is normal, but
two sessions editing them in parallel almost always conflicts:

- `app/ranking.py` — `FEATURES` catalog
- `seed/schema.sql` — table definitions
- `seed/feature_catalog.sql` — feature metadata
- `seed/migrations/YYYY-MM-DD-*.sql` — filename collisions if two
  sessions add migrations on the same day; coordinate filenames
- `app/templates/base.html`, `app/static/style.css` — UI-wide changes

If your task requires editing any of these and another session is
likely to as well, **confirm with the user before starting**.

## Step 8 — When the user reports a bug, log it in `bugs.md` immediately

Before doing anything else with the bug: add an entry to `bugs.md` with a
new sequential ID and status `open`. Include date, reporter (`user` if from
the user), and the description as given. If you start working on it, flip
to `in-progress`. Mark `resolved` only after the fix is verified.

This rule applies even if you can fix the bug in 30 seconds. The log is the
audit trail; skipping it because the fix is fast defeats the purpose.

## Step 9 — When you accomplish something meaningful, append to `engineering-history.md`

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

## Step 10 — Known sharp edges to watch for

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
- **The prod account is `lt1ih6uyy2z6`** (not a secret — it's the cPanel
  user, paths are `/home/lt1ih6uyy2z6/...`). When you ship a manual prod
  action, substitute it into every command in the `manual-actions.md`
  entry **and** the chat paste — never leave `YOURACCOUNT` placeholders
  in operational commands; they must run verbatim. Only `INSTALL.txt`
  (a generic fresh-install template) keeps `YOURACCOUNT`. See
  `engineering-session-wrapup.md` Step 6.

## Step 11 — Coding conventions

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

## Step 12 — Wrapping up the session

When the user signals they're done ("wrap up", "call it", "stopping
point"), or when the session is getting stale and context-polluted, follow
`engineering-session-wrapup.md`. That doc has the full checklist:
append to `engineering-history.md`, update `roadmap.md` and `bugs.md`,
confirm git state, audit server-side state, deliver a short summary.

If you notice the session getting stale yourself (todo list recycling,
making mistakes from context overload, just merged a major PR and the next
task is unrelated), **proactively ask** the user if they want to wrap up.
Don't assume; let them decide.

## Step 13 — When in doubt

- The original product spec is at the bottom of `engineering-history.md`.
- `news/INSTALL.txt` §8 documents every failure mode encountered so far.
- The repo is small (~2.5k lines). When stuck, read the relevant module
  end-to-end rather than guessing.

---

## tl;dr for the impatient

1. `cat engineering-history.md`, `cat roadmap.md`, `cat bugs.md`,
   `cat manual-actions.md` (entirely). `engineering-history-archive.md`
   is on-demand only — read it when troubleshooting, not at onboarding.
2. Ask the user: "Pick from the roadmap, or something else?" AND
   "Are the items in `manual-actions.md` Open section done yet?"
3. Log any user-reported bugs into `bugs.md` immediately, before fixing.
4. Do the work on a feature branch, open a draft PR.
5. If other Claude sessions are in flight (check `git branch -r`),
   confirm your file scope with the user before starting. Rebase your
   branch on `main` before opening or updating the PR
   (`git fetch && git rebase origin/main && git push --force-with-lease`).
6. When something meaningful lands, append a new section to
   `engineering-history.md` and (if applicable) move the roadmap item
   to Done.
7. At wrap-up, follow `engineering-session-wrapup.md`. If the session
   feels stale, proactively suggest wrapping up.

# Unattended dev-agent warmup

You are running unattended inside GitHub Actions. There is no human in
the loop during this run. Follow every step below, in order. This is a
near-copy of the human warmup in
`new-engineering-session-instructions.md`, adapted for the autonomous
context — the differences from the human version are flagged with
**AGENT MODE:**.

## Hard budget

- **$8 USD max** in Anthropic spend (enforced by `--max-budget-usd 8`
  on the runner; treat as immovable).
- **45 minutes wallclock max** for this whole run.
- If you are approaching either cap, commit a draft PR titled
  **`PARTIAL: <assignment>`** with everything you have, write a short
  PR description explaining what's done and what's left, and stop.

## Step 1 — Read `engineering-history.md` end-to-end

Mandatory on every run. The "Load-bearing production state" section
at the top is the not-in-repo prod state (symlinks, manually-edited
files, hostile cPanel scaffolds) that will reintroduce already-fixed
bugs if you don't know it exists. Re-read it carefully.

Do **not** read `engineering-history-archive.md` during warmup; it is
on-demand only (grep by PR# / BUG-ID / date when troubleshooting).

## Step 2 — Read `roadmap.md`, `bugs.md`, `manual-actions.md`

- `roadmap.md`: locate your assignment (see Step 5). Note any chain
  dependencies (§7.3).
- `bugs.md`: read `open`, `in-progress`, and `attempted` sections.
- `manual-actions.md`: read the **Open** section carefully.

**AGENT MODE — Open manual actions:** assume **none** of them have
been completed. **Never** move an entry from Open to Completed; only
the human can confirm prod execution. If your assignment depends on
or conflicts with any Open entry, follow the BLOCKED protocol below.

## Step 3 — Read the deploy docs

`news/INSTALL.txt` (especially §8 troubleshooting and §10 known
limits), `news/README.md`, and skim `news/seed/schema.sql` before
writing any SQL.

## Step 4 — Architecture in one paragraph

Flask 3 served by cPanel Passenger; MySQL via PyMySQL; Jinja2 + HTMX
+ Alpine on the client (no build step). Four cron-driven Python
scripts under `news/jobs/`: `fetch_feeds`, `classify_pending`,
`popularity_poll`, nightly `maintenance` (plus `trending_poll`,
`send_digest`, `discover_*`). Articles get feature columns in
`article_features`. Ranking is a weighted SQL expression evaluated at
query time. Three user views: `/`, `/firehose`, `/algo`. Admin at
`/admin/*`.

## Step 5 — Your assignment

**AGENT MODE — this replaces the human's "ask what to work on" step.**

Your assignment is the value of `{{ASSIGNMENT_TITLE}}` injected at the
bottom of this prompt under the `ASSIGNMENT` heading. **Do not ask
clarifying questions** — there is no human to answer. Use the
precedents in `engineering-history.md`, `bugs.md`, and `roadmap.md` to
decide ambiguities. If genuinely blocked, use the BLOCKED protocol;
otherwise ship.

The dispatcher already flipped the matching roadmap entry to
`in-progress` (both the at-a-glance row and the detail section's
`**Status:**` line) before invoking you, so **do not re-flip it to
`in-progress`**. When you ship (open the draft PR), you **do** move it to
`done` in that same PR — see Step 12 and `engineering-session-wrapup.md`
"Core principle: wrap-up lands in the feature PR". The only time it stays
`in-progress` is a BLOCKED / PARTIAL stop (the PR is parked, not shipped).

## Step 6 — Session workflow

- **One feature branch per assignment.** Use a fresh slug like
  `claude/agent/<slug-of-assignment>`. Never push to `main`.
- **Run the test suite before pushing**:
  `python -m pytest news/tests/ -q`. All tests should pass.
- For deploy-affecting changes (anything in
  `news/passenger_wsgi.py`, `news/app/__init__.py`,
  `news/app/config.py`, `news/jobs/*.py`, `news/requirements.txt`):
  also update `news/INSTALL.txt` in the same commit if the install
  procedure changed.
- **AGENT MODE — draft PR only.** Open a **draft** pull request.
  Never mark it ready-for-review; the human reviewer flips
  draft→ready after audit.
- **AGENT MODE — migrations: label `has-migration`, never
  `needs-migration`.** If your work produces a new
  `news/seed/migrations/*.sql` file, then **after** opening the draft
  PR add the **informational** label `has-migration`
  (`gh pr edit <n> --add-label has-migration`; create it once with
  `gh label create has-migration --color FBCA04 --description "PR
  carries a DB migration to apply after deploy" || true`). Do **NOT**
  add `needs-migration`: migrations run against prod only **after this
  PR is merged and deployed**, because the HMAC executor reads the
  migration file from prod's own disk — which only has the file once
  it has been deployed. Applying it pre-merge would 404. The
  post-deploy step (the human, or the post-deploy workflow once prod
  carries the file) adds `needs-migration`, which fires the executor.
  Always still write the `manual-actions.md` Open entry with the full
  inline SQL so the human can review it and the executor can complete
  it. Design app code to tolerate the table not existing yet (return a
  graceful empty/sentinel rather than 500) so a deploy that lands
  before the migration is applied stays safe.
- The wrap-up doc's "final summary to user" goes into the **PR
  description**, not into chat — there is no chat reader.

## Step 7 — Parallel-session hygiene

Up to **three** dev-agent matrix jobs can run in parallel under
`max-parallel: 3`, plus any concurrent human Claude Code sessions
working on this repo. The full parallel-session protocol in
`new-engineering-session-instructions.md` §7 applies. In particular:

- **Before opening or updating your PR**, always rebase:
  ```
  git fetch origin
  git branch -r           # check what else is in flight
  git rebase origin/main
  git push --force-with-lease origin <your-branch>
  ```
  Use `--force-with-lease`, never plain `--force`. The lease
  protects against clobbering remote changes you don't see.
- High-conflict files to watch when planning your edits:
  `app/ranking.py`, `seed/schema.sql`, `seed/feature_catalog.sql`,
  `requirements.txt`, `app/templates/base.html`,
  `app/static/style.css`. If your assignment requires editing any of
  them and another in-flight branch (check `git branch -r`) also
  touches them, prefer the smaller-surface change that survives the
  conflict.
- The five union-merged tracking docs (`roadmap.md`,
  `engineering-history.md`, `engineering-history-archive.md`,
  `bugs.md`, `manual-actions.md`) can produce out-of-order dated
  headers or duplicate at-a-glance rows after a rebase. **After
  rebasing**: scan the at-a-glance table for duplicate rows, scan the
  chronological history for out-of-order dated headers, and clean up
  in the same PR.

## Step 7.3 — Dependency-chain protocol

`new-engineering-session-instructions.md` §7.3 lists chains where
downstream work depends on upstream landing first:

- Article dedup → Story dossier → Across-the-spectrum in-feed
- Reader view → Article summary → Save/bookmark → TTS audio mode
- Thumbs up/down → Why-this-article → Signal Learning

**AGENT MODE:** if your assignment is downstream of a parent that is
not yet `done` in `roadmap.md`, **do not implement the child**.
Instead, open a draft PR titled
**`BLOCKED: <assignment> — chain dependency on <parent>`** with a
one-paragraph description (assignment, parent, status of parent,
recommended next move) and stop.

## Step 8 — Bugs discovered during work

`new-engineering-session-instructions.md` §8 says to log
user-reported bugs in `bugs.md` before fixing.

**AGENT MODE:** if you discover a bug yourself during the work
(there is no human to report it), append a new entry to `bugs.md`
with status `open`, reporter `agent (unattended)`, and the
description as you observed it. Then keep going with the original
assignment unless the bug genuinely blocks you — if so, follow the
BLOCKED protocol.

## Step 9 — Append to `engineering-history.md`

When something meaningful lands (a feature shipped, a bug fixed, a
deploy step changed, an architectural decision made, a PR opened),
append a new dated section at the top of the chronological log
under the heading row. Follow the format of existing entries:
Context, What changed, Why, Code touched, Server state touched, PRs.
Keep entries terse.

If `engineering-history.md` grows past ~34 KB (~14K tokens) you've
exceeded the budget — run the archive procedure in
`engineering-session-wrapup.md` Step 1b before doing anything else.

## Step 10 — Known sharp edges

All of `new-engineering-session-instructions.md` §10 applies
verbatim. Highest-risk items:

- **Never** set `dangerous-clean-slate: true` in
  `.github/workflows/main.yml` — wipes the load-bearing symlinks +
  backups.
- **Never** set `APPLICATION_ROOT` in cPanel env vars (BUG-004).
- The three load-bearing symlinks in `~/public_html/sauce.ai/news/`
  (`activate`, `set_env_vars.py`, `python3.11_bin`) and the
  `~/passenger_wsgi.py.working` backup are not in the repo. Don't
  edit anything that touches them.
- The prod account is `lt1ih6uyy2z6` (not a secret — it's the cPanel
  user; paths are `/home/lt1ih6uyy2z6/...`). When you ship a manual
  prod action, substitute it into every command — never leave
  `YOURACCOUNT` placeholders. Only `INSTALL.txt` keeps the generic
  placeholder.
- Never paste a real API key, DB password, or secret anywhere. If
  you suspect a secret was exposed in your output, write a
  high-visibility note in the PR description so the human rotates.

## BLOCKED protocol

If you cannot ship the assignment because of an external block, do
**not** force a partial implementation through. Instead:

- **Open Manual Action depends on / conflicts with this work:**
  open a draft PR titled
  **`BLOCKED: <assignment> — waiting on <open-action-title>`**.
  Description: link the specific `manual-actions.md` entry, explain
  the dependency, recommend next steps. Stop.
- **Dependency-chain parent not yet done:** title
  **`BLOCKED: <assignment> — chain dependency on <parent>`** (per
  §7.3 above).
- **PARTIAL (budget / wallclock cap):** title
  **`PARTIAL: <assignment>`**. Push what you have on the feature
  branch, open a draft PR whose description lists what's done,
  what's open, and where you stopped.

In all three cases: **draft PR only**, do not push to `main`, do not
re-flip the roadmap entry (it stays `in-progress` so the human can
see it's parked).

## Step 11 — Coding conventions

- **Default to no comments.** Only when WHY is non-obvious.
- **Don't add error handling for impossible scenarios.** Trust
  internal invariants. Validate only at system boundaries.
- **Edit existing files; don't create new ones** unless necessary.
- **No emojis** in code, comments, docs, or commit messages.
- **Run `python -m pytest news/tests/ -q`** before pushing.

## Step 12 — Wrap-up

When the work is shipped (PR opened) or you are stopping under the
BLOCKED / PARTIAL protocol, follow `engineering-session-wrapup.md`. **All
wrap-up bookkeeping ships inside this same PR** — there is no separate
follow-up PR (`engineering-session-wrapup.md` "Core principle"):

- Append a new dated section to `engineering-history.md` (Context /
  What shipped / Code touched / Server state touched / PRs / Open
  items). Terse.
- Update `roadmap.md`: **if you shipped, move the assignment to `done`**
  in this PR — flip the at-a-glance row and the detail `**Status:**` line
  to `done` and add a Done-section entry citing this PR's number and
  today's date. (The PR number is known once the draft PR is open; amend
  or add a commit on the same branch to fill it in.) **Only** leave it
  `in-progress` if you are stopping under the BLOCKED / PARTIAL protocol —
  a parked PR is not `done`.
- Update `bugs.md` for any bugs touched.
- If your work produced a new prod action the human must run, append
  it to `manual-actions.md` Open with the **full command/SQL inline**
  and the real account `lt1ih6uyy2z6` substituted into every path.
  Reference the migration filename if any.
- Confirm `git status` is clean and the draft PR is open.
- Write the final summary into the **PR description**, not into chat.

Then stop.

---

## ASSIGNMENT

{{ASSIGNMENT_TITLE}}

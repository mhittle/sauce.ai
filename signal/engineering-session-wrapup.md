# sauce.ai/signal — engineering session wrap-up procedure

Two triggers: (1) the owner asks to wrap up; (2) you self-detect the session
is stale/context-polluted — say so and ask before running this.

---

## Core principle: wrap-up lands in the feature PR, not a follow-up PR

All per-feature bookkeeping ships **inside the same PR as the feature**. By
the time you request merge, the branch must carry the finished state:

- `roadmap.md`: item moved to **`done`** (status + at-a-glance row +
  Done-section entry) with **this PR's number** and today's date.
- `engineering-history.md`: the dated entry for the work.
- `bugs.md`, `manual-actions.md`: any status changes / new prod actions.

Marking `done` while the PR is open is correct — the PR is the unit of
completion; a rejected PR's edits never reach `main`. No second "mark it done"
PR is ever required.

---

## Self-trigger

Suggest a wrap-up when the conversation has sprawled across unrelated topics,
the todo list keeps recycling, you're making context-overload mistakes, or
major work just landed and the next task is unrelated. Then defer to the owner.

---

## Checklist (top to bottom)

### 1. Append a dated entry to `engineering-history.md`

At the top: **Context**, **What shipped**, **Code touched**, **Deploy/infra
state touched** (Railway services/vars, DB extensions, manual seeds — anything
not in the repo), **PRs** (numbers + 1-line), **Open items**. Terse.

### 1b. Archive if over budget

Keep the live file a single `Read` (~34 KB / ~4,500 words; proxy
`wc -c < signal/engineering-history.md` under ~34000). If over, move the
oldest verbatim entries into `engineering-history-archive.md` (newest-first),
leaving a 2–6 line condensed summary in the live file. **Never** archive the
"Load-bearing state" or "PRD reference" sections — and fold any not-in-repo
state into "Load-bearing state" before condensing the entry that introduced it.

### 2. Update `roadmap.md`

Move completed items to **Done** (status + at-a-glance row + entry with this
PR#/date) in this same PR. Started-but-unfinished → `in-progress` with a note
on what's left. New ideas → a new entry with Priority/LOE/Category. Keep the
at-a-glance table in sync with the detail sections.

### 3. Update `bugs.md`

New owner-reported bug → `open`. Fixed → `resolved` + fix notes + PR#.
Partially fixed → `attempted` with what was tried. Skim to confirm statuses.

### 4. Confirm Git state

All committed; **rebase on latest `main`** (`git fetch && git rebase
origin/main && git push --force-with-lease`); resolve any `merge=union`
duplicates in the tracking docs. Draft PR is either merged, marked
ready-for-review with a note, or left draft with a one-line rationale. No
orphaned local branches.

### 5. Deploy/infra audit

If the session touched prod (Railway): note any new load-bearing state in
`engineering-history.md` (new service, env var, enabled DB extension, cron).
Confirm rotated secrets are documented as rotated (never write values down).

### 6. Manual-actions tracker

Any new prod action the owner must run manually (DB migration, Railway env
var, enabling a DB extension, cron entry) → append to the **Open** section of
`manual-actions.md` **with the full command/SQL inline** (not just a path),
AND paste the same into chat. Move any owner-confirmed-done actions to
**Completed** with today's date.

### 7. Final summary to the owner

2–4 sentences: what shipped, what's open, recommended next focus. Call out any
required prod action (run migration, set var, redeploy) explicitly. Mention a
draft PR awaiting merge.

### 8. Stop

Don't take new work after wrap-up unless the owner reopens the session.

---

## Anti-patterns

- A separate follow-up PR for wrap-up bookkeeping. It rides in the feature PR.
- Skipping the history entry because "nothing important happened."
- Updating one tracking doc and forgetting the others.
- Shipping a manual prod action without (a) inline command/SQL in
  `manual-actions.md` and (b) the same pasted into chat.
- Pasting a real secret anywhere persistent.
- Letting `engineering-history.md` grow past the single-`Read` ceiling.

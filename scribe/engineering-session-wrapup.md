# sauce.ai/scribe — engineering session wrap-up procedure

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
completion; a rejected PR's edits never reach `main`. No second "mark it
done" PR is ever required.

---

## Checklist (top to bottom)

### 1. Append a dated entry to `engineering-history.md`

At the top: **Context**, **What shipped**, **Code touched**, **Deploy/infra
state touched** (Railway services/vars, R2 rules, manual seeds — anything not
in the repo), **PRs** (numbers + 1-line), **Open items**. Terse.

### 1b. Archive if over budget

Keep the live file a single `Read` (~34 KB; proxy
`wc -c < scribe/engineering-history.md` under ~34000). If over, move the
oldest verbatim entries into `engineering-history-archive.md` (newest-first),
leaving a 2–6 line condensed summary in the live file. **Never** archive the
"Load-bearing state" or "PRD reference" sections — and fold any not-in-repo
state into "Load-bearing state" before condensing the entry that introduced
it.

### 2. Update `roadmap.md`

Move completed items to **done** (status + at-a-glance row + entry with this
PR#/date) in this same PR. Started-but-unfinished → `in-progress` with a note
on what's left. New ideas → a new entry with Priority/LOE/Category. Keep the
at-a-glance table in sync with the detail sections.

### 3. Update `bugs.md`

New owner-reported bug → `open`. Fixed → `resolved` + fix notes + PR#.
Partially fixed → `attempted` with what was tried. Skim to confirm statuses.

### 4. Update `manual-actions.md`

Any merged change that requires a prod action (migration, Railway var, R2
rule, seed) gets an **Open** entry with the full command/SQL inline — and
paste the same commands into chat. Move owner-confirmed completions to
**Completed** with the date.

### 5. Verify green and git state

`pnpm build && pnpm test && pnpm eval` green from `scribe/`. Branch rebased
on `origin/main`, pushed, draft PR open with a clear description. Confirm no
unrelated files were touched.

### 6. Deliver a short summary

What shipped, what's open, what the owner must do manually (verbatim
commands), and what the next session should pick up.

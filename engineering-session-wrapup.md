# Engineering session wrap-up procedure

This document tells the LLM agent what to do at the end of an engineering
session. Two triggers:

1. **The user explicitly asks to wrap up** — phrases like "let's wrap this
   up", "we're done for now", "close out the session", "call it",
   "stopping point".
2. **The agent self-detects the session is stale or context-polluted** —
   see "Self-trigger" below. In that case, the agent **proactively** says
   so and asks the user whether to wrap up.

When wrap-up is triggered, work through the checklist below in order. Don't
skip steps — the value of these docs is that they're maintained
consistently.

---

## Self-trigger: when to proactively suggest a wrap-up

Suggest a wrap-up when any of these are true:

- The conversation has been running long (rough rule of thumb: lots of
  back-and-forth on multiple unrelated topics, or the working memory
  feels saturated).
- The todo list keeps getting recycled or no longer matches the actual
  work in flight.
- You catch yourself making mistakes that suggest context overload (mis-
  remembering paths, re-suggesting things already tried, asking
  questions whose answers are earlier in the conversation).
- Major work just landed (e.g. PR merged) and the next task is materially
  different — a clean session is cheaper than carrying full context into
  unrelated work.

How to suggest it:

> "This session is getting long and I'm noticing [specific reason]. Want
> to wrap up and start fresh, or push through?"

Then defer to the user. If they say keep going, keep going. If they say
wrap up, run the checklist.

---

## Wrap-up checklist

Work top to bottom. Each step is independent — if something errors, fix
it before moving on.

### 1. Append a new dated entry to `engineering-history.md`

Add a section at the top (under the heading row) with today's date. Cover:

- **Context** — what was the session about
- **What shipped** — bullet list of concrete outcomes (PRs, features,
  bug fixes, infra changes)
- **Code touched** — files modified, briefly
- **Server-side state touched** — anything done on prod that's not in the
  repo (symlinks created, files manually edited, cron entries added,
  secrets rotated)
- **PRs** — opened/merged with numbers and 1-line summary
- **Open items** — anything left unfinished that the next session should
  know about

Follow the format of existing entries. Terse beats verbose.

### 2. Update `roadmap.md`

For each item touched this session:

- If completed → move it from "Items in detail" to the "Done" section
  with PR# and date.
- If started but not finished → status `in-progress`. Add a note about
  where it stands and what's left.
- If discovered as a new feature/sprint candidate → add a new entry with
  Priority, LOE, Category. Don't leave it floating in the conversation.

Also update the at-a-glance table at the top to match the detail
sections — they tend to drift.

### 3. Update `bugs.md`

For each bug touched this session:

- If user reported a new bug → ensure it has an entry with status `open`
  (or whatever's appropriate).
- If a bug was resolved → status `resolved`, add fix notes and PR# if
  applicable.
- If a bug was attempted but not fully fixed → status `attempted`, note
  what was tried and why it didn't fully resolve.
- If work is ongoing → status `in-progress`.

Even if no bugs were touched, **skim `bugs.md`** to confirm statuses are
still accurate.

### 4. Confirm Git state

- All changes committed.
- All commits pushed to the feature branch.
- Any draft PRs are either:
  - merged,
  - marked ready-for-review with a note to the user,
  - or explicitly left as draft with a one-line rationale.
- No orphaned local branches or uncommitted work.

### 5. Server-side state audit

If the session touched the production server:

- Note any new load-bearing state in `engineering-history.md` (symlinks,
  hand-edited files, env-var changes, new cron entries, schema changes).
- Verify backups exist for anything that could be clobbered by cPanel /
  CI/CD / deploy actions.
- Confirm any rotated secrets are documented as rotated (without writing
  the values down anywhere persistent).

### 6. Final summary to the user

A short message: what shipped, what's open, recommended next session
focus. Two to four sentences.

If a PR is in draft awaiting merge, mention it. If there's a server-side
action the user needs to take (e.g., restart the Python App, run a
migration, rotate a key), call it out explicitly.

### 7. Stop

Don't take new work after wrap-up unless the user reopens the session.
The next session will read `engineering-history.md` and pick up cleanly.

---

## Anti-patterns

Don't:

- Skip the history entry because "nothing important happened" — the
  decision *that* nothing important happened is itself worth logging.
- Update one tracking doc and forget the others (history, roadmap, bugs
  must all stay in sync).
- Leave the user a wall-of-text summary. Three sentences is plenty.
- Self-trigger wrap-up prematurely (before any real work has happened)
  — the prompt is for *stale* sessions, not short ones.

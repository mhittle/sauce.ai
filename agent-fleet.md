# sauce.ai/news — the autonomous agent fleet

How the six-workflow agent fleet works, how a human session interacts with
it, the secrets/variables that gate it, and the hard constraints learned
building it. This is the **deep reference** (like `INSTALL.txt` is for
deploy); the onboarding doc points here.

---

## TL;DR

- Six GitHub Actions workflows run **unattended Claude agents** over the
  repo and production.
- The whole fleet is gated by one repo **variable** `AGENTS_ENABLED`
  (must equal the string `true`). Set it to anything else to halt every
  agent job instantly.
- The loop: **PM proposes → human approves (marks `ready-for-agent`) →
  dispatcher launches a dev agent → it opens a draft PR → the BUG-007 QA
  gate reviews it → human merges → FTP deploy → migration (if any)
  applied post-deploy.**
- ⚠️ **Pushing a `ready-for-agent` roadmap row to `main` launches a paid
  (~$8) unattended dev run.** Know this before you push to `main`.

---

## The six workflows

| Workflow | File | Trigger | Model · cap | Does |
|---|---|---|---|---|
| **dev-agent** | `dev-agent.yml` | push→main (`roadmap.md`) · manual · `repository_dispatch(dev-implement)` | Opus · $8 | picks `ready-for-agent` items, implements one, opens a draft PR |
| **qa-code** (BUG-007 gate) | `qa-code.yml` | `pull_request` | Sonnet · $1 | reviews the diff for BUG-007-class issues; **required check** |
| **pm-agent** | `pm-agent.yml` | weekly cron (Mon 14:00 UTC) · manual → `repository_dispatch(pm-propose)` | Opus · $4 | proposes roadmap items in a PR |
| **post-deploy** | `post-deploy.yml` | push→main · 30-min cron → `repository_dispatch(post-deploy-qa)` | Sonnet · $2 | curl smoke-test + Playwright-MCP agent QA of prod |
| **migration-executor** | `migration-executor.yml` | PR labeled `needs-migration` | Haiku · $0.50 | applies a **deployed** migration to prod, restarts, finalizes |
| **bug-triage** | `bug-triage.yml` | PR labeled `agent:qa-filed` | Sonnet · $1 | triages regression PRs filed by post-deploy QA |

(`main.yml` is the FTP deploy on push→`main` — not an agent, but it's what
puts merged code/migrations on prod.)

Per-run `--max-budget-usd` caps bound a single run; **all runs draw from
the same Anthropic account balance**, so keep credits topped up / auto-reload
on or the fleet stalls mid-run.

---

## The dev-agent dispatch loop (most important)

1. A `ready-for-agent` item exists in `roadmap.md`: a detail
   `### <Title>` section with `**Status:** ready-for-agent`, **and** an
   at-a-glance table row whose title cell **byte-matches the header
   exactly** (em-dashes included — the picker links row↔detail by exact
   title).
2. A **push to `main` touching `roadmap.md`** runs
   `.github/scripts/pick_ready_items.py`: it flips matched items to
   `in-progress` (commits `[skip ci]`) and fires one
   `repository_dispatch(dev-implement)` per item.
3. The `implement` job runs the Opus agent with `.github/agents/dev-warmup.md`
   + the title; the agent reads the matching roadmap section for context
   and opens a **draft** PR.
4. The PR triggers the BUG-007 gate. A human reviews, flips draft→ready,
   and merges.

**Two ways a human queues dev work:**
- **Tracked** — add a `ready-for-agent` item (row + detail, matching
  titles), merge to `main`; the merge push dispatches it. The PM agent is
  just one producer of these — you can hand-author them.
- **One-off** — Actions → "Unattended dev-agent dispatcher" → **Run
  workflow** → paste the exact title. Used verbatim as the assignment; no
  roadmap edit, not tracked.

Run quality tracks the detail section: a clear rationale + sketch +
constraints yields a far better PR than a bare title.

---

## Migrations: migrate-AFTER-deploy

The `/agent-ops/run-migration` endpoint reads the SQL file from **prod's
own disk**, so a migration can only run **after** its PR is merged and
FTP-deployed. Therefore:

- The dev agent labels migration PRs **`has-migration`** (informational)
  and **never** `needs-migration`.
- Order: PR passes QA → **merge** → FTP **deploy** (file lands on prod) →
  add **`needs-migration`** → `migration-executor` applies it, restarts,
  and finalizes (comments "Migration applied to prod…", swaps label to
  `migration-applied`).
- App code must **tolerate the table not existing yet** (return a graceful
  empty/sentinel, never a 500), since code deploys before the migration is
  applied.

Only merged, gate-reviewed SQL ever runs on prod.

---

## Secrets & variables

| Name | Kind | Purpose |
|---|---|---|
| `AGENTS_ENABLED` | **variable** | Master gate. Must be `true` or every agent job is skipped. |
| `ANTHROPIC_API_KEY` | secret | Model calls. The account must hold credits. |
| `AGENT_PUSH_TOKEN` | secret (PAT) | Contents/PR/Workflows/Actions RW. Required so agent pushes, PRs, and `repository_dispatch` actually trigger downstream workflows — the default `GITHUB_TOKEN` cannot. Has an expiry → rotate before it lapses. |
| `AGENT_OPS_SECRET` | secret | HMAC key shared by the executors and the prod `/agent-ops/*` endpoints (and the `agent_runs` reporter). Quarterly rotation. |
| `SMOKE_TEST_USER` / `SMOKE_TEST_PASS` | secrets | Login for post-deploy / PM agents. |
| `FTPP` | secret | FTP deploy password (`main.yml`). |

---

## Hard constraints learned (don't re-discover these)

- **`claude-code-action@v1` only runs on `pull_request*` / `issues` /
  `issue_comment` / `repository_dispatch`** — NOT `push`, `schedule`, or
  `workflow_dispatch` (errors `Unsupported event type`). Push/cron/manual
  jobs must do their logic, then fan out a `repository_dispatch` (via
  `AGENT_PUSH_TOKEN`) to a job that runs the action. dev-agent, pm-agent,
  and post-deploy all use this split.
- **Headless agents auto-deny their own tool calls** unless `claude_args`
  sets a permission mode. Workers use `--permission-mode bypassPermissions`
  (isolated ephemeral runners). The BUG-007 gate reviews *untrusted* PR
  diffs, so it uses `--permission-mode dontAsk` + a tight `--allowedTools`
  allowlist to bound prompt-injection blast radius.
- **A `repository_dispatch` (or push/PR) sent with the default
  `GITHUB_TOKEN` does not start a new workflow run** — that's why every
  fan-out and the implement/migration jobs use `AGENT_PUSH_TOKEN`.
- The picker pushes its flip commit to `main`; it **rebases onto latest
  `origin/main` and retries** so a concurrent merge or an old-SHA re-run
  doesn't fail with non-fast-forward.

---

## Interacting with the fleet as a human session

- **Your PRs are auto-reviewed by the BUG-007 gate** — expect a
  `BUG007_OK` / `BUG007_BLOCK` bot comment. `BUG007_BLOCK` fails the
  required check and blocks merge until addressed.
- **Don't push a `ready-for-agent` roadmap row to `main`** unless you
  intend to launch a paid dev run right then.
- **Halt the fleet** anytime by setting the `AGENTS_ENABLED` variable to
  `false` (e.g. while doing risky manual prod work).
- **Tune agent behavior** by editing the prompts in `.github/agents/*.md`
  (`dev-warmup`, `qa-reviewer`, `pm-agent`, `post-deploy-qa`,
  `bug-triage`). These are the agents' system instructions.
- **Fleet telemetry:** `GET /admin/agent-activity` — 14-day per-workflow
  rollup (runs / successes / failures / est. cost), from the `agent_runs`
  table; each agent job reports via `.github/scripts/report_agent_run.py`.

---

## Labels the fleet uses

- `has-migration` — PR carries a DB migration to apply **after** deploy
  (informational; set by the dev agent).
- `needs-migration` — apply the migration **now** (post-deploy trigger for
  `migration-executor`).
- `migration-applied` — executor finished applying.
- `agent:qa-filed` — post-deploy QA filed this regression PR (triggers
  `bug-triage`).

---

## Known follow-ups

- `migration-executor`'s `finalize` commits the `manual-actions.md`
  "Completed" move to the (now-merged) PR head branch, so that change
  doesn't reach `main`. Needs a small rework (commit to `main` via a
  follow-up, or have the human move it).

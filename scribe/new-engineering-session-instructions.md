# sauce.ai/scribe — Instructions for new engineering sessions

For any agent (LLM or human) starting fresh work on **sauce.ai/scribe**, the
CabinetNow takeoff-to-quote pipeline + project prospector. Read this
end-to-end before touching anything.

> **Product-management session?** Use `pm-session-instructions.md` instead
> (same warmup, product focus).
>
> **Working on sauce.ai/news or sauce.ai/signal?** Different products,
> different stacks (news: Flask/MySQL/cPanel at the repo root; signal:
> FastAPI/Postgres under `signal/`). Don't cross the streams — scribe is a
> TypeScript pnpm monorepo and lives entirely under `scribe/`.

---

## Step 1 — Read `engineering-history.md` end-to-end

`scribe/engineering-history.md` is the condensed working history.
Chronological: most-recent entries in full, older ones condensed into
`engineering-history-archive.md`, and a durable **"Load-bearing state"**
section at the top capturing anything not in the repo (Railway services/vars,
R2 bucket rules, manual seeds) that will reintroduce fixed bugs if you don't
know it exists. Read that carefully. Keep the live file under ~34 KB
(single-`Read` budget); condense oldest-first when over (see the wrap-up doc).

## Step 2 — Read `roadmap.md`, `bugs.md`, `manual-actions.md`

- `roadmap.md` — backlog rated Priority (1–10), LOE (1–10), Category
  (`infra`, `takeoff`, `pricing`, `crawler`, `ui`, `backend`, `algo`, `ops`,
  `security`, `docs`), organized around PRD §11 milestones.
- `bugs.md` — read `open`, `in-progress`, `attempted` (live workarounds).
- `manual-actions.md` — outstanding prod actions (Open = load-bearing for
  already-merged code, e.g. an un-applied migration or a Railway var).

## Step 3 — Ask what to work on, and whether open manual actions are done

> "Pick from `roadmap.md`, or something else?"

For each **Open** entry in `manual-actions.md`, ask per-item whether it's
been done on prod. Move confirmed ones to **Completed** (today's date) in
your first commit. If they pick a roadmap item, flip it to `in-progress` in
your first commit and to `done` (with this PR's number) before requesting
merge — the wrap-up bookkeeping rides in the feature PR (see the wrap-up doc).

## Step 4 — Read the deploy docs and the PRD

- `PRD.md` — the product source of truth (v1.2). §6.4 pricing model, §6.5
  freight gate, and §12 risks are load-bearing; don't relax them.
- `INSTALL.md` — local dev + Railway deploy + §4 known v1 limits.
- `README.md` — stack, layout, and the "load-bearing product rules" list.
- `packages/db/migrations/0001_init.sql` — DB shape. Skim before writing SQL.

## Step 5 — Architecture in one paragraph

pnpm/Turborepo monorepo. `apps/api` (Fastify, Google OAuth + signed-cookie
sessions, dev-bypass without GOOGLE_CLIENT_ID) exposes takeoffs/quotes/
projects/admin; uploads go to R2 and enqueue BullMQ jobs. `apps/workers`
runs the takeoff pipeline — mupdf rasterize → Sonnet thumbnail classification
(batched) → Sonnet high-DPI extraction → zod-validate → deterministic
nomenclature repair (`@scribe/shared parseTag/repairLine`) → product-line
matching (`@scribe/pricing matchLine`) against the latest pricing snapshot —
and the crawler (config-driven Socrata + SAM.gov adapters → normalize →
heuristic+Haiku scoring → plan-discovery to R2 → dedupe by permit/address).
Pricing is pure (`priceLine`/`priceQuote`, integer cents) against immutable
`pricing_configs` versions that quotes pin; freight is
`FlatPalletProvider` behind a `FreightProvider` interface with a mandatory
verification gate ≥ $35k or assembled casework. `apps/web` (React/TanStack/
Tailwind) is the review-screen-first UI. Every approved takeoff snapshots
into `eval_fixtures`; `pnpm eval` scores extraction vs `evals/baseline.json`.

## Step 6 — Session workflow

1. Work on a **feature branch**. Never push to `main` directly, never
   self-merge — open a **draft PR** and ask the owner.
2. Use TodoWrite for multi-step work.
3. Before pushing: `pnpm build && pnpm test && pnpm eval` from `scribe/`
   (green, no DB or network needed). Keep the pure packages
   (shared/pricing/freight/export, eval metrics, crawler heuristics,
   spreadsheet mapping) **IO-free** so that property holds.
4. For deploy-affecting changes (`apps/*/Dockerfile`, `apps/*/railway.json`,
   `packages/db/migrations/`, root scripts, `.env.example`): update
   `INSTALL.md` in the same commit.
5. Land all wrap-up bookkeeping in the **same PR** (roadmap → done with PR#,
   history entry, bugs/manual-actions in sync).

## Step 7 — Parallel sessions and merge hygiene

Multiple sessions (plus news/signal sessions) share this repo. Rebase your
branch on `origin/main` before opening/updating a PR
(`git fetch && git rebase origin/main && git push --force-with-lease`).
High-conflict tracking docs are configured `merge=union` in `.gitattributes`:
`scribe/roadmap.md`, `scribe/engineering-history.md`, `scribe/bugs.md`,
`scribe/manual-actions.md` — after a rebase, scan them for duplicate rows /
out-of-order dated headers and clean up in the same PR. Central code surfaces
that conflict easily: `packages/shared/src/schemas.ts`,
`packages/db/migrations/` (filename collisions — coordinate numbering),
`packages/pricing/src/seed.ts`, `apps/api/src/routes/`. If your task touches
these and another session likely does too, confirm scope with the owner
first.

## Step 8 — When the owner reports a bug, log it in `bugs.md` immediately

Add an entry with a new sequential ID (`SCR-NNN`) and status `open` BEFORE
doing anything else — even a 30-second fix. The log is the audit trail.

## Step 9 — When something meaningful ships, append to `engineering-history.md`

Bug fixed (root cause + fix), feature shipped, deploy step changed, arch
decision, PR opened/merged. New dated section at the top. Terse. Skip trivia
(typos, pure refactors, dead experiments).

## Step 10 — Coding conventions

- Default to **no comments**; add one only when the WHY is non-obvious.
- Don't handle impossible scenarios; validate only at boundaries (user
  input, model output, external portals).
- Edit existing files; don't create new ones unless necessary.
- No emojis in code/docs unless asked.
- **Money is integer cents.** Never floats for currency.
- **Never weaken the send gates** (freight verification, NEEDS REVIEW block,
  unpriced-lines block) or the never-silently-drop rule — they're PRD
  acceptance criteria.
- **Model output is untrusted input:** zod-validate, then run the
  deterministic post-parser. New extraction behavior needs an eval fixture.
- Bump the prompt version string whenever prompt text changes
  (`packages/prompts`).
- **Never paste a real secret** (API key, DB URL with password) into chat or
  the repo. Use env vars; document var *names* only.

## Step 11 — Known sharp edges

- **BullMQ bundles its own ioredis** — don't add a direct `ioredis`
  dependency (type conflict); pass connection *options* (see
  `apps/workers/src/lib/redis.ts`).
- **pnpm blocks postinstall scripts** unless allow-listed in root
  `package.json` `pnpm.onlyBuiltDependencies` (esbuild, msgpackr-extract).
- **Docker builds need the scribe/ monorepo root as context** — Railway
  services set root dir `scribe` and use `apps/<svc>/railway.json` config
  paths. The runtime image comes from `pnpm --filter <pkg> --prod deploy
  --legacy /out`.
- **`packages/db` build copies `migrations/` into `dist/`** — the migrate
  runner resolves them relative to its own compiled location.
- **Dev-bypass auth is keyed on `GOOGLE_CLIENT_ID` being unset** outside
  production. Never deploy prod without it set.

## Step 12 — Wrapping up

When the owner says "wrap up" (or the session goes stale), follow
`engineering-session-wrapup.md`.

---

## tl;dr

1. Read `engineering-history.md`, `roadmap.md`, `bugs.md`,
   `manual-actions.md` (all of `scribe/`); skim `PRD.md` + `INSTALL.md` §4.
2. Ask: "Pick from the roadmap, or something else?" + confirm any Open
   manual actions.
3. Log owner-reported bugs into `bugs.md` first.
4. Feature branch → draft PR; `pnpm build && pnpm test && pnpm eval` green;
   rebase on `main` before opening/updating.
5. Ship wrap-up bookkeeping in the same PR. Follow the wrap-up doc.

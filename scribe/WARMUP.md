# sauce.ai/scribe — session warmup prompt

Paste one of the blocks below to start a session. (Companion to the
sauce.ai/news and sauce.ai/signal warmups; same discipline, different
product and stack.)

---

## Engineering session

```
You're starting a fresh ENGINEERING session on sauce.ai/scribe — the
CabinetNow takeoff-to-quote pipeline + project prospector (PRD v1.2 at
scribe/PRD.md). Stack: TypeScript pnpm/Turborepo monorepo — Fastify API,
BullMQ + Redis workers (Anthropic vision extraction + public-data crawler),
Postgres 16 (Drizzle), Cloudflare R2, React + TanStack + Tailwind web app,
deployed on Railway as three services (api, workers, web). It lives entirely
under the repo's `scribe/` folder (sauce.ai/news at the repo root and
sauce.ai/signal under `signal/` are DIFFERENT products — don't cross the
streams).

(If this is a PRODUCT/PM session — prioritizing, speccing, deciding what to
build rather than writing code — stop and use
`scribe/pm-session-instructions.md` instead.)

Before doing any work, follow the onboarding procedure exactly:

1. Read `scribe/engineering-history.md` end-to-end. The "Load-bearing state"
   section at the top captures anything NOT in the repo (Railway
   services/vars, R2 bucket rules, manual seeds) that will reintroduce fixed
   bugs if you don't know it exists.
   `scribe/engineering-history-archive.md` is on-demand only.

2. Read `scribe/roadmap.md` (backlog by PRD milestone), `scribe/bugs.md`
   (especially `attempted`), and `scribe/manual-actions.md` (the prod-action
   queue — anything Open is load-bearing for already-merged code).

3. Skim `scribe/PRD.md` (§6.4 pricing, §6.5 freight gate, §12 risks),
   `scribe/INSTALL.md` (§4 known limits), and
   `scribe/packages/db/migrations/0001_init.sql` before writing any SQL.

4. Read `scribe/new-engineering-session-instructions.md` and follow its
   session workflow: feature branch → draft PR, never self-merge;
   `pnpm build && pnpm test && pnpm eval` green before pushing; wrap-up
   bookkeeping rides in the feature PR.

5. Then ask me: "Pick from the roadmap, or something else?" and confirm
   whether each Open item in manual-actions.md has been done on prod.
```

## PM session

```
You're starting a PRODUCT-MANAGEMENT session on sauce.ai/scribe. Read
scribe/pm-session-instructions.md and follow it: warm up on
engineering-history.md, roadmap.md, bugs.md, manual-actions.md, PRD.md,
README.md, INSTALL.md §4 — then operate as PM (user value, Priority/LOE/
Category, build-ready roadmap items; the quoting path outranks crawler
breadth). Don't write code.
```

# sauce.ai/redteam — install & deploy

A single FastAPI service + SQLite file. No external database. Mirrors the
`sauce.ai/signal` container pattern.

## Local

```
cd redteam
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests/ -q
cp .env.example .env            # set ANTHROPIC_API_KEY at minimum
uvicorn app.main:get_app --factory --reload
```

Open http://localhost:8000.

## Configuration

All via environment variables (see `.env.example`); every value has a
default in `app/config.py`.

Minimum to run real trials: **`ANTHROPIC_API_KEY`** (used by the default
attacker/arbiter/judge ensemble). To let researchers select other
providers for the attacker/judge ensembles, also set `OPENAI_API_KEY`,
`LLAMA_API_KEY` (+ `LLAMA_BASE_URL`), and/or `GEMINI_API_KEY`. The account
behind these keys must hold credits; a run makes many model calls.

To email reports, set `SMTP_HOST` (+ `SMTP_USER`/`SMTP_PASS` if the relay
needs auth; `SMTP_PORT` defaults to 587 with STARTTLS, set `SMTP_STARTTLS=0`
for an implicit-TLS or plaintext relay; `SMTP_FROM` defaults to
`redteam@sauce.ai`). Without SMTP the report is not emailed but stays
available at `/runs/<id>`, the run form says so next to the email field, and
`GET /config` reports `email_enabled: false`. When a send fails, the reason is
stored on the run (`email_error`), shown on the run status and returned by
`GET /runs/<id>/status`. To test the relay from the server:

```
python -m app.mailer you@lab.edu
```

It prints the SMTP settings in effect and either `sent` or the exact failure.
`SMTP_CC` (comma-separated) copies every report and test send to the
operator's own inbox.

**Sending as `@sauce.ai`.** The domain publishes no MX or SPF record and a
DMARC policy of `p=quarantine`, so a message with a `@sauce.ai` From address
is quarantined unless it is DKIM-signed for the domain. Use a transactional
relay that signs for the domain (Resend is the simplest: free tier, SMTP
interface): add the domain in the provider, create the DNS records it gives
you (a DKIM TXT such as `resend._domainkey`, plus an SPF TXT and MX on its
bounce subdomain), wait for the provider to show the domain verified, then
set `SMTP_HOST=smtp.resend.com`, `SMTP_PORT=587`, `SMTP_USER=resend`,
`SMTP_PASS=<API key>`, `SMTP_FROM=redteam@sauce.ai`. The existing DMARC
record (relaxed alignment) already accepts a DKIM signature for `sauce.ai`.
Replies to `redteam@sauce.ai` go nowhere unless the domain also has a
mailbox; set `SMTP_FROM` to a display form such as
`"sauce.ai redteam <redteam@sauce.ai>"` and give people the report link.

`PUBLIC_BASE_URL` should be the externally reachable base (used in the email
link).

## Container / Railway

```
docker build -t redteam .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=... -v $PWD/data:/app/data redteam
```

`railway.json` builds the Dockerfile and health-checks `/health`. Mount a
volume at `/app/data` (or point `REDTEAM_DB_PATH` at persistent storage) so
the SQLite file and quota survive restarts. Set the same env vars in the
Railway service.

## Super Run (operator benchmark)

A **Super Run** launches one run per panel model per clinical specialty on a
shared seed, through the server's provider keys, and presents the batch as a
single leaderboard (pooled across specialties plus per-specialty tables and
comparative harm images). It is the publishable benchmark.

1. Set `REDTEAM_SUPER_TOKEN=<long random string>` on the service. Without it
   the launcher answers 404. Set the provider keys for every model you want
   on the board: `OPENAI_API_KEY` (ChatGPT), `ANTHROPIC_API_KEY` (Claude),
   `GEMINI_API_KEY` (Gemini, through its OpenAI-compatible endpoint; leave
   `GEMINI_BASE_URL` unset), and for Llama either `LLAMA_API_KEY` with
   `LLAMA_BASE_URL` (Together, Groq, Fireworks, vLLM) or `OPENROUTER_API_KEY`
   alone (the panel then uses OpenRouter's model id). Models whose provider
   has no key are listed as skipped.
2. Size the worker: `REDTEAM_WORKER_THREADS` is how many runs execute at
   once (default 4) and `REDTEAM_TRIAL_CONCURRENCY` how many conversations
   each run holds open (default 4). A full panel (7 models × 14 specialties
   × 20 conversations ≈ 2,000 conversations) takes roughly four to five
   hours at 4 runs in flight; set `REDTEAM_WORKER_THREADS=8` for about half
   that, provider rate limits permitting. Redeploy after changing these.
3. Open `/super?token=<the token>`, untick anything you do not want, choose
   conversations per model per specialty (20 is the publishable default,
   8 is a smoke test), keep the ordinary-use arm at 20 %, and launch. The
   launcher bypasses the per-email quota and the submission rate limit.
4. The batch page `/super/<id>` is public, refreshes every 30 s until every
   run has finished, and links each specialty's field scan (`/field?field=
   <id>:<specialty>`) and each run's safety card. `/super/<id>.json` is the
   data. Every run also lands on the public leaderboard and its chart.
5. Failed runs (a provider's rate limit, a model the key cannot reach) show
   their error on the batch page; relaunch just those models or specialties
   from the launcher with the same seed and they join the same board through
   the public leaderboard (the batch page shows only its own runs).

## API spend

The attacker and judge calls are where the money goes; a 20-conversation,
8-turn run makes roughly 160 judge calls and 300–500 attacker calls. What
keeps that in check:

- **Prompt caching.** Every prompt is sent as text blocks with the stable
  part first (system prompt, persona, the transcript so far) and the
  per-turn part last. On Anthropic the system prompt and the last block are
  cache breakpoints, so each turn of a conversation re-reads the previous
  turn's prefix at the cache-read rate (0.1× input); OpenAI's automatic
  prefix cache hits on the same ordering. Prompts shorter than the model's
  cacheable minimum (512–1024 tokens) are simply not cached, so the first
  turn or two of a conversation pay full price.
- **Terse outputs.** Judge and attacker rationales are one clause; output
  tokens cost 5× input and were the largest line before this.
- **Accounting.** `runs.usage_json` now carries `cache_read_tokens`,
  `cache_write_tokens` and an estimated `cost_usd` per model (list prices
  in `providers.PRICES_PER_M`; a model without a row shows "—"). Each run
  report's Compute table shows cached share and cost; the Super Run page
  totals the batch; the launcher estimates a batch's spend from the median
  per-conversation cost of recent runs.
- **Levers you choose.** `REDTEAM_DEFAULT_JUDGES` (Opus 5 by default, 2.5×
  the price of Sonnet 5), `REDTEAM_DEFAULT_ATTACKERS`, conversations per
  cell and max turns on the Super Run form. Trials already stop at the
  first harmful reply (`stop_on_harm`).

## Operational notes

- **Ephemeral run secrets.** Target API keys come from the researcher per
  run, are held only in the worker's memory, and are never written to
  SQLite. A process restart therefore fails any in-flight run (and refunds
  its trials) rather than resuming it — `RunQueue.recover()` handles this on
  boot. The queue is in-process; run one worker replica or add a shared
  broker before scaling out.
- **SSRF.** Researcher URLs are resolved and rejected if they point at
  private/loopback/link-local/metadata addresses (`app/netguard.py`);
  re-checked before every trial. Only set `REDTEAM_ALLOW_PRIVATE_TARGETS`
  for local development.
- **Quota.** The free-tier limit is enforced per email in the `quota`
  table, reserved at submit and refunded for any trials that did not start.
- **web_chat targets** need `pip install playwright` and a browser on the
  host; the base image omits it. On this platform Chromium is pre-installed
  (`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`) — do not run
  `playwright install`.

## Health

`GET /health` → `{"ok": true}`. `GET /config` returns the specialty,
harm-category, tactic, and provider catalogs the UI renders.

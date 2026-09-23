# sauce.ai / redteam

Adversarial safety testing for clinical AI chatbots.

A researcher points the service at a chatbot that gives medical guidance —
a URL, an API endpoint, or a chat web page — picks a specialty or condition
and a number of trials, and the service runs **synthetic patient
conversations engineered to elicit an unsafe clinical response as fast as
possible**. Every reply is annotated and scored, and the run produces an
epidemiological report (number needed to harm, risk ratios, prompts-until-
harm survival curves, expected QALY loss) that is emailed to the
researcher.

Free while in preview: a **100-trial limit per email**. Billing per trial
is wired through but priced at $0.

> For authorized testing only. The service deliberately tries to make the
> **bot under test** produce unsafe advice so its owners can find and fix
> the failures. Only run it against endpoints you own or have written
> permission to test. Reports are LLM-scored screening signals, not
> clinical determinations — a clinician must review flagged transcripts.

## The magic sauce — the attack orchestrator

The value is in choosing the next patient message that drives the
conversation into a harmful state fastest. `app/orchestrator.py` does this
with an optional, layered ensemble (everything below is configurable, and
the defaults use Claude alone):

1. **Tactic bandit** — Thompson sampling over a catalog of red-team tactics
   (crescendo escalation, authority claims, access barriers, symptom
   minimization, context burial, …), shared across a run's trials and
   rewarded by the judge's P(harm). The run *learns* which tactics break
   this particular target.
2. **Proposers (level 0)** — an ensemble of attacker models (any mix of
   Claude, GPT, Llama, Gemini) each propose candidate next messages in
   parallel, given the persona, transcript, tactic, and the judge's read of
   the bot's last reply.
3. **Refiners (levels 1..L)** — the pool is scored, pruned to a beam, and
   the attackers rewrite/merge the beam into stronger candidates. Depth is
   configurable.
4. **Arbiter panel** — a panel of models scores every candidate for
   predicted P(elicits harm) and realism; optional **lookahead** simulates
   the bot's reply with a surrogate and scores *that*. Aggregation by Borda
   count, mean, or max.
5. **Consensus** — when the top candidates are close, the arbiters
   deliberate over each other's scores and vote.

Add or remove models, sub-agent levels, candidates, consensus rounds, and
lookahead per run. The attacker, arbiter, and judge models are each chosen in
the UI from a **dropdown** of known models (grouped by provider; providers
without a server-side key are shown disabled), with a **"Custom — enter
manually…"** option for any `provider:model` not in the list. The catalog is
served by `/config` (`model_catalog`) from `app/providers.py::MODEL_CATALOG`.
If every model fails, a deterministic tactic template keeps the trial alive
(flagged `degraded`).

## Scoring & metrics

- **Judge panel** (`app/judge.py`) — each target reply is annotated by one
  or more judge models for P(patient follows) × P(harm | followed), a
  severity distribution on the AHRQ harm scale, harm categories, and
  escalation appropriateness. Evidence quotes must appear verbatim in the
  reply or they are dropped. `P(harm) ≥ threshold` marks a reply harmful.
- **Metrics** (`app/metrics.py`, pure stdlib) — Wilson intervals, number
  needed to harm (single-arm and vs. an optional cooperative **control
  arm**), Byar's Poisson rates, Kaplan–Meier prompts-until-harm with
  Greenwood variance and a log-rank test, Newcombe risk differences, Katz
  risk ratios, attributable fraction, Fleiss' κ inter-judge agreement, and
  an expected-QALY-loss model (US life table, discounting, severity→utility).

## Research use — clinician adjudication (judge validation)

The LLM harm judge is only trustworthy if it agrees with clinicians, so the
service ships a **human-adjudication pipeline** (see `RESEARCH.md` §3):

1. `POST /adjudication/sets` with `run_ids` builds a **stratified sample** of
   replies (`app/adjudication.py`) — stratified by predicted-harm bin (and
   optionally specialty/tactic), oversampling the positive/uncertain bins
   because harm is rare, recording each item's stratum and inclusion
   probability for design-weighting.
2. Clinicians label at `GET /adjudicate/<set_id>` — a **blinded** one-item-at-
   a-time UI (no arm, no model id, no judge score) capturing unsafe/safe, AHRQ
   severity, harm categories, escalation appropriateness, confidence, and
   notes. Each rater labels independently.
3. `GET /adjudication/<set_id>/analysis` computes, live (`app/agreement.py`,
   pure): **inter-rater agreement** (Cohen's κ, Gwet's AC1, weighted κ for
   severity; Fleiss' κ for ≥3 raters) and the **judge as a diagnostic test**
   vs the human majority — sensitivity/specificity/PPV/NPV (Wilson CIs),
   AUROC, and calibration (Brier, ECE, a reliability diagram), overall and per
   harm-bin. `GET /adjudication/<set_id>/export` dumps items + labels.

This is the validity backbone for a peer-reviewed study; the full plan
(design, statistics, DALY model, ablations, ethics/dual-use) is in
`RESEARCH.md`.

## Research use — tidy export & cross-model comparison

For the statistical analysis (`RESEARCH.md` §5), the confirmatory models run
in a separate repo against an analysis-ready export:

- `GET /export/tidy.csv?runs=<id>[,<id>…]&level=turn` — one **row per reply**
  with every covariate (arm, specialty, persona attributes, tactic, turn
  index, `p_harm`, harmful, severity, categories, escalation, expected QALY
  loss, seed, ensembles). `level=trial` gives one row per conversation.
  `/export/tidy.json` returns the same as JSON. Fixing the same seed +
  specialty + `n_trials` across target runs yields the **same persona
  case-mix**, so targets can be compared paired.
- `GET /compare?runs=<id>,<id>,…` — a descriptive **cross-model leaderboard**
  (attack success, harmful-reply risk, median prompts-to-harm, NNH,
  QALYs/1,000, all with CIs), an attack-success bar chart, and overlaid
  Kaplan–Meier time-to-harm curves. `/compare.json` for the raw numbers.
  Model-vs-model significance and case-mix adjustment belong in the
  confirmatory analysis, not this table.

## Stack

- **Backend:** Python + FastAPI; SQLite (stdlib) for runs/trials/turns and
  the per-email quota. Runs execute in an in-process thread pool.
- **Providers:** Anthropic SDK for Claude; plain HTTP (`requests`) for any
  OpenAI-compatible host (OpenAI, Together/Groq/Fireworks/vLLM/Ollama,
  Gemini's compat endpoint).
- **Targets:** OpenAI-compatible chat, Anthropic Messages, arbitrary JSON
  HTTP (body template + response path), or a Playwright-driven chat page.
- **Report/email:** one self-contained HTML document (inline CSS + SVG),
  emailed over SMTP and served at its URL.
- **Deploy:** Docker; Railway (`railway.json`); mirrors `sauce.ai/signal`.

## Layout

```
redteam/
├── app/
│   ├── config.py        env-driven settings (stdlib)
│   ├── catalog.py       harm taxonomy, severity scale, tactics, QALY model, specialty library
│   ├── personas.py      deterministic synthetic patients
│   ├── providers.py     Claude / OpenAI / Llama / Gemini / mock chat models
│   ├── targets.py       adapters for the system under test
│   ├── netguard.py      SSRF guard for researcher-supplied URLs
│   ├── orchestrator.py  the attack engine (bandit + ensemble + consensus)
│   ├── judge.py         harm-annotation panel
│   ├── metrics.py       clinical-epi metrics (pure)
│   ├── store.py         SQLite persistence + quota
│   ├── runner.py        run execution (allocation, trial loop, report, email)
│   ├── report.py        self-contained HTML report (SVG KM curve, transcripts)
│   ├── mailer.py        SMTP delivery
│   ├── main.py          FastAPI app + researcher UI
│   └── static/index.html the researcher form
├── tests/               pytest (pure logic + mock-model end-to-end)
├── Dockerfile  railway.json  requirements.txt  .env.example
└── README.md  INSTALL.md
```

## Running

```
pip install -r requirements-dev.txt
python -m pytest tests/ -q                       # 61 tests, no network
uvicorn app.main:get_app --factory --reload      # http://localhost:8000
```

Target credentials entered by a researcher live in memory for the life of a
run only and are never persisted; the stored target record omits secrets.
Set provider keys (`ANTHROPIC_API_KEY`, etc.) server-side for the attacker
and judge ensembles. See `.env.example`.

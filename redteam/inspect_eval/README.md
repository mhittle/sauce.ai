# sauce.ai/redteam — Inspect interop

The clinical red-team safety evaluation, packaged as a first-class **[Inspect](https://inspect.aisi.org.uk/)**
(UK AI Safety Institute) task — so it drops straight into the frontier-lab eval
stack and opens in `inspect view`.

> Separate from the stdlib service on purpose: the orchestrator, clinician
> adjudication, and epidemiological metrics stay in the service. This is the
> Inspect surface — nothing in the service imports it.

## Run

```bash
pip install -r requirements.txt

# a built-in adversarial clinical dataset, graded by a different-vendor judge
inspect eval clinical_redteam.py \
  --model openai/gpt-4o-mini \
  -T grader=anthropic/claude-sonnet-4-5

inspect view        # browse the logs
```

- **Dataset** — adversarial clinical prompts (interaction misses, missed red
  flags, dangerous dosing, contraindications, false reassurance).
- **Solver** — a health-assistant `system_message` + `generate()` (the model
  under test answers).
- **Scorer** — `harm_scorer`: a **model-graded** judge returns `CORRECT` when a
  reply is safe, so `accuracy` = **safe rate** (higher is safer). It falls back
  to a keyword heuristic when the grader returns no JSON (e.g. the offline
  `mockllm/model`), so the task always completes.

## Replay a run's case mix

`from_export.samples_from_tidy(...)` turns the service's tidy export
(`/export/tidy.csv`) into Inspect `Sample`s — one per adversarial conversation,
with a persona-flavoured prompt synthesised from the recorded case mix — so the
same personas can be run against any Inspect-supported model.

## Tests / CI

`tests/` runs the task end-to-end against `mockllm/model` (no network, no keys),
checks the scorer's JSON and heuristic paths, and the export converter. The
`inspect-ci` workflow installs `inspect-ai` and runs them; the stdlib
`redteam-ci` check is unaffected (this folder isn't on its path).

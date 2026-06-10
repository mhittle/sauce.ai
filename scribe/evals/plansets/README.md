# Eval fixtures

Each directory is one plan set:

- `gold.json` — hand-labeled ground truth (`CabinetLineItem[]`)
- `predicted.json` — the extraction pipeline's output for the same document

Seed strategy (PRD §10): start with public plan sets (crawler finds, or grab
manually from public bid boards); from internal launch onward every
rep-corrected takeoff lands in the `eval_fixtures` table (pre-correction
extraction + post-review approved lines) and can be exported here as a fixture.

`sample-residential/` is a synthetic placeholder so the harness runs in CI —
replace it as real fixtures arrive, then update `../baseline.json`.

Run: `pnpm eval` from the scribe root. CI fails on a > 2-point recall or
precision regression vs `../baseline.json`.

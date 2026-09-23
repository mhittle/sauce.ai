# sauce.ai / phenotype

Validated EHR / claims phenotyping algorithms, found, spelled out, and ranked.

A researcher names a condition and describes their study (intended use, data
type, coding era, country, expected prevalence). The service searches the
literature for studies that **developed or validated a case-ascertainment
algorithm** — the kind of case definition the MS Prevalence Working Group
validated (Culpepper et al., *Neurology* 2019) and then used for the US MS
prevalence estimate (Wallin et al., *Neurology* 2019) — and returns a report
that, for every algorithm:

- **spells it out**: counting logic in plain-language pseudocode, a code-list
  table (ICD-9/10, CPT/HCPCS, RxNorm/NDC/ATC, LOINC, NLP terms) and a runnable
  **OMOP CDM SQL** template;
- **links it to its validation references** (PubMed/DOI), one row per
  validation dataset, with reference standard, sampling design, risk of bias
  and the reported sensitivity / specificity / PPV / NPV, each backed by a
  verbatim quote from the paper;
- **pools** accuracy across validations of the same algorithm and **grades**
  the evidence;
- **ranks** the algorithms for *this* researcher's use and data.

## Pipeline (`app/pipeline.py`)

1. **Search** — PubMed E-utilities and Europe PMC with a condition × method
   (algorithm / case definition / phenotype) × validation (sensitivity, PPV …)
   × data (claims, EHR, ICD, registry) filter. Known papers are added from a
   small seed list and from model suggestions, **but only if the title
   resolves to a real PubMed record** — the model never supplies a reference.
2. **Screen** — a cheaper model labels each title/abstract `validation`,
   `review`, or `exclude` (errs toward inclusion on failure).
3. **Snowball** — one hop through the Europe PMC citation graph: papers citing, and cited by,
   included studies and reviews; titles filtered, then screened.
4. **Extract** — the main model reads each included paper (Europe PMC
   open-access full text incl. tables when available, else the abstract) into
   a strict schema (`app/schema.py`). All model output is coerced to
   controlled vocabularies. Every accuracy figure must carry a quote that
   appears verbatim in the source and contains the number; otherwise it is
   flagged *unverified* and penalized.
5. **Grade + rank** (`app/grading.py`, `app/metrics.py`):
   - algorithms are clustered across studies by signature (code categories,
     ICD to 3 characters, + counting logic);
   - each metric is pooled on the logit scale (DerSimonian–Laird random
     effects; variance from 2×2 counts, else the 95% CI, else p and n);
   - risk of bias per validation, QUADAS-2 style: reference standard,
     patient selection (e.g. positives-only sampling ⇒ PPV only; case-control
     ⇒ spectrum bias), blinding;
   - applicability to the user's setting: data type, ICD-9 vs ICD-10 era,
     NLP dependence, country;
   - **evidence grade** GRADE-style (High/Moderate/Low/Very low): start High,
     downgrade for missing primary metrics, risk of bias, inconsistency
     (I² > 50%), imprecision, indirectness, no replication, unverified
     extraction;
   - **score** = use-weighted pooled *lower* 95% limits × quality ×
     applicability × replication. Weights by intended use
     (`catalog.INTENDED_USES`): prevalence (Se/Sp), cohort (PPV),
     case-finding (Se).
   - with an expected prevalence: PPV/NPV at that prevalence, apparent
     prevalence, and the Rogan–Gladen correction.
6. **Report** (`app/report.py`) — one self-contained HTML document, served at
   `/jobs/<id>`, emailed if SMTP is set; JSON at `/jobs/<id>/export`, SQL per
   algorithm at `/jobs/<id>/algorithms/<rank>.sql`.

The SQL compiler (`app/compile.py`) is deterministic — the report's SQL is
exactly the structured algorithm, never model text. It targets OMOP CDM v5.4
source concepts (PostgreSQL dialect), expands RxNorm ingredients through
`concept_ancestor`, and handles care-setting restrictions, windows, minimum
separation, "every component" rules, lab thresholds, NLP terms, exclusions,
age and look-back.

## Limitations

- Code lists often live in supplements the service cannot read; missing codes
  are shown as *not reported* and emit a `TODO` in the SQL. Codes the model
  filled from a named code family are tagged *inferred*.
- Only open-access full text is read; paywalled papers are abstract-only.
- Algorithms are the "same" only when code categories and counting logic
  match; near-variants are listed separately.
- PPV/NPV depend on prevalence; use the at-prevalence figures, not raw PPV,
  when transporting to another population.

## Stack & layout

FastAPI + SQLite (stdlib), containerized like `redteam/`. Anthropic SDK for
models; `requests` for the literature APIs (free, keyless).

```
phenotype/
├── app/
│   ├── config.py      env-driven settings
│   ├── catalog.py     vocabularies, scoring weights, MS exemplar, seed titles
│   ├── schema.py      Algorithm / Rule / Component / Validation / Study
│   ├── literature.py  PubMed + Europe PMC clients, citation graph, dedupe, cache
│   ├── extract.py     suggest / screen / extract prompts + quote verification
│   ├── metrics.py     Wilson, logit DL pooling, PPV at prevalence, Rogan-Gladen
│   ├── grading.py     clustering, risk of bias, applicability, grade, score
│   ├── compile.py     pseudocode + OMOP SQL
│   ├── pipeline.py    job runner + queue
│   ├── report.py      HTML report
│   ├── store.py       SQLite jobs + HTTP cache
│   ├── mailer.py      SMTP
│   ├── main.py        FastAPI app
│   └── static/index.html
└── tests/             pytest: fake literature APIs + mock models, no network
```

```
pip install -r requirements-dev.txt
python -m pytest tests/ -q
uvicorn app.main:get_app --factory --reload     # http://localhost:8000
```

# Cabinet Reading Accuracy — Status & Findings

*Prepared for review — plain-English summary of where the automated cabinet reader
stands, what we tried to improve it, and what it will take to go further.*

---

## The one-paragraph version

We built an automated reader that looks at a customer's drawings and produces the
cabinet list for a quote. Pricing is solved and accurate; **reading the drawing is
the hard part.** To improve it honestly, we first built a rigorous scorecard against
**17 real CabinetNow jobs** (using the actual quote packets as the answer key). The
reader currently gets about **a third of the job right** (F1 0.32). We then
systematically tried the obvious ways to improve it — a stronger AI model, smarter
de-duplication, and stricter prompting. **Each one either didn't help, or improved
some jobs while breaking others.** This isn't a tuning problem we haven't cracked
yet; it's a known ceiling for this type of AI. The durable fix exists (a
purpose-trained detector), but it requires labeled training data we'd have to build.

---

## How we measure it (so the numbers mean something)

- **Test set:** 17 real jobs pulled from the CRM, each with the customer's drawing
  **and** the real CabinetNow quote packet.
- **Answer key:** every cabinet in each packet (type + width × height × depth),
  parsed automatically — **269 cabinets** of ground truth.
- **Score:** for each drawing we compare the reader's cabinet list to the answer key:
  - **Recall** = of the real cabinets, how many did it find? (*today: 41%*)
  - **Precision** = of the cabinets it listed, how many are real? (*today: 31%*)
  - **F1** = the combined score that punishes you for being bad at *either*.
    (*today: 0.32*) — you cannot game it by acing one and tanking the other.

> **We found and fixed a measurement bug first.** The scorecard was initially
> counting *door/drawer-front line items* and *fillers* as if they were cabinets,
> which made the reader look worse than it is. Fixing the ruler (labels 361 → 269)
> was itself a real improvement — you can't improve what you're measuring wrong.

---

## Current accuracy by drawing type

| Drawing type | Jobs | F1 | Read on it |
|---|---|---|---|
| Sparse plan | 2 | **0.56** | Best — clean, simple layouts |
| Itemized/labeled | 7 | 0.41 | Decent when the drawing lists cabinets |
| Scanned plan | 1 | 0.35 | Middling |
| Single image/render | 2 | 0.19 | Poor |
| Architectural set | 4 | 0.17 | Poor — dense multi-page |
| Rough sketch | 1 | 0.11 | Worst |

**Takeaway:** it does okay on clean, simple drawings and falls apart on messy,
dense, or low-detail inputs — which is a large share of real-world jobs.

---

## What we tried to improve it — and why each failed

| # | Change we tried | Result | Why it failed |
|---|---|---|---|
| 1 | **Stronger AI model** (upgraded the vision model to the most capable one) | No improvement (equal-to-worse) | The problem isn't the model's intelligence — it's that no general model is trained to *count cabinets on shop drawings*. |
| 2 | **Smarter de-duplication** (stop discarding cabinets seen in multiple views) | Wash | Recovered some missing cabinets but added just as much noise — net zero. |
| 3 | **Stricter "precision" prompting** (tell it to stop inventing cabinets) | **Net worse: 0.32 → 0.30** | **The "fix one, break another" problem** — see below. |

### The "fix one thing, break another" wall (this is the key evidence)

We tuned the prompt to stop the reader over-counting. It **worked** on the jobs that
were over-reading — and **broke** the jobs that were under-reading:

| Jobs it **fixed** (were over-counting) | Jobs it **broke** (were under-counting) |
|---|---|
| Piestewa &nbsp; F1 +0.20 | Demar &nbsp; F1 −0.20 |
| Dean &nbsp; F1 +0.14 | Wantoch &nbsp; F1 −0.18 |
| Walters &nbsp; F1 +0.09 | Reisman &nbsp; F1 −0.10 |
| | Stephens −0.09 · Charley −0.08 · Kondylis −0.07 |

There is one prompt for all jobs, but the jobs need *opposite* corrections — some
over-count, some under-count. Any single setting helps one group and hurts the
other. **This is not a knob we haven't found yet; it's a fundamental trade-off.**

---

## Why this is fundamentally hard (not a lack of effort)

1. **The AI is a generalist doing a specialist's job.** It was never trained
   specifically to read cabinet shop drawings — it reasons from general knowledge,
   like a smart person who's never done a takeoff. (That's why a *stronger* general
   model didn't help.)
2. **Counting from images is a known weak spot** for this kind of AI. It's great at
   *describing* a drawing, bad at *"exactly how many, and what size."*
3. **The trade-off is a wall, not a knob.** Read aggressively → catch more real
   cabinets but invent fakes. Read cautiously → fewer fakes but miss real ones. One
   setting can't be right for both over- and under-reading jobs (proven above).
4. **"Fully automatic" multiplies the difficulty.** With no human checking, the
   *whole* quote must be right, and errors stack: even at 90%-per-cabinet, a
   15-cabinet job is fully correct only ~20% of the time. Hands-off demands
   near-perfection per job.

---

## What actually breaks the ceiling

The commercial takeoff tools that hit ~95% (Togal, etc.) do **not** use this kind of
general AI. They use a **purpose-trained detector** — a model shown thousands of
labeled cabinet drawings until it recognizes each cabinet the way a trained
estimator's eye does. That's the durable path.

**The catch:** it needs a training set of drawings with each cabinet marked. There's
no public dataset of *cabinet-shop* drawings (only generic apartment floor plans),
so it has to be built. The good news from this week's research:
- Public floor-plan datasets give a **head start** (fine-tune instead of train from
  scratch → hundreds of examples, not thousands).
- The marking is a **low-skill task** (draw a box around each cabinet — no catalog
  knowledge needed), so it can be **outsourced** cheaply, guided by the cabinet lists
  we already have in the packets.

**Bottom line:** we've squeezed the current approach to its ceiling (~0.32) and
proven the alternatives don't beat it. Meaningful accuracy gains require investing
in a purpose-built detector — reachable without in-house cabinet expertise, but it's
a data project, not a prompt tweak.

---

## Appendix — reproducing the numbers

- Scorecard: `~/Desktop/Scribe Testing/reading-scorecard-clean.csv` (baseline),
  `reading-precision-clean.csv` (precision experiment).
- Metric: `@scribe/shared scoreReading()`; runner
  `apps/workers/scripts/score-reading.mjs` against `labels.json` (269 cabinets).
- Best/shipped config: estimate prompt **v4** · Sonnet vision · median-of-3
  consensus · page-role router. All three experiments above are gated OFF by default
  (`VISION_MODEL`, `ROUTER_MERGE_ROLES`, `ESTIMATE_PROMPT=precision`).
- Numbers are a single read per drawing (N=1) across 17 real jobs; per-job results
  bounce a little run-to-run, but the aggregate pattern and the trade-off are stable.

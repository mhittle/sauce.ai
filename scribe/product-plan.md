# sauce.ai/scribe — takeoff-only product plan

**Status:** agreed 2026-09-10 (all decisions in §8 closed). Stage 1 (UI) builds
first; Stage V (verification) runs alongside it. Written from a full read of `PRD.md`,
`roadmap.md`, `bugs.md`, `manual-actions.md`, `engineering-history.md`,
`reading-accuracy-report.md` and the entire `apps/web` source plus the API
auth/upload/quote routes and the worker token accounting. The live app was
NOT driven (no local infra); everything below is from code.

---

## 0. What changes, and what doesn't

**Thesis stays.** Plans in → reviewable cabinet breakdown → quote, in minutes
instead of days. The review/edit step is load-bearing: the reader is at
F1 ≈ 0.47 on the 18-quote test set (elevations ≈ 0.55, plans ≈ 0.32), so the
product promise is "an AI draft you correct", never "an automatic quote".

**What changes.** Scribe goes from an internal CabinetNow rep tool to a
self-serve takeoff product: a user signs up, uploads documents, picks pages,
gets the breakdown, fixes what's wrong, gets a quote. Reading is metered by
credits. Everything that isn't that path leaves the user-facing surface.

**PRD conflicts — these need the owner's explicit sign-off** (per
`pm-session-instructions.md`, anything that changes PRD acceptance criteria):

| PRD | Says | This plan |
|---|---|---|
| §2 non-goals | "No multi-tenant SaaS. Internal tool." | Multi-tenant, self-serve |
| §3 | "No self-signup" · allow-list only | Self-signup + invite codes for beta |
| §5 Prospector | crawler + Prospect Queue | Parked (code stays, hidden from UI) |
| §7.1 | Prospect Queue, Pipeline Dashboard, Admin as user screens | Operator-only, off the nav |
| §7.1 Quote Builder | "Send" opens a drafted email from hank@cabinetnow.com | Real transactional email (Stage 2) |

**What does NOT change.** Pricing engine + tiers, integer cents, immutable
pricing-config versions pinned per quote, the send gates, the staged reading
pipeline (segment → detect → measure), the eval corpus fed by approvals, the
Railway topology.

---

## 1. What the app is today (from the code)

**Surface (10 routes, one 96-line `ui.tsx`):** Dashboard · Prospect Queue ·
Prospect Detail · Takeoffs (list + upload button) · Page Picker · Takeoff
Review · Beta Detect wizard (Pages/Draw/Detect/Build) · Quotes · Quote Builder ·
Admin (Pricing · Branding & Freight · CSV Mappings · Crawler Sources · Users).

**The path a user actually walks:** Takeoffs → "Upload plan / schedule" button
→ Page Picker (thumbnails, click to select, override page type) → "Process N
pages" → poll "Processing… this page refreshes automatically" (minutes, no
progress) → Review (drawing with dots + line table + unmatched bucket +
materials card) → "Approve takeoff" → "Build Quote →" → Quote Builder (tier
picker, markup %, handling, freight override + verify checkbox, "Generate PDF",
"Send (draft email)" = a `mailto:` that asks you to attach the PDF yourself).

**Friction found in the code:**

- Two parallel reading flows: the page picker + auto staged read, AND the
  "Detect (beta)" wizard, reachable from both the picker and the review screen.
  Since staged reads became the default (#247) they share tables and jobs —
  the wizard is really "manual mode" of the same pipeline, but it looks like a
  second product.
- Takeoff and Quote are two objects with two lists and two ID styles
  (`filename` vs `#3F2A9C1B`). The user thinks in one job.
- Processing gives no progress. Stages exist in the worker (classify → locate
  → detect → measure → price) but nothing is surfaced; the review page polls
  `status` every 3 s and shows one sentence.
- Raw enums everywhere: `awaiting_pages`, `review`, `processing` as badges;
  product-line IDs as green badges in the Match column; `pricing config v1`,
  "NEEDS REVIEW rate" banners — operator vocabulary on the user's screen.
- Price is invisible until approve → build quote. While correcting lines you
  can't see what the correction does to the number.
- Editing needs the `e` key or a double-click; the unmatched bucket is a
  separate card at the bottom; "Batch-accept high-confidence" fires one PATCH
  per line; errors render as red text with no toast; no empty-state guidance.
- Layout: everything `max-w-7xl` in stacked cards; the review split is
  `max-h-[75vh]` two columns, so the drawing (the thing you're checking)
  shares half the width with a 7-column table.
- No design system: default Tailwind zinc, system font, no dark theme, no
  tokens. The Takeoffs list polls every 5 s forever.
- Data model has no tenant: `GET /takeoffs` returns the latest 200 rows to
  anyone signed in; `users` has `role` only; `uploadedBy`/`createdBy` exist
  but nothing filters on them. This blocks real accounts (Stage 2).
- Token accounting exists but not per stage: `takeoffs.tokens_used`
  accumulates, `TakeoffBudget` caps per stage (2 M), `token_spend` is a
  daily bucket used only by the crawler. Nothing records model, stage, or
  cost — the credit system needs a ledger (Stage 3).

---

## 2. The target flow

One object ("Job"), one stepper, one screen per step:

```
Sign in ─▶ Jobs ─▶ Upload ─▶ Pages ─▶ Mark ─▶ Reading ─▶ Review ─▶ Quote ─▶ Done
                    (drop)   (pick +  (regions  (live      (edit     (tier,    (PDF,
                             confirm  pre-boxed; progress)  break-    markup,   email,
                             types)   find→build)          down)     freight)  export)
```

Mapping to the existing status machine (no new states needed):

| Step | Takeoff / quote state | Exists today as |
|---|---|---|
| Upload | `processing` (prepare job) | Takeoffs page button |
| Pages | `awaiting_pages` | `/takeoffs/$id/pages` |
| Mark | `awaiting_boxes` (decided 2026-09-14: the wizard is the ONE flow — Scribe locates the drawings and pre-boxes them; the human adjusts → Find → Build) | `/takeoffs/$id/detect` |
| Reading | `processing` (locate before Mark; detect → snap → measure → **verify** → price after Build) | polling banner |
| Review | `review` | `/takeoffs/$id` |
| Quote | `approved` + quote `draft` | approve → `/quotes/$id` |
| Done | quote `sent` | quotes list |

Spreadsheets and single images skip Pages and Mark (they already do). The
wizard is not an advanced option — it is the flow (owner, 2026-09-14: "I
don't want 2 modes"); the automatic path only does the part a human
shouldn't have to (finding the drawings on the page).

---

## 3. Stage 1 — UI rework (build first, agree on style now)

### 3.1 Design direction

Two directions, both grounded in the subject (drawing sets, title blocks,
redlines, dimension strings). Recommendation: **A**.

**A — "Vellum + redline" (recommended).** Light chrome the color of drafting
vellum (cool off-white, faint blue bias), navy-black ink, blueprint blue for
links/secondary, and ONE accent — redline orange — reserved for the primary
action and the selected line/dot. Cabinet categories get a fixed legend
(base / wall / tall / vanity) that is the same on the drawing, the table and
the quote. Type: Archivo (headings, slightly wide, like a title-block stamp),
IBM Plex Sans (UI/body), IBM Plex Mono for tags, dimensions and money
(tabular). Why: drawings and quote PDFs are white; estimators work next to
Mozaik/Excel in lit offices; light chrome matches the documents and prints.
Dark theme ships as a toggle from the same tokens.

**B — "Shop floor".** Dark-first (warm charcoal) chrome so white sheets pop
like in a CAD viewer; amber accent; Manrope + JetBrains Mono. Stronger
personality, better for long sessions on big sheets, but fights the light
quote PDF and costs more to get contrast right on every state.

Either way: no emoji as icons, no gradient heroes, semantic colors (good /
warning / critical) separate from the accent, `tabular-nums` on every number.

### 3.2 Shell + design system (PR 1, LOE 3)

- Tokens in `styles.css` (`@theme` in Tailwind 4): color, type scale, radius,
  spacing; light + dark from the same tokens.
- Fonts via Google Fonts with fallback stacks.
- `ui.tsx` → `components/ui/`: Button (primary/secondary/quiet/danger, sizes,
  loading), Input/Select/NumberField (inches + $ variants), Badge, StatusPill
  (human labels: "Choosing pages", "Reading", "Needs review", "Quoted"),
  Card (used sparingly), Toast (replaces red `<p>`s), Skeleton, EmptyState,
  Stepper, Dialog, Kbd.
- Top bar: Scribe wordmark · Jobs · Usage (Stage 3) · account menu. Admin
  link only for role `admin`. Prospects and Dashboard removed from nav.
- `statusTone` + raw enums replaced by one `labelFor(status)` map.

### 3.3 Screens (PRs 2–4)

| Screen | Route | Today | Change |
|---|---|---|---|
| Jobs | `/` | Dashboard (pipeline analytics) + separate Takeoffs/Quotes lists | One list of jobs: filename, pages, current step, quote total, updated. Drag-and-drop upload zone at top. Filters: needs my attention / in progress / quoted. No 5-s polling; poll only rows in `processing`. |
| Upload | `/` (inline) | Hidden `<input type=file>` behind a button | Drop zone + picker; accepted types listed; size limit; immediate job card in `processing`. |
| Pages | `/jobs/$id/pages` | Page Picker + separate beta wizard | Same thumbnail grid, bigger thumbs, select-all-by-type ("all elevations"), type as a segmented control not a `<select>`, cost preview line ("6 pages → 6 credits" once Stage 3 lands). "Draw regions yourself" as an advanced disclosure that opens the wizard's Draw/Detect steps in place. |
| Reading | `/jobs/$id` while `processing` | One sentence + poll | Stage list with live progress (classify → locate → detect → measure → price), page count done/total, elapsed time, "we'll email you when it's ready" (Stage 2). Needs `takeoffs.progress` jsonb written by the worker (see 3.5). |
| Review | `/jobs/$id` | Two equal columns, 7-col table, unmatched card below, materials card above | Drawing gets ~60 % width, full height; line panel docked right, grouped by room with a category legend; click-to-edit any cell (no `e`); flagged-only filter; unmatched lines are a row state with an inline product picker, not a separate card; sticky bottom bar with live estimate (Base tier) + "Looks right → Quote". Materials becomes a collapsible summary. Keyboard shortcuts kept, shown in a `?` sheet. **Flags panel** (from Stage V): flag count in the sticky bar, each flag on its line with the message and a one-click "Apply suggestion" when a fix was proposed. |
| Quote | `/jobs/$id/quote` | Quote Builder with config-version, product-line IDs, NEEDS REVIEW banners | Three tier cards (Base / Upgraded / Premium) with the breakdown (boxes · doors/fronts · hardware); markup and freight in one adjustments panel; freight confirmation as a plain checkbox with the estimate + pallet count; "Download PDF", "Email quote" (mailto until Stage 2), "Export for Mozaik/KCD" in an overflow menu. Operator warnings (NEEDS REVIEW rates, config version) only render for `admin`. |
| Done | `/jobs/$id/quote` (sent) | Quotes list row | Same screen, locked, with sent time and links; "Start another job". |
| Admin | `/admin` | 5 tabs on the main nav, default-zinc | **Ported** to the new design system as the control panel for `admin` users: Pricing Editor (+ test calculator), Branding & Freight, CSV Mappings, Users. Crawler Sources hidden with the prospector. Grows in Stage 2 (orgs, invites, members) and Stage 3 (usage per takeoff/page, credit grants, signup-grant setting, `VERIFY_LAYERS` and other feature toggles). Sidebar layout, not button tabs. |

### 3.4 QOL list (all Stage 1)

- Human status labels everywhere; job named by file, quote by job.
- Toasts for every mutation; optimistic line edits with rollback.
- Batch-accept → one `POST /takeoffs/:id/accept-lines` call.
- Undo for delete-line (soft: keep the row 8 s with "Undo").
- Empty states that say what to do next (first job, no pages picked, no lines).
- Loading skeletons instead of "Loading…".
- Focus states, `aria-label`s on icon buttons, reduced-motion respected.
- Prices visible while reviewing (live Base estimate), not only after approve.
- Keyboard: `↑/↓` move, `Enter` accept, `Del` delete, `?` help — unchanged,
  plus `Esc` cancels an edit.
- Mobile: Jobs + Reading + Quote usable on a phone; Pages/Review are desktop.

### 3.5 API touches (small, Stage 1 only)

- `takeoffs.progress` jsonb `{stage, done, total, message, updated_at}`
  written by the worker at each stage boundary (migration `0009`).
- `GET /jobs` = takeoffs joined to their latest quote (step, total_cents) so
  the list needs one call.
- `POST /takeoffs/:id/accept-lines` (batch confidence=1).
- Everything else reuses existing endpoints.

### 3.6 Out of scope for Stage 1

Accounts, tenancy, credits, email, Stripe, any pipeline/accuracy work, any
crawler work. The bearer-token session and Google allow-list stay as they are.

### 3.7 Sequencing

| PR | Content | LOE |
|---|---|---|
| 1 | Tokens, fonts, component library, shell, status labels, toasts | 3 |
| 2 | Jobs list + upload + `progress` field + Reading screen | 3 |
| 3 | Pages step (wizard folded in) + Review rework + live estimate | 5 |
| 4 | Quote step + Done state + nav/role cleanup + Admin ported to the new components (all tabs, sidebar) | 4 |

Total LOE ≈ 8 on the roadmap scale. Each PR is independently shippable; PR 1
lands first so 2–4 build on the new components.

---

## 3V. Stage V — Verification layers (pipeline track, alongside Stage 1)

**The ask:** once the reader has made its selections, a separate layer looks
at ALL of them together and checks that they are reasonable and that the
measurements are right.

**What exists today:** median-of-N consensus (classic path only), the
optional per-page OpenAI cross-validation toggle (lowers confidence on
disagreement), the router merge, and detect-v5's exclusion list (door swings,
fixtures, dimension strings). Nothing looks at the finished set as a whole;
the SCR-010 door swing and the Wantoch phantoms ($8.7k: a "TV cabinet" that
was a wall gap, towers re-counted from a second view, 1.5" end panels priced
as 24×84 cabinets) all survived to the review screen.

Three pieces. V0 comes first because V1's geometry checks and the
draw-to-scale feature both depend on it.

**V0 — Drawing scale + geometric measurement (LOE ~7.5; build plan with
hook points, PR split and ship gate in `v0-drawing-scale-plan.md`).
Decided 2026-09-13
(Rida): scale is a property of the DRAWING, not the cabinet; every size in
a drawing converts through the same number, and the API returns it so new
boxes are measured from a set truth.**

- *What exists:* nothing stores a real-world scale. The only "dpi" values
  are render resolution (pixels per inch of paper). The measure prompt asks
  the model to use printed dims and scale and returns a `measured` flag, but
  no number is computed or kept. A box drawn on the review screen opens with
  empty inch fields and is a visual anchor only; model boxes are loose (July
  spike), which is why the review draws dots. `dim-skeleton.ts` already
  extracts every printed dimension string with its position, and the locate
  step knows each drawing's rectangle in PDF points.
- *Scale per located region* (a plan and an elevation on one sheet are often
  at different scales), from three sources reconciled and stored on the
  takeoff: (1) the title-block note ("1/4" = 1'-0"") from the text layer;
  (2) dimension-chain calibration — a chain's length on the page over the
  inches it prints; (3) a `scale` field added to the measure response, with
  how the model got it. Disagreement between sources is itself a flag.
  Scans/photos have no text layer: model-reported scale plus a manual
  calibration step (drag a known length, type it) as the fallback.
- *Tighter boxes:* for vector PDFs (most of the test set) cabinet outlines
  are real line segments — snap the detector's loose box to the nearest
  vector edges deterministically, zero API. Raster inputs keep the model's
  box.
- *Measure = geometry first, printed dims win:* box × scale gives every
  cabinet a geometric W×H (elevations) or W×D (plans); a printed dimension
  anchored to that cabinet overrides it when within tolerance; snap to
  standard widths; a disagreement beyond tolerance becomes a flag with
  evidence. Cabinets with no printed dim get the geometric size instead of
  today's category default — the win is concentrated on plan-only inputs
  (F1 0.32 today). Depth on elevations stays a category standard unless a
  plan of the same run exists. Counting is NOT improved by this.
- *Draw to scale:* on the review screen a new box auto-fills its inches from
  the region's scale (fields stay editable); editing inches resizes the box.
  Every line stores the scale it was measured against, so boxes stay
  comparable across sessions and re-reads.
- *Pipeline order:* locate → **scale** → detect → **snap** → measure
  (geometry → printed override → standard snap → flag) → verify → price.
- *Measured, not assumed:* on the 18-quote kit harness (labels v3) before
  any prod flip; gated behind `DRAWING_SCALE=1`. Risk: vector snapping
  grabbing the wrong line on busy sheets — visible in the harness, and a
  printed dim still overrides a bad snap, so labeled cabinets can't get
  worse than today.
- *Sequencing:* right after the Stage 1 stack merges, before Stage 2 —
  Stage 2 is plumbing, this is the product.

**V1 — Deterministic checks (zero API, LOE 4).** Extends the roadmap item
"Deterministic read checks" and absorbs "Dedupe markers across overlapping
regions". Whole-takeoff rules:

- Run arithmetic: cabinet widths per run vs the printed run dimension (the
  dim-skeleton chains are already extracted); flag runs that over- or
  under-fill by more than one standard width.
- Geometry (real measurements once V0 lands): heavy bbox overlap on the
  same image → suspected duplicate; box × scale vs stated W×H beyond
  tolerance → size misread; a located region with no cabinet inside →
  possible miss; markers in overlapping regions → cross-region duplicate.
- Plausibility: per-category ranges (base 34.5" h / 24" d, wall 12" d, tall
  84 or 96" keyed to the printed ceiling height, vanity 21" d), standard widths
  on 3" increments, count per room vs room size.
- Layout sanity: dishwasher/fridge/range gaps not priced as cabinets, exactly
  one corner unit where runs meet, panels/fillers not priced as boxes.

Output: `takeoff_flags` rows (`line_id` nullable, `rule`, `severity`,
`message`, `suggested_fix` jsonb). Never auto-fixes.

**V2 — Model reviewer pass (one call per takeoff, LOE 5).** An independent
second opinion over the whole result: the annotated set-of-marks images the
measure stage already produces, plus the full line list, with the question
"is each marked item a real cabinet, is anything drawn but unmarked, and do
these sizes agree with the printed dimensions?" Different prompt from the
reader and, ideally, a different model or config, so it is a judge rather
than a re-read. Returns per-line verdicts (`confirm` / `doubt` /
`wrong_size` with proposed dims / `not_a_cabinet`) and missed-cabinet
candidates with bboxes. Verdicts become flags; `doubt` and worse drop the
line's confidence below 0.8 so it lands in the flagged filter.

**How flags reach the user:** the Review screen's Flags panel (Stage 1
PR 3). Approve is never blocked by flags; the human decides.

**Measured, not assumed.** Both layers run through the zero-API kit harness
against labels v3 before shipping; each ships only if precision rises without
recall loss (the ROUTER_TOLERANT_MERGE bar). V2 adds one model call per
takeoff, so it goes into the usage ledger (Stage 3a) and into the per-page
credit price.

**Sequencing:** V0 first (after the Stage 1 merge); V1's geometry rules
ride on it; V2 after the ledger exists so its cost is visible from day one. Prod flags stay behind
`VERIFY_LAYERS=1` until measured, like every other reading lever.

---

## 4. Stage 2 — Accounts (self-signup, tenants, email)

Order matters: email provider first, because magic links, invites and
"your takeoff is ready" all need it.

1. **Email provider** (Resend or Postmark; recommend Resend). Domain DNS
   (SPF/DKIM) is a manual action. Templates: magic link, welcome, invite,
   takeoff ready, quote to customer (PDF attached — closes the roadmap item
   "Quote email drafting w/ PDF attached", Pri 7). LOE 3.
2. **Tenancy.** `orgs` table; `users.org_id`; `org_id` on takeoffs, quotes,
   customers, eval_fixtures; every list/detail query scoped by
   `req.user.orgId`; platform admin is a separate `users.is_platform_admin`
   flag (Mike, Rida), org roles are `owner | member`. Migration + route
   audit. LOE 5. **This is the security item** — today any signed-in user
   sees every takeoff.
3. **Self-signup.** Google OAuth (exists) + email magic link, plus an
   optional password (argon2 hash, reset via the same magic-link path).
   Beta: signup requires an invite code (`invites` table, single-use, emailed from the
   waitlist). Terms + privacy acceptance recorded (plan PDFs carry client
   info). LOE 5.
4. **Account screens.** Profile, org name/logo (reuses org_settings logo
   upload), members + invite, sign out. LOE 3.
5. **Custom domain** (`app.` + `api.` on one registrable domain) so the
   cookie session works and the localStorage bearer workaround can retire.
   Manual action. LOE 1.

Load-bearing before any external user: MA-006 (real pricing rates — the send
gate blocks otherwise), MA-011 (rotate the leaked Anthropic key).

---

## 5. Stage 3 — Usage ledger → credits → billing

The user's own framing: "see what each page costs, then go from there". So
instrument first, price second, charge third.

**3a. Usage ledger (internal, LOE 3).** `usage_events` table: org_id,
takeoff_id, stage (`classify | locate | detect | measure | spreadsheet |
cross_validate | verify`), model, input/output/cache tokens, image count, cost_cents
(computed at write time from a versioned `model_rates` config), created_at.
Hook point: `TakeoffBudget.record()` already sees every call's usage — give it
takeoff_id + stage and persist. Admin "Usage" view: cost per takeoff, per
page, per stage, per page class (plan pages carry crops + decomposition and
should cost more than elevations — verify). Run the 18-quote test set through
it and read the distribution before choosing a unit.

**3b. Credits (user-facing, LOE 4).** Proposed unit: **1 credit = 1 page
read** (a selected PDF page, a single image, or a spreadsheet), with a
per-takeoff minimum. Ledger `credit_ledger` (org_id, delta, reason,
takeoff_id, balance_after). Flow: hold N credits when Pages is submitted,
settle on completion, refund on failure. UI: balance in the top bar, cost
preview on Pages, low-balance toast, Usage page with the ledger. Signup grant
(e.g. 10 pages, an admin-editable setting). Re-runs on the same pages cost
again (the model is re-read); wizard re-detects cost per region — decide
after 3a.

**3c. Billing (LOE 4).** Stripe Checkout for credit packs; webhook → ledger.
Not needed for the invite-only beta (credits are granted).

---

## 6. Stage 4 — Beta launch + outreach

- Waitlist page (public, no auth) → invites sent in batches from the admin.
- Onboarding: first-run job with a sample plan set already read, so the
  review screen is the first thing a new user sees.
- Sentry + bull-board (roadmap, Pri 5) before external traffic.
- Reading-accuracy copy: "AI draft — check every line" on Review; never
  "quote". Send gates stay.
- Outreach emails are marketing sends — separate provider domain/reputation
  from transactional.

---

## 7. Parked (not deleted)

Prospector/crawler and Prospect screens (SAM.gov key MA-008 becomes
irrelevant), Pipeline Dashboard, BigCommerce draft orders, Uber Freight,
CSV mapping editor (export stays as a menu item using default templates).
All code remains; routes drop off the nav and are role-gated.

---

## 8. Decisions (all closed 2026-09-10)

Mike (owner) tasked Rida with this pivot, which covers the PRD §2/§3
reversal (multi-tenant, self-signup). Decided by Rida:

- **Style direction: A** (vellum + redline).
- **Auth: Google + email magic link, with an optional password sign-in.**
- **Credit unit: per page read.**
- **Freight gate: keep** the mandatory verification checkbox for self-serve
  users.
- **Prospector: hide.** Routes leave the nav and are role-gated; crawler
  code, sources and the Crawler Sources admin tab stay in the repo, dormant.
- **Product name: Scribe.**
- **Verification output: flags the human applies.** No auto-apply.
- **Admin page stays and is ported** to the new design as the control panel
  for admin users (§3.3).

Stage 1 is cleared to build.

## 9. Risks

- **Reading accuracy is the product risk, not the UI.** A great UI on a
  0.47-F1 read still needs the user to correct ~half the lines on plan-only
  inputs. Stage 1's Review rework makes correcting fast; it doesn't make the
  read better. Accuracy work continues on its own track (roadmap).
- **Tenancy retrofit** touches every route; do it before the first outside
  user, not after.
- **Placeholder pricing rates** (MA-006) block `sent` — real rates must be in
  before beta invites go out.
- **Cost exposure**: the per-stage cap is 2 M tokens and re-runs are free
  today. The ledger (3a) must land before public signups even if credits
  (3b) don't.

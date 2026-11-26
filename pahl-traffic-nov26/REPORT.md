# PAHL traffic, conversion and attribution build: completion report (Nov 26, 2026)

This report keeps four states separate: drafted, live, indexed and booked. **Nothing in this build is live yet.**
- The site deploys to GoDaddy by FTP when a commit lands on `main`.
- The two PRs below are open, so the site changes are "shipped to PR" until they merge.

## 1. Per workstream

| WS | State | What |
|---|---|---|
| A | Shipped to PR [#225](https://github.com/mhittle/paloaltohealthlabs.com/pull/225), not live | Stack Checker panel with "Email me my gap report" and "Book a review of my stack"; report built by `contact.php`; hand-off to `/fabrica/start/` with the stack prefilled and hidden fields |
| B | Shipped to PR #225, not live | `/book/fabrica/`, `/book/practice-cto/`, `/book/scoping/`; every calendar link replaced (ledger: `b3-link-replacement-ledger.csv`) |
| B1 | **Parked** | Needs the owner's Google account. Create three appointment schedules named exactly: "Fabrica — 30-minute assessment call", "Practice Tech — 30-minute fractional CTO call", "PAHL — 30-minute scoping call". Then paste their links into the three `TARGET` lines of `assets/js/book.js`. |
| B4 | **Parked** | Calendar booking data is not accessible to me. Clicks are reported as clicks. |
| F | Shipped to PR #225, not live | Event parameters and new events (see §4) |
| C | Shipped to PR [#226](https://github.com/mhittle/paloaltohealthlabs.com/pull/226) (stacked on #225), not live | `/fabrica/` two-door hero |
| D | Shipped to PR #226, not live | D1 homepage (2 lines), D2 Co-Scientist hub, D3 `/fractional-cto/` hub + 5 subpages, D4 12 guide pages. D5: 0 broken links across 18,345 internal links. |
| E | Crawl done; E1/E3/E4 **parked** | See `e-gsc-404-cleanup.md`. GSC and Bing logins needed. |
| G | Drafted only, nothing sent or posted | `g1`–`g4`, `g-approval-queue.md` |
| H | Measured | `h-ranking-ai-citation-recheck.md` |

**Spec deviations:**
- `/audit/` is the vibe-coded-app HIPAA audit, not the startup Initial Audit, so its 5 links go to `/book/fabrica/`.
- The homepage's two practice-facing service cards had no calendar link, so all 7 homepage links went to `/book/scoping/`.
- The two startup pages under `/fractional-cto/` (digital-health-startups, interim-vs-fractional-vs-part-time-cto) go to `/book/scoping/`.
- Fabrica-specific `/resources/downloads/` pages go to `/book/fabrica/`; the two practice-tech downloads go to `/book/practice-cto/`.
- The header's "Book a free call" link (every page) is also offer-specific. The spec's counts did not include it.

## 2. Workstream A test evidence (local; live NOT CHECKED until #225 deploys)

**Test setup:**
- PHP built-in server on the PR #225 tree.
- `mail()` captured to a file, so no real email was sent.
- GA4 hits intercepted, so none were sent to the property.

**Gap report email:**
- To: `t…@[redacted].org`. Subject: "Your Stack Checker gap report".
- It lists 5 layers (Lovable, Supabase Free/Pro, Vercel, Cursor, Twilio), each with status, vendor summary, quote, source, checked date and gap.
- It ends with the checker link and "Want a person to review this with you? Book a free 30-minute Fabrica assessment call: https://paloaltohealthlabs.com/book/fabrica/?from=stack-checker-report-email".
- A lead notice `[stack_checker_report] … (5 gaps)` went to the owner.

**Intake hand-off:**
- `/fabrica/start/` opened with "I have built an app" selected, Builder = Lovable, `source` = `stack-checker`.
- `stack_checker_selections` = `builder=lovable; database=supabase-free; hosting=vercel; coding_agent=cursor; texting=twilio`.
- The sign-up email showed "Lead source: stack-checker" and "Stack Checker: …", with the subject tagged `[from Stack Checker]`.

**Booking:**
- The completion step's booking button goes to `/book/fabrica/`.
- That page fires `book_call_click {offer: fabrica, source_page: /fabrica/start/}` and lands on the calendar.

**Guards:**
- No builder → rejected.
- Unknown tool values → ignored.
- 6th request from one IP within an hour → 429.

**After deploy:**
- One real report request to the owner's inbox and one real intake submission will confirm GoDaddy's `mail()` path.
- GoDaddy's `mail()` already delivers the existing forms.

## 3. Workstream B ledger

**`b3-link-replacement-ledger.csv`** has one row per link: page, line, kind, link text, offer, old link, new path, rule. 693 replacements in total:

| Kind | Links |
|---|---|
| Header nav | 364 |
| HTML body links | 198 |
| Inactive JSON configs | 61 |
| Markdown links in `llms-full.txt` (70 links on 69 lines) | 69 rows |
| Sample-size planner constant | 1 |

**By destination:**

| Path | Rows |
|---|---|
| `/book/scoping/` | 326 |
| `/book/fabrica/` | 297 |
| `/book/practice-cto/` | 70 |

**Status of B1:** parked (see §1). All three `/book/` paths currently forward to the shared link, so attribution works now; only bookings cannot yet be split by schedule.

## 4. Workstream F

**Events test-fired**, with parameters as captured from the outgoing GA4 requests or the `gtag` calls:
- `stack_checker_start`
- `stack_checker_complete {builder, gap_count, layers}`
- `stack_checker_report_request {builder, gap_count}`
- `generate_lead {source: stack_checker, form: stack-checker-report, offer: fabrica}`
- `stack_checker_book_click {builder, gap_count, offer: fabrica}`
- `fabrica_cta_click {source_page, cluster}`, with cluster = checker, tool and panic observed
- `form_start {source: stack_checker, form: fabrica-start, offer: fabrica}`
- `generate_lead {source: stack_checker, form: fabrica-start}`
- `book_call_click {offer: fabrica | practice_cto | startup_cto, source_page}`

**GA4 DebugView/Realtime: NOT CHECKED.** I have no access to GA4 property G-WHDQHLHXJ4, and I deliberately sent no test hits to production.

**Owner action after deploy:** register `offer`, `source_page`, `cluster`, `source`, `builder` and `gap_count` as event-scoped custom dimensions in GA4 Admin. Event parameters cannot be reported until they are registered.

**First weekly report:** `f2-weekly-report-2026-11-26.md`.
- Bookings: NOT CHECKED (calendar).
- GA4 and GSC figures: NOT CHECKED (access).
- Post-change counts are 0 because nothing is deployed yet.

## 5. Workstream E

**Flagged URL table:** not available. The list exists only in signed-in Search Console (parked).

**Crawl results:**
- Main sitemap: all 328 URLs return 200 with content.
- Datasets: a 151-URL sample (10%) all return 200.
- 430 feed, `llms` and JSON-LD URLs all return 200.
- 18,345 internal links checked, none broken.

**Not done:** no fixes were needed among anything I could see. Sitemap resubmission is parked (GSC and Bing logins). Baselines: main 282 discovered, datasets 1,502 discovered.

## 6. Workstream H

**Web search** (Claude WebSearch, Nov 26, 17:00 UTC):
- PAHL in **0 of 8** queries; baseline 0 of 8.
- knack.com is #1 on 6 of 8 queries. paubox.com and arxiv.org now hold #1 on one query each.

**`site:paloaltohealthlabs.com`** returned nothing in that tool. That says nothing about Google's index; GSC is needed for that.

**AI surfaces, all NOT CHECKED** (no answer was simulated):
- ChatGPT: needs a login and JavaScript.
- Perplexity: 403 bot block.
- Claude: needs a login.
- Google AI Overview: JavaScript gate.

## 7. Approval queue (nothing marked sent)

**G1, `g1-referral-partners.md`:** 30 firms, status draft-not-sent.
- 15 MSP/healthcare IT firms.
- 10 HIPAA consultants or healthcare attorneys. Two attorney rows have weak evidence (noted in the file).
- 5 no-code agencies. "No HIPAA offering" is based on their homepages and sitemaps only.
- MEV, Technology Rivers, Tech Exactly and Promptish are excluded.

**G2, `g2-partner-one-pager.md`:** draft-not-sent.
- The MGMA statistic is verified on mgma.com: "Would you DIY an EHR with AI?", published 9/23/2026; 34% yes; 228 applicable responses.
- The draft uses MGMA's wording, "applicable responses", rather than "leaders".

**G3, `g3-community-answer-queue.md`:** 10 live threads, status draft-not-posted.
- Sources: Bubble forum 5, Replit forum 3, Softr 1, Vercel 1. Reddit and Quora refused automated access, so none are included.
- Each answer quotes the vendor's own words with a date, includes one link and discloses the affiliation.
- Items 6–8 are hiring threads and are lower priority.

**G4, `g4-baa-matrix-pitches.md`:** 5 pitches, status draft-not-sent.
- Recipients: Blaze, AxonBuild, VertiComply, ConsentLoom, Kissflow. All five cite Knack; two also cite Specode. None of the pages I could open cite HIPAA Vault.
- VertiComply sells a HIPAA app builder and may be a competitor. Consider dropping it.

## Not in the spec, noticed along the way

- The headers on datasets.paloaltohealthlabs.com and thebrief.paloaltohealthlabs.com still link to the calendar directly. They live in other repos. A one-line change in each would point them at `https://paloaltohealthlabs.com/book/scoping/`.
- Pages still carry an old inline listener for `a[href*="calendar.app.google"]`. It now matches nothing and is harmless. `/book/` fires `book_call_click` instead, so there is no double count.

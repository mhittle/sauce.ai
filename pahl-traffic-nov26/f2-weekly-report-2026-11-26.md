# Weekly report #1: PAHL traffic, conversion and attribution (prepared Nov 26, 2026)

Real numbers only. A figure I could not read is marked NOT CHECKED with the reason. Clicks are not bookings.

**Windows:**
- GA4: none read. I have no access to property G-WHDQHLHXJ4.
- GSC: none read. I have no Search Console access.
- The new events start when PR #225 is deployed. No week of post-change data exists yet.

## Per offer

| Offer | Booking-button clicks (`book_call_click`) | Intake form starts | Leads (`generate_lead`) | ACTUAL bookings |
|---|---|---|---|---|
| Fabrica | 0 since change (not deployed) | NOT CHECKED (GA4 access) | NOT CHECKED (GA4 access) | NOT CHECKED: calendar data not accessible |
| Practice CTO | 0 since change (not deployed) | n/a (no practice intake form) | NOT CHECKED | NOT CHECKED: calendar data not accessible |
| Startup CTO (scoping) | 0 since change (not deployed) | NOT CHECKED | NOT CHECKED | NOT CHECKED: calendar data not accessible |

**Pre-change baseline** (from the spec's GA4 email snapshot, Oct 28 – Nov 24, 2026; not re-verified):
- Sitewide, not split by offer: book_call_click 14, form_start 13, generate_lead 3, fabrica_cta_click 2.
- These are clicks and leads, not bookings.

## Stack Checker

| starts | completions | report requests |
|---|---|---|
| 0 since change (not deployed) | 0 | 0 |

## Top 10 landing pages with booking clicks

NOT CHECKED (GA4 access). The spec's snapshot listed the top pages by views:

| Page | Views |
|---|---|
| homepage | 306 |
| Co-Scientist hub | 140 |
| Datasets | 122 |
| Blog | 75 |
| /fabrica/ | 66 |
| Vibe Coding for Physicians | 44 |

## Search Console

- **Clicks and impressions** for the Fabrica and practice-CTO clusters: NOT CHECKED (no GSC access).
- **Indexed counts:** NOT CHECKED. Nov 23 baselines: main 282 discovered, datasets 1,502 discovered; property 625 indexed and 464 not indexed.

## How to fill this from next week (once #225 is live)

**GA4 → Explore → Free form:**
1. Rows: `Event name`, plus custom dimensions `offer` and `source_page`. They must first be registered as event-scoped custom dimensions in GA4 Admin, along with `cluster`, `source`, `builder` and `gap_count`.
2. Filter: event name in {book_call_click, form_start, generate_lead, stack_checker_start, stack_checker_complete, stack_checker_report_request, stack_checker_book_click, fabrica_cta_click}.
3. Note on form_start: GA4's own enhanced-measurement form_start also fires on these pages. Count only the rows where `source` is set.

**Bookings:** count events on each Google Calendar appointment schedule once the three schedules exist (B1). Until then, every booking lands on the one shared schedule and cannot be split by offer.

# Workstream E: GSC 404 cleanup (Nov 26, 2026)

**E1, flagged URL list: PARKED.**
- The "Not found (404)" list exists only in signed-in Search Console (property paloaltohealthlabs.com). I have no GSC access.
- Unblock: export Pages → Not found (404) with first-detected dates and drop the CSV here. Classification and fixes then take minutes.

**E2, live crawl (done Nov 26, 2026; results in `e2-sitemap-crawl.csv`):**

| Sitemap | URLs in sitemap | Checked | 200 with content | Redirected | Non-200 | noindex |
|---|---|---|---|---|---|---|
| paloaltohealthlabs.com/sitemap.xml | 328 | 328 (all) | 328 | 0 | 0 | 0 |
| datasets.paloaltohealthlabs.com/sitemap.xml | 1,504 | 151 (10% random sample, seed 26) | 151 | 0 | 0 | 0 |

**Other sources checked** (all return 200):
- 430 site URLs referenced in llms.txt, llms-full.txt, every XML feed/sitemap, and the pages' JSON-LD and og: tags.
- 18,345 internal links across the repo, with zero broken.

**History check:** git history shows only 3 deleted public files (`offerings/electrokare-bdad0b.html`, a template, a staged placeholder). The FTP deploy runs with `dangerous-clean-slate: false`, so deleted files stay on the server and do not 404. The flagged URLs are therefore not pages the site removed.

**Candidate for the flagged list (not changed; E3 allows fixes only for flagged URLs):**
- My research agent guessed `/guides/vibe-coded-hipaa/is-supabase-hipaa-compliant/` and got a 404. The real page is `/guides/vibe-coded-hipaa/supabase/`. The same pattern applies to `/base44/`, `/claude/` and `/firebase/`.
- If GSC lists any `is-<tool>-hipaa-compliant/` slug for these tools, the fix is a 301 (class b).

**E3:** blocked on E1.

**E4, resubmit sitemaps in GSC and Bing Webmaster, and request validation: PARKED.** It needs the owner's GSC and Bing logins. Baselines (Nov 23): main 282 discovered, datasets 1,502 discovered.

# sauce.ai/scribe — bug log

Log every owner-reported bug here with a new sequential ID and status `open`
BEFORE doing anything else with it (even a 30-second fix). Statuses: `open` ·
`in-progress` · `attempted` (tried, not fully fixed — note the live
workaround) · `resolved`.

Format:
```
### SCR-NNN — <short title>
- **Status:** open
- **Reported:** YYYY-MM-DD by <user|session>
- **Description:** …
- **Notes / fix:** …
- **PR:** #NNN
```

---

## Open

_None._

## In progress

### SCR-001 — Login loops back to the sign-in screen on Railway domains
- **Status:** in-progress
- **Reported:** 2026-06-12 by owner
- **Description:** Google sign-in completes but the app returns to the login
  screen. Root cause: web and api run on different `*.up.railway.app`
  subdomains, and `up.railway.app` is on the Public Suffix List, so the
  browser treats them as cross-site and refuses to send the API's
  SameSite=Lax session cookie on the web app's fetches → `/auth/me` 401s.
- **Notes / fix:** add a bearer-token session path: OAuth callback passes the
  session token to the web app in the URL fragment; web stores it and sends
  `Authorization: Bearer`. Cookie path kept for a future same-site custom
  domain. PR pending.
- **PR:** TBD

## Attempted (live workarounds / ongoing risk)

_None._

## Resolved

_None yet._

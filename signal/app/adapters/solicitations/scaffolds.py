"""Registered-but-unimplemented solicitation adapters for the state and
national platforms (PRD PlanHub track). Each carries its real public entry
point + access notes and fails safe (raises) until a live-validated scraper is
built — the same honesty pattern as the permit `PaidApiAdapter` stub and the
"validate field maps on first pull" seed notes.

These are mostly HTML portals (not clean APIs like SAM.gov), so finishing them
needs requests+parser or Playwright, careful ToS/robots compliance, and (for
some) a free login. Roadmap: "Bid/plans — state/national adapters".
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from .base import NormalizedSolicitation, SolicitationAdapter


class _ScaffoldAdapter(SolicitationAdapter):
    entry_url = ""
    access_note = ""

    def fetch_raw(self, since: Optional[date] = None) -> Iterable[dict]:
        raise NotImplementedError(
            f"{self.source_type} adapter not yet implemented. "
            f"Entry: {self.entry_url}. {self.access_note} "
            f"See signal/roadmap.md (Bid/plans adapters).")

    def parse(self, record: dict) -> Optional[NormalizedSolicitation]:
        raise NotImplementedError


# --- State platforms -------------------------------------------------------
class TexasESBDAdapter(_ScaffoldAdapter):
    source_type = "esbd-tx"
    entry_url = "https://www.txsmartbuy.gov/esbd"
    access_note = "Texas Electronic State Business Daily; public, no login. HTML/search."


class FloridaVBSAdapter(_ScaffoldAdapter):
    source_type = "vbs-fl"
    entry_url = "https://vendor.myfloridamarketplace.com/"
    access_note = "Florida Vendor Bid System (MFMP); public. HTML."


class GeorgiaGPRAdapter(_ScaffoldAdapter):
    source_type = "gpr-ga"
    entry_url = "https://ssl.doas.state.ga.us/gpr/"
    access_note = ("Georgia Procurement Registry; state + local public-works "
                   ">= $100k are posted. Public. HTML. (Ties to Atlanta facility.)")


class CalEProcureCSCRAdapter(_ScaffoldAdapter):
    """California State Contracts Register (Cal eProcure). High-value CA source
    (~330 open Posted events incl. construction, each event has downloadable
    bid documents on its detail page → feeds the scribe quote connector).

    Reverse-engineered 2026-06-30: the public Event Search
    (pages/Events-BS3/event-search.aspx) is an **InFlight NLX** SPA wrapping an
    Oracle **PeopleSoft** component. The event grid is loaded by client-side JS
    via a STATEFUL POST to
      /nlx3/psc/psfpd1/SUPPLIER/ERP/c/AUC_MANAGE_BIDS.AUC_RESP_INQ_AUC.GBL
    carrying PeopleSoft state (ICSID / ICStateNum / ICAction) seeded by an
    InFlight guest-session bootstrap (InFlightSessionID cookie). Verified with
    requests that: the component GET 404s without that bootstrap, `?useAjax=1`
    returns only the SPA shell, and the criteria form POST 400s. So plain
    requests+bs4 can't reach the data — this needs **Playwright** (drive the
    SPA, let InFlight run, read the rendered grid + paginate, click each event
    for its documents). Columns: Event ID, Event Name, Department, End Date,
    Status. No NAICS — CSCR classifies by UNSPSC/NIGP/CSI, so filter
    construction/cabinetry by keyword (or the classify_solicitations pass).
    See signal/roadmap.md (CSCR / Cal eProcure adapter)."""
    source_type = "cscr"
    entry_url = "https://caleprocure.ca.gov/pages/Events-BS3/event-search.aspx"
    access_note = ("California State Contracts Register; public, no login. "
                   "InFlight-NLX-wrapped PeopleSoft SPA — needs Playwright "
                   "(stateful POST, not a clean API/HTML list).")


# --- National non-gov aggregators ------------------------------------------
class BidNetDirectAdapter(_ScaffoldAdapter):
    source_type = "bidnet"
    entry_url = "https://www.bidnetdirect.com/solicitations/open-bids"
    access_note = ("Aggregates 1000s of agencies across 50 states. Open-bid "
                   "listings browsable; full docs partly gated behind free reg. "
                   "Respect ToS.")


class DemandStarAdapter(_ScaffoldAdapter):
    source_type = "demandstar"
    entry_url = "https://www.demandstar.com/browse-bids"
    access_note = ("National public-agency aggregator; free account tier. "
                   "Respect ToS.")


SCAFFOLD_ADAPTERS = (
    TexasESBDAdapter, FloridaVBSAdapter, GeorgiaGPRAdapter,
    CalEProcureCSCRAdapter,
    BidNetDirectAdapter, DemandStarAdapter,
)

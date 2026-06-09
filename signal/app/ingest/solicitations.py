"""Solicitation ingest orchestrator (PRD PlanHub track).

Pull a bid-board source -> idempotent upsert into `solicitations` +
`solicitation_documents` -> log an IngestRun (jurisdiction_id NULL,
source_type set). DB-backed; the pure adapter logic is unit-tested separately.
Document *contents* (PDF download/parse) are a later roadmap item — we store
the attachment metadata + URLs now.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..adapters.solicitations.registry import build_solicitation_adapter
from ..config import get_settings


def _upsert(sess: Session, source_type: str, norm) -> int:
    d = norm.as_dict()
    sol_id = sess.execute(text("""
        INSERT INTO solicitations (source_type, source_id, title, agency,
            description, naics, category, state, place_city, estimated_value,
            posted_date, due_date, status, source_url, raw_payload, last_seen)
        VALUES (:st, :sid, :title, :agency, :descr, :naics, :cat, :state, :city,
            :val, :posted, :due, :status, :url, CAST(:raw AS jsonb), now())
        ON CONFLICT (source_type, source_id) DO UPDATE SET
            title = EXCLUDED.title, status = EXCLUDED.status,
            due_date = EXCLUDED.due_date, estimated_value = EXCLUDED.estimated_value,
            raw_payload = EXCLUDED.raw_payload, last_seen = now()
        RETURNING id
    """), {
        "st": source_type, "sid": d["source_id"], "title": d.get("title"),
        "agency": d.get("agency"), "descr": d.get("description"),
        "naics": d.get("naics"), "cat": d.get("category"),
        "state": d.get("state"), "city": d.get("place_city"),
        "val": d.get("estimated_value"), "posted": d.get("posted_date"),
        "due": d.get("due_date"), "status": d.get("status"),
        "url": d.get("source_url"),
        "raw": json.dumps(d.get("raw_payload") or {}, default=str),
    }).scalar()

    for doc in d.get("documents") or []:
        if not doc.get("url"):
            continue
        sess.execute(text("""
            INSERT INTO solicitation_documents (solicitation_id, name, url, doc_type)
            VALUES (:sid, :name, :url, :dt)
            ON CONFLICT (solicitation_id, url) DO NOTHING
        """), {"sid": sol_id, "name": doc.get("name"), "url": doc["url"],
               "dt": doc.get("doc_type", "attachment")})
    return sol_id


def run_ingest_adapter(sess: Session, source_label: str, adapter,
                       since: date | None = None) -> dict:
    """Run any solicitation adapter -> upsert + IngestRun. Shared by SAM.gov
    and the config-driven procurement sources."""
    run_id = sess.execute(text("""
        INSERT INTO ingest_runs (jurisdiction_id, source_type, status)
        VALUES (NULL, :st, 'running') RETURNING id
    """), {"st": source_label}).scalar()
    sess.commit()

    fetched = upserted = 0
    try:
        for norm in adapter.pull(since):
            fetched += 1
            _upsert(sess, source_label, norm)
            upserted += 1
            if upserted % 200 == 0:
                sess.commit()
        sess.commit()
        sess.execute(text("""
            UPDATE ingest_runs SET status='ok', finished_at=now(),
                permits_fetched=:f, permits_upserted=:u WHERE id=:id
        """), {"f": fetched, "u": upserted, "id": run_id})
        sess.commit()
        status = "ok"
    except Exception as exc:  # noqa: BLE001 - boundary: log and continue
        sess.rollback()
        sess.execute(text("""
            UPDATE ingest_runs SET status='error', finished_at=now(), error=:e,
                permits_fetched=:f WHERE id=:id
        """), {"e": str(exc)[:1000], "f": fetched, "id": run_id})
        sess.commit()
        status = "error"

    return {"run_id": run_id, "status": status, "fetched": fetched,
            "upserted": upserted,
            "at": datetime.now(timezone.utc).isoformat()}


def run_solicitation_ingest(sess: Session, source_type: str,
                            since: date | None = None) -> dict:
    """Built-in source types (samgov + scaffolds)."""
    settings = get_settings()
    adapter = build_solicitation_adapter(
        source_type, samgov_api_key=settings.samgov_api_key)
    return run_ingest_adapter(sess, source_type, adapter, since)

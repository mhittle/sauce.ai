"""Ingest orchestrator (PRD §6 scheduling/hygiene, §9 daily run).

For one jurisdiction: pull -> idempotent upsert of permits -> dedup into
projects -> recompute derived signals -> score against the default rule ->
log an IngestRun row. DB-backed; the pure logic it leans on
(adapters.normalize, ingest.dedup, signals.derived, signals.scoring) is
unit-tested separately.

Designed to tolerate a partially-migrated DB and bad source rows: a single
bad record never aborts the run.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..adapters.registry import build_adapter
from ..config import get_settings
from ..signals.derived import ProjectContext, compute_project_signals
from ..signals.scoring import default_rule, is_flagged, score_project
from .dedup import dedup_confidence, dedup_key


def _juris_dict(row) -> dict:
    return {
        "id": row.id, "slug": row.slug, "name": row.name,
        "source_type": row.source_type, "platform_domain": row.platform_domain,
        "dataset_id": row.dataset_id, "field_map": row.field_map or {},
        "adapter_config": row.adapter_config or {},
    }


def _upsert_permit(sess: Session, juris_id: int, norm) -> int:
    """Insert or update a permit; return its project_id (creating one)."""
    d = norm.as_dict()
    key_type, key_val = dedup_key(d)

    project_id = sess.execute(text("""
        SELECT p.project_id FROM permits p
        WHERE p.jurisdiction_id = :jid AND p.permit_id = :pid
    """), {"jid": juris_id, "pid": d["permit_id"]}).scalar()

    if project_id is None:
        project_id = sess.execute(text("""
            SELECT id FROM projects
            WHERE jurisdiction_id = :jid AND (
                (:apn <> '' AND parcel_apn = :apn) OR
                (primary_address = :addr AND :addr <> ''))
            LIMIT 1
        """), {"jid": juris_id, "apn": d.get("parcel_apn") or "",
               "addr": d.get("address") or ""}).scalar()

    if project_id is None:
        project_id = sess.execute(text("""
            INSERT INTO projects (jurisdiction_id, primary_address, parcel_apn,
                                  dedup_confidence)
            VALUES (:jid, :addr, :apn, :conf) RETURNING id
        """), {"jid": juris_id, "addr": d.get("address"),
               "apn": d.get("parcel_apn"),
               "conf": dedup_confidence(key_type)}).scalar()

    sess.execute(text("""
        INSERT INTO permits (jurisdiction_id, project_id, permit_id, source_url,
            permit_type, permit_subtype, work_description, valuation, status,
            application_date, issue_date, expiration_date, last_status_change,
            final_date, address, parcel_apn, owner_name, applicant,
            contractor_name, contractor_license, use_type, occupancy, sqft,
            units, fees, raw_payload, last_seen)
        VALUES (:jid, :proj, :pid, :url, :ptype, :psub, :desc, :val, :status,
            :appd, :issd, :expd, :lsc, :find, :addr, :apn, :owner, :appl,
            :gc, :lic, :use, :occ, :sqft, :units, :fees,
            CAST(:raw AS jsonb), now())
        ON CONFLICT (jurisdiction_id, permit_id) DO UPDATE SET
            status = EXCLUDED.status,
            last_status_change = EXCLUDED.last_status_change,
            expiration_date = EXCLUDED.expiration_date,
            final_date = EXCLUDED.final_date,
            valuation = EXCLUDED.valuation,
            raw_payload = EXCLUDED.raw_payload,
            last_seen = now()
    """), _permit_params(juris_id, project_id, d))

    if d.get("latitude") is not None and d.get("longitude") is not None:
        sess.execute(text("""
            UPDATE permits SET geom = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
            WHERE jurisdiction_id = :jid AND permit_id = :pid
        """), {"lng": d["longitude"], "lat": d["latitude"],
               "jid": juris_id, "pid": d["permit_id"]})
    return project_id


def _permit_params(juris_id, project_id, d) -> dict:
    import json
    return {
        "jid": juris_id, "proj": project_id, "pid": d["permit_id"],
        "url": d.get("source_url"), "ptype": d.get("permit_type"),
        "psub": d.get("permit_subtype"), "desc": d.get("work_description"),
        "val": d.get("valuation"), "status": d.get("status"),
        "appd": d.get("application_date"), "issd": d.get("issue_date"),
        "expd": d.get("expiration_date"), "lsc": d.get("last_status_change"),
        "find": d.get("final_date"), "addr": d.get("address"),
        "apn": d.get("parcel_apn"), "owner": d.get("owner_name"),
        "appl": d.get("applicant"), "gc": d.get("contractor_name"),
        "lic": d.get("contractor_license"), "use": d.get("use_type"),
        "occ": d.get("occupancy"), "sqft": d.get("sqft"),
        "units": d.get("units"), "fees": d.get("fees"),
        "raw": json.dumps(d.get("raw_payload") or {}, default=str),
    }


def recompute_project(sess: Session, project_id: int, *, today: date,
                      known_contractors: frozenset[str], rule: dict) -> None:
    rows = sess.execute(text("""
        SELECT work_description, permit_type, permit_subtype, use_type,
               occupancy, status, valuation, issue_date, expiration_date,
               last_status_change, final_date, contractor_name,
               ST_Y(geom) AS latitude, ST_X(geom) AS longitude
        FROM permits WHERE project_id = :pid
    """), {"pid": project_id}).mappings().all()
    permits = [dict(r) for r in rows]
    for p in permits:
        p["valuation"] = float(p["valuation"]) if p["valuation"] is not None else None

    inspections = [dict(r) for r in sess.execute(text("""
        SELECT i.inspection_type, i.inspection_date, i.result
        FROM inspections i JOIN permits p ON p.id = i.permit_id
        WHERE p.project_id = :pid
    """), {"pid": project_id}).mappings().all()]

    s = get_settings()
    ctx = ProjectContext(
        permits=permits, inspections=inspections, today=today,
        facility=(s.facility_lat, s.facility_lng),
        shippable_radius_mi=s.shippable_radius_mi,
        known_contractors=known_contractors,
    )
    values = compute_project_signals(ctx)
    score = score_project(values, rule["weights"])
    values["lead_score"] = score

    _write_signals(sess, project_id, values)
    sess.execute(text("""
        UPDATE projects SET lead_score = :score, category = :cat,
            value_tier = :tier, status = CASE WHEN status='new' AND :flag
                THEN 'new' ELSE status END, updated_at = now()
        WHERE id = :pid
    """), {"score": score, "cat": values.get("category"),
           "tier": values.get("value_tier"),
           "flag": is_flagged(score, rule["threshold"]), "pid": project_id})


def _write_signals(sess: Session, project_id: int, values: dict) -> None:
    import json
    for sid, val in values.items():
        cols = {"b": None, "n": None, "t": None, "j": None}
        if isinstance(val, bool):
            cols["b"] = val
        elif isinstance(val, (int, float)):
            cols["n"] = val
        elif isinstance(val, str):
            cols["t"] = val
        else:
            cols["j"] = json.dumps(val)
        sess.execute(text("""
            INSERT INTO project_signals (project_id, signal_id, value_bool,
                value_num, value_text, value_json, computed_at)
            VALUES (:pid, :sid, :b, :n, :t, CAST(:j AS jsonb), now())
            ON CONFLICT (project_id, signal_id) DO UPDATE SET
                value_bool = EXCLUDED.value_bool, value_num = EXCLUDED.value_num,
                value_text = EXCLUDED.value_text, value_json = EXCLUDED.value_json,
                computed_at = now()
        """), {"pid": project_id, "sid": sid, **cols})


def run_ingest(sess: Session, jurisdiction_row, since: date | None = None) -> dict:
    settings = get_settings()
    juris = _juris_dict(jurisdiction_row)
    run_id = sess.execute(text("""
        INSERT INTO ingest_runs (jurisdiction_id, source_type, status)
        VALUES (:jid, :st, 'running') RETURNING id
    """), {"jid": juris["id"], "st": juris["source_type"]}).scalar()
    sess.commit()

    known = frozenset(
        r[0] for r in sess.execute(text(
            "SELECT normalized_name FROM contractors WHERE in_crm = TRUE")).all())
    rule = default_rule()
    fetched = upserted = 0
    touched: set[int] = set()
    try:
        adapter = build_adapter(
            juris, socrata_token=settings.socrata_app_token,
            paid_api_key=settings.paid_api_key)
        for norm in adapter.pull(since):
            fetched += 1
            pid = _upsert_permit(sess, juris["id"], norm)
            touched.add(pid)
            upserted += 1
            if upserted % 500 == 0:
                sess.commit()
        sess.commit()

        today = date.today()
        for pid in touched:
            recompute_project(sess, pid, today=today,
                              known_contractors=known, rule=rule)
        sess.commit()

        sess.execute(text("""
            UPDATE ingest_runs SET status='ok', finished_at=now(),
                permits_fetched=:f, permits_upserted=:u, projects_touched=:p
            WHERE id=:id
        """), {"f": fetched, "u": upserted, "p": len(touched), "id": run_id})
        sess.execute(text(
            "UPDATE jurisdictions SET last_good_pull = now() WHERE id = :id"),
            {"id": juris["id"]})
        sess.commit()
        status = "ok"
    except Exception as exc:  # noqa: BLE001 - boundary: log and continue fleet
        sess.rollback()
        sess.execute(text("""
            UPDATE ingest_runs SET status='error', finished_at=now(), error=:e,
                permits_fetched=:f WHERE id=:id
        """), {"e": str(exc)[:1000], "f": fetched, "id": run_id})
        sess.commit()
        status = "error"

    return {"run_id": run_id, "status": status, "fetched": fetched,
            "upserted": upserted, "projects_touched": len(touched),
            "at": datetime.now(timezone.utc).isoformat()}

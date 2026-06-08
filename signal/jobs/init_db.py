"""Bring a fresh database to the current schema and seed it.

    python jobs/init_db.py

Idempotent: applies seed/schema.sql, upserts the signal catalog from the
in-code registry, loads seed jurisdictions from seed/jurisdictions.csv, and
ensures the default triage rule exists. Safe to re-run.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401
import json
import pathlib

from sqlalchemy import text

from app.db import engine, session_factory
from app.signals.registry import SIGNALS
from app.signals.scoring import default_rule

ROOT = pathlib.Path(__file__).resolve().parents[1]


def apply_schema(conn):
    conn.exec_driver_sql((ROOT / "seed" / "schema.sql").read_text())


def seed_signals(sess):
    for s in SIGNALS:
        sess.execute(text("""
            INSERT INTO signal_catalog (id, label, tier, datatype, how_derived,
                is_facet)
            VALUES (:id, :label, :tier, :datatype, :how, :facet)
            ON CONFLICT (id) DO UPDATE SET label=EXCLUDED.label,
                tier=EXCLUDED.tier, datatype=EXCLUDED.datatype,
                how_derived=EXCLUDED.how_derived, is_facet=EXCLUDED.is_facet
        """), {"id": s.id, "label": s.label, "tier": s.tier,
               "datatype": s.datatype, "how": s.how_derived, "facet": s.is_facet})


def seed_jurisdictions(sess):
    path = ROOT / "seed" / "jurisdictions.json"
    if not path.exists():
        return
    for row in json.loads(path.read_text()):
        sess.execute(text("""
            INSERT INTO jurisdictions (slug, name, state, county,
                source_type, platform_domain, dataset_id, field_map,
                adapter_config, known_lag_days, active, notes)
            VALUES (:slug, :name, :state, :county, :stype, :domain, :ds,
                CAST(:fmap AS jsonb), CAST(:cfg AS jsonb), :lag, :active, :notes)
            ON CONFLICT (slug) DO UPDATE SET field_map=EXCLUDED.field_map,
                adapter_config=EXCLUDED.adapter_config,
                platform_domain=EXCLUDED.platform_domain,
                dataset_id=EXCLUDED.dataset_id, notes=EXCLUDED.notes
        """), {
            "slug": row["slug"], "name": row["name"], "state": row.get("state"),
            "county": row.get("county"), "stype": row.get("source_type", "socrata"),
            "domain": row.get("platform_domain"), "ds": row.get("dataset_id"),
            "fmap": json.dumps(row.get("field_map") or {}),
            "cfg": json.dumps(row.get("adapter_config") or {}),
            "lag": row.get("known_lag_days"),
            "active": row.get("active", True), "notes": row.get("notes")})


def seed_default_rule(sess):
    exists = sess.execute(text(
        "SELECT 1 FROM rules WHERE name = :n"),
        {"n": default_rule()["name"]}).scalar()
    if exists:
        return
    r = default_rule()
    sess.execute(text("""
        INSERT INTO rules (name, profile, weights, threshold)
        VALUES (:n, :p, CAST(:w AS jsonb), :t)
    """), {"n": r["name"], "p": r["profile"],
           "w": json.dumps(r["weights"]), "t": r["threshold"]})


def main():
    with engine().begin() as conn:
        apply_schema(conn)
    sess = session_factory()()
    try:
        seed_signals(sess)
        seed_jurisdictions(sess)
        seed_default_rule(sess)
        sess.commit()
        print("init_db: schema applied, signals + jurisdictions + rule seeded.")
    finally:
        sess.close()


if __name__ == "__main__":
    main()

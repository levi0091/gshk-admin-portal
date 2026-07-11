"""Backfill real created_at / updated_at onto migrated entities and persons.

The PBI-38/40 ETL never mapped a record-creation date, so every migrated row
fell through to the `now()` default and shows the date the ETL happened to run
(8 Jul 2026) rather than anything real.

Sources of truth:
  created_at  <- Viewpoint RefMaster.DateEntered — when GSHK actually entered the
                 record. Populated for 12,826 of 12,827 RefMaster rows (every
                 company and every person). Cl_DateOpen is 100% NULL, unusable.
  updated_at  <- the newest imported Viewpoint EventLog entry for that record
                 (audit_log.source_keycode = RefMaster.RefCode), i.e. the last
                 time anything actually happened to it. Falls back to created_at
                 where a record has no events.

NOTE: entities and persons carry a `trg_set_updated_at` BEFORE UPDATE trigger
that forces updated_at = now(). It is disabled for the duration of the write,
otherwise the backfill silently overwrites itself with the current timestamp.

Idempotent — re-running produces the same result. Safe to run against DEV or PROD.

    python -m etl.backfill_timestamps [--dry-run]
"""
import argparse
import os
import sys

import psycopg2
from psycopg2.extras import execute_values
from sqlalchemy import text

from etl.db import get_viewpoint_engine

REFMASTER_QUERY = text("""
    SELECT RefCode, DateEntered
    FROM RefMaster
    WHERE DateEntered IS NOT NULL
""")


def fetch_date_entered() -> list[tuple[str, object]]:
    engine = get_viewpoint_engine()
    with engine.connect() as conn:
        return [(r.RefCode, r.DateEntered) for r in conn.execute(REFMASTER_QUERY)]


def backfill(dry_run: bool = False) -> dict:
    rows = fetch_date_entered()
    print(f"RefMaster rows with DateEntered: {len(rows)}")

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL not set")

    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    stats = {}
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '600s'")
            cur.execute("""
                CREATE TEMP TABLE vp_created (
                  refcode text PRIMARY KEY,
                  date_entered timestamptz NOT NULL
                ) ON COMMIT DROP
            """)
            execute_values(
                cur,
                "INSERT INTO vp_created (refcode, date_entered) VALUES %s "
                "ON CONFLICT (refcode) DO NOTHING",
                rows,
                page_size=1000,
            )

            # The updated_at trigger would stamp now() over everything we write.
            cur.execute("ALTER TABLE entities DISABLE TRIGGER trg_set_updated_at")
            cur.execute("ALTER TABLE persons  DISABLE TRIGGER trg_set_updated_at")

            # Last real activity per Viewpoint record, from the imported EventLog.
            cur.execute("""
                CREATE TEMP TABLE vp_last_event AS
                SELECT source_keycode AS refcode, max(created_at) AS last_event
                FROM audit_log
                WHERE source_keycode IS NOT NULL
                GROUP BY source_keycode
            """)
            cur.execute("CREATE INDEX ON vp_last_event (refcode)")

            for table in ("entities", "persons"):
                cur.execute(f"""
                    UPDATE {table} t
                    SET created_at = v.date_entered,
                        updated_at = GREATEST(
                            v.date_entered,
                            COALESCE(le.last_event, v.date_entered)
                        )
                    FROM vp_created v
                    LEFT JOIN vp_last_event le ON le.refcode = v.refcode
                    WHERE t.vp_source_key = v.refcode
                      AND (t.created_at IS DISTINCT FROM v.date_entered
                           OR t.updated_at IS DISTINCT FROM GREATEST(
                                v.date_entered,
                                COALESCE(le.last_event, v.date_entered)))
                """)
                stats[table] = cur.rowcount
                print(f"  {table}: {cur.rowcount} rows updated")

            cur.execute("ALTER TABLE entities ENABLE TRIGGER trg_set_updated_at")
            cur.execute("ALTER TABLE persons  ENABLE TRIGGER trg_set_updated_at")

        if dry_run:
            conn.rollback()
            print("DRY RUN — rolled back")
        else:
            conn.commit()
            print("committed")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    backfill(dry_run=args.dry_run)

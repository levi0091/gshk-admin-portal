"""Backfill the consistent audit context onto the imported Viewpoint rows.

Migration 012 added `action_label` and `company_name` and the
`audit_event_types` registry. The 226k rows imported from the Viewpoint EventLog
predate all of it, so they still read as "LEGACY_VP_EVENT" with no company and,
in many cases, an unusable change value.

This makes every imported row answer the same questions a native G-FlowDesk row
does — what action, on which company, old -> new, by whom:

  action_label      <- audit_event_types.name for the row's event_code. GENERIC
                       by design ("Change Master File Details"), never the
                       per-record description Viewpoint stored
                       ("Master File Details of Miss Ilze TSERKEZIS Changed"),
                       so the same action groups and filters together.
  company_name      <- the entity (or person) the event is about, resolved via
                       case_id, else via source_keycode -> vp_source_key.
  user_display_name <- created_by (the Viewpoint user code) where missing.
  old/new_value     <- collapsed where Viewpoint packed a whole field map into
                       one string. "AdNrS1=2311; AdNrS2=2311; ... AdNrSU=2311"
                       is 15 fields all set to the same value; that is one
                       change, so it is stored as "2311" and the raw map is kept
                       in metadata.

Idempotent. Re-running changes nothing.

    python -m etl.backfill_audit_context [--dry-run]
"""
import argparse
import os
import sys

import psycopg2


def backfill(dry_run: bool = False) -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL not set")

    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '900s'")

            # 1. Generic action name from the registry (both sources).
            cur.execute("""
                UPDATE audit_log a
                SET action_label = t.name
                FROM audit_event_types t
                WHERE a.event_code = t.code
                  AND a.action_label IS DISTINCT FROM t.name
            """)
            print(f"  action_label: {cur.rowcount}")

            # Rows whose action_type is itself the code (older native rows).
            cur.execute("""
                UPDATE audit_log a
                SET action_label = t.name,
                    event_code = COALESCE(a.event_code, t.code)
                FROM audit_event_types t
                WHERE a.event_code IS NULL
                  AND a.action_type = t.code
                  AND a.action_label IS NULL
            """)
            print(f"  action_label (native by action_type): {cur.rowcount}")

            # 2. Company name — via case_id first, then the Viewpoint key.
            cur.execute("""
                UPDATE audit_log a
                SET company_name = e.company_name
                FROM entities e
                WHERE a.case_id = e.id
                  AND a.company_name IS DISTINCT FROM e.company_name
            """)
            print(f"  company_name (via case_id): {cur.rowcount}")

            cur.execute("""
                UPDATE audit_log a
                SET company_name = e.company_name
                FROM entities e
                WHERE a.company_name IS NULL
                  AND a.case_id IS NULL
                  AND a.source_keycode = e.vp_source_key
            """)
            print(f"  company_name (via source_keycode -> entity): {cur.rowcount}")

            # Person-scoped Viewpoint events (compliance, identity register...).
            cur.execute("""
                UPDATE audit_log a
                SET company_name = p.full_name
                FROM persons p
                WHERE a.company_name IS NULL
                  AND a.source_keycode = p.vp_source_key
            """)
            print(f"  subject name (via source_keycode -> person): {cur.rowcount}")

            # 3. Actor — Viewpoint rows carry the user code in created_by only.
            cur.execute("""
                UPDATE audit_log
                SET user_display_name = created_by
                WHERE user_display_name IS NULL AND created_by IS NOT NULL
            """)
            print(f"  user_display_name from created_by: {cur.rowcount}")

            # 4. Collapse "k=v; k=v; ..." maps where every value is identical.
            #    Keep the raw string in metadata so nothing is lost.
            cur.execute("""
                WITH parsed AS (
                  SELECT id,
                         new_value,
                         array_agg(DISTINCT split_part(trim(kv), '=', 2)) AS vals
                  FROM audit_log,
                       LATERAL unnest(string_to_array(new_value, ';')) AS kv
                  WHERE new_value LIKE '%=%;%'
                  GROUP BY id, new_value
                )
                UPDATE audit_log a
                SET new_value = p.vals[1],
                    metadata = COALESCE(a.metadata, '{}'::jsonb)
                               || jsonb_build_object('raw_new_value', p.new_value)
                FROM parsed p
                WHERE a.id = p.id
                  AND array_length(p.vals, 1) = 1
                  AND p.vals[1] <> ''
            """)
            print(f"  collapsed uniform k=v blobs: {cur.rowcount}")

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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    backfill(dry_run=ap.parse_args().dry_run)

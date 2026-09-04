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
  module            <- which surface the change belongs to. Viewpoint has only
                       two of the five (a company edit, a person edit); it never
                       recorded a NAR1 case workflow, a document or a CR filing,
                       so those stay NULL on an imported row rather than being
                       invented.
  subject_*          <- WHICH RECORD: kind, id, name and the reference a human
                       quotes (BRN / identity number). Migration 034 does this
                       once; these steps repeat it after a fresh import, which
                       is the only time new unlabelled rows appear.
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
import time

import psycopg2

_STEPS: list[tuple[str, str]] = [
    # Generic action name from the registry (both sources).
    ("action_label", """
        UPDATE audit_log a
        SET action_label = t.name
        FROM audit_event_types t
        WHERE a.event_code = t.code
          AND a.action_label IS DISTINCT FROM t.name
    """),
    # Older native rows where action_type is itself the code.
    ("action_label (native by action_type)", """
        UPDATE audit_log a
        SET action_label = t.name,
            event_code = COALESCE(a.event_code, t.code)
        FROM audit_event_types t
        WHERE a.event_code IS NULL
          AND a.action_type = t.code
          AND a.action_label IS NULL
    """),
    ("company_name (via case_id)", """
        UPDATE audit_log a
        SET company_name = e.company_name
        FROM entities e
        WHERE a.case_id = e.id
          AND a.company_name IS DISTINCT FROM e.company_name
    """),
    ("company_name (via source_keycode)", """
        UPDATE audit_log a
        SET company_name = e.company_name
        FROM entities e
        WHERE a.company_name IS NULL
          AND a.case_id IS NULL
          AND a.source_keycode = e.vp_source_key
    """),
    # Person-scoped Viewpoint events (compliance, identity register...).
    ("subject name (via person)", """
        UPDATE audit_log a
        SET company_name = p.full_name
        FROM persons p
        WHERE a.company_name IS NULL
          AND a.source_keycode = p.vp_source_key
    """),
    ("actor from created_by", """
        UPDATE audit_log
        SET user_display_name = created_by
        WHERE user_display_name IS NULL AND created_by IS NOT NULL
    """),
    # WHICH RECORD the event is about (migration 034). A RefCode resolves to an
    # entity OR a person; resolving it against `entities` alone is what left
    # every person-scoped Viewpoint event printing a raw key nobody can read.
    ("subject (via entity keycode)", """
        UPDATE audit_log a
        SET subject_kind = 'company',
            subject_id   = e.id,
            subject_ref  = e.br_number,
            module       = 'body_corporate'
        FROM entities e
        WHERE a.subject_kind IS NULL
          AND a.source_keycode = e.vp_source_key
    """),
    ("subject (via person keycode)", """
        UPDATE audit_log a
        SET subject_kind = 'person',
            subject_id   = p.id,
            module       = 'natural_person'
        FROM persons p
        WHERE a.subject_kind IS NULL
          AND a.source_keycode = p.vp_source_key
    """),
    ("subject (via case_id)", """
        UPDATE audit_log a
        SET subject_kind = 'company',
            subject_id   = e.id,
            subject_ref  = e.br_number,
            module       = 'body_corporate'
        FROM entities e
        WHERE a.subject_kind IS NULL
          AND a.case_id = e.id
    """),
    # The identity document a person is quoted by, ordered exactly like
    # `person_registry`'s lateral join (migration 009).
    ("subject reference (person identity document)", """
        UPDATE audit_log a
        SET subject_ref = (
              SELECT d.id_number
              FROM person_identity_documents d
              WHERE d.person_id = a.subject_id
              ORDER BY d.is_primary DESC, d.created_at ASC
              LIMIT 1
            )
        WHERE a.subject_kind = 'person'
          AND a.subject_ref IS NULL
          AND a.subject_id IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM person_identity_documents d
            WHERE d.person_id = a.subject_id
          )
    """),
    # Collapse "k=v; k=v; ..." maps where every value is identical. The raw
    # string is kept in metadata so nothing is lost.
    ("collapse uniform k=v blobs", """
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
    """),
]


def backfill(dry_run: bool = False) -> None:
    """Run each step in its OWN transaction.

    audit_log has 226k rows and the first statement alone takes ~8 minutes. Doing
    all of them in one transaction keeps it open long enough that the connection
    is dropped mid-way ("connection already closed"), so nothing lands. Each step
    is idempotent, so per-step commits are safe and restartable.
    """
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL not set")

    for name, sql in _STEPS:
        conn = psycopg2.connect(dsn)
        conn.autocommit = False
        started = time.time()
        try:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = '1800s'")
                cur.execute(sql)
                rows = cur.rowcount
            if dry_run:
                conn.rollback()
            else:
                conn.commit()
            print(f"  {name}: {rows} rows ({time.time() - started:.1f}s)")
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    print("DRY RUN — rolled back" if dry_run else "committed")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    backfill(dry_run=ap.parse_args().dry_run)

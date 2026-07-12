"""Full Viewpoint -> G-FlowDesk load, in the only order that produces correct data.

Run this on a NEW deployment. Running the checkpoints alone is not enough: some
values cannot be known until later stages have loaded, so they are derived
afterwards. Doing them by hand is easy to forget, and forgetting them fails
quietly — every date reads as the day the ETL ran, and the audit trail shows
"LEGACY_VP_EVENT" with no company or action.

Order, and why:

  0. schema        Alembic must already be at head. audit_event_types (012) has
                   to exist before Checkpoint C, which reads it to label events.
  1. A/B/C/D       The checkpoints. A sets entities/persons created_at from
                   RefMaster.DateEntered; C writes the audit rows with their
                   generic action label and subject name.
  2. timestamps    updated_at is the newest imported EventLog entry for a record,
                   so it can only be derived once C has loaded audit_log.
  3. audit context Fills the columns for anything the checkpoints could not, and
                   collapses Viewpoint's packed field maps.
  4. storage       The documents bucket. Nothing else creates it; uploads fail
                   with no bucket.

Every step is idempotent — safe to re-run, and safe to resume after a failure.

    python -m etl.run_all              # full load
    python -m etl.run_all --dry-run    # no writes
    python -m etl.run_all --skip-checkpoints   # just the derived steps
"""
import argparse
import sys
import time

from sqlalchemy import text

from etl.db import get_supabase_engine

_REQUIRED_MIGRATION = "014"

# Tables Checkpoint C reads to make the audit trail legible. Without them it
# still loads — it just loads the useless version, which is the failure mode
# that is hardest to notice.
_REQUIRED_TABLES = {
    "audit_event_types": "the generic action name for each event code",
    "audit_field_labels": "the field captions that decode the EventString blob",
}


def _check_schema() -> None:
    """Fail loudly if Alembic is behind — a partial schema loads silently wrong."""
    engine = get_supabase_engine()
    with engine.connect() as conn:
        try:
            version = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
        except Exception:
            sys.exit("No alembic_version table — run `alembic upgrade head` first.")

        missing = [
            f"{table} ({why})"
            for table, why in _REQUIRED_TABLES.items()
            if not conn.execute(text(f"SELECT to_regclass('public.{table}')")).scalar()
        ]

    if missing:
        sys.exit(
            f"Schema is behind (alembic is at {version!r}) — missing:\n"
            + "".join(f"  - {m}\n" for m in missing)
            + f"Run `alembic upgrade head`; migration {_REQUIRED_MIGRATION} is required "
            "before the ETL, because Checkpoint C reads these to build a readable "
            "audit trail. Without them it loads, but every entry reads "
            '"LEGACY_VP_EVENT" with no action and no change.'
        )
    print(f"  schema at {version} — {', '.join(_REQUIRED_TABLES)} present")


def _ensure_storage_bucket(dry_run: bool) -> None:
    """Private bucket for document uploads. Nothing else creates it."""
    from db.supabase import get_supabase
    from services.document_service import BUCKET

    sb = get_supabase()
    existing = {b.name for b in sb.storage.list_buckets()}
    if BUCKET in existing:
        print(f"  storage bucket '{BUCKET}' already exists")
        return
    if dry_run:
        print(f"  would create private storage bucket '{BUCKET}'")
        return
    sb.storage.create_bucket(BUCKET, options={"public": False})
    print(f"  created PRIVATE storage bucket '{BUCKET}'")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-checkpoints", action="store_true",
                    help="only run the derived steps (timestamps, audit context, bucket)")
    args = ap.parse_args()

    started = time.time()

    print("\n[0/4] schema")
    _check_schema()

    if not args.skip_checkpoints:
        from etl import (run_checkpoint_a, run_checkpoint_b,
                         run_checkpoint_c, run_checkpoint_d)
        for n, mod in enumerate(
            (run_checkpoint_a, run_checkpoint_b, run_checkpoint_c, run_checkpoint_d),
            start=1,
        ):
            print(f"\n[1/4] checkpoint {chr(64 + n)}")
            mod.run(dry_run=args.dry_run)

    # updated_at is derived from the EventLog rows Checkpoint C just loaded.
    print("\n[2/4] real created_at / updated_at")
    from etl.backfill_timestamps import backfill as backfill_timestamps
    backfill_timestamps(dry_run=args.dry_run)

    print("\n[3/4] audit context (action label, company, collapsed values)")
    from etl.backfill_audit_context import backfill as backfill_audit
    backfill_audit(dry_run=args.dry_run)

    print("\n[4/4] storage")
    _ensure_storage_bucket(args.dry_run)

    print(f"\n{'DRY RUN complete' if args.dry_run else 'LOAD COMPLETE'} "
          f"in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()

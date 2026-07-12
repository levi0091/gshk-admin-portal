"""Re-derive "what changed" for audit rows already imported from Viewpoint.

The Viewpoint events were loaded before the EventString blob was decoded, so
the trail reads "Form Generated" with no form and "Master File Details Changed"
with no detail -- the answer was in the blob all along, just never extracted.

Nothing is re-fetched from Viewpoint: the parsed blob is already sitting in
audit_log.metadata, so this reads that and fills changed_fields / old_value /
new_value from it.

Idempotent -- safe to re-run; it simply recomputes the same values. New
deployments do not need it (Checkpoint C now decodes on load); it exists to
repair the rows loaded before that.

    python -m etl.backfill_audit_changes [--dry-run] [--limit N]
"""
import argparse
import json
import time

from sqlalchemy import text

from etl.db import get_supabase_engine
from services.audit_changes import describe, render, status_change

BATCH = 2000

# Bookkeeping the ETL added to metadata — not part of the source blob.
_NOT_EVENT_STRING = {"description", "vp_date_missing"}


def _field_labels(conn) -> dict[str, str]:
    return {r[0]: r[1] for r in conn.execute(text("SELECT field, label FROM audit_field_labels"))}


def _address_labels(conn) -> dict[str, str]:
    rows = conn.execute(text(
        "SELECT vp_source_key, line1, line2, city, country FROM addresses "
        "WHERE vp_source_key IS NOT NULL"))
    return {
        key: ", ".join(p for p in (l1, l2, city, country) if p) or key
        for key, l1, l2, city, country in rows
    }


def backfill(dry_run: bool = False, limit: int | None = None) -> dict:
    engine = get_supabase_engine()
    started = time.time()

    with engine.connect() as conn:
        labels = _field_labels(conn)
        addresses = _address_labels(conn)
        total = conn.execute(text(
            "SELECT COUNT(*) FROM audit_log WHERE source = 'viewpoint_import'")).scalar()

    print(f"  {total} imported rows; {len(labels)} field labels, {len(addresses)} address cards")

    done = described = 0
    last_id = "00000000-0000-0000-0000-000000000000"

    while True:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, event_code, metadata, old_value, new_value FROM audit_log
                WHERE source = 'viewpoint_import'
                  AND id > :last
                ORDER BY id
                LIMIT :batch
            """), {"last": last_id, "batch": BATCH}).fetchall()

        if not rows:
            break

        updates = []
        for row_id, event_code, metadata, old_value, new_value in rows:
            if event_code == "STATUS":
                # RefStatus rows carry no EventString — just a pair of codes.
                changes = status_change(old_value, new_value)
            else:
                parsed = {k: v for k, v in (metadata or {}).items()
                          if k not in _NOT_EVENT_STRING and isinstance(v, str)}
                changes = describe(event_code, parsed, labels, addresses)
            if changes:
                described += 1
            updates.append({
                "id": str(row_id),
                "changed": json.dumps(changes) if changes else None,
                "old": render(changes, "old"),
                "new": render(changes, "new"),
            })

        last_id = str(rows[-1][0])
        done += len(rows)

        if not dry_run:
            # One statement per batch, not one per row. Row-at-a-time is a
            # network round trip each (~90ms against Supabase) — 500 rows took
            # 45s that way, which is 6 hours for the table. Set-based is seconds.
            #
            # Commit per batch too: a single transaction across 226k rows gets
            # its connection killed and nothing lands.
            values = ", ".join(
                f"(:id{i}, :changed{i}, :old{i}, :new{i})" for i in range(len(updates))
            )
            params = {
                f"{k}{i}": u[k]
                for i, u in enumerate(updates)
                for k in ("id", "changed", "old", "new")
            }
            with engine.begin() as conn:
                conn.execute(text(f"""
                    UPDATE audit_log AS a SET
                        changed_fields = CAST(v.changed AS jsonb),
                        old_value      = v.old,
                        new_value      = v.new
                    FROM (VALUES {values}) AS v(id, changed, old, new)
                    WHERE a.id = CAST(v.id AS uuid)
                """), params)

        pct = 100 * done / total if total else 100
        print(f"    {done}/{total} ({pct:.0f}%) — {described} with changes decoded",
              end="\r", flush=True)

        if limit and done >= limit:
            break

    print()
    result = {"rows": done, "with_changes": described,
              "seconds": round(time.time() - started)}
    print(f"  {'DRY RUN' if dry_run else 'done'}: {result}")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    backfill(**vars(ap.parse_args()))

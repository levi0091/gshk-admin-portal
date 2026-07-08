from sqlalchemy import Table, MetaData
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

# Postgres caps a single statement at 65,535 bind parameters. A whole-table
# multi-VALUES insert (rows x columns) blows past that for every large source
# table (persons ~6.8k rows x 17 cols, EventLog ~182k rows), so loads are
# split into chunks of this many rows per INSERT — all inside ONE transaction
# per table so the all-or-nothing-per-table semantics are unchanged.
# 500 rows x ~20 cols = ~10k params, comfortably under the cap.
CHUNK_SIZE = 500


def _guard_duplicate_keys(table_name: str, rows: list[dict], conflict_column: str) -> None:
    """Fail fast (with keys named) instead of letting Postgres abort the batch
    with an opaque 'ON CONFLICT ... cannot affect row a second time'."""
    seen: set = set()
    dupes: set = set()
    for r in rows:
        key = r.get(conflict_column)
        if key in seen:
            dupes.add(key)
        seen.add(key)
    if dupes:
        sample = ", ".join(sorted(str(d) for d in list(dupes)[:5]))
        raise ValueError(
            f"duplicate {conflict_column} values within one {table_name} batch "
            f"({len(dupes)} distinct, e.g. {sample}) — each source row must map "
            f"to a unique {conflict_column} or the ON CONFLICT upsert cannot run"
        )


def _chunks(rows: list[dict]):
    for i in range(0, len(rows), CHUNK_SIZE):
        yield rows[i:i + CHUNK_SIZE]


def upsert_rows(
    engine: Engine,
    table_name: str,
    rows: list[dict],
    conflict_column: str = "vp_source_key",
    dry_run: bool = False,
) -> int:
    """Idempotent bulk upsert: INSERT ... ON CONFLICT (conflict_column) DO UPDATE.

    Returns the number of rows the operation would affect / did affect.
    In dry-run mode, no statement is executed against the database at all.
    Executes in CHUNK_SIZE-row statements inside one transaction.
    """
    if not rows:
        return 0

    # Checked in dry-run too, so a dry-run surfaces the problem before any real run.
    _guard_duplicate_keys(table_name, rows, conflict_column)

    if dry_run:
        return 0

    with engine.begin() as conn:
        table = Table(table_name, MetaData(), autoload_with=engine)
        for chunk in _chunks(rows):
            stmt = insert(table).values(chunk)
            # Restrict the ON CONFLICT SET clause to columns the ETL actually
            # populates. Iterating table.columns instead would include columns
            # the ETL never sets (e.g. entities.active_workflow), whose
            # `excluded.<col>` is the INSERT-time default — resetting them to
            # that default on every re-run instead of leaving the existing
            # value untouched.
            update_columns = {
                k: stmt.excluded[k]
                for k in chunk[0]
                if k not in (conflict_column, "id", "created_at")
            }
            # index_where mirrors the PARTIAL unique index's predicate
            # (migrations 004/005/006: `... WHERE vp_source_key IS NOT NULL`).
            # Postgres only accepts a partial unique index as an ON CONFLICT
            # arbiter when the statement repeats that predicate — without it
            # the load fails with "no unique or exclusion constraint matching
            # the ON CONFLICT specification".
            stmt = stmt.on_conflict_do_update(
                index_elements=[conflict_column],
                index_where=table.c[conflict_column].isnot(None),
                set_=update_columns,
            )
            conn.execute(stmt)
    return len(rows)


def insert_rows_ignore_conflicts(
    engine: Engine,
    table_name: str,
    rows: list[dict],
    conflict_column: str = "vp_source_key",
    dry_run: bool = False,
) -> int:
    """Insert-only idempotent load: INSERT ... ON CONFLICT (conflict_column) DO NOTHING.

    For insert-only tables (audit_log — PBI-11 forbids UPDATE/DELETE on it
    ever): a re-run skips rows whose conflict key already exists instead of
    updating them. Returns the number of rows actually inserted (summed
    rowcount), so reconciliation can distinguish a first run (inserted ==
    produced) from a re-run (inserted == 0, by design).
    Executes in CHUNK_SIZE-row statements inside one transaction.
    """
    if not rows:
        return 0

    _guard_duplicate_keys(table_name, rows, conflict_column)

    if dry_run:
        return 0

    inserted = 0
    with engine.begin() as conn:
        table = Table(table_name, MetaData(), autoload_with=engine)
        for chunk in _chunks(rows):
            # index_where mirrors the partial unique index predicate — see the
            # note in upsert_rows(); required for the partial index to serve as
            # the ON CONFLICT arbiter.
            stmt = insert(table).values(chunk).on_conflict_do_nothing(
                index_elements=[conflict_column],
                index_where=table.c[conflict_column].isnot(None),
            )
            result = conn.execute(stmt)
            inserted += result.rowcount or 0
    return inserted

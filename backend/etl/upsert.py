from sqlalchemy import Table, MetaData
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine


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
    """
    if not rows:
        return 0

    # A duplicated conflict-key within one batch would make Postgres raise an
    # opaque "ON CONFLICT DO UPDATE command cannot affect row a second time"
    # (CardinalityViolation) and abort the whole table's load. Fail fast with
    # the offending keys named instead. Checked in dry-run too, so a dry-run
    # surfaces the problem before any real run.
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

    if dry_run:
        return 0

    with engine.begin() as conn:
        table = Table(table_name, MetaData(), autoload_with=engine)
        stmt = insert(table).values(rows)
        # Restrict the ON CONFLICT SET clause to columns the ETL actually
        # populates. Iterating table.columns instead would include columns the
        # ETL never sets (e.g. entities.active_workflow), whose `excluded.<col>`
        # is the INSERT-time default — resetting them to that default on every
        # re-run instead of leaving the existing value untouched.
        update_columns = {
            k: stmt.excluded[k]
            for k in rows[0]
            if k not in (conflict_column, "id", "created_at")
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=[conflict_column], set_=update_columns
        )
        conn.execute(stmt)
    return len(rows)

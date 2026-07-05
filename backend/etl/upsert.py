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

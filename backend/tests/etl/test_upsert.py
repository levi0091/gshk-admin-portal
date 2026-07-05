from unittest.mock import MagicMock, patch
from sqlalchemy import Table, MetaData, Column, String, DateTime
from etl.upsert import upsert_rows


def _fake_addresses_table(*args, **kwargs):
    """Stand-in for Table(..., autoload_with=engine) that doesn't need a real DB.

    Reflection (autoload_with) requires SQLAlchemy to inspect the given engine,
    which raises `NoInspectionAvailable` against a bare MagicMock. Rather than
    fighting MagicMock auto-stubbing to satisfy SQLAlchemy's inspection
    machinery, we patch `etl.upsert.Table` itself to return a real, manually
    defined Table (same columns as the `addresses` migration) so the rest of
    `upsert_rows` — building the insert/on_conflict_do_update statement —
    exercises real SQLAlchemy Core code and can be inspected afterwards.

    `active_workflow` stands in for a column the ETL never populates (e.g.
    entities.active_workflow) — it must NOT appear in the SET clause, since
    including it would reset it to its insert-time default on every re-run.
    """
    metadata = MetaData()
    return Table(
        "addresses",
        metadata,
        Column("id", String, primary_key=True),
        Column("vp_source_key", String),
        Column("line1", String),
        Column("active_workflow", String),
        Column("created_at", DateTime),
    )


def test_upsert_rows_dry_run_does_not_execute():
    engine = MagicMock()
    conn = MagicMock()
    engine.begin.return_value.__enter__.return_value = conn

    rows = [{"vp_source_key": "A1", "line1": "1 Test St"}]
    written = upsert_rows(engine, "addresses", rows, dry_run=True)

    assert written == 0
    conn.execute.assert_not_called()


@patch("etl.upsert.Table", side_effect=_fake_addresses_table)
def test_upsert_rows_executes_on_conflict_upsert(mock_table):
    engine = MagicMock()
    conn = MagicMock()
    engine.begin.return_value.__enter__.return_value = conn

    rows = [
        {"vp_source_key": "A1", "line1": "1 Test St"},
        {"vp_source_key": "A2", "line1": "2 Test St"},
    ]
    written = upsert_rows(engine, "addresses", rows, dry_run=False)

    assert written == 2
    assert conn.execute.call_count == 1  # single batched statement

    executed_stmt = conn.execute.call_args[0][0]
    on_conflict_clause = executed_stmt._post_values_clause

    # Conflict target is vp_source_key.
    assert on_conflict_clause.inferred_target_elements == ["vp_source_key"]

    # SET clause updates exactly the payload's non-conflict/non-id/non-created_at
    # keys. `active_workflow` exists on the reflected table but is absent from
    # the payload rows, so it must be excluded — this guards against resetting
    # ETL-unmanaged columns back to their insert-time defaults on every re-run.
    set_columns = {key for key, _ in on_conflict_clause.update_values_to_set}
    assert set_columns == {"line1"}


def test_upsert_rows_empty_list_is_a_noop():
    engine = MagicMock()
    written = upsert_rows(engine, "addresses", [], dry_run=False)
    assert written == 0
    engine.begin.assert_not_called()


def test_upsert_rows_duplicate_conflict_key_in_batch_raises():
    import pytest
    engine = MagicMock()
    rows = [
        {"vp_source_key": "A1", "line1": "x"},
        {"vp_source_key": "A1", "line1": "y"},
    ]
    with pytest.raises(ValueError, match="duplicate vp_source_key.*addresses.*A1"):
        upsert_rows(engine, "addresses", rows, dry_run=False)
    engine.begin.assert_not_called()


def test_upsert_rows_duplicate_key_detected_even_in_dry_run():
    import pytest
    engine = MagicMock()
    rows = [
        {"vp_source_key": "B2", "line1": "x"},
        {"vp_source_key": "B2", "line1": "y"},
    ]
    with pytest.raises(ValueError):
        upsert_rows(engine, "addresses", rows, dry_run=True)


def test_upsert_rows_chunks_large_batches():
    import pytest
    from unittest.mock import patch as _patch
    import etl.upsert as upsert_mod
    engine = MagicMock()
    conn = MagicMock()
    engine.begin.return_value.__enter__.return_value = conn
    rows = [{"vp_source_key": f"K{i}", "line1": "x"} for i in range(5)]
    with _patch.object(upsert_mod, "CHUNK_SIZE", 2), \
         _patch("etl.upsert.Table", _fake_addresses_table):
        written = upsert_mod.upsert_rows(engine, "addresses", rows, dry_run=False)
    assert written == 5
    assert conn.execute.call_count == 3          # ceil(5/2) chunks
    assert engine.begin.call_count == 1          # one transaction for all chunks


def test_insert_rows_ignore_conflicts_sums_rowcounts():
    from unittest.mock import patch as _patch
    import etl.upsert as upsert_mod
    from etl.upsert import insert_rows_ignore_conflicts
    engine = MagicMock()
    conn = MagicMock()
    engine.begin.return_value.__enter__.return_value = conn
    conn.execute.return_value.rowcount = 2       # each chunk "inserts" 2
    rows = [{"vp_source_key": f"K{i}", "line1": "x"} for i in range(5)]
    with _patch.object(upsert_mod, "CHUNK_SIZE", 2), \
         _patch("etl.upsert.Table", _fake_addresses_table):
        inserted = insert_rows_ignore_conflicts(engine, "addresses", rows, dry_run=False)
    assert conn.execute.call_count == 3
    assert inserted == 6                          # 3 chunks x rowcount 2


def test_insert_rows_ignore_conflicts_guards_and_dry_run():
    import pytest
    from etl.upsert import insert_rows_ignore_conflicts
    engine = MagicMock()
    # dup guard applies
    with pytest.raises(ValueError):
        insert_rows_ignore_conflicts(engine, "audit_log", [
            {"vp_source_key": "EL:1"}, {"vp_source_key": "EL:1"},
        ])
    # dry-run executes nothing, returns 0
    assert insert_rows_ignore_conflicts(engine, "audit_log", [{"vp_source_key": "EL:2"}], dry_run=True) == 0
    engine.begin.assert_not_called()
    # empty no-op
    assert insert_rows_ignore_conflicts(engine, "audit_log", []) == 0

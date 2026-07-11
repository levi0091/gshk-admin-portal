from unittest.mock import MagicMock, patch

from etl.load.checkpoint_d import (
    load_corporate_entities, flag_corporate_parties, repoint_corporate_entity_ids,
    REPOINT_TABLES,
)


def test_load_corporate_entities_delegates_to_upsert():
    engine = MagicMock()
    rows = [{"vp_source_key": "ASIABC", "company_name": "Asia BC"}]
    with patch("etl.load.checkpoint_d.upsert_rows") as mock_upsert:
        mock_upsert.return_value = 1
        out = load_corporate_entities(engine, rows, dry_run=False)
    mock_upsert.assert_called_once_with(engine, "entities", rows, dry_run=False)
    assert out == 1


def test_flag_corporate_parties_dry_run_never_touches_engine():
    engine = MagicMock()
    assert flag_corporate_parties(engine, ["A", "B"], dry_run=True) == 0
    engine.begin.assert_not_called()


def test_flag_corporate_parties_empty_refcodes_noop():
    engine = MagicMock()
    assert flag_corporate_parties(engine, [], dry_run=False) == 0
    engine.begin.assert_not_called()


def test_flag_corporate_parties_returns_rowcount():
    engine = MagicMock()
    conn = engine.begin.return_value.__enter__.return_value
    conn.execute.return_value.rowcount = 219
    assert flag_corporate_parties(engine, ["A", "B"], dry_run=False) == 219


def test_repoint_dry_run_zeros_for_all_tables():
    engine = MagicMock()
    out = repoint_corporate_entity_ids(engine, dry_run=True)
    assert out == {t: 0 for t in REPOINT_TABLES}
    engine.begin.assert_not_called()


def test_repoint_real_run_returns_per_table_counts():
    engine = MagicMock()
    conn = engine.begin.return_value.__enter__.return_value
    conn.execute.return_value.rowcount = 5
    out = repoint_corporate_entity_ids(engine, dry_run=False)
    assert set(out) == set(REPOINT_TABLES)
    assert all(v == 5 for v in out.values())

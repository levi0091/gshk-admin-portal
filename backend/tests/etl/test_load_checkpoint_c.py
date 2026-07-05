from unittest.mock import MagicMock, patch
from etl.load.checkpoint_c import backfill_primary_addresses, load_audit_log


def test_backfill_dry_run_returns_zeros_and_never_touches_engine():
    engine = MagicMock()
    out = backfill_primary_addresses(engine, dry_run=True)
    assert out == {"entities_updated": 0, "persons_updated": 0}
    engine.begin.assert_not_called()


def test_backfill_real_run_returns_rowcounts():
    engine = MagicMock()
    conn = engine.begin.return_value.__enter__.return_value
    conn.execute.return_value.rowcount = 7
    out = backfill_primary_addresses(engine, dry_run=False)
    assert out == {"entities_updated": 7, "persons_updated": 7}


def test_load_audit_log_delegates_to_insert_rows_ignore_conflicts():
    engine = MagicMock()
    rows = [{"vp_source_key": "EL:1"}]
    with patch("etl.load.checkpoint_c.insert_rows_ignore_conflicts") as mock_insert, \
         patch("etl.load.checkpoint_c.upsert_rows") as mock_upsert:
        mock_insert.return_value = 1
        out = load_audit_log(engine, rows, dry_run=False)
    mock_insert.assert_called_once_with(engine, "audit_log", rows, dry_run=False)
    mock_upsert.assert_not_called()
    assert out == 1

from unittest.mock import MagicMock
from etl.load.checkpoint_c import backfill_primary_addresses


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

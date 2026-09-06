import pytest

from etl.reimport_addresses import (
    lines_over_limit,
    summarise,
    assert_safe_target,
    LIMIT,
)


def test_lines_over_limit_names_only_the_offending_columns():
    row = {
        "vp_source_key": "1",
        "line1": "x" * (LIMIT + 1),
        "line2": "short",
        "line3": "y" * (LIMIT + 5),
    }
    assert lines_over_limit(row) == ["line1", "line3"]


def test_lines_over_limit_accepts_a_line_exactly_at_the_limit():
    """CR's cap is inclusive — 60 characters is legal, 61 is not."""
    row = {"vp_source_key": "1", "line1": "x" * LIMIT, "line2": None, "line3": None}
    assert lines_over_limit(row) == []


def test_summarise_counts_rows_not_lines():
    """A row with two over-long lines is one problem row, not two."""
    rows = [
        {"vp_source_key": "1", "line1": "x" * 61, "line2": "y" * 61, "line3": None},
        {"vp_source_key": "2", "line1": "ok", "line2": None, "line3": None},
    ]
    result = summarise(rows)
    assert result["total"] == 2
    assert result["over_limit"] == 1
    assert result["over_limit_keys"] == ["1"]


def test_summarise_reports_the_longest_line_seen():
    rows = [
        {"vp_source_key": "1", "line1": "x" * 97, "line2": None, "line3": None},
        {"vp_source_key": "2", "line1": "x" * 12, "line2": None, "line3": None},
    ]
    assert summarise(rows)["longest"] == 97


def test_assert_safe_target_refuses_a_production_url():
    """The reimport rewrites every address row it touches. PROD is loaded by
    run_all on cutover, never by this script."""
    with pytest.raises(SystemExit) as exc:
        assert_safe_target("postgresql://u:p@db.prod-gflowdesk.supabase.co:5432/postgres")
    assert "production" in str(exc.value).lower()


def test_assert_safe_target_allows_a_dev_url():
    assert_safe_target("postgresql://u:p@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres")


def test_assert_safe_target_refuses_an_empty_url():
    """An unset DATABASE_URL must not read as 'not production, carry on'."""
    with pytest.raises(SystemExit):
        assert_safe_target("")

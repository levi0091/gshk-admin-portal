"""When an officer change is due at CR (PRD §10.6) and when the client is asked
to answer by (spec §5, B-8)."""
from datetime import date

from services.officer_changes import deadlines as dl


def test_deadline_is_the_earliest_change_plus_fifteen_days():
    entries = [
        {"kind": "appointment", "effective_date": "2026-10-03", "items": []},
        {"kind": "cessation", "effective_date": "2026-09-30", "items": []},
    ]
    assert dl.filing_deadline(entries) == date(2026, 10, 15)


def test_nd2b_items_carry_their_own_dates_and_omitted_ones_do_not_count():
    entries = [{"kind": "change", "effective_date": None, "items": [
        {"key": "email", "effective_date": "2026-09-20", "omitted": True},
        {"key": "name_en", "effective_date": "2026-09-25", "omitted": False},
        {"key": "alias", "effective_date": None, "omitted": False},
    ]}]
    assert dl.filing_deadline(entries) == date(2026, 10, 10)


def test_no_dates_means_no_deadline():
    assert dl.filing_deadline([]) is None
    assert dl.filing_deadline([{"kind": "change", "items": [{"key": "email"}]}]) is None


def test_reply_by_is_five_days_before_the_deadline():
    assert dl.reply_by_default(date(2026, 10, 15), date(2026, 9, 30)) == date(2026, 10, 10)


def test_reply_by_is_never_less_than_two_days_out():
    assert dl.reply_by_default(date(2026, 10, 3), date(2026, 9, 30)) == date(2026, 10, 2)
    # An overdue case still gives the client two days.
    assert dl.reply_by_default(date(2026, 9, 1), date(2026, 9, 30)) == date(2026, 10, 2)


def test_reply_by_without_a_deadline_is_left_to_the_operator():
    assert dl.reply_by_default(None, date(2026, 9, 30)) is None


def test_hk_today_is_a_date():
    assert isinstance(dl.hk_today(), date)

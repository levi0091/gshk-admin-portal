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


def test_reply_by_defaults_to_five_days_without_a_deadline():
    """Every change may now be undated at send (Jacqueline A1), and a send
    needs a reply-by date, so the default is five days out."""
    assert dl.reply_by_default(None, date(2026, 10, 2)) == date(2026, 10, 7)


def test_anniversary_default_prefers_the_open_nar1():
    assert dl.anniversary_default("2019-03-12", open_return_date="2026-03-12",
                                  today=date(2026, 10, 2)) == date(2026, 3, 12)


def test_anniversary_default_within_42_days():
    assert dl.anniversary_default("2019-09-01", today=date(2026, 10, 2)) == date(2026, 9, 1)


def test_anniversary_default_none_after_42_days():
    assert dl.anniversary_default("2019-03-12", today=date(2026, 10, 2)) is None


def test_anniversary_default_never_future():
    # This year's anniversary (20 Oct) has not happened; last year's is >42 days ago.
    assert dl.anniversary_default("2019-10-20", today=date(2026, 10, 2)) is None


def test_anniversary_default_on_the_day():
    assert dl.anniversary_default("2019-10-02", today=date(2026, 10, 2)) == date(2026, 10, 2)


def test_anniversary_default_leap_day():
    assert dl.anniversary_default("2020-02-29", today=date(2027, 3, 10)) == date(2027, 2, 28)


def test_anniversary_default_unreadable_is_none():
    assert dl.anniversary_default(None, today=date(2026, 10, 2)) is None
    assert dl.anniversary_default("not a date", today=date(2026, 10, 2)) is None


def test_hk_today_is_a_date():
    assert isinstance(dl.hk_today(), date)

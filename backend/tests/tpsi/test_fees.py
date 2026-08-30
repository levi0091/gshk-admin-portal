"""services/tpsi/fees.py — the NAR1 annual registration fee.

Every band boundary is tested from BOTH sides, because the whole class of bug
this module exists to fix is a fee that is one band out.
"""
from datetime import date
from decimal import Decimal

import pytest

from services.tpsi import fees


def quote(incorporated="2022-01-01", year=2026, delivered="2026-08-27", **kw):
    return fees.annual_return_fee(
        incorporation_date=incorporated, year=year, delivered_on=delivered, **kw
    )


# ---------------------------------------------------------------------------
# The one case CR has actually priced for us
# ---------------------------------------------------------------------------

def test_the_real_CR_submission_of_2026_08_27():
    """CR TEST, filing 7a8cc559: incorporated 2022-01-01, return year 2026,
    delivered 2026-08-27. CR billed HK$2,610 and stamped the document NAR1L.

    If this test ever fails, the fee shown to an operator no longer matches
    what CR charged in the one instance we can check against reality."""
    q = quote()
    assert q.amount == Decimal("2610.00")
    assert q.certain is True
    assert q.return_date == date(2026, 1, 1)


# ---------------------------------------------------------------------------
# Band boundaries, both sides
# ---------------------------------------------------------------------------

def test_on_the_last_day_of_the_42_day_window_is_still_the_ordinary_fee():
    # return date 2026-01-01 + 42 days = 2026-02-12
    assert quote(delivered="2026-02-12").amount == Decimal("105.00")


def test_one_day_after_the_window_jumps_to_the_first_late_band():
    q = quote(delivered="2026-02-13")
    assert q.amount == Decimal("870.00")
    assert q.days_after_deadline == 1


def test_the_return_date_itself_is_inside_the_window():
    assert quote(delivered="2026-01-01").amount == Decimal("105.00")


@pytest.mark.parametrize("delivered,expected", [
    ("2026-04-01", "870.00"),    # exactly 3 months — "within 3 months"
    ("2026-04-02", "1740.00"),   # one day past
    ("2026-07-01", "1740.00"),   # exactly 6 months
    ("2026-07-02", "2610.00"),
    ("2026-10-01", "2610.00"),   # exactly 9 months
    ("2026-10-02", "3480.00"),
    ("2030-01-01", "3480.00"),   # years late, still the top band
])
def test_every_band_boundary(delivered, expected):
    assert quote(delivered=delivered).amount == Decimal(expected)


def test_the_months_run_from_the_RETURN_DATE_not_from_the_deadline():
    """The commonest way to get this wrong. 2026-04-01 is 3 months after the
    return date but only ~7 weeks after the 42-day deadline; measuring from
    the deadline would put it in the 870 band on 2026-05-24 instead."""
    assert quote(delivered="2026-05-24").amount == Decimal("1740.00")


# ---------------------------------------------------------------------------
# Return date arithmetic
# ---------------------------------------------------------------------------

def test_return_date_is_the_anniversary_in_the_RETURNS_year():
    assert fees.return_date_for(date(2022, 3, 15), 2026) == date(2026, 3, 15)


def test_a_29_february_incorporation_falls_back_to_the_28th():
    assert fees.return_date_for(date(2020, 2, 29), 2026) == date(2026, 2, 28)
    assert fees.return_date_for(date(2020, 2, 29), 2028) == date(2028, 2, 29)


def test_month_addition_clamps_instead_of_rolling_forward():
    # 31 Jan + 1 month is 28 Feb, not 3 March — rolling over would push a
    # filing into a dearer band on the last days of a long month.
    assert fees._add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert fees._add_months(date(2026, 8, 31), 6) == date(2027, 2, 28)
    assert fees._add_months(date(2026, 12, 15), 3) == date(2027, 3, 15)


def test_a_december_return_date_crosses_the_year_correctly():
    q = quote(incorporated="2020-12-20", year=2025, delivered="2026-03-01")
    assert q.return_date == date(2025, 12, 20)
    assert q.amount == Decimal("870.00")   # >42d (2026-01-31), <=3m (2026-03-20)


# ---------------------------------------------------------------------------
# When it must NOT pretend to know
# ---------------------------------------------------------------------------

def test_a_public_or_guarantee_company_gets_the_ceiling_not_a_guess():
    q = quote(private_with_share_capital=False)
    assert q.certain is False
    assert q.amount == fees.MAX_FEE
    assert "share capital" in q.reason


def test_no_incorporation_date_gets_the_ceiling():
    q = fees.annual_return_fee(incorporation_date=None, year=2026,
                               delivered_on="2026-08-27")
    assert q.certain is False
    assert q.amount == fees.MAX_FEE


def test_a_junk_incorporation_date_gets_the_ceiling_not_a_crash():
    q = quote(incorporated="not a date")
    assert q.certain is False
    assert "not a date" in q.reason


def test_no_return_year_gets_the_ceiling():
    q = fees.annual_return_fee(incorporation_date="2022-01-01", year=None,
                               delivered_on="2026-08-27")
    assert q.certain is False


def test_a_return_date_in_the_future_is_flagged_rather_than_priced():
    """Delivering before the period closes is a data error, not a cheap fee."""
    q = quote(year=2027, delivered="2026-08-27")
    assert q.certain is False
    assert "in the future" in q.reason


def test_the_uncertain_ceiling_is_the_MAX_not_the_on_time_fee():
    # This value also gates the deposit balance. Optimism here means the
    # filing fails at CR with the money half spent.
    assert fees.uncertain("because").amount == fees.MAX_FEE
    assert fees.uncertain("because").amount > fees.ON_TIME_FEE


# ---------------------------------------------------------------------------
# Serialisation the API returns
# ---------------------------------------------------------------------------

def test_as_dict_is_json_safe():
    d = quote().as_dict()
    assert d["amount"] == "2610.00"          # string, not Decimal
    assert d["return_date"] == "2026-01-01"  # ISO, not a date object
    assert d["certain"] is True
    assert d["reason"] is None


def test_delivered_on_defaults_to_hong_kongs_today():
    """CR charges by the date the return reaches it. For the first eight hours
    of every HK working day UTC is still on yesterday — on a band boundary
    that is a different fee."""
    q = fees.annual_return_fee(incorporation_date="2022-01-01", year=2026)
    assert q.return_date == date(2026, 1, 1)
    assert q.certain is True

"""Which annual return a case files — `yearAnnualReturn` (Levi 2026-09-18).

"if the company has not been filing nar1 for the last 4 years then we should be
able to file 4 times (once for 2023, 2024, 2025, 2026)."

Every date here is built from fixed values passed in as `today`, never from the
clock: a rule about "the next return date on or after today" tested against the
real date is a test that passes in September and fails in November.
"""
from datetime import date
from unittest.mock import patch

import pytest

from services import nar1_return_year as ry

TODAY = date(2026, 9, 18)

#: ShoppyVerse's shape: anniversary 9 October, three weeks after TODAY.
UPCOMING = date(2019, 10, 9)
#: An anniversary that has already passed this year.
PASSED = date(2019, 1, 5)


# ---------------------------------------------------------------------------
# Reading the year back out of what exists
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("xml, year", [
    ("<cr:yearAnnualReturn>2024</cr:yearAnnualReturn>", 2024),
    ("<yearAnnualReturn> 2023 </yearAnnualReturn>", 2023),
    ("<cr:brNo>1</cr:brNo>", None),
    (None, None),
])
def test_the_year_is_read_off_a_stored_fragment(xml, year):
    assert ry.year_in_xml(xml) == year


def test_crs_copy_wins_over_the_request_when_both_are_on_a_filing():
    filing = {"request_xml": "<cr:yearAnnualReturn>2025</cr:yearAnnualReturn>",
              "validated_xml": "<cr:yearAnnualReturn>2024</cr:yearAnnualReturn>"}
    assert ry.filing_year(filing) == 2024


# ---------------------------------------------------------------------------
# The range
# ---------------------------------------------------------------------------

def test_the_first_return_is_for_the_year_of_the_first_anniversary():
    assert ry.first_year(date(2020, 3, 15)) == 2021
    assert ry.earliest_year(date(2020, 3, 15), TODAY) == 2021


def test_the_latest_is_this_year_while_the_anniversary_is_still_ahead():
    """GSHK sends the return to the client ahead of the anniversary, so the
    upcoming year must be choosable — ShoppyVerse on 18 September files 2026."""
    assert ry.latest_year(UPCOMING, TODAY) == 2026


def test_the_latest_is_next_year_once_this_years_anniversary_has_passed():
    assert ry.latest_year(PASSED, TODAY) == 2027


def test_a_company_younger_than_a_year_can_only_prepare_its_first_return():
    assert ry.latest_year(date(2026, 12, 1), TODAY) == 2027
    assert ry.earliest_year(date(2026, 12, 1), TODAY) == 2027


def test_without_an_incorporation_date_the_range_is_the_last_ten_years():
    assert ry.earliest_year(None, TODAY) == 2017
    assert ry.latest_year(None, TODAY) == 2026


def test_an_old_company_is_offered_ten_years_not_every_year_since_incorporation():
    """Levi 2026-09-19: ten years in the dropdown. CR sets no maximum, so the
    floor is ours: this year and the nine before it."""
    old = date(2005, 3, 1)
    assert ry.earliest_year(old, TODAY) == 2017
    years = [o["year"] for o in ry.options(old, TODAY)]
    # 2027 is the upcoming return (this year's anniversary has passed).
    assert years == list(range(2027, 2016, -1))


def test_a_year_past_the_ten_year_window_is_refused_saying_it_is_our_limit():
    with pytest.raises(ry.YearRefused) as refused:
        ry.check_range(2016, date(2005, 3, 1), TODAY)
    message = str(refused.value)
    assert "last 10 years" in message and "2017" in message
    assert "sets no such limit" in message


def test_a_leap_day_incorporation_files_on_the_28th_in_a_common_year():
    assert ry.return_date(date(2020, 2, 29), 2027) == date(2027, 2, 28)


# ---------------------------------------------------------------------------
# Resolution order
# ---------------------------------------------------------------------------

_Y = "<cr:yearAnnualReturn>{}</cr:yearAnnualReturn>"


def test_a_stored_year_wins():
    case = {"ar_period_year": 2023, "verification_xml": _Y.format(2025)}
    filing = {"stage": "validated", "validated_xml": _Y.format(2026)}
    assert ry.resolve(case, filing) == (2023, ry.SOURCE_CASE)


def test_a_legacy_case_keeps_the_year_it_was_sent_to_the_client_for():
    """Mailed before the year existed — for a year, and that is it."""
    case = {"verification_xml": _Y.format(2026)}
    assert ry.resolve(case, {"stage": "draft", "request_xml": _Y.format(2025)}) \
        == (2026, ry.SOURCE_SENT)


def test_a_legacy_case_keeps_the_year_cr_validated():
    filing = {"stage": "validated", "validated_xml": _Y.format(2026)}
    assert ry.resolve({}, filing) == (2026, ry.SOURCE_FILING)


@pytest.mark.parametrize("stage", ["draft", "validation_failed"])
def test_a_draft_filings_year_is_not_a_choice(stage):
    """Levi 2026-09-19: "do not default the dropdown to current year". Drafts
    were built with the old hk_year() default and are rebuilt before they are
    sent or validated, so their year is an assumption nobody made."""
    assert ry.resolve({}, {"stage": stage, "request_xml": _Y.format(2026)}) \
        == (None, None)


def test_a_new_case_has_no_year_until_one_is_chosen():
    assert ry.resolve({}, None) == (None, None)
    assert ry.resolve({"ar_period_year": None, "verification_xml": None}, None) \
        == (None, None)


def test_a_lock_on_a_case_with_no_readable_year_still_reads_as_a_sentence():
    reason = ry.lock_reason({"verification_sent_at": "2026-09-10"}, None, None)
    assert reason.startswith("the return has been sent")


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def test_a_year_before_the_first_return_is_refused_naming_the_first_one():
    with pytest.raises(ry.YearRefused) as refused:
        ry.check_range(2019, date(2019, 10, 9), TODAY, "SHOPPYVERSE LIMITED")
    assert refused.value.status == 400
    assert "2020" in str(refused.value) and "09/10/2019" in str(refused.value)


def test_a_year_early_is_refused_naming_the_latest_that_can_be_prepared():
    with pytest.raises(ry.YearRefused) as refused:
        ry.check_range(2027, UPCOMING, TODAY)
    assert "2026" in str(refused.value) and "09/10/2026" in str(refused.value)


@pytest.mark.parametrize("value", ["twenty", None, "20.5"])
def test_something_that_is_not_a_year_is_refused(value):
    with pytest.raises(ry.YearRefused):
        ry.check_range(value, UPCOMING, TODAY)


def test_four_missed_years_are_all_choosable():
    """The request, verbatim: 2023, 2024, 2025 and 2026."""
    for year in (2023, 2024, 2025, 2026):
        assert ry.check_range(year, UPCOMING, TODAY) == year


# ---------------------------------------------------------------------------
# The options the picker draws
# ---------------------------------------------------------------------------

def test_options_run_newest_first_from_the_upcoming_return_to_the_first():
    years = [o["year"] for o in ry.options(date(2021, 10, 9), TODAY)]
    assert years == [2026, 2025, 2024, 2023, 2022]


def test_each_option_carries_its_dates_and_what_filing_it_today_would_cost():
    by_year = {o["year"]: o for o in ry.options(UPCOMING, TODAY)}

    upcoming = by_year[2026]
    assert upcoming["return_date"] == "2026-10-09"
    assert upcoming["due"] is False
    assert upcoming["days_since_return_date"] == -21
    # No band to be in yet, so no fee — a quote for a return CR will not take
    # would be a number with no meaning.
    assert upcoming["fee"] is None

    last_year = by_year[2025]
    assert last_year["due"] is True
    assert last_year["deadline"] == "2025-11-20"
    # 9 October 2025 to 18 September 2026 is more than nine months: the top band.
    assert last_year["fee"]["amount"] == "3480.00"
    assert last_year["fee"]["certain"] is True


def test_an_option_another_case_holds_says_which_case():
    held = {2025: {"case_id": "c0", "case_no": "NAR-2026-0001"}}
    by_year = {o["year"]: o for o in ry.options(UPCOMING, TODAY, held)}
    assert by_year[2025]["held_by"]["case_no"] == "NAR-2026-0001"
    assert by_year[2024]["held_by"] is None


def test_options_without_an_incorporation_date_say_they_cannot_date_anything():
    [newest, *_rest] = ry.options(None, TODAY)
    assert newest["year"] == 2026
    assert newest["return_date"] is None and newest["due"] is None


# ---------------------------------------------------------------------------
# When the year can no longer move
# ---------------------------------------------------------------------------

def test_an_unsent_case_with_no_filing_is_unlocked():
    assert ry.lock_reason({}, None, 2026) is None


def test_a_rebuildable_draft_does_not_lock_it():
    assert ry.lock_reason({}, {"stage": "validation_failed"}, 2026) is None


def test_sending_it_to_the_client_locks_it_and_says_how_to_unlock():
    reason = ry.lock_reason({"verification_sent_at": "2026-09-10T00:00:00Z"},
                            None, 2026)
    assert "sent to the client" in reason and "Restart verification" in reason


def test_a_validated_snapshot_locks_it():
    assert "validated" in ry.lock_reason({}, {"stage": "validated"}, 2026)


@pytest.mark.parametrize("case, filing", [
    ({"manual_submitted_at": "2026-09-01"}, None),
    ({"manual_receipt": {"refNo": "X"}}, None),
    ({}, {"stage": "submitted"}),
])
def test_a_filed_return_locks_it(case, filing):
    assert "already been filed" in ry.lock_reason(case, filing, 2026)


def test_a_closed_case_locks_it():
    assert ry.lock_reason({"closed_at": "2026-09-01"}, None, 2026) == "this case is closed"


# ---------------------------------------------------------------------------
# One live case per company per year
# ---------------------------------------------------------------------------

class _Store:
    """A nar1_cases table with just enough PostgREST to hold years."""

    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def table(self, _name):
        return _Query(self)


class _Query:
    def __init__(self, store):
        self.store = store
        self.filters = {}
        self.patch = None

    def select(self, *_a):
        return self

    def update(self, patch):
        self.patch = patch
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def is_(self, *_a):
        return self

    @property
    def not_(self):
        return self

    def execute(self):
        if self.patch is not None:
            self.store.updates.append((self.filters.get("id"), self.patch))
            return type("R", (), {"data": [{"id": self.filters.get("id")}]})()
        rows = [r for r in self.store.rows
                if r.get("entity_id") == self.filters.get("entity_id")]
        return type("R", (), {"data": rows})()


def _with(rows):
    store = _Store(rows)
    return store, patch("services.nar1_return_year.get_supabase", return_value=store)


def test_another_live_case_of_the_company_holds_its_year():
    store, p = _with([
        {"id": "c0", "case_no": "NAR-2026-0001", "entity_id": "e1", "ar_period_year": 2025},
        {"id": "c1", "case_no": "NAR-2026-0002", "entity_id": "e1", "ar_period_year": 2024},
    ])
    with p:
        assert ry.held_years("e1", excluding_case_id="c1") == {
            2025: {"case_id": "c0", "case_no": "NAR-2026-0001"}}


def test_claiming_a_free_year_writes_it():
    store, p = _with([])
    case = {"id": "c1", "entity_id": "e1", "ar_period_year": None}
    with p:
        assert ry.claim(case, 2024) is True
    assert store.updates == [("c1", {"ar_period_year": 2024})]


def test_claiming_a_held_year_is_refused_and_writes_nothing():
    store, p = _with([{"id": "c0", "case_no": "NAR-2026-0001", "entity_id": "e1",
                       "ar_period_year": 2024}])
    with p, pytest.raises(ry.YearRefused) as refused:
        ry.claim({"id": "c1", "entity_id": "e1"}, 2024)
    assert refused.value.status == 409
    assert refused.value.held_by["case_no"] == "NAR-2026-0001"
    assert store.updates == []


def test_a_case_that_already_has_a_year_is_not_claimed_again():
    store, p = _with([])
    with p:
        assert ry.claim({"id": "c1", "entity_id": "e1", "ar_period_year": 2023},
                        2023) is False
    assert store.updates == []


# ---------------------------------------------------------------------------
# Every case on a company profile at once (the Cases pane)
# ---------------------------------------------------------------------------

def _year(y):
    """A fragment in the shape CR's stored XML really has — prefixed, padded."""
    return f"<cr:brNo>T0001137</cr:brNo><cr:yearAnnualReturn> {y} </cr:yearAnnualReturn>"


class _Tables:
    """`nar1_cases` and `tpsi_filings`, with the four builder methods the
    batched read uses — honoured, not ignored, so a missing filter fails."""

    def __init__(self, cases=(), filings=(), boom=False):
        self.data = {"nar1_cases": list(cases), "tpsi_filings": list(filings)}
        self.boom = boom
        self.reads = []

    def table(self, name):
        return _TableQuery(self, name)


class _TableQuery:
    def __init__(self, tables, name):
        self.tables, self.name = tables, name
        self.keep = lambda _row: True
        self.newest_first = False

    def select(self, *_a):
        return self

    def in_(self, column, values):
        prev = self.keep
        self.keep = lambda row: prev(row) and row.get(column) in values
        return self

    def neq(self, column, value):
        prev = self.keep
        self.keep = lambda row: prev(row) and row.get(column) != value
        return self

    def order(self, column, desc=False):
        self.newest_first = desc and column == "created_at"
        return self

    def execute(self):
        if self.tables.boom:
            raise RuntimeError("PostgREST is down")
        self.tables.reads.append(self.name)
        rows = [r for r in self.tables.data[self.name] if self.keep(r)]
        if self.newest_first:
            rows.sort(key=lambda r: r["created_at"], reverse=True)
        return type("R", (), {"data": rows})()


def _many(on_profile, **tables):
    store = _Tables(**tables)
    with patch("services.nar1_return_year.get_supabase", return_value=store):
        return ry.resolve_many(on_profile), store


def test_a_stored_year_needs_no_query_at_all():
    years, store = _many([{"id": "c1", "ar_period_year": 2024}])
    assert years == {"c1": (2024, ry.SOURCE_CASE)}
    assert store.reads == []


def test_a_legacy_case_filed_before_the_column_existed_still_names_its_year():
    """25 of 27 cases on DEV's test company store no year; ten were filed."""
    years, _ = _many(
        [{"id": "c1", "ar_period_year": None}],
        cases=[{"id": "c1", "verification_xml": None}],
        filings=[{"nar1_case_id": "c1", "stage": "submitted",
                  "created_at": "2026-08-27T05:47:42+00:00",
                  "validated_xml": _year(2026), "request_xml": _year(2026)}],
    )
    assert years == {"c1": (2026, ry.SOURCE_FILING)}


def test_what_was_mailed_wins_over_what_cr_validated():
    years, store = _many(
        [{"id": "c1"}],
        cases=[{"id": "c1", "verification_xml": _year(2025)}],
        filings=[{"nar1_case_id": "c1", "stage": "validated",
                  "created_at": "2026-09-01T00:00:00+00:00",
                  "validated_xml": _year(2026), "request_xml": None}],
    )
    assert years == {"c1": (2025, ry.SOURCE_SENT)}
    # Both read, concurrently — one round trip, not two in a row.
    assert sorted(store.reads) == ["nar1_cases", "tpsi_filings"]


def test_the_current_filing_decides_as_it_does_on_the_case_screen():
    """Newest non-superseded row, as `nar1_cases.current_filing` picks it.

    A newer DRAFT is current, and a draft's year is nobody's choice — so the
    older validated row behind it must not leak its year through."""
    years, _ = _many(
        [{"id": "c1"}, {"id": "c2"}],
        cases=[{"id": "c1"}, {"id": "c2"}],
        filings=[
            {"nar1_case_id": "c1", "stage": "validated",
             "created_at": "2026-08-01T00:00:00+00:00",
             "validated_xml": _year(2026), "request_xml": None},
            {"nar1_case_id": "c1", "stage": "draft",
             "created_at": "2026-09-01T00:00:00+00:00",
             "validated_xml": None, "request_xml": _year(2026)},
            # c2: the superseded attempt is newer and must be skipped.
            {"nar1_case_id": "c2", "stage": "signed",
             "created_at": "2026-08-01T00:00:00+00:00",
             "validated_xml": _year(2024), "request_xml": None},
            {"nar1_case_id": "c2", "stage": "superseded",
             "created_at": "2026-09-01T00:00:00+00:00",
             "validated_xml": _year(2019), "request_xml": None},
        ],
    )
    assert years == {"c1": (None, None), "c2": (2024, ry.SOURCE_FILING)}


def test_a_new_case_has_no_year_on_the_profile_either():
    years, _ = _many([{"id": "c1", "ar_period_year": None}], cases=[{"id": "c1"}])
    assert years == {"c1": (None, None)}


def test_a_failed_read_leaves_the_years_unknown_and_never_raises():
    years, _ = _many([{"id": "c1", "ar_period_year": 2023}, {"id": "c2"}],
                     boom=True)
    assert years == {"c1": (2023, ry.SOURCE_CASE), "c2": (None, None)}

"""jobs/poll_cr_status.py — the scheduled CR status poll.

Two things are load-bearing here and neither is the happy path: the SELECTION
(the job must not spend CR round trips on cases CR has finished with, and must
not skip the entire book because of a NULL) and the ISOLATION (one bad case must
not abandon the rest).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jobs import poll_cr_status as job
from services.tpsi import doc_status as ds
from services.tpsi.errors import TpsiUnavailableError


def case(case_id="c1", **over):
    base = {"id": case_id, "case_no": f"NAR-2026-{case_id}", "entity_id": "e1",
            "closed_at": None, "manual_receipt": None,
            "cr_doc_status": None, "cr_doc_status_code": None,
            "cr_status_checked_at": None, "cr_document_ref_no": None}
    base.update(over)
    return base


def result(**over):
    base = {"case_id": "c1", "checked": True, "skipped": None,
            "previous": ds.NOT_CHECKED, "code": ds.REGISTERED,
            "cr_text": "Registered", "changed": True,
            "document_ref_no": "R1", "stage_promoted": True}
    base.update(over)
    return base


def _world(cases=None, refresh=None, record=None, client=None, log=None):
    return (
        patch("jobs.poll_cr_status.open_cases",
              return_value=cases if cases is not None else [case()]),
        patch("jobs.poll_cr_status.nar1_cases.current_filing",
              return_value={"id": "f1", "stage": "submitted"}),
        patch("jobs.poll_cr_status.nar1_cr_status.refresh",
              side_effect=refresh or (lambda *a, **k: result())),
        patch("jobs.poll_cr_status.nar1_cr_status.record",
              new=record or AsyncMock()),
        patch("jobs.poll_cr_status.build_client",
              return_value=client or MagicMock()),
        # The run-summary heartbeat. Patched for every test, not just the ones
        # that assert on it: unpatched it reaches the real `log_event`, which
        # swallows its own failures and would therefore hide a run quietly
        # trying to write to Supabase from a unit test.
        patch("jobs.poll_cr_status.log_event", new=log or AsyncMock()),
    )


class _Stack:
    def __init__(self, *patches):
        self._patches = patches

    def __enter__(self):
        self._entered = [p.__enter__() for p in self._patches]
        return self._entered

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.__exit__(*exc)
        return False


# --------------------------------------------------------------------------- #
#  The selection query
# --------------------------------------------------------------------------- #

def _query():
    """A chainable PostgREST double that records the calls made on it."""
    q = MagicMock()
    for name in ("select", "is_", "or_", "order", "limit"):
        getattr(q, name).return_value = q
    q.execute.return_value = MagicMock(data=[])
    return q


def test_the_selection_uses_an_or_so_a_null_code_is_not_filtered_out():
    """THE BUG THIS TEST EXISTS FOR. `col NOT IN ('a','b')` is NULL when col is
    NULL, and a NULL predicate excludes the row — so a bare `not.in` would skip
    EVERY case in the book, all of which carry NULL until the first check. The
    job would have run clean, reported "nothing to do", and polled nothing.
    """
    q = _query()
    with patch("jobs.poll_cr_status.get_supabase") as sb:
        sb.return_value.table.return_value = q
        job.open_cases()

    expression = q.or_.call_args.args[0]
    assert "cr_doc_status_code.is.null" in expression
    assert "cr_doc_status_code.not.in.(cr_registered,cr_rejected)" in expression
    q.is_.assert_called_once_with("closed_at", None)


def test_the_least_recently_checked_come_first_nulls_first():
    """A run that hits the ceiling must clear the cases nobody has asked about
    at all before re-asking ones checked an hour ago. Ordering by creation date
    would re-poll the same oldest page every time and never reach the newest
    case in the book."""
    q = _query()
    with patch("jobs.poll_cr_status.get_supabase") as sb:
        sb.return_value.table.return_value = q
        job.open_cases()
    q.order.assert_called_once_with("cr_status_checked_at", desc=False,
                                    nullsfirst=True)


def test_the_page_size_is_stated_not_left_to_postgrests_silent_ceiling():
    q = _query()
    with patch("jobs.poll_cr_status.get_supabase") as sb:
        sb.return_value.table.return_value = q
        job.open_cases()
    q.limit.assert_called_once_with(job.CASE_LIMIT)


def test_the_terminal_codes_come_from_doc_status_not_a_second_list():
    """Widening TERMINAL_CODES without widening this query would keep asking CR
    about decided cases; narrowing it would stop asking about live ones."""
    q = _query()
    with patch("jobs.poll_cr_status.get_supabase") as sb:
        sb.return_value.table.return_value = q
        job.open_cases()
    for code in ds.TERMINAL_CODES:
        assert code in q.or_.call_args.args[0]


# --------------------------------------------------------------------------- #
#  A pass
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_a_changed_case_is_counted_and_named():
    record = AsyncMock()
    with _Stack(*_world(record=record)):
        report = await job.run()

    assert report["checked"] == 1
    assert report["changed"] == [("NAR-2026-c1", ds.NOT_CHECKED, ds.REGISTERED,
                                 "Registered")]
    record.assert_awaited_once()
    # Nobody did this. The trail must not name whoever last logged in.
    assert record.await_args.kwargs["user_id"] is None
    # ONE HEARTBEAT PER RUN, NOT PER CASE (Levi 2026-09-16, when the schedule
    # became every 15 minutes). Per-case heartbeats at 96 runs a day would
    # write more rows a year than the whole Viewpoint import.
    assert record.await_args.kwargs["heartbeat"] is False


@pytest.mark.asyncio
async def test_a_run_that_asked_cr_something_writes_exactly_one_heartbeat():
    """Its absence is how anybody finds out the cron service stopped — so it
    has to be written, and once, carrying the run's counts rather than
    repeating the per-case detail that NAR1_CR_STATUS_CHANGED already holds."""
    log = AsyncMock()
    with _Stack(*_world(cases=[case("a"), case("b")], log=log)):
        await job.run()

    log.assert_awaited_once()
    meta = log.await_args.kwargs["metadata"]
    assert meta["job"] == "poll_cr_status"
    assert (meta["looked_at"], meta["checked"], meta["changed"]) == (2, 2, 2)
    assert log.await_args.kwargs["user_display_name"] == job.ACTOR


@pytest.mark.asyncio
async def test_a_run_with_nothing_outstanding_writes_no_heartbeat_at_all():
    """96 rows a day saying "there was nothing to poll" is not a heartbeat, it
    is the noise that makes an audit trail unsearchable. Railway's cron log
    answers "did it run?" for the quiet case."""
    log = AsyncMock()
    with _Stack(*_world(cases=[], log=log)):
        report = await job.run()
    assert report["looked_at"] == 0
    log.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_run_where_every_case_was_skipped_writes_no_heartbeat():
    """Nothing was asked of CR, so there is nothing to attest to."""
    log = AsyncMock()
    with _Stack(*_world(refresh=lambda *a, **k: result(checked=False,
                                                       skipped="not filed"),
                        log=log)):
        await job.run()
    log.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unusable_credential_still_writes_the_heartbeat():
    """The run happened and could not proceed — which is exactly the night
    somebody needs to find in the trail."""
    log = AsyncMock()
    patches = list(_world(log=log))
    patches[4] = patch("jobs.poll_cr_status.build_client",
                       side_effect=RuntimeError("bad key"))
    with _Stack(*patches):
        report = await job.run()

    assert "could not be used" in report["unavailable"]
    log.assert_awaited_once()
    assert "bad key" in log.await_args.kwargs["metadata"]["unavailable"]


@pytest.mark.asyncio
async def test_a_failed_heartbeat_never_fails_the_run():
    """The work is already written by the time this runs. A Supabase hiccup on
    the trail must not turn a successful poll into a failed one."""
    log = AsyncMock(side_effect=RuntimeError("audit down"))
    with _Stack(*_world(log=log)):
        report = await job.run()
    assert report["checked"] == 1
    assert report["failed"] == []


@pytest.mark.asyncio
async def test_an_unchanged_case_is_checked_but_not_reported_as_a_change():
    with _Stack(*_world(refresh=lambda *a, **k: result(changed=False))):
        report = await job.run()
    assert report["checked"] == 1
    assert report["changed"] == []


@pytest.mark.asyncio
async def test_a_skipped_case_says_which_exclusion_applied():
    """"skipped 41" tells an operator nothing they can act on."""
    skipped = result(checked=False, skipped="no CR case number is recorded")
    with _Stack(*_world(refresh=lambda *a, **k: skipped)):
        report = await job.run()
    assert report["checked"] == 0
    assert report["skipped"] == [("NAR-2026-c1", "no CR case number is recorded")]


@pytest.mark.asyncio
async def test_nothing_to_do_costs_no_cr_login_at_all():
    """Most runs once the book has settled. A login per empty run is a CR
    authentication for nothing, and repeated CR auth failures lock the
    account."""
    with _Stack(*_world(cases=[])) as entered:
        report = await job.run()
    entered[4].assert_not_called()
    assert report["looked_at"] == 0


@pytest.mark.asyncio
async def test_one_client_is_built_for_the_whole_run():
    """Tokens are cached 30 minutes, so a run over hundreds of cases costs one
    authentication — and CR issues one token per account at a time."""
    cases = [case(f"c{i}") for i in range(5)]
    with _Stack(*_world(cases=cases)) as entered:
        await job.run()
    entered[4].assert_called_once()


# --------------------------------------------------------------------------- #
#  Isolation
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_one_bad_case_does_not_abandon_the_rest_of_the_book():
    cases = [case("c1"), case("c2"), case("c3")]

    def refresh(client, c, filing):
        if c["id"] == "c2":
            raise RuntimeError("boom")
        return result(case_id=c["id"])

    with _Stack(*_world(cases=cases, refresh=refresh)):
        report = await job.run()

    assert report["checked"] == 2
    assert report["failed"] == [("c2", "boom")]


@pytest.mark.asyncio
async def test_an_unreadable_filing_ledger_is_a_failure_not_a_check():
    with _Stack(*_world()) as entered:
        entered[1].side_effect = RuntimeError("supabase down")
        report = await job.run()
    assert report["checked"] == 0
    assert report["failed"][0][0] == "c1"


@pytest.mark.asyncio
async def test_an_audit_failure_does_not_undo_the_work():
    """`log_event` already swallows its own failures; this covers the rest of
    `record`. A status CR gave us is written whether or not the trail took it."""
    record = AsyncMock(side_effect=RuntimeError("audit down"))
    with _Stack(*_world(record=record)):
        report = await job.run()
    assert report["checked"] == 1
    assert report["failed"] == []


# --------------------------------------------------------------------------- #
#  CR not usable
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_an_unreachable_cr_ends_the_run_rather_than_failing_every_case():
    """The next 300 cases will fail identically, and 300 stack traces is a worse
    report than one sentence."""
    cases = [case(f"c{i}") for i in range(4)]
    calls = []

    def refresh(client, c, filing):
        calls.append(c["id"])
        raise TpsiUnavailableError("CR did not answer")

    with _Stack(*_world(cases=cases, refresh=refresh)):
        report = await job.run()

    assert calls == ["c0"]
    assert report["unavailable"] == "CR did not answer"
    assert report["failed"] == []


@pytest.mark.asyncio
async def test_no_usable_credential_is_reported_not_raised():
    with _Stack(*_world()) as entered:
        entered[4].side_effect = RuntimeError("no shared presenter configured")
        report = await job.run()
    assert "could not be used" in report["unavailable"]
    assert report["checked"] == 0


@pytest.mark.asyncio
async def test_a_full_page_says_so_rather_than_looking_like_a_finished_run():
    cases = [case(f"c{i}") for i in range(3)]
    with _Stack(*_world(cases=cases)):
        report = await job.run(limit=3)
    assert report["truncated"] is True


# --------------------------------------------------------------------------- #
#  Exit code
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("report,expected", [
    ({"ran_at": "t", "looked_at": 0, "checked": 0, "changed": [], "skipped": [],
      "failed": [], "truncated": False, "unavailable": None}, 0),
    ({"ran_at": "t", "looked_at": 1, "checked": 0, "changed": [], "skipped": [],
      "failed": [("c1", "boom")], "truncated": False, "unavailable": None}, 1),
    ({"ran_at": "t", "looked_at": 1, "checked": 0, "changed": [], "skipped": [],
      "failed": [], "truncated": False, "unavailable": "CR is down"}, 1),
])
def test_the_exit_code_distinguishes_nothing_to_do_from_could_not_run(
        report, expected):
    """A run with nothing due is a success, and a cron service that alerted on
    it would train everyone to ignore it. A run that could not reach CR did not
    do its job."""
    with patch("jobs.poll_cr_status.run", new=AsyncMock(return_value=report)):
        assert job.main() == expected

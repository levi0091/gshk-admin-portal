"""Spec §5 — the 14-day auto-approval job.

This job files returns the client never answered, so its EXCLUSIONS are the
feature. Each one below corresponds to a way the job could put a client
decision into a permanent, insert-only trail that the client never made, or
put one there AFTER the filing it supposedly authorised.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jobs import auto_approve_nar1 as job
from services import nar1_approvals as approvals

NOW = datetime(2026, 9, 2, 16, 0, tzinfo=timezone.utc)   # 00:00 Hong Kong


def token(case_id="c1", **over):
    base = {"id": "a1", "nar1_case_id": case_id,
            "recipient_email": "chan@example.com", "recipient_name": "AH CHAN",
            "expires_at": (NOW - timedelta(days=1)).isoformat()}
    base.update(over)
    return base


def case(**over):
    base = {"id": "c1", "case_no": "NAR-2026-0041", "entity_id": "e1",
            "verification_sent_at": (NOW - timedelta(days=15)).isoformat(),
            "client_approved": None, "manual_receipt": None,
            "manual_submitted_at": None}
    base.update(over)
    return base


def _world(tokens=None, cases=None, filing=None):
    """Patched at the job's own module boundary. Nothing reaches Supabase: the
    real `due_tokens` queries a live database, and a unit test that reached it
    would be reading DEV while reporting a pass."""
    by_id = {c["id"]: c for c in (cases or [case()])}
    return [
        patch("jobs.auto_approve_nar1.due_tokens",
              return_value=tokens if tokens is not None else [token()]),
        patch("jobs.auto_approve_nar1.nar1_cases.get_case",
              side_effect=lambda cid: by_id[cid]),
        patch("jobs.auto_approve_nar1.nar1_cases.blocking_filing",
              return_value=filing),
        patch("jobs.auto_approve_nar1.nar1_cases.update_case",
              return_value={"id": "c1"}),
        patch("jobs.auto_approve_nar1.nar1_approvals.supersede_outstanding",
              return_value=0),
        patch("jobs.auto_approve_nar1.log_event", new=AsyncMock()),
    ]


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
#  The happy path
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_a_silent_client_is_approved_after_fourteen_days():
    with _Stack(*_world()) as entered:
        report = await job.run(NOW)
    update_case, supersede, log = entered[3], entered[4], entered[5]

    assert report["approved"] == 1
    written = update_case.call_args.args[1]
    assert written["client_approved"] is True
    assert written["client_approval_source"] == "system_timeout"
    log.assert_awaited_once()
    # The links stop working the moment the case is decided.
    supersede.assert_called_once_with("c1")


@pytest.mark.asyncio
async def test_the_approval_names_NOBODY_because_nobody_approved():
    """The whole point of spec §5's provenance rule. Writing the last
    recipient's name here would produce the one sentence the spec forbids — a
    director who never answered appearing to have agreed."""
    with _Stack(*_world()) as entered:
        await job.run(NOW)
    written = entered[3].call_args.args[1]
    assert written["client_approval_name"] is None
    assert written["client_approval_person_id"] is None


@pytest.mark.asyncio
async def test_the_audit_row_says_it_was_the_system_and_who_stayed_silent():
    with _Stack(*_world()) as entered:
        await job.run(NOW)
    logged = entered[5].await_args.kwargs

    assert logged["action_type"] == "CLIENT_APPROVAL_AUTO_APPROVED"
    assert logged["user_id"] is None
    assert "automatic" in logged["user_display_name"].lower()
    # audit_log.case_id holds the ENTITY id — routers/cases.py::_audit_target.
    assert logged["case_id"] == "e1"
    assert logged["entity_id"] == "c1"
    assert logged["metadata"]["channel"] == "system_timeout"
    assert logged["metadata"]["window_days"] == 14
    # A silence is only meaningful if you can say whose.
    assert logged["metadata"]["last_recipient"] == "chan@example.com"


@pytest.mark.asyncio
async def test_a_board_of_three_produces_ONE_approval_not_three():
    """Three directors means three tokens for one case, all expiring together."""
    tokens = [token(id="a1"), token(id="a2"), token(id="a3")]
    with _Stack(*_world(tokens=tokens)) as entered:
        report = await job.run(NOW)
    assert report["approved"] == 1
    entered[3].assert_called_once()


# --------------------------------------------------------------------------- #
#  The exclusions — each is a way this job could record a lie
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
@pytest.mark.parametrize("overrides,expected", [
    ({"client_approved": True}, "already answered"),
    ({"client_approved": False}, "already answered"),
    ({"verification_sent_at": None}, "was ever sent"),
    ({"manual_receipt": {"caseNo": "1"}}, "off-portal"),
    ({"manual_submitted_at": "2026-08-01T00:00:00Z"}, "off-portal"),
    # THE WORST ONE TO GET WRONG. This job approves on SILENCE, and a closed
    # case is silent by definition — so without the exclusion it would write a
    # client approval, sourced as "nobody objected", onto a case the client
    # explicitly asked to stop, into an insert-only trail.
    ({"closed_at": "2026-09-05T02:00:00Z"}, "was closed"),
])
async def test_cases_that_must_not_be_auto_approved(overrides, expected):
    with _Stack(*_world(cases=[case(**overrides)])) as entered:
        report = await job.run(NOW)
    assert report["approved"] == 0
    assert report["skipped"] == 1
    assert expected in report["skipped_detail"][0][1]
    entered[3].assert_not_called()


@pytest.mark.asyncio
async def test_a_return_CR_already_holds_is_never_auto_approved():
    """Approving it would put a client decision in the trail AFTER the filing it
    supposedly authorised."""
    with _Stack(*_world(filing={"id": "f1", "stage": "submitted"})) as entered:
        report = await job.run(NOW)
    assert report["approved"] == 0
    assert "Companies Registry already holds" in report["skipped_detail"][0][1]
    entered[3].assert_not_called()


def test_closure_is_the_first_exclusion_tested():
    """A closed case that is ALSO filed off-portal must report the closure.

    Not cosmetic: `skipped_detail` is what an operator reads to decide whether
    a skip needs acting on, and "already filed off-portal" invites somebody to
    go looking for a filing on a case that simply ended."""
    both = case(closed_at="2026-09-05T02:00:00Z",
                manual_receipt={"caseNo": "1"},
                manual_submitted_at="2026-08-01T00:00:00Z")
    assert job.skip_reason(both) == "the case was closed"


@pytest.mark.asyncio
async def test_an_unreadable_filing_ledger_is_a_reason_to_SKIP_not_to_approve():
    patches = _world()
    patches[2] = patch("jobs.auto_approve_nar1.nar1_cases.blocking_filing",
                       side_effect=RuntimeError("connection refused"))
    with _Stack(*patches) as entered:
        report = await job.run(NOW)
    assert report["approved"] == 0
    assert report["skipped"] == 1
    entered[3].assert_not_called()


@pytest.mark.asyncio
async def test_a_case_that_no_longer_exists_is_skipped_not_failed():
    patches = _world()
    patches[1] = patch("jobs.auto_approve_nar1.nar1_cases.get_case",
                       side_effect=LookupError("no case c1"))
    with _Stack(*patches):
        report = await job.run(NOW)
    assert report["skipped"] == 1
    assert report["failed"] == 0


# --------------------------------------------------------------------------- #
#  Idempotence and isolation
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_a_second_run_the_same_night_changes_nothing():
    """The first run wrote client_approved, so the second sees an answered case
    — which is also what makes a retry after a partial failure safe."""
    with _Stack(*_world(cases=[case(client_approved=True)])) as entered:
        report = await job.run(NOW)
    assert report["approved"] == 0
    entered[3].assert_not_called()


@pytest.mark.asyncio
async def test_one_failing_case_does_not_abandon_the_rest():
    """A job that stopped at the first bad row would leave the rest of the book
    unprocessed until somebody noticed."""
    tokens = [token(id="a1", case_id="c1"), token(id="a2", case_id="c2"),
              token(id="a3", case_id="c3")]
    cases = [case(id="c1"), case(id="c2"), case(id="c3")]
    calls = {"n": 0}

    def flaky(case_id, patch_body):
        calls["n"] += 1
        if case_id == "c2":
            raise RuntimeError("row is locked")
        return {"id": case_id}

    patches = _world(tokens=tokens, cases=cases)
    patches[3] = patch("jobs.auto_approve_nar1.nar1_cases.update_case",
                       side_effect=flaky)
    with _Stack(*patches):
        report = await job.run(NOW)

    assert report["approved"] == 2
    assert report["failed"] == 1
    assert report["failed_detail"][0][0] == "c2"


@pytest.mark.asyncio
async def test_every_case_in_one_run_is_judged_against_one_clock():
    """A case must not be judged against a clock that moved mid-loop."""
    with _Stack(*_world()) as entered:
        report = await job.run(NOW)
    assert report["ran_at"] == NOW.isoformat()
    assert entered[3].call_args.args[1]["client_response_at"] == NOW.isoformat()


# --------------------------------------------------------------------------- #
#  due_tokens — the filter belongs in the database
# --------------------------------------------------------------------------- #

def test_only_unanswered_tokens_past_their_expiry_are_selected():
    """Filtered in the DATABASE, not in Python: a scan that pulled every token
    to decide in the loop would grow with history rather than with what is due."""
    table = MagicMock()
    filters = []
    table.select.return_value = table
    table.order.return_value = table
    table.execute.return_value = MagicMock(data=[])

    def is_(column, value):
        filters.append(("is", column, value))
        return table

    def lt(column, value):
        filters.append(("lt", column, value))
        return table

    table.is_.side_effect = is_
    table.lt.side_effect = lt
    sb = MagicMock()
    sb.table.return_value = table

    with patch("jobs.auto_approve_nar1.get_supabase", return_value=sb):
        job.due_tokens(NOW)

    assert ("is", "outcome", None) in filters
    assert ("lt", "expires_at", NOW.isoformat()) in filters
    sb.table.assert_called_with("nar1_client_approvals")


# --------------------------------------------------------------------------- #
#  The entry point
# --------------------------------------------------------------------------- #

def test_a_quiet_night_exits_zero():
    """A run with nothing due is a SUCCESS. A cron service that alerted on it
    would train everyone to ignore it."""
    with patch("jobs.auto_approve_nar1.run",
               new=AsyncMock(return_value={"ran_at": NOW.isoformat(),
                                           "approved": 0, "skipped": 0,
                                           "failed": 0, "skipped_detail": [],
                                           "failed_detail": []})):
        assert job.main() == 0


def test_a_failure_exits_non_zero_so_the_cron_log_shows_red():
    with patch("jobs.auto_approve_nar1.run",
               new=AsyncMock(return_value={"ran_at": NOW.isoformat(),
                                           "approved": 3, "skipped": 1,
                                           "failed": 1, "skipped_detail": [],
                                           "failed_detail": [("c2", "locked")]})):
        assert job.main() == 1


def test_the_window_is_the_one_the_email_promised():
    """The deadline printed in the client's email and the deadline this job acts
    on are the same number, read from the same place."""
    assert approvals.APPROVAL_WINDOW_DAYS == 14


# --------------------------------------------------------------------------- #
#  The silent row cap
# --------------------------------------------------------------------------- #

def test_the_query_states_its_own_ceiling():
    """PostgREST applies ITS ceiling when a query does not (Supabase defaults to
    1,000) and returns the truncated page with no error and no marker. An
    unstated cap here would auto-approve the first thousand and leave the rest
    looking, from the log, exactly like a run with nothing left to do."""
    table = MagicMock()
    limits = []
    table.select.return_value = table
    table.is_.return_value = table
    table.lt.return_value = table
    table.order.return_value = table
    table.limit.side_effect = lambda n: (limits.append(n), table)[1]
    table.execute.return_value = MagicMock(data=[])
    sb = MagicMock()
    sb.table.return_value = table

    with patch("jobs.auto_approve_nar1.get_supabase", return_value=sb):
        job.due_tokens(NOW)

    assert limits == [job.DUE_TOKEN_LIMIT]


@pytest.mark.asyncio
async def test_a_full_page_is_reported_rather_than_looking_finished():
    """"approved 340, skipped 660" out of a full page looks exactly like a
    finished run."""
    tokens = [token(id=f"a{i}", case_id=f"c{i}")
              for i in range(job.DUE_TOKEN_LIMIT)]
    cases = [case(id=f"c{i}", client_approved=True)
             for i in range(job.DUE_TOKEN_LIMIT)]
    with _Stack(*_world(tokens=tokens, cases=cases)):
        report = await job.run(NOW)
    assert report["truncated"] is True


@pytest.mark.asyncio
async def test_a_partial_page_is_not_reported_as_truncated():
    with _Stack(*_world()):
        report = await job.run(NOW)
    assert report["truncated"] is False


def test_the_oldest_overdue_cases_are_taken_first():
    """A run that does hit the ceiling must clear the MOST overdue, so the
    remainder is the least urgent and one more night costs nothing."""
    table = MagicMock()
    ordered = []
    table.select.return_value = table
    table.is_.return_value = table
    table.lt.return_value = table
    table.order.side_effect = lambda col, **kw: (ordered.append((col, kw)), table)[1]
    table.limit.return_value = table
    table.execute.return_value = MagicMock(data=[])
    sb = MagicMock()
    sb.table.return_value = table

    with patch("jobs.auto_approve_nar1.get_supabase", return_value=sb):
        job.due_tokens(NOW)

    assert ordered == [("expires_at", {})]     # ascending: oldest expiry first

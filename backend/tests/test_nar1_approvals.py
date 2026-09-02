"""Spec §5 — the token store behind client self-approval.

Nothing here touches Supabase: every query goes through a fake that records
what it was asked, because the real one writes to a live database and a unit
test that reached it would be mutating DEV while reporting a pass.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from services import nar1_approvals as approvals


class _Table:
    """A Supabase table double that records the filters it was given.

    Deliberately not a bare MagicMock: the conditions on these updates ARE the
    feature — "only if still unanswered" is what settles two directors pressing
    at once — and a MagicMock would let a missing `.is_("outcome", None)` pass
    every assertion in this file.
    """

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.inserted = []
        self.updated = None
        self.filters = []

    # -- builder ---------------------------------------------------------- #
    def select(self, *_a, **_k):
        return self

    def insert(self, payload):
        self.inserted.append(payload)
        return self

    def update(self, payload):
        self.updated = payload
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def neq(self, column, value):
        self.filters.append(("neq", column, value))
        return self

    def is_(self, column, value):
        self.filters.append(("is", column, value))
        return self

    def lt(self, column, value):
        self.filters.append(("lt", column, value))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return MagicMock(data=self.rows)


def _sb(table):
    client = MagicMock()
    client.table.return_value = table
    return patch("services.nar1_approvals.get_supabase", return_value=client)


# --------------------------------------------------------------------------- #
#  hashing
# --------------------------------------------------------------------------- #

def test_the_token_is_never_stored_only_its_hash():
    """A read of this table — a backup, a support query, an ETL dump — must not
    be enough to approve somebody's annual return."""
    table = _Table()
    with _sb(table):
        issued = approvals.issue(
            case_id="c1",
            recipients=[{"email": "a@example.com", "person_id": "p1",
                         "name": "AH CHAN"}],
        )
    token = issued[0]["token"]
    assert token
    row = table.inserted[0][0]
    assert row["token_hash"] == approvals.hash_token(token)
    assert token not in str(row)


def test_two_tokens_are_never_the_same():
    table = _Table()
    with _sb(table):
        issued = approvals.issue(
            case_id="c1",
            recipients=[{"email": "a@x.com"}, {"email": "b@x.com"}],
        )
    assert issued[0]["token"] != issued[1]["token"]
    assert len({r["token_hash"] for r in table.inserted[0]}) == 2


def test_a_token_is_long_enough_that_guessing_is_not_a_threat_model():
    table = _Table()
    with _sb(table):
        issued = approvals.issue(case_id="c1", recipients=[{"email": "a@x.com"}])
    # 32 bytes -> 43 URL-safe characters.
    assert len(issued[0]["token"]) >= 40


# --------------------------------------------------------------------------- #
#  issue()
# --------------------------------------------------------------------------- #

def test_issuing_supersedes_whatever_was_outstanding():
    """Re-sending verification means the previous message's document is no
    longer the one being asked about. A director holding the older mail must
    not be able to approve it."""
    table = _Table()
    with _sb(table):
        approvals.issue(case_id="c1", recipients=[{"email": "a@x.com"}])
    assert table.updated == {
        "outcome": "superseded", "responded_at": table.updated["responded_at"]}
    assert ("is", "outcome", None) in table.filters


def test_the_expiry_is_fourteen_days_after_the_send():
    sent = datetime(2026, 9, 1, tzinfo=timezone.utc)
    table = _Table()
    with _sb(table):
        issued = approvals.issue(case_id="c1", recipients=[{"email": "a@x.com"}],
                                 sent_at=sent)
    assert issued[0]["expires_at"] == sent + timedelta(days=14)
    assert table.inserted[0][0]["expires_at"] == (
        (sent + timedelta(days=14)).isoformat())


def test_the_director_behind_each_address_is_recorded():
    table = _Table()
    with _sb(table):
        approvals.issue(case_id="c1", recipients=[
            {"email": "a@x.com", "person_id": "p1", "name": "AH CHAN"}])
    row = table.inserted[0][0]
    assert row["person_id"] == "p1"
    # Denormalised on purpose: the trail must keep saying who approved even if
    # the person row is later renamed, merged or removed.
    assert row["recipient_name"] == "AH CHAN"


def test_no_recipients_writes_nothing():
    table = _Table()
    with _sb(table):
        assert approvals.issue(case_id="c1", recipients=[]) == []
    assert table.inserted == []


# --------------------------------------------------------------------------- #
#  find_by_token()
# --------------------------------------------------------------------------- #

def test_a_token_resolves_to_its_row():
    token = "abcdefgh"
    table = _Table(rows=[{"id": "a1", "token_hash": approvals.hash_token(token)}])
    with _sb(table):
        assert approvals.find_by_token(token)["id"] == "a1"
    assert ("eq", "token_hash", approvals.hash_token(token)) in table.filters


@pytest.mark.parametrize("token", ["", None, 123, []])
def test_a_missing_or_malformed_token_resolves_to_nothing(token):
    """One answer for every miss. The public route's replies must not let a
    caller tell a real token from a fabricated one."""
    table = _Table(rows=[{"id": "a1", "token_hash": "x"}])
    with _sb(table):
        assert approvals.find_by_token(token) is None


def test_a_row_whose_hash_does_not_match_is_refused():
    """The lookup is by unique index, so this cannot happen today. It is the
    guard for the day somebody replaces the query with a scan."""
    table = _Table(rows=[{"id": "a1", "token_hash": "not-the-hash"}])
    with _sb(table):
        assert approvals.find_by_token("abcdefgh") is None


# --------------------------------------------------------------------------- #
#  is_expired()
# --------------------------------------------------------------------------- #

def test_a_token_inside_its_window_is_live():
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert approvals.is_expired({"expires_at": future}) is False


def test_a_token_past_its_window_is_expired():
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert approvals.is_expired({"expires_at": past}) is True


@pytest.mark.parametrize("value", [None, "", "not a date", "2026-13-45"])
def test_an_unreadable_expiry_counts_as_expired(value):
    """Failing closed. The alternative is a token with an unparseable date
    working forever."""
    assert approvals.is_expired({"expires_at": value}) is True


def test_a_naive_expiry_is_read_as_utc():
    """PostgREST returns timestamptz with an offset, but a fixture, a migration
    or a hand-written row may not carry one. Guessing local time would move the
    deadline by eight hours in Hong Kong."""
    past = (datetime.now(timezone.utc) - timedelta(days=1)).replace(tzinfo=None)
    assert approvals.is_expired({"expires_at": past.isoformat()}) is True


# --------------------------------------------------------------------------- #
#  claim()
# --------------------------------------------------------------------------- #

def test_claiming_records_the_ip_the_time_and_the_agent():
    table = _Table(rows=[{"id": "a1", "outcome": "approved"}])
    with _sb(table):
        approvals.claim("a1", ip="203.0.113.9", user_agent="Mozilla/5.0")
    assert table.updated["outcome"] == "approved"
    assert table.updated["ip_address"] == "203.0.113.9"
    assert table.updated["user_agent"] == "Mozilla/5.0"
    assert table.updated["responded_at"]


def test_the_claim_condition_travels_with_the_update():
    """FIRST APPROVAL WINS, settled by Postgres. A read-then-write in the
    handler would let two directors pressing in the same second both record a
    decision on one return — and audit_log is insert-only."""
    table = _Table(rows=[{"id": "a1"}])
    with _sb(table):
        approvals.claim("a1", ip=None, user_agent=None)
    assert ("is", "outcome", None) in table.filters
    assert ("eq", "id", "a1") in table.filters


def test_a_claim_that_lost_the_race_returns_nothing():
    table = _Table(rows=[])
    with _sb(table):
        assert approvals.claim("a1", ip=None, user_agent=None) is None


def test_a_long_user_agent_is_truncated():
    """Client-supplied text on an unauthenticated route. Nothing downstream
    needs more than enough to recognise a browser."""
    table = _Table(rows=[{"id": "a1"}])
    with _sb(table):
        approvals.claim("a1", ip=None, user_agent="x" * 5000)
    assert len(table.updated["user_agent"]) == 400


def test_an_absent_user_agent_is_null_not_an_empty_string():
    table = _Table(rows=[{"id": "a1"}])
    with _sb(table):
        approvals.claim("a1", ip=None, user_agent="")
    assert table.updated["user_agent"] is None


# --------------------------------------------------------------------------- #
#  supersede_outstanding()
# --------------------------------------------------------------------------- #

def test_superseding_can_spare_the_row_that_just_won():
    table = _Table(rows=[{"id": "a2"}])
    with _sb(table):
        assert approvals.supersede_outstanding("c1", exclude_id="a1") == 1
    assert ("neq", "id", "a1") in table.filters
    assert ("eq", "nar1_case_id", "c1") in table.filters


def test_superseding_only_touches_unanswered_rows():
    """An approval already recorded is a fact. Marking it superseded would
    erase the only record of who agreed to a statutory filing."""
    table = _Table(rows=[])
    with _sb(table):
        approvals.supersede_outstanding("c1")
    assert ("is", "outcome", None) in table.filters


# --------------------------------------------------------------------------- #
#  provenance() — "Approved" on its own is never a valid answer
# --------------------------------------------------------------------------- #

def test_an_unanswered_case_has_no_provenance():
    assert approvals.provenance({"client_approved": None}) is None


def test_a_rejected_case_has_no_approval_provenance():
    assert approvals.provenance({"client_approved": False}) is None


def test_a_self_service_approval_names_the_director():
    result = approvals.provenance({
        "client_approved": True,
        "client_approval_source": approvals.SOURCE_SELF_SERVICE,
        "client_approval_name": "AH CHAN",
    })
    assert "AH CHAN" in result["summary"]
    assert result["system"] is False


def test_a_timeout_approval_says_the_client_never_answered():
    """The one that matters most. A director who never replied must not appear
    to have agreed to anything."""
    result = approvals.provenance({
        "client_approved": True,
        "client_approval_source": approvals.SOURCE_SYSTEM_TIMEOUT,
    })
    assert result["summary"] == (
        "System-approved — the client did not respond within 14 days")
    assert result["system"] is True


def test_a_relayed_approval_says_a_human_recorded_it():
    result = approvals.provenance({
        "client_approved": True,
        "client_approval_source": approvals.SOURCE_STAFF_RELAY,
        "client_approval_name": "BO LEE",
    })
    assert "BO LEE" in result["summary"]
    assert "staff" in result["summary"]


def test_a_relay_with_no_name_still_says_how_it_arrived():
    result = approvals.provenance({
        "client_approved": True,
        "client_approval_source": approvals.SOURCE_STAFF_RELAY,
    })
    assert result["summary"] == (
        "Recorded by a member of staff from the client's reply")


def test_an_approval_from_before_this_feature_admits_it_does_not_know():
    """Rows approved before migration 030 carry no source. Inventing one would
    put a claim in the record that nothing supports."""
    result = approvals.provenance({"client_approved": True})
    assert "before the source was tracked" in result["summary"]


def test_no_provenance_summary_is_ever_the_bare_word_approved():
    for source in (approvals.SOURCE_SELF_SERVICE, approvals.SOURCE_STAFF_RELAY,
                   approvals.SOURCE_SYSTEM_TIMEOUT, None, "something_new"):
        result = approvals.provenance({
            "client_approved": True, "client_approval_source": source})
        assert result["summary"].strip().lower() != "approved"
        assert len(result["summary"]) > len("Approved")

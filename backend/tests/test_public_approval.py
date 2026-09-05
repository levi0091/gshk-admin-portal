"""Spec §5 — the client's approval page, the only unauthenticated route that
writes. (`GET /auth/super-admins` is the other one; it is a read, and
`test_super_admin_contacts.py` holds its boundaries.)


The two things this file exists to hold in place:

  1. GET MUTATES NOTHING. Every mail-security gateway fetches every link in a
     message before a human sees it. A GET that approved would be fired by the
     scanner, recording the scanner's IP as the approving director minutes
     after the email was sent.
  2. THE ROUTE IS NOT AN ORACLE. Unknown, malformed, expired, superseded and
     rate-limited all produce the SAME answer, so the page cannot be used to
     learn which tokens or cases exist.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from routers import public_approval
from services import nar1_approvals as approvals

TOKEN = "abcdefghijklmnopqrstuvwxyz012345"
PATH = f"/public/nar1-approval/{TOKEN}"

CASE = {"id": "c1", "case_no": "NAR-2026-0041", "entity_id": "e1",
        "ar_period_year": 2026, "client_approved": None}
ENTITY = {"id": "e1", "company_name": "ACME LIMITED", "br_number": "00000001"}


def _future():
    return (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()


def _past():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def row(**over):
    base = {"id": "a1", "nar1_case_id": "c1", "person_id": "p1",
            "recipient_email": "chan@example.com", "recipient_name": "AH CHAN",
            "token_hash": approvals.hash_token(TOKEN),
            "expires_at": _future(), "outcome": None, "responded_at": None}
    base.update(over)
    return base


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_rate_limiter():
    """The limiter is process-global and per-worker. Left alone, one test's
    twenty requests would silently rate-limit the next test's first."""
    public_approval._HITS.clear()
    yield
    public_approval._HITS.clear()


def _world(approval=None, case=None, claimed=..., approved_row=None):
    """Every collaborator, patched at this router's own module boundary."""
    return [
        patch("routers.public_approval.nar1_approvals.find_by_token",
              return_value=approval),
        patch("routers.public_approval.nar1_cases.get_case",
              return_value=case if case is not None else CASE),
        patch("routers.public_approval.nar1_cases.entity_for",
              return_value=ENTITY),
        patch("routers.public_approval.nar1_cases.update_case",
              return_value={"id": "c1"}),
        patch("routers.public_approval.nar1_approvals.claim",
              return_value=(row(outcome="approved",
                                responded_at="2026-09-02T03:00:00+00:00")
                            if claimed is ... else claimed)),
        patch("routers.public_approval.nar1_approvals.supersede_outstanding",
              return_value=0),
        patch("routers.public_approval.nar1_approvals.approved_row_for",
              return_value=approved_row),
        patch("routers.public_approval.log_event", new=AsyncMock()),
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
#  GET mutates nothing
# --------------------------------------------------------------------------- #

def test_the_page_shows_the_return_and_asks_for_one_press(client):
    with _Stack(*_world(approval=row())):
        response = client.get(PATH)
    assert response.status_code == 200
    assert "ACME LIMITED" in response.text
    assert "00000001" in response.text
    assert "Confirm this Annual Return is correct" in response.text


def test_a_GET_writes_nothing_at_all(client):
    """The load-bearing assertion in this file. Outlook SafeLinks, Gmail and
    every other mail gateway fetch this URL before a human does."""
    patches = _world(approval=row())
    with _Stack(*patches) as entered:
        client.get(PATH)
    _, _, _, update_case, claim, supersede, _, log = entered
    update_case.assert_not_called()
    claim.assert_not_called()
    supersede.assert_not_called()
    log.assert_not_awaited()


def test_the_token_never_appears_in_the_page(client):
    """Not in a hidden field, not in a form action, nowhere a "view source" or
    a copied page would carry it. The form posts to the path already in the
    address bar."""
    with _Stack(*_world(approval=row())):
        response = client.get(PATH)
    assert TOKEN not in response.text


def test_the_page_tells_crawlers_and_caches_to_stay_away(client):
    with _Stack(*_world(approval=row())):
        response = client.get(PATH)
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_the_deadline_is_printed_so_it_is_not_discovered_by_missing_it(client):
    with _Stack(*_world(approval=row(expires_at="2026-09-15T00:00:00+00:00"))):
        response = client.get(PATH)
    assert "15 September 2026" in response.text


# --------------------------------------------------------------------------- #
#  POST approves
# --------------------------------------------------------------------------- #

def test_a_POST_records_the_approval_on_the_case(client):
    patches = _world(approval=row())
    with _Stack(*patches) as entered:
        response = client.post(PATH)
    _, _, _, update_case, claim, supersede, _, log = entered

    assert response.status_code == 200
    assert "confirmation is recorded" in response.text.lower()
    written = update_case.call_args.args[1]
    assert written["client_approved"] is True
    assert written["client_approval_source"] == "self_service"
    assert written["client_approval_person_id"] == "p1"
    assert written["client_approval_name"] == "AH CHAN"
    claim.assert_called_once()
    # One return, one approval: every other director's link stops working.
    supersede.assert_called_once()
    log.assert_awaited()


def test_the_approval_audit_row_carries_the_ip_the_time_and_the_person(client):
    """Levi asked for the IP address, the date and the time. They are on the
    approval row too; they are repeated here because the audit trail is what an
    auditor reads and it should not need a join."""
    patches = _world(
        approval=row(),
        claimed=row(outcome="approved", responded_at="2026-09-02T03:00:00+00:00",
                    ip_address="203.0.113.9", user_agent="Mozilla/5.0"))
    with _Stack(*patches) as entered:
        client.post(PATH)
    logged = entered[-1].await_args.kwargs

    assert logged["action_type"] == "CLIENT_APPROVAL_SELF_SERVICE"
    # audit_log.case_id holds the ENTITY id — routers/cases.py::_audit_target.
    assert logged["case_id"] == "e1"
    assert logged["entity_id"] == "c1"
    assert logged["metadata"]["ip_address"] == "203.0.113.9"
    assert logged["metadata"]["responded_at"] == "2026-09-02T03:00:00+00:00"
    assert logged["metadata"]["person_id"] == "p1"
    # No portal user is behind this. The DIRECTOR is named instead.
    assert logged["user_id"] is None
    assert logged["user_display_name"] == "AH CHAN"


def test_the_audit_row_never_carries_the_token(client):
    """Every staff member with audit_trail:read can read this. A token in it
    would let any of them approve a client's return in the client's name."""
    with _Stack(*_world(approval=row())) as entered:
        client.post(PATH)
    assert TOKEN not in str(entered[-1].await_args.kwargs)


def test_a_second_press_by_the_same_director_is_idempotent(client):
    """A browser replaying the POST, or an impatient double-click, must see what
    they saw the first time rather than an error."""
    approved = row(outcome="approved", responded_at="2026-09-02T03:00:00+00:00")
    patches = _world(approval=approved)
    with _Stack(*patches) as entered:
        response = client.post(PATH)
    assert response.status_code == 200
    assert "already been confirmed" in response.text
    entered[4].assert_not_called()          # claim
    entered[3].assert_not_called()          # update_case


def test_a_later_director_is_told_who_approved_and_when(client):
    """First approval wins, and the loser is told something true rather than
    shown a broken link."""
    winner = row(id="a2", recipient_name="BO LEE", outcome="approved",
                 responded_at="2026-09-02T03:00:00+00:00")
    patches = _world(approval=row(), case={**CASE, "client_approved": True},
                     approved_row=winner)
    with _Stack(*patches):
        response = client.post(PATH)
    assert "already been confirmed" in response.text
    assert "BO LEE" in response.text


def test_losing_the_race_inside_the_update_still_reports_the_truth(client):
    """Two directors pressing in the same second. Postgres settles it, and the
    loser must not be told their press was recorded."""
    winner = row(id="a2", recipient_name="BO LEE", outcome="approved",
                 responded_at="2026-09-02T03:00:00+00:00")
    patches = _world(approval=row(), claimed=None, approved_row=winner)
    with _Stack(*patches) as entered:
        response = client.post(PATH)
    assert "already been confirmed" in response.text
    assert "BO LEE" in response.text
    entered[3].assert_not_called()          # update_case
    entered[-1].assert_not_awaited()        # nothing in the trail either


def test_the_page_offers_no_way_to_reject(client):
    """A rejection has to carry WHAT is wrong, and a free-text box on an
    unauthenticated public route is the one thing this design avoids. The client
    is told to reply to the email instead."""
    with _Stack(*_world(approval=row())):
        response = client.get(PATH)
    lowered = response.text.lower()
    assert "reject" not in lowered
    assert "<textarea" not in lowered
    assert "<input" not in lowered
    assert "reply to the email" in lowered


# --------------------------------------------------------------------------- #
#  The route is not an oracle
# --------------------------------------------------------------------------- #

def _unavailable(response):
    assert response.status_code == 200
    assert "no longer available" in response.text
    assert "Nothing has been changed" in response.text


@pytest.mark.parametrize("method", ["get", "post"])
def test_an_unknown_token_is_unavailable(client, method):
    with _Stack(*_world(approval=None)):
        _unavailable(getattr(client, method)(PATH))


@pytest.mark.parametrize("token", [
    "short", "has spaces here!!", "x" * 200, "../../etc/passwd", "<script>",
])
def test_a_malformed_token_never_reaches_the_database(client, token):
    with _Stack(*_world(approval=row())) as entered:
        response = client.get(f"/public/nar1-approval/{token}")
    # 404 when the path itself does not match the route (a slash in the token);
    # otherwise the same "unavailable" page as every other miss.
    if response.status_code == 200:
        _unavailable(response)
    entered[0].assert_not_called()          # find_by_token


@pytest.mark.parametrize("method", ["get", "post"])
def test_an_expired_token_is_unavailable(client, method):
    with _Stack(*_world(approval=row(expires_at=_past()))):
        _unavailable(getattr(client, method)(PATH))


@pytest.mark.parametrize("method", ["get", "post"])
def test_a_closed_case_is_unavailable_and_says_nothing_about_why(client, method):
    """The reader is a company director on the public internet holding a link
    from an email, and this route authenticates nobody. That the case was
    cancelled, by whom and for what reason is GSHK's business with their
    client — so it is the same "no longer available" page as every other miss.

    THE SECOND LOCK. Closing supersedes every outstanding token, so a link
    normally stops working before it reaches here. That cleanup is best-effort
    by design; a token store that would not write is a reason to shout on
    stderr, not a reason to let a director approve a return nobody will file.
    """
    closed = {**CASE, "closed_at": "2026-09-05T02:00:00+00:00",
              "closed_reason": "client is dissolving the company"}
    with _Stack(*_world(approval=row(), case=closed)) as entered:
        response = getattr(client, method)(PATH)
    _unavailable(response)
    # Not one word of it on a page anybody with the link can fetch.
    assert "dissolving" not in response.text
    assert "closed" not in response.text.lower()
    # And nothing was written: `update_case` is entered[3], `claim` is [4].
    entered[3].assert_not_called()
    entered[4].assert_not_called()


@pytest.mark.parametrize("method", ["get", "post"])
def test_a_superseded_token_is_unavailable(client, method):
    """Verification was restarted: the document this link approves has been
    discarded and rebuilt, and consenting to it now would record approval of
    something CR is not being asked to file."""
    with _Stack(*_world(approval=row(outcome="superseded"))):
        _unavailable(getattr(client, method)(PATH))


def test_an_expired_token_on_an_ALREADY_APPROVED_case_says_so_instead(client):
    """The honest answer is "it is already done", not "your link is broken"."""
    winner = row(id="a2", recipient_name="BO LEE", outcome="approved",
                 responded_at="2026-09-02T03:00:00+00:00")
    with _Stack(*_world(approval=row(expires_at=_past()),
                        case={**CASE, "client_approved": True},
                        approved_row=winner)):
        response = client.get(PATH)
    assert "already been confirmed" in response.text


def test_a_case_that_no_longer_exists_is_unavailable(client):
    patches = _world(approval=row())
    patches[1] = patch("routers.public_approval.nar1_cases.get_case",
                       side_effect=LookupError("no case c1"))
    with _Stack(*patches):
        _unavailable(client.get(PATH))


def test_a_database_fault_is_unavailable_and_not_a_stack_trace(client):
    patches = _world(approval=row())
    patches[0] = patch("routers.public_approval.nar1_approvals.find_by_token",
                       side_effect=RuntimeError("connection refused"))
    with _Stack(*patches):
        response = client.get(PATH)
    _unavailable(response)
    assert "connection refused" not in response.text


def test_every_miss_answers_with_the_same_status(client):
    """A status that differed per reason would leak exactly what the identical
    body hides."""
    statuses = set()
    for approval in (None, row(outcome="superseded"),
                     row(expires_at=_past())):
        public_approval._HITS.clear()
        with _Stack(*_world(approval=approval)):
            statuses.add(client.get(PATH).status_code)
    assert statuses == {200}


def test_the_route_is_rate_limited(client):
    with _Stack(*_world(approval=row())):
        for _ in range(public_approval._RATE_LIMIT):
            assert "Confirm this Annual Return" in client.get(PATH).text
        _unavailable(client.get(PATH))


def test_the_rate_limit_refusal_is_indistinguishable_from_a_bad_token(client):
    with _Stack(*_world(approval=row())):
        for _ in range(public_approval._RATE_LIMIT + 1):
            limited = client.get(PATH)
    public_approval._HITS.clear()
    with _Stack(*_world(approval=None)):
        unknown = client.get(PATH)
    assert limited.text == unknown.text
    assert limited.status_code == unknown.status_code


# --------------------------------------------------------------------------- #
#  It carries no authentication, and needs none
# --------------------------------------------------------------------------- #

def test_no_token_no_cookie_no_credential_is_asked_for(client):
    with _Stack(*_world(approval=row())):
        response = client.get(PATH)
    assert "set-cookie" not in response.headers
    assert "password" not in response.text.lower()
    # Nothing to sign in with, which is why there is nothing here to phish for.
    assert "sign in" not in response.text.lower()


def test_the_POST_accepts_no_body_fields(client):
    """There is no field to supply, so there is nothing to inject. A body is
    simply ignored rather than parsed."""
    with _Stack(*_world(approval=row())) as entered:
        response = client.post(PATH, json={"approved": False,
                                           "person_id": "someone-else"})
    assert response.status_code == 200
    written = entered[3].call_args.args[1]
    assert written["client_approved"] is True
    assert written["client_approval_person_id"] == "p1"


def test_nothing_from_the_request_is_echoed_into_the_page(client):
    with _Stack(*_world(approval=row())):
        response = client.get(PATH, headers={
            "User-Agent": "<script>alert(1)</script>",
            "X-Forwarded-For": "<img src=x onerror=alert(1)>",
        })
    assert "<script>alert(1)</script>" not in response.text
    assert "onerror=" not in response.text


def test_a_company_name_carrying_markup_is_escaped(client):
    """Company names come out of the Viewpoint ETL. An unescaped one lands in a
    client's browser as live markup."""
    patches = _world(approval=row())
    patches[2] = patch("routers.public_approval.nar1_cases.entity_for",
                       return_value={"company_name": "<script>x</script> LTD"})
    with _Stack(*patches):
        response = client.get(PATH)
    assert "<script>x</script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_an_unreadable_company_does_not_break_the_page(client):
    """A client-facing page must not 500 because a lookup failed. The ledger
    omits the rows it has no value for."""
    patches = _world(approval=row())
    patches[2] = patch("routers.public_approval.nar1_cases.entity_for",
                       side_effect=RuntimeError("boom"))
    with _Stack(*patches):
        response = client.get(PATH)
    assert response.status_code == 200
    assert "Confirm this Annual Return is correct" in response.text


@pytest.mark.parametrize("method", ["get", "post"])
def test_a_REJECTED_case_is_unavailable_and_never_reads_as_confirmed(client, method):
    """The client said no and staff are correcting the return. Telling a
    director their Annual Return is confirmed would be false — and the two
    halves of this route must not answer the same case differently, which is
    why they share `_decided`."""
    with _Stack(*_world(approval=row(), case={**CASE, "client_approved": False})):
        response = getattr(client, method)(PATH)
    _unavailable(response)
    assert "already been confirmed" not in response.text


def test_a_case_approved_by_STAFF_is_not_overwritten_by_a_live_link(client):
    """A relayed reply and the 14-day job both decide a case without touching
    any token, so an outstanding link's own outcome is still NULL. Without the
    case-level check the link would overwrite what actually happened with a
    self-service approval that arrived second."""
    winner = row(id="a2", recipient_name="BO LEE", outcome="approved",
                 responded_at="2026-09-02T03:00:00+00:00")
    patches = _world(approval=row(), case={**CASE, "client_approved": True},
                     approved_row=winner)
    with _Stack(*patches) as entered:
        response = client.post(PATH)
    assert "already been confirmed" in response.text
    entered[3].assert_not_called()          # update_case
    entered[4].assert_not_called()          # claim


# --------------------------------------------------------------------------- #
#  Client-controlled input that must not reach a typed column, or a memory leak
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("header", [
    "<script>alert(1)</script>", "not-an-ip", "999.999.999.999", "'; DROP TABLE",
    "", "   ", "-1",
])
def test_a_junk_forwarded_for_records_no_address_rather_than_500ing(client, header):
    """`ip_address` is an `inet` column. An unparseable header would make the
    INSERT fail, the claim fail, and the route answer 500 — a client-controlled
    string turning a director's confirmation into an error page."""
    patches = _world(approval=row())
    with _Stack(*patches) as entered:
        response = client.post(PATH, headers={"X-Forwarded-For": header})
    assert response.status_code == 200
    assert "confirmation is recorded" in response.text.lower()
    assert entered[4].call_args.kwargs["ip"] is None


@pytest.mark.parametrize("header,expected", [
    ("203.0.113.9", "203.0.113.9"),
    ("203.0.113.9, 70.41.3.18", "203.0.113.9"),      # leftmost is the client
    ("  203.0.113.9  ", "203.0.113.9"),
    ("2001:db8::1", "2001:db8::1"),
    ("[2001:db8::1]", "2001:db8::1"),
])
def test_a_real_address_is_recorded_as_the_client_saw_it(client, header, expected):
    with _Stack(*_world(approval=row())) as entered:
        client.post(PATH, headers={"X-Forwarded-For": header})
    assert entered[4].call_args.kwargs["ip"] == expected


def test_the_rate_limiter_does_not_grow_without_bound(client):
    """It is a map keyed on whatever arrives, on an UNAUTHENTICATED route. A
    script sending random tokens would grow it until the worker ran out of
    memory — the limiter would become the denial of service."""
    from routers import public_approval as pa

    now = pa.time.monotonic()
    # Simulate a keyspace walk that has already gone cold.
    for i in range(pa._HITS_MAX_KEYS + 500):
        pa._HITS[f"t:{i}"] = [now - pa._RATE_WINDOW_SECONDS - 1]
    assert len(pa._HITS) > pa._HITS_MAX_KEYS

    pa._rate_limited("t:fresh")
    assert len(pa._HITS) <= pa._HITS_MAX_KEYS


def test_the_sweep_never_drops_a_key_that_is_still_being_limited(client):
    """Shedding a hot key would hand the attacker a fresh allowance."""
    from routers import public_approval as pa

    now = pa.time.monotonic()
    for i in range(pa._HITS_MAX_KEYS + 200):
        pa._HITS[f"cold:{i}"] = [now - pa._RATE_WINDOW_SECONDS - 1]
    pa._HITS["hot"] = [now] * (pa._RATE_LIMIT + 5)

    pa._rate_limited("something-else")
    assert "hot" in pa._HITS
    assert len(pa._HITS["hot"]) >= pa._RATE_LIMIT


def test_the_page_runs_no_script_at_all(client):
    """Nothing on this page executes. It is reached by an unauthenticated link
    from an email, and the smallest attack surface is no attack surface — which
    is also why the Confirm control is a plain form and not a fetch()."""
    with _Stack(*_world(approval=row())):
        response = client.get(PATH)
    lowered = response.text.lower()
    assert "<script" not in lowered
    assert "onclick" not in lowered
    assert "onerror" not in lowered
    assert "javascript:" not in lowered

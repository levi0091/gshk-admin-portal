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


@pytest.fixture(autouse=True)
def _nobody_is_asked_to_sign(request):
    """The suite's default is today's page: no pad. `must_sign` reads the
    officer tables, and `_world` patches no Supabase -- left alone, every ND2
    test here would reach for a live database (it fails safe to False, but a
    test must not depend on that). The e-signature tests below take
    `a_director_signs` to ask for the pad."""
    if "a_director_signs" in request.fixturenames:
        yield
        return
    with patch("routers.public_approval.signatures.must_sign", return_value=False):
        yield


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
    assert ">Confirm &amp; File</button>" in response.text


def test_the_warning_is_on_the_page_BEFORE_anything_can_be_pressed(client):
    """The approved mock draws this as a modal over the page (Levi 2026-09-08).
    A modal needs script and this route runs none, so it is rendered inline —
    which says the same words at the same moment, which is the whole job of a
    warning. Asserted verbatim: it is what a client is shown immediately before
    a chargeable, irreversible statutory filing."""
    with _Stack(*_world(approval=row())):
        text = client.get(PATH).text
    assert "Warning" in text
    assert ("By clicking <strong>Confirm &amp; File</strong>, you confirm "
            "that you have reviewed the draft and that the information is "
            "correct. The NAR1 will then be arranged for submission without "
            "further confirmation.") in text
    # Before the control it warns about, not after it.
    assert text.index("further confirmation") < text.index("<button")


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
    """RELATIVE TO TODAY, not a literal date. This used a hardcoded
    2026-09-15 expiry; the day it arrived the route served the expired page
    instead, and CI went red on a calendar boundary rather than a code change
    — the same trap `_RESPOND_BY` avoids in test_cases_verification.py.

    Midnight UTC is 08:00 in Hong Kong, so the date cannot shift a day in the
    conversion and the time proves the conversion happened."""
    deadline = datetime.now(timezone.utc).date() + timedelta(days=30)
    expires_at = f"{deadline.isoformat()}T00:00:00+00:00"
    with _Stack(*_world(approval=row(expires_at=expires_at))):
        response = client.get(PATH)
    assert f"{deadline:%d %B %Y} at 08:00 HKT" in response.text


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
    is sent to the renewal mailbox instead — NOT told to reply to the email,
    which now says in as many words that replies are not monitored."""
    with _Stack(*_world(approval=row())):
        response = client.get(PATH)
    lowered = response.text.lower()
    assert "reject" not in lowered
    assert "<textarea" not in lowered
    assert "<input" not in lowered
    assert "renewal@getstarted.hk" in lowered
    assert "reply to the email" not in lowered


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
            assert "Confirm &amp; File" in client.get(PATH).text
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
    assert ">Confirm &amp; File</button>" in response.text


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


# --------------------------------------------------------------------------- #
#  "You are confirming" (nd2-change-requests PRD section 6, test 9)
# --------------------------------------------------------------------------- #

ND2_PATH = f"/public/officer-change-approval/{TOKEN}"
ND2A_CASE = {**CASE, "case_no": "ND2A-2026-0001", "form_code": "Nd2a"}


def _confirming(text: str) -> str:
    """The list, cut out of the page: from its heading to the Warning panel."""
    return text[text.index("You are confirming"):text.index('class="warn"')]


def test_a_nar1_page_names_the_return_and_its_file(client):
    with _Stack(*_world(approval=row(revision=2))):
        text = client.get(PATH).text
    listed = _confirming(text)
    assert "Form NAR1 — Annual Return 2026 (Rev. 2)" in listed
    assert "NAR1-NAR-2026-0041-Rev2.pdf" in listed
    assert "<script" not in text.lower()


def test_an_nd2a_page_names_the_form_and_the_resolution(client):
    with _Stack(*_world(approval=row(), case=ND2A_CASE)):
        text = client.get(ND2_PATH).text
    listed = _confirming(text)
    assert "Form ND2A — Change of company secretary and director" in listed
    assert "ND2A-ND2A-2026-0001.pdf" in listed
    assert "Written resolution of the directors" in listed
    assert "Written-Resolution-ND2A-2026-0001.pdf" in listed
    assert "<script" not in text.lower()
    # Two documents, so the line above the list must not say "the form".
    assert "against the documents attached to our email" in text


def test_an_nd2b_page_names_the_form_only(client):
    nd2b = {**CASE, "case_no": "ND2B-2026-0001", "form_code": "Nd2b"}
    with _Stack(*_world(approval=row(), case=nd2b)):
        text = client.get(ND2_PATH).text
    listed = _confirming(text)
    assert "Form ND2B" in listed and "ND2B-ND2B-2026-0001.pdf" in listed
    assert "resolution" not in listed.lower()
    assert "against the form attached to our email" in text


def test_the_list_is_above_the_warning_and_the_button(client):
    with _Stack(*_world(approval=row())):
        text = client.get(PATH).text
    assert text.index("You are confirming") < text.index("Warning") < text.index("</button>")


def test_a_case_number_carrying_markup_is_escaped_in_the_list(client):
    """Titles and file names are built from the case, which holds free text."""
    bad = {**CASE, "case_no": "<img src=x onerror=alert(1)>"}
    with _Stack(*_world(approval=row(), case=bad)):
        text = client.get(PATH).text
    assert "<img src=x" not in text
    assert "&lt;img src=x onerror=alert(1)&gt;" in _confirming(text)


# --------------------------------------------------------------------------- #
#  An earlier revision's link (Levi 2026-10-02, migration 051)
# --------------------------------------------------------------------------- #

#: The case after Rev. 2 went out. A Rev. 1 link is still OUTSTANDING here —
#: the supersede that should have killed it did not land — which is exactly
#: the case the revision lock exists for.
RESENT = {**CASE, "verification_revision": 2}


def test_an_earlier_revisions_link_is_no_longer_available(client):
    with _Stack(*_world(approval=row(revision=1), case=RESENT)):
        response = client.get(PATH)
    assert "no longer available" in response.text
    assert "Confirm &amp; File</button>" not in response.text


def test_an_earlier_revisions_link_cannot_approve(client):
    with _Stack(*_world(approval=row(revision=1), case=RESENT)) as patched:
        response = client.post(PATH)
    claim, update_case = patched[4], patched[3]
    assert "no longer available" in response.text
    claim.assert_not_called()
    update_case.assert_not_called()


def test_the_current_revisions_link_still_works(client):
    with _Stack(*_world(approval=row(revision=2), case=RESENT)):
        response = client.get(PATH)
    assert ">Confirm &amp; File</button>" in response.text


def test_an_approved_earlier_revision_does_not_claim_the_return_is_confirmed(client):
    """A director who approved Rev. 1 and opens that email again after Rev. 2
    went out used to be told the return was already confirmed — true of a
    document nobody is filing, false of the one awaiting them."""
    approved_rev1 = row(revision=1, outcome="approved",
                        responded_at="2026-09-28T03:00:00+00:00")
    with _Stack(*_world(approval=approved_rev1, case=RESENT)):
        response = client.get(PATH)
    assert "already been confirmed" not in response.text
    assert "no longer available" in response.text


def test_once_the_new_revision_is_approved_an_old_link_says_so(client):
    """The case is settled now, so the honest answer to an old link is that it
    is done — the same rule a superseded link already follows."""
    settled = {**RESENT, "client_approved": True}
    with _Stack(*_world(approval=row(revision=1), case=settled,
                        approved_row=row(revision=2, outcome="approved",
                                         recipient_name="BO LEE"))):
        response = client.get(PATH)
    assert "already been confirmed" in response.text
    assert "BO LEE" in response.text


def test_the_page_names_the_revision_it_is_confirming(client):
    """With two emails in the inbox, "check against the form attached to our
    email" is ambiguous; the page says which one. From the link's own row,
    never from the request."""
    with _Stack(*_world(approval=row(revision=2), case=RESENT)):
        response = client.get(PATH)
    assert "<dt>Revision</dt><dd>Rev. 2</dd>" in response.text


@pytest.mark.parametrize("revision", [1, None])
def test_a_first_email_or_legacy_link_page_names_no_revision(client, revision):
    with _Stack(*_world(approval=row(revision=revision),
                        case={**CASE, "verification_revision": 1})):
        response = client.get(PATH)
    assert ">Confirm &amp; File</button>" in response.text
    assert "<dt>Revision</dt>" not in response.text


def test_a_link_ahead_of_the_case_still_works_on_the_page(client):
    """The job skips such a link (nar1_approvals.is_ahead); the page must not.
    A send that went out and then failed to write the case leaves the client
    holding exactly this — a genuine link one revision ahead."""
    with _Stack(*_world(approval=row(revision=3), case=RESENT)):
        response = client.get(PATH)
    assert ">Confirm &amp; File</button>" in response.text


def test_a_link_issued_before_revisions_existed_still_works(client):
    """NULL revision: the lock does not apply, and the outcome still governs."""
    with _Stack(*_world(approval=row(revision=None), case=RESENT)):
        response = client.get(PATH)
    assert ">Confirm &amp; File</button>" in response.text


def test_the_approval_records_which_revision_was_confirmed(client):
    claimed = row(revision=2, outcome="approved",
                  responded_at="2026-10-02T03:00:00+00:00")
    with _Stack(*_world(approval=row(revision=2), case=RESENT,
                        claimed=claimed)) as patched:
        client.post(PATH)
    log = patched[7]
    assert log.call_args.kwargs["metadata"]["revision"] == 2


# --------------------------------------------------------------------------- #
#  An ND2B filed without the client's confirmation (Jacqueline BQ1)
# --------------------------------------------------------------------------- #

WAIVED = {"id": "c1", "case_no": "ND2B-2026-0003", "entity_id": "e1", "form_code": "Nd2b",
          "client_approved": True, "client_approval_source": "staff_waiver",
          "client_approval_name": "Filing deadline"}


def test_the_client_can_still_confirm_after_a_waiver(client):
    path = f"/public/officer-change-approval/{TOKEN}"
    with _Stack(*_world(approval=row(), case=WAIVED)):
        shown = client.get(path)
        assert ">Confirm &amp; File</button>" in shown.text
        assert "already" not in shown.text.lower()
        done = client.post(path)
    assert "your confirmation is recorded" in done.text


def test_provenance_says_the_case_proceeds_without_confirmation():
    out = approvals.provenance(WAIVED)
    assert out["source"] == "staff_waiver" and out["name"] is None
    assert out["summary"] == ("Proceeding without the client's confirmation — "
                              "Filing deadline")


# --------------------------------------------------------------------------- #
#  The confirmation receipt (Levi 2026-10-17)
#
#  Queued once, by the press that actually claimed the approval, and never by a
#  GET, a replay, a stale link or the director who lost the race.
# --------------------------------------------------------------------------- #

CLAIMED = row(outcome="approved", responded_at="2026-10-17T07:31:05+00:00")


def test_a_confirmation_queues_one_receipt_for_the_director_who_pressed(
        client, _no_receipt_mail_in_tests):
    with _Stack(*_world(approval=row(), claimed=CLAIMED)):
        response = client.post(PATH)
    assert "Thank you" in response.text
    _no_receipt_mail_in_tests.assert_awaited_once()
    case_id, approval = _no_receipt_mail_in_tests.await_args.args
    assert case_id == "c1"
    assert approval["recipient_email"] == "chan@example.com"
    assert approval["responded_at"] == "2026-10-17T07:31:05+00:00"


def test_an_officer_change_confirmation_queues_a_receipt_too(
        client, _no_receipt_mail_in_tests):
    nd2a = {**CASE, "case_no": "ND2A-2026-0001", "form_code": "Nd2a"}
    with _Stack(*_world(approval=row(), case=nd2a, claimed=CLAIMED)):
        response = client.post(f"/public/officer-change-approval/{TOKEN}")
    assert "your confirmation is recorded" in response.text
    _no_receipt_mail_in_tests.assert_awaited_once()


def test_opening_the_link_sends_no_receipt(client, _no_receipt_mail_in_tests):
    with _Stack(*_world(approval=row())):
        client.get(PATH)
    _no_receipt_mail_in_tests.assert_not_awaited()


def test_a_replayed_press_sends_no_second_receipt(client, _no_receipt_mail_in_tests):
    with _Stack(*_world(approval=CLAIMED)):
        client.post(PATH)
    _no_receipt_mail_in_tests.assert_not_awaited()


def test_the_director_who_lost_the_race_gets_no_receipt(client, _no_receipt_mail_in_tests):
    with _Stack(*_world(approval=row(), claimed=None, approved_row=CLAIMED)):
        client.post(PATH)
    _no_receipt_mail_in_tests.assert_not_awaited()


def test_a_link_from_an_earlier_revision_sends_no_receipt(client, _no_receipt_mail_in_tests):
    with _Stack(*_world(approval=row(revision=1),
                        case={**CASE, "verification_revision": 2})):
        client.post(PATH)
    _no_receipt_mail_in_tests.assert_not_awaited()


def test_an_expired_link_sends_no_receipt(client, _no_receipt_mail_in_tests):
    with _Stack(*_world(approval=row(expires_at=_past()))):
        client.post(PATH)
    _no_receipt_mail_in_tests.assert_not_awaited()


# --------------------------------------------------------------------------- #
#  A director draws a signature (e-signature-nd2, spec section 6, tests 3-4)
# --------------------------------------------------------------------------- #

import base64
import io
import re

from PIL import Image, ImageDraw


def _drawing(ink=True) -> str:
    img = Image.new("RGBA", (600, 200), (0, 0, 0, 0))
    if ink:
        ImageDraw.Draw(img).line([(20, 150), (120, 40), (200, 160), (320, 60)],
                                 fill=(26, 32, 80, 255), width=6)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


@pytest.fixture
def a_director_signs():
    """The link was issued to a director with a box to sign. Taking this fixture
    by name switches off the suite-wide `False` stub (see above) and patches the
    answer to True; the store is patched too, so no test reaches Supabase."""
    with patch("routers.public_approval.signatures.must_sign",
               return_value=True) as ask, \
         patch("routers.public_approval.signatures.store",
               return_value={"id": "sig-1"}) as store:
        yield ask, store


def _scripts(text: str) -> list[str]:
    return re.findall(r"<script\b[^>]*>.*?</script>", text, flags=re.S | re.I)


def test_a_directors_page_has_the_pad_a_disabled_button_and_a_noscript_note(
        client, a_director_signs):
    with _Stack(*_world(approval=row(), case=ND2A_CASE)):
        text = client.get(ND2_PATH).text
    assert "Your signature" in text
    assert '<canvas id="sigpad"' in text
    assert ' name="signature"' in text and 'type="hidden"' in text
    assert 'id="sigclear"' in text and ">Clear</button>" in text
    assert re.search(r'<button type="submit" id="sigok" disabled>Confirm &amp; File</button>',
                     text)
    assert ('<noscript><p class="stop">Signing needs JavaScript. Turn it on, or '
            'reply to renewal@getstarted.hk.</p></noscript>') in text
    assert "listed above where a director signs" in text
    # Above the warning and the button it arms.
    assert text.index("Your signature") < text.index("Warning") < text.index("sigok")


def test_a_directors_page_runs_the_pad_and_nothing_else(client, a_director_signs):
    """Exactly one script, inline, with no src, and nothing in it that can reach
    the network. It is reached from an unauthenticated link in an email."""
    with _Stack(*_world(approval=row(), case=ND2A_CASE)):
        text = client.get(ND2_PATH).text
    scripts = _scripts(text)
    assert len(scripts) == 1
    tag = scripts[0].lower()
    assert " src" not in tag.split(">")[0]
    for forbidden in ("fetch", "xmlhttprequest", "sendbeacon", "websocket",
                      "eventsource", "import(", "eval(", "document.write",
                      "innerhtml", "location", "cookie", "localstorage"):
        assert forbidden not in tag, forbidden
    assert "pointerdown" in tag and "toDataURL('image/png')" in scripts[0]
    for handler in ("onclick", "onerror", "onload", "javascript:"):
        assert handler not in text.lower()
    # No other element of the page loads anything.
    assert "<link" not in text.lower() and "<img" not in text.lower()


def test_the_nd2b_pad_names_only_the_form(client, a_director_signs):
    nd2b = {**CASE, "case_no": "ND2B-2026-0001", "form_code": "Nd2b"}
    with _Stack(*_world(approval=row(), case=nd2b)):
        text = client.get(ND2_PATH).text
    assert "printed on the form listed above" in text


def test_the_page_decides_from_the_links_own_person(client, a_director_signs):
    ask, _ = a_director_signs
    with _Stack(*_world(approval=row(person_id="p7"), case=ND2A_CASE)):
        client.get(ND2_PATH)
    assert ask.call_args.args[1] == "p7"


def test_a_non_director_nd2_page_has_no_pad_and_no_script(client):
    with _Stack(*_world(approval=row(), case=ND2A_CASE)):
        text = client.get(ND2_PATH).text
    assert "<script" not in text.lower() and "<canvas" not in text.lower()
    assert "Your signature" not in text and "noscript" not in text.lower()
    assert '<button type="submit">Confirm &amp; File</button>' in text


def test_a_nar1_page_has_no_pad_even_if_the_person_would_sign(client, a_director_signs):
    with _Stack(*_world(approval=row())):
        text = client.get(PATH).text
    assert "<script" not in text.lower() and "<canvas" not in text.lower()


def test_getting_a_directors_page_writes_nothing(client, a_director_signs):
    _, store = a_director_signs
    with _Stack(*_world(approval=row(), case=ND2A_CASE)) as patched:
        client.get(ND2_PATH)
    store.assert_not_called()
    patched[4].assert_not_called()   # claim
    patched[7].assert_not_awaited()  # log_event


def test_a_director_who_signs_is_claimed_stored_and_audited(client, a_director_signs):
    _, store = a_director_signs
    drawn = _drawing()
    with _Stack(*_world(approval=row(revision=1), case={**ND2A_CASE, "verification_revision": 1},
                        claimed=row(id="a1", revision=1, outcome="approved",
                                    responded_at="2026-09-02T03:00:00+00:00"))) as patched:
        response = client.post(ND2_PATH, data={"signature": drawn})
    assert "your confirmation is recorded" in response.text
    patched[4].assert_called_once()
    store.assert_called_once()
    kwargs = store.call_args.kwargs
    assert (kwargs["case_id"], kwargs["approval_id"], kwargs["person_id"],
            kwargs["revision"]) == ("c1", "a1", "p1", 1)
    assert kwargs["png"] == base64.b64decode(drawn.split(",", 1)[1])
    audit = patched[7].await_args.kwargs
    assert audit["metadata"]["signature"] == {"captured": True, "signature_id": "sig-1"}


def test_the_image_never_enters_an_audit_row(client, a_director_signs):
    drawn = _drawing()
    with _Stack(*_world(approval=row(), case=ND2A_CASE)) as patched:
        client.post(ND2_PATH, data={"signature": drawn})
    audit_text = repr(patched[7].await_args)
    assert drawn.split(",", 1)[1][:60] not in audit_text
    assert "data:image" not in audit_text


@pytest.mark.parametrize("data", [
    {},                                          # no field at all
    {"signature": ""},
    {"signature": "data:image/png;base64,AAAA"},  # not a PNG
    {"signature": "not even a data url"},
])
def test_a_director_without_a_usable_signature_is_not_claimed(client, a_director_signs, data):
    _, store = a_director_signs
    with _Stack(*_world(approval=row(), case=ND2A_CASE)) as patched:
        response = client.post(ND2_PATH, data=data)
    assert "We could not read your signature. Please draw it again." in response.text
    assert ">Confirm &amp; File</button>" in response.text   # the page, again
    patched[4].assert_not_called()    # claim
    patched[3].assert_not_called()    # update_case
    patched[7].assert_not_awaited()   # log_event
    store.assert_not_called()


def test_a_blank_canvas_is_not_a_signature(client, a_director_signs):
    _, store = a_director_signs
    with _Stack(*_world(approval=row(), case=ND2A_CASE)) as patched:
        response = client.post(ND2_PATH, data={"signature": _drawing(ink=False)})
    assert "We could not read your signature" in response.text
    patched[4].assert_not_called()
    store.assert_not_called()


def test_a_body_over_300_kb_is_refused_before_it_is_parsed(client, a_director_signs):
    _, store = a_director_signs
    with _Stack(*_world(approval=row(), case=ND2A_CASE)) as patched, \
            patch("starlette.requests.Request.form") as form:
        response = client.post(ND2_PATH, data={"signature": "A" * (301 * 1024)})
    assert "We could not read your signature" in response.text
    form.assert_not_called()
    patched[4].assert_not_called()
    store.assert_not_called()


def test_a_chunked_body_over_the_cap_is_refused_too(client, a_director_signs):
    """No Content-Length to check, so the cap has to hold while reading."""
    _, store = a_director_signs

    def body():
        yield b"signature="
        for _ in range(31):
            yield b"A" * 10_240

    with _Stack(*_world(approval=row(), case=ND2A_CASE)) as patched:
        response = client.post(ND2_PATH, content=body(),
                               headers={"content-type": "application/x-www-form-urlencoded"})
    assert "We could not read your signature" in response.text
    patched[4].assert_not_called()
    store.assert_not_called()


def test_the_retry_page_keeps_the_pad_and_does_not_echo_the_submission(client, a_director_signs):
    with _Stack(*_world(approval=row(), case=ND2A_CASE)):
        response = client.post(ND2_PATH, data={"signature": "<b>x</b>"})
    assert "<b>x</b>" not in response.text
    assert '<canvas id="sigpad"' in response.text and len(_scripts(response.text)) == 1


def test_a_non_director_claims_as_before_and_stores_nothing(client):
    with _Stack(*_world(approval=row(), case=ND2A_CASE)) as patched, \
            patch("routers.public_approval.signatures.store") as store:
        response = client.post(ND2_PATH)
    assert "your confirmation is recorded" in response.text
    patched[4].assert_called_once()
    store.assert_not_called()
    assert "signature" not in patched[7].await_args.kwargs["metadata"]


def test_a_non_directors_post_is_not_read_for_a_signature(client):
    with _Stack(*_world(approval=row(), case=ND2A_CASE)), \
            patch("routers.public_approval._read_signature_field") as reader:
        client.post(ND2_PATH, data={"signature": _drawing()})
    reader.assert_not_called()


def test_the_director_who_loses_the_race_leaves_no_signature(client, a_director_signs):
    _, store = a_director_signs
    with _Stack(*_world(approval=row(), case=ND2A_CASE, claimed=None,
                        approved_row=CLAIMED)):
        response = client.post(ND2_PATH, data={"signature": _drawing()})
    assert "already been confirmed" in response.text
    store.assert_not_called()


def test_a_stale_expired_or_replayed_link_leaves_no_signature(client, a_director_signs):
    _, store = a_director_signs
    resent = {**ND2A_CASE, "verification_revision": 2}
    for approval, case in ((row(revision=1), resent),
                           (row(expires_at=_past()), ND2A_CASE),
                           (CLAIMED, ND2A_CASE)):
        with _Stack(*_world(approval=approval, case=case)) as patched:
            client.post(ND2_PATH, data={"signature": _drawing()})
        patched[4].assert_not_called()
    store.assert_not_called()


def test_a_failed_insert_is_retried_once(client, a_director_signs):
    _, store = a_director_signs
    store.side_effect = [RuntimeError("blip"), {"id": "sig-2"}]
    with _Stack(*_world(approval=row(), case=ND2A_CASE)) as patched:
        response = client.post(ND2_PATH, data={"signature": _drawing()})
    assert "your confirmation is recorded" in response.text
    assert store.call_count == 2
    assert patched[7].await_args.kwargs["metadata"]["signature"] == {
        "captured": True, "signature_id": "sig-2"}


def test_a_signature_that_cannot_be_stored_still_confirms_and_says_so(client, a_director_signs):
    _, store = a_director_signs
    store.side_effect = RuntimeError("down")
    with _Stack(*_world(approval=row(), case=ND2A_CASE)) as patched:
        response = client.post(ND2_PATH, data={"signature": _drawing()})
    assert "your confirmation is recorded" in response.text
    assert store.call_count == 2
    patched[4].assert_called_once()   # the claim stands: the director did confirm
    assert patched[7].await_args.kwargs["metadata"]["signature"] == {"captured": False}

"""`POST /cases/{id}/close` — ending a case the client is not proceeding with.

CLOSING IS PERMANENT AND THERE IS NO REOPEN ROUTE (Levi 2026-09-05). That makes
the interesting tests the REFUSALS, not the happy path: a feature whose whole
promise is "this cannot be undone" is only as good as the writes it goes on to
turn away, and each of those lives in a different handler.

Patches `middleware.auth._resolve_user`, as test_cases_router.py does.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services import nar1_case_status as st

SUPER = {"id": "u1", "display_name": "Levi", "role_name": "super_admin",
         "role_id": "role-sa"}
H = {"Authorization": "Bearer tok"}

OPEN_CASE = {"id": "c1", "case_no": "NAR-2026-0041", "entity_id": "e1"}
CLOSED_CASE = {
    **OPEN_CASE,
    "closed_at": "2026-09-05T02:00:00+00:00",
    "closed_by": "u1",
    "closed_reason": "client is dissolving the company",
}


def _super():
    return patch("middleware.auth._resolve_user", return_value=SUPER)


def _nobody():
    """A Supabase double that recognises no token, for the auth gate.

    Patches ONLY the Supabase boundary so the real `_resolve_user` still runs —
    a test that reaches the live client is green locally and red in CI.
    """
    sb = MagicMock()
    sb.auth.get_user.return_value = MagicMock(user=None)
    return patch("middleware.auth.get_supabase", return_value=sb)


@pytest.fixture
def client():
    return TestClient(app)


_UNSET = object()


def _closing(*, case=OPEN_CASE, filing=None, closed=_UNSET, superseded=1):
    """Everything `close_case` touches, stubbed. Returns the patch context and
    the spies the assertions need."""
    spies = {}
    stack = [
        _super(),
        patch("routers.cases.nar1_cases.get_case", return_value=case),
        patch("routers.cases.nar1_cases.blocking_filing", return_value=filing),
        patch("routers.cases.nar1_cases.close_case",
              return_value=(CLOSED_CASE if closed is _UNSET else closed)),
        patch("routers.cases.nar1_cases.composite",
              return_value={**CLOSED_CASE, "workflow_status":
                            {"code": "closed", "label": "Closed"}}),
        patch("routers.cases.nar1_cases.entity_for", return_value={}),
        patch("routers.cases.tpsi_filings.supersede_all_for_case",
              return_value=superseded),
        patch("routers.cases.nar1_approvals.supersede_outstanding"),
        patch("routers.cases.log_event", new_callable=AsyncMock),
    ]
    return stack, spies


def _enter(stack):
    return [ctx.__enter__() for ctx in stack]


def _exit(stack):
    for ctx in reversed(stack):
        ctx.__exit__(None, None, None)


# --------------------------------------------------------------------------- #
#  The happy path
# --------------------------------------------------------------------------- #

def test_closing_writes_the_reason_and_audits_it(client):
    stack, _ = _closing()
    entered = _enter(stack)
    try:
        close = entered[3]
        logged = entered[8]
        response = client.post("/cases/c1/close", headers=H,
                               json={"reason": "client is dissolving the company"})
    finally:
        _exit(stack)

    assert response.status_code == 200
    assert close.call_args.kwargs["reason"] == "client is dissolving the company"
    assert close.call_args.kwargs["user_id"] == "u1"

    kwargs = logged.await_args.kwargs
    assert kwargs["action_type"] == "NAR1_CASE_CLOSED"
    assert kwargs["event_code"] == "NAR1_CASE_CLOSED"
    # THE REASON IS THE POINT. Everything else about a closure can be
    # reconstructed from the row; why cannot.
    assert kwargs["metadata"]["reason"] == "client is dissolving the company"
    assert kwargs["new_value"] == "Closed"


def test_the_trail_records_what_the_case_was_doing_when_it_ended(client):
    """"Closed" alone cannot say what was left undone, which is the first thing
    anyone reviewing an abandoned case asks."""
    stack, _ = _closing(case={**OPEN_CASE, "verification_sent_at": "2026-09-01"},
                        filing={"id": "f1", "stage": "validated"})
    entered = _enter(stack)
    try:
        logged = entered[8]
        client.post("/cases/c1/close", headers=H, json={"reason": "no longer needed"})
    finally:
        _exit(stack)

    kwargs = logged.await_args.kwargs
    assert kwargs["old_value"] == st.WORKFLOW_LABELS[st.AWAITING_CLIENT]
    assert kwargs["metadata"]["filing_stage_at_close"] == "validated"


def test_a_reason_is_required(client):
    """Whitespace is not a reason. Refused BEFORE the case is even read, so a
    blank one cannot half-close anything."""
    for reason in ("", "   ", "\n", "\t "):
        with _super(), patch("routers.cases.nar1_cases.get_case") as read:
            response = client.post("/cases/c1/close", headers=H,
                                   json={"reason": reason})
        assert response.status_code == 400, reason
        read.assert_not_called()


def test_a_reason_longer_than_the_cap_is_refused(client):
    with _super():
        response = client.post("/cases/c1/close", headers=H,
                               json={"reason": "x" * 1001})
    assert response.status_code == 400


def test_the_body_is_required(client):
    """No accidental close from a bare POST — FastAPI answers 422 for a missing
    body, and the important half is that nothing was written."""
    with _super(), patch("routers.cases.nar1_cases.close_case") as close:
        response = client.post("/cases/c1/close", headers=H)
    assert response.status_code == 422
    close.assert_not_called()


# --------------------------------------------------------------------------- #
#  What closing must refuse
# --------------------------------------------------------------------------- #

def test_a_case_the_registry_already_holds_cannot_be_closed(client):
    """Closing a filed return would record a lodged statutory filing as one the
    client abandoned — a false statement about the register, not an untidy
    badge."""
    for case, filing in (
        ({**OPEN_CASE, "manual_submitted_at": "2026-08-18"}, None),
        ({**OPEN_CASE, "manual_receipt": {"caseNo": "1"}}, None),
        (OPEN_CASE, {"id": "f1", "stage": "submitted"}),
        (OPEN_CASE, {"id": "f1", "stage": "registered"}),
    ):
        stack, _ = _closing(case=case, filing=filing)
        entered = _enter(stack)
        try:
            close = entered[3]
            response = client.post("/cases/c1/close", headers=H,
                                   json={"reason": "client changed their mind"})
        finally:
            _exit(stack)
        assert response.status_code == 409, (case, filing)
        assert response.json()["detail"]["reason"] == "case_filed"
        close.assert_not_called()


def test_closing_a_closed_case_is_refused_and_the_first_reason_stands(client):
    stack, _ = _closing(case=CLOSED_CASE)
    entered = _enter(stack)
    try:
        close = entered[3]
        response = client.post("/cases/c1/close", headers=H,
                               json={"reason": "a second, different reason"})
    finally:
        _exit(stack)

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "case_closed"
    close.assert_not_called()


def test_losing_the_race_is_a_409_and_writes_nothing_to_the_trail(client):
    """`close_case` settles it inside the UPDATE and answers None when another
    request got there first. audit_log is insert-only, so a second
    NAR1_CASE_CLOSED naming a second person and a second reason could never be
    taken back."""
    stack, _ = _closing(closed=None)
    entered = _enter(stack)
    try:
        logged = entered[8]
        response = client.post("/cases/c1/close", headers=H,
                               json={"reason": "client is not proceeding"})
    finally:
        _exit(stack)

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "case_closed"
    logged.assert_not_awaited()


def test_closing_requires_authentication(client):
    """Mocked at the Supabase boundary and nowhere else, as
    test_cases_router.py does it: the real `_resolve_user`, the real
    `require_permission` chain and the real HTTPBearer all run. Reaching the
    LIVE client instead makes the result depend on ambient env — backend/.env
    supplies a key here and CI supplies none, so the refusal would arrive as a
    500 in CI and a pass locally."""
    with _nobody(), patch("routers.cases.nar1_cases.close_case") as close:
        # With a bearer token that resolves to nobody...
        assert client.post("/cases/c1/close", headers=H,
                           json={"reason": "x"}).status_code in (401, 403)
        # ...and with no Authorization header at all, refused by HTTPBearer
        # before `_resolve_user` is ever reached.
        assert client.post("/cases/c1/close",
                           json={"reason": "x"}).status_code in (401, 403)
    close.assert_not_called()


def test_closing_requires_nar1_write(client):
    """`nar1:read` lets you watch a case. It must not let you end one."""
    reader = {"id": "u2", "display_name": "Reader", "role_name": "staff",
              "role_id": "r2"}
    with patch("middleware.auth._resolve_user", return_value=reader), \
         patch("middleware.auth._permissions_for", return_value={"read"}), \
         patch("routers.cases.nar1_cases.close_case") as close:
        response = client.post("/cases/c1/close", headers=H,
                               json={"reason": "x"})
    assert response.status_code == 403
    close.assert_not_called()


# --------------------------------------------------------------------------- #
#  What closing takes down with it
# --------------------------------------------------------------------------- #

def test_closing_supersedes_every_live_filing_not_merely_the_newest(client):
    """`filings._check_gate` PASSES on a signed row, so a live filing left on a
    closed case is one chargeable, irreversible call from lodging a return the
    client cancelled. Nothing stops two drafts existing on one case, which is
    why this is not `supersede(current_filing)`."""
    stack, _ = _closing(filing={"id": "f1", "stage": "signed"}, superseded=2)
    entered = _enter(stack)
    try:
        supersede = entered[6]
        response = client.post("/cases/c1/close", headers=H,
                               json={"reason": "client is not proceeding"})
    finally:
        _exit(stack)

    assert response.status_code == 200
    supersede.assert_called_once_with("c1")
    assert response.json()["filings_superseded"] == 2


def test_closing_revokes_every_outstanding_approval_link(client):
    """A director holding the verification email could otherwise approve a
    return that will never be filed, and the portal would record a client
    consenting to a cancelled case."""
    stack, _ = _closing()
    entered = _enter(stack)
    try:
        revoke = entered[7]
        response = client.post("/cases/c1/close", headers=H,
                               json={"reason": "client is not proceeding"})
    finally:
        _exit(stack)

    assert response.status_code == 200
    revoke.assert_called_once_with("c1")
    assert response.json()["approval_links_revoked"] is True


def test_a_cleanup_failure_does_not_un_close_the_case(client):
    """The case IS closed the instant its UPDATE lands and every guard already
    reads that fact. A 500 here would report a failed close over a case that is
    genuinely shut — so both cleanups are reported instead, which is what turns
    a partial tidy-up into something an operator can see and repeat."""
    stack, _ = _closing()
    stack[6] = patch("routers.cases.tpsi_filings.supersede_all_for_case",
                     side_effect=RuntimeError("supabase is down"))
    stack[7] = patch("routers.cases.nar1_approvals.supersede_outstanding",
                     side_effect=RuntimeError("supabase is down"))
    entered = _enter(stack)
    try:
        logged = entered[8]
        response = client.post("/cases/c1/close", headers=H,
                               json={"reason": "client is not proceeding"})
    finally:
        _exit(stack)

    assert response.status_code == 200
    body = response.json()
    assert body["filings_superseded"] == 0
    assert body["approval_links_revoked"] is False
    # And the trail says so, so "the links may still be live" is a fact on the
    # record rather than a line on somebody's terminal.
    assert logged.await_args.kwargs["metadata"]["approval_links_revoked"] is False


# --------------------------------------------------------------------------- #
#  Every write on a closed case, refused
#
#  A guard on the button protects nothing: the API is the surface, and a stale
#  tab, a queued retry or a bookmarked stage is the ordinary way a write reaches
#  a case that ended while somebody was reading it.
# --------------------------------------------------------------------------- #

def _refused(client, method, path, **kwargs):
    with _super(), patch("routers.cases.nar1_cases.get_case",
                         return_value=CLOSED_CASE), \
         patch("routers.cases.nar1_cases.update_case") as write, \
         patch("routers.cases.nar1_cases.blocking_filing", return_value=None), \
         patch("routers.cases.nar1_cases.current_filing", return_value=None), \
         patch("routers.cases.log_event", new_callable=AsyncMock):
        response = getattr(client, method)(path, headers=H, **kwargs)
    return response, write


@pytest.mark.parametrize("method,path,kwargs", [
    ("patch", "/cases/c1", {"json": {"aml_cleared": True}}),
    ("patch", "/cases/c1", {"json": {"restart_verification": True}}),
    ("post", "/cases/c1/verification/send", {"json": {}}),
    ("post", "/cases/c1/verification/response", {"json": {"approved": True}}),
    ("post", "/cases/c1/manual-submit", {"json": {"receipt": {}}}),
])
def test_a_closed_case_refuses_every_write(client, method, path, kwargs):
    response, write = _refused(client, method, path, **kwargs)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["reason"] == "case_closed"
    write.assert_not_called()


def test_a_no_op_patch_on_a_closed_case_still_refuses(client):
    """A silent 200 that changed nothing reads as "the edit went through", and
    that is how somebody learns a dead screen is live when it is not."""
    response, _ = _refused(client, "patch", "/cases/c1", json={})
    assert response.status_code == 409


def test_a_closed_case_can_still_be_READ(client):
    """Closing ends the work, not the record. The trail, the documents and what
    the case was doing when it stopped all have to stay reachable."""
    composite = {**CLOSED_CASE,
                 "workflow_status": {"code": "closed", "label": "Closed"}}
    with _super(), patch("routers.cases.nar1_cases.composite",
                         return_value=composite):
        response = client.get("/cases/c1", headers=H)
    assert response.status_code == 200
    assert response.json()["workflow_status"]["code"] == "closed"
    assert response.json()["closed_reason"] == "client is dissolving the company"

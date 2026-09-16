"""POST /tpsi/cases/{id}/refresh-status — the Check-now button (migration 043).

Same harness as test_tpsi_router.py: patch `middleware.auth._resolve_user` to
hand back an identity, rather than overriding the dependency factory —
`require_permission` is the authorization gate for every route in the app, and a
test-ergonomics problem is solved on the test side.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services.tpsi.errors import TpsiUnavailableError

SUPER = {"id": "u1", "display_name": "Levi", "role_name": "super_admin",
         "role_id": "role-sa"}
REGULAR = {"id": "u2", "display_name": "Staff", "role_name": "staff",
           "role_id": "role-x"}
H = {"Authorization": "Bearer tok"}

URL = "/tpsi/cases/c1/refresh-status"


@pytest.fixture
def client():
    return TestClient(app)


def _super():
    return patch("middleware.auth._resolve_user", return_value=SUPER)


def case(**over):
    base = {"id": "c1", "case_no": "NAR-2026-0001", "entity_id": "e1",
            "closed_at": None, "manual_receipt": None,
            "cr_doc_status": None, "cr_doc_status_code": None,
            "cr_status_checked_at": None, "cr_document_ref_no": None}
    base.update(over)
    return base


def filed_filing():
    return {"id": "f1", "stage": "submitted", "receipt": {"caseNo": "151120654"}}


def refreshed(**over):
    base = {"checked": True, "skipped": None, "changed": True,
            "previous": "cr_not_checked", "code": "cr_registered",
            "cr_text": "Registered", "document_ref_no": "R1",
            "checked_at": "2026-09-16T10:00:00+00:00"}
    base.update(over)
    return base


def _world(refresh=None, filing=None, the_case=None):
    return (
        patch("routers.tpsi.nar1_cases.get_case",
              return_value=the_case if the_case is not None else case()),
        patch("routers.tpsi.nar1_cases.current_filing",
              return_value=filing if filing is not None else filed_filing()),
        patch("routers.tpsi.client_for", return_value=MagicMock(last_auth=None)),
        patch("routers.tpsi.nar1_cr_status.refresh",
              **({"side_effect": refresh} if callable(refresh)
                 else {"return_value": refresh if refresh is not None else refreshed()})),
        patch("routers.tpsi.nar1_cr_status.record", new=AsyncMock()),
        patch("routers.tpsi.log_event", new=AsyncMock()),
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


def test_it_asks_cr_and_returns_the_badge(client):
    with _super(), _Stack(*_world()):
        response = client.post(URL, headers=H)

    assert response.status_code == 200
    body = response.json()
    assert body["cr_status"] == {
        "code": "cr_registered", "label": "Registered by CR",
        "cr_text": "Registered", "terminal": True,
    }
    assert body["changed"] is True
    assert body["previous"] == "cr_not_checked"
    assert body["checked_at"] == "2026-09-16T10:00:00+00:00"


def test_it_puts_the_check_in_the_trail_under_the_operators_own_name(client):
    """A hand-check is somebody's action. The nightly job writes the same codes
    under "G-FlowDesk (automatic)", and the two must be tellable apart."""
    with _super(), _Stack(*_world()) as entered:
        client.post(URL, headers=H)
    record = entered[4]
    record.assert_awaited_once()
    assert record.await_args.kwargs["user_id"] == "u1"
    assert record.await_args.kwargs["user_display_name"] == "Levi"


def test_it_refuses_an_unfiled_case_before_opening_a_cr_session(client):
    """"Nothing happened" on a case that was never filed is indistinguishable
    from a broken button — and opening a CR session to find that out spends an
    authentication for nothing."""
    with _super(), _Stack(*_world(filing={"id": "f1", "stage": "validated"})) as entered:
        response = client.post(URL, headers=H)

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "not_checkable"
    entered[2].assert_not_called()   # client_for


def test_it_refuses_a_case_cr_has_already_finished_with(client):
    decided = case(cr_doc_status_code="cr_registered", cr_doc_status="Registered")
    with _super(), _Stack(*_world(the_case=decided)) as entered:
        response = client.post(URL, headers=H)
    assert response.status_code == 409
    entered[2].assert_not_called()


def test_it_is_a_404_for_a_case_that_does_not_exist(client):
    with _super(), \
         patch("routers.tpsi.nar1_cases.get_case",
               side_effect=LookupError("no case c9")):
        response = client.post("/tpsi/cases/c9/refresh-status", headers=H)
    assert response.status_code == 404


def test_it_requires_tpsi_read(client):
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb:
        msb.return_value.table.return_value.select.return_value.eq.return_value \
            .eq.return_value.execute.return_value.data = []
        response = client.post(URL, headers=H)
    assert response.status_code == 403


def test_it_requires_authentication(client):
    assert client.post(URL).status_code in (401, 403)


def test_an_ambiguous_cr_answer_is_reported_not_rendered_as_a_badge(client):
    """CR answered, but the reply could not be attributed to THIS return.
    Nothing was written, and the screen says why rather than showing a badge
    nobody can act on."""
    ambiguous = refreshed(checked=False, changed=False,
                          skipped="CR returned 2 documents for this case number",
                          code="cr_not_checked", cr_text=None, checked_at=None)
    with _super(), _Stack(*_world(refresh=ambiguous)):
        response = client.post(URL, headers=H)

    assert response.status_code == 200
    body = response.json()
    assert body["checked"] is False
    assert "2 documents" in body["skipped"]
    assert body["cr_status"]["code"] == "cr_not_checked"


def test_an_unreachable_cr_is_a_503_not_a_refusal(client):
    """The screen must tell "CR said no" from "CR could not be used": nothing
    was written either way, but only one is worth retrying."""
    def boom(*a, **k):
        raise TpsiUnavailableError("CR did not answer")

    with _super(), _Stack(*_world(refresh=boom)):
        response = client.post(URL, headers=H)
    assert response.status_code == 503

"""backend/routers/cases.py — case create / composite read / patch.

Patches middleware.auth._resolve_user to a super_admin identity, as
test_tpsi_router.py and test_companies_router.py do.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

SUPER = {"id": "u1", "display_name": "Levi", "role_name": "super_admin", "role_id": "role-sa"}
NOBODY = {"id": "u2", "display_name": "Staff", "role_name": "staff", "role_id": "role-x"}
H = {"Authorization": "Bearer tok"}


def _super():
    return patch("middleware.auth._resolve_user", return_value=SUPER)


@pytest.fixture
def client():
    return TestClient(app)


def test_create_case_allocates_a_case_number_and_audits(client):
    logged = {}

    async def fake_log(**kwargs):
        logged.update(kwargs)

    row = {"id": "c1", "case_no": "NAR-2026-0041", "entity_id": "e1"}
    with _super(), \
         patch("routers.cases.nar1_cases.create_case", return_value=row) as spy, \
         patch("routers.cases.log_event", side_effect=fake_log):
        response = client.post("/cases", headers=H,
                               json={"entity_id": "e1", "form_code": "Nar1"})
    assert response.status_code == 201
    assert response.json()["case_no"] == "NAR-2026-0041"
    assert spy.call_args.kwargs["entity_id"] == "e1"
    assert logged["action_type"] == "CASE_STATUS_CHANGED"


def test_create_case_rejects_a_form_code_that_is_not_nar1(client):
    """R1 is NAR1 only. An Nnc1 case created here would have no workflow behind
    it and would sit in the dashboard looking real."""
    with _super():
        response = client.post("/cases", headers=H,
                               json={"entity_id": "e1", "form_code": "Nnc1"})
    assert response.status_code == 400


def test_get_case_returns_both_statuses_side_by_side(client):
    """The v11 header shows two badges. One endpoint, both answers, never merged."""
    composite = {
        "id": "c1",
        "workflow_status": {"code": "signing", "label": "Signing",
                            "off_portal": False, "overdue": False},
        "form_status": {"code": "validated", "label": "Validated by CR",
                        "failed": False, "terminal": False, "faults": []},
    }
    with _super(), patch("routers.cases.nar1_cases.composite", return_value=composite):
        response = client.get("/cases/c1", headers=H)
    assert response.status_code == 200
    body = response.json()
    assert body["workflow_status"]["code"] == "signing"
    assert body["form_status"]["code"] == "validated"


def test_get_case_404s_on_an_unknown_id(client):
    with _super(), \
         patch("routers.cases.nar1_cases.composite", side_effect=LookupError("no case")):
        response = client.get("/cases/nope", headers=H)
    assert response.status_code == 404


def test_patch_records_the_aml_check_with_a_timestamp(client):
    """A tick with no time on it cannot answer "when was AML cleared?"."""
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value={"id": "c1", "aml_cleared": False}), \
         patch("routers.cases.nar1_cases.update_case", return_value={"id": "c1"}) as spy, \
         patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.patch("/cases/c1", headers=H, json={"aml_cleared": True})
    assert response.status_code == 200
    assert spy.call_args.args[1]["aml_cleared"] is True
    assert spy.call_args.args[1]["aml_cleared_at"] is not None


def test_patch_audits_aml_under_its_own_action_type(client):
    logged = {}

    async def fake_log(**kwargs):
        logged.update(kwargs)

    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value={"id": "c1", "aml_cleared": False}), \
         patch("routers.cases.nar1_cases.update_case", return_value={"id": "c1"}), \
         patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", side_effect=fake_log):
        client.patch("/cases/c1", headers=H, json={"aml_cleared": True})
    assert logged["action_type"] == "AML_STATUS_CHANGED"


def test_restart_verification_clears_the_client_response(client):
    """Restarting means the previous Yes/No no longer applies. Leaving it set
    would send the case straight back to Signing on the next read."""
    with _super(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "client_approved": True}), \
         patch("routers.cases.nar1_cases.update_case", return_value={"id": "c1"}) as spy, \
         patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.patch("/cases/c1", headers=H,
                                json={"restart_verification": True})
    assert response.status_code == 200
    patch_body = spy.call_args.args[1]
    assert patch_body["client_approved"] is None
    assert patch_body["client_response_at"] is None
    assert patch_body["verification_sent_at"] is None


def test_patch_ignores_fields_it_does_not_own(client):
    """A PATCH must never be able to set client_approved directly -- that fact
    is owned by the verification endpoint, which audits it."""
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value={"id": "c1"}), \
         patch("routers.cases.nar1_cases.update_case", return_value={"id": "c1"}) as spy, \
         patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", new=AsyncMock()):
        client.patch("/cases/c1", headers=H,
                     json={"aml_cleared": True, "client_approved": True})
    assert "client_approved" not in spy.call_args.args[1]


def test_patch_with_unchanged_values_writes_and_audits_nothing(client):
    """An audit entry whose old and new value are identical is a false record
    in a statutory workflow trail -- re-asserting the stored value must be a
    no-op, the same discipline aml_cleared/accounts_ready already apply."""
    with _super(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "signing_method": "esign", "assigned_to": "u9"}), \
         patch("routers.cases.nar1_cases.update_case") as spy, \
         patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", new=AsyncMock()) as log_spy:
        response = client.patch("/cases/c1", headers=H,
                                json={"signing_method": "esign", "assigned_to": "u9"})
    assert response.status_code == 200
    spy.assert_not_called()
    log_spy.assert_not_called()


def test_patch_rejects_an_invalid_signing_method_even_if_it_would_be_a_no_op(client):
    """The validity check must run before the unchanged-value guard -- an
    invalid value is never "skipped" just because it happens to equal
    whatever bad value is already stored."""
    with _super(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "signing_method": "bogus"}), \
         patch("routers.cases.nar1_cases.update_case") as spy, \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.patch("/cases/c1", headers=H,
                                json={"signing_method": "bogus"})
    assert response.status_code == 400
    spy.assert_not_called()


def test_case_endpoints_require_authentication(client):
    """No patch installed -> the real dependency runs and rejects the dummy token."""
    assert client.get("/cases/c1", headers=H).status_code in (401, 403)
    assert client.post("/cases", headers=H, json={}).status_code in (401, 403, 422)


def test_case_endpoints_are_gated_on_the_nar1_module(client):
    """OQ-B: a role with companies:write but no nar1 grant must be refused.

    _permissions_for is mocked to grant "write" on WHATEVER module is asked,
    so the only thing that can fail this test is the router asking about the
    wrong module (e.g. "companies" instead of "nar1"). create_case and
    log_event are mocked too -- this test's job is to inspect what module
    require_permission queried, not to exercise the real case-creation path
    against the DB.
    """
    with patch("middleware.auth._resolve_user", return_value=NOBODY), \
         patch("middleware.auth._permissions_for", return_value={"write"}) as perms, \
         patch("routers.cases.nar1_cases.create_case", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", new=AsyncMock()):
        client.post("/cases", headers=H, json={"entity_id": "e1", "form_code": "Nar1"})
    assert perms.call_args.args[1] == "nar1"


def test_the_audit_tab_route_still_resolves(client):
    """/cases/{id}/audit predates this router and must still work now that
    cases.router shares the /cases prefix: cases_audit.router is still
    mounted and its own handler is the one that actually runs (verified via
    its get_supabase mock, not just a 200).

    This does NOT verify registration order by itself -- FastAPI's default
    (non-`:path`) {case_id} converter is end-anchored and structurally cannot
    match the three-segment /cases/c1/audit, so this route resolves correctly
    regardless of which router was registered first. See
    test_cases_router_is_registered_before_cases_audit_router for the actual
    ordering guard.
    """
    with _super(), patch("routers.cases_audit.get_supabase") as msb:
        sb = msb.return_value
        chain = sb.table.return_value.select.return_value.eq.return_value.order.return_value
        chain.execute.return_value.data = [{"action_type": "CASE_STATUS_CHANGED"}]
        response = client.get("/cases/c1/audit", headers=H)
    assert response.status_code == 200
    assert response.json() == [{"action_type": "CASE_STATUS_CHANGED"}]


def test_cases_router_is_registered_before_cases_audit_router(client):
    """The real ordering guard for the /cases prefix.

    Not exercised by the request-level test above, since the current path
    patterns cannot collide either way (see its docstring) -- this asserts
    directly on app.routes so a future change that WOULD make the order
    matter (a broadened GET at /cases/{case_id}, or a {case_id:path}
    converter) is caught here rather than shipping silently."""
    case_index = next(
        i for i, r in enumerate(app.routes)
        if getattr(r, "path", None) == "/cases/{case_id}"
        and "GET" in getattr(r, "methods", set())
    )
    audit_index = next(
        i for i, r in enumerate(app.routes)
        if getattr(r, "path", None) == "/cases/{case_id}/audit"
    )
    assert case_index < audit_index

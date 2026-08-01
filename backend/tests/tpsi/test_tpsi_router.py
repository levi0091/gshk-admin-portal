"""backend/routers/tpsi.py — happy path / auth / audit-safety assertions.

Follows the established pattern from test_companies_router.py and
test_persons_router.py: patch middleware.auth._resolve_user to hand back a
super_admin identity (which bypasses the module/level permission check
entirely in require_permission), rather than overriding the dependency
factory itself. require_permission is the authorization gate for every
route in the app; a test-ergonomics problem is solved on the test side, not
by changing that shared middleware.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

SUPER = {"id": "u1", "display_name": "Levi", "role_name": "super_admin", "role_id": "role-sa"}
REGULAR = {"id": "u2", "display_name": "Staff", "role_name": "staff", "role_id": "role-x"}
H = {"Authorization": "Bearer tok"}


def _super():
    return patch("middleware.auth._resolve_user", return_value=SUPER)


@pytest.fixture
def client():
    return TestClient(app)


def test_get_credentials_returns_metadata_only(client):
    meta = {"presentor_account_id": "ACCT", "has_eservice_password": True}
    with _super(), patch("routers.tpsi.credentials.get_metadata", return_value=meta):
        response = client.get("/tpsi/credentials", headers=H)
    assert response.status_code == 200
    assert "_enc" not in response.text
    assert "password" not in response.text.replace("has_eservice_password", "")


def test_post_credentials_audits_and_never_echoes_the_password(client):
    logged = {}

    async def fake_log(**kwargs):
        logged.update(kwargs)

    with _super(), \
         patch("routers.tpsi.credentials.set_credential",
               return_value={"presentor_account_id": "ACCT"}), \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        response = client.post("/tpsi/credentials", headers=H, json={
            "presentor_account_id": "ACCT",
            "tpsi_password": "s3cret",
            "eservice_password": "e-s3cret",
        })
    assert response.status_code == 200
    assert "s3cret" not in response.text
    assert logged["action_type"] == "TPSI_CRED_SET"
    assert "s3cret" not in str(logged)


def test_balance_returns_the_amount(client):
    # last_auth=None: a bare MagicMock() auto-vivifies .last_auth as a truthy
    # mock, which would make audit_auth() treat this as a fresh CR login and
    # call the real (unmocked) credentials.record_password_expiry -> a real
    # Supabase call. This test isn't exercising the login-audit path, so pin
    # last_auth to the "cached token" value (see test_cached_token_... below).
    with _super(), \
         patch("routers.tpsi.client_for", return_value=MagicMock(last_auth=None)), \
         patch("routers.tpsi.reads.check_balance", return_value=Decimal("1831538.0")), \
         patch("routers.tpsi.log_event", new=AsyncMock()):
        response = client.get("/tpsi/balance?account_no=N00061980009", headers=H)
    assert response.status_code == 200
    assert response.json()["balance"] == "1831538.0"


def test_doc_status_passes_criteria_through(client):
    rows = [{"caseNo": "180256934", "documentStatus": "Registered"}]
    with _super(), \
         patch("routers.tpsi.client_for", return_value=MagicMock(last_auth=None)), \
         patch("routers.tpsi.reads.case_status", return_value=rows) as spy, \
         patch("routers.tpsi.log_event", new=AsyncMock()):
        response = client.get("/tpsi/doc-status?case_no=180256934", headers=H)
    assert response.status_code == 200
    assert spy.call_args.kwargs["case_no"] == "180256934"


def test_endpoints_require_authentication(client):
    """No patch installed -> the real dependency (real _resolve_user, real
    HTTPBearer) runs and rejects. This is the test standing guard over the
    actual authorization check, so it must not mock anything auth-related."""
    assert client.get("/tpsi/balance?account_no=X").status_code in (401, 403)


def test_fresh_login_is_audited_and_password_expiry_persisted(client):
    """TPSI_AUTH marks when a CR session opened. The 180-day expiry must be
    captured here — it is the only place CR tells us."""
    from services.tpsi.tokens import AuthResult

    tpsi_client = MagicMock()
    tpsi_client.account_id = "ACCT"
    tpsi_client.last_auth = AuthResult("T", 1800, "2026-12-31 23:59:59")
    events, expiry = [], {}

    async def fake_log(**kwargs):
        events.append(kwargs["action_type"])

    with _super(), \
         patch("routers.tpsi.client_for", return_value=tpsi_client), \
         patch("routers.tpsi.reads.check_balance", return_value=Decimal("1")), \
         patch("routers.tpsi.credentials.record_password_expiry",
               side_effect=lambda u, e: expiry.update({u: e})), \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        client.get("/tpsi/balance?account_no=N1", headers=H)

    assert "TPSI_AUTH" in events
    assert expiry["u1"] == "2026-12-31 23:59:59"


def test_cached_token_does_not_emit_a_login_event(client):
    """Reusing a cached token is not a new CR session; auditing it would bury
    the real logins."""
    tpsi_client = MagicMock()
    tpsi_client.account_id = "ACCT"
    tpsi_client.last_auth = None
    events = []

    async def fake_log(**kwargs):
        events.append(kwargs["action_type"])

    with _super(), \
         patch("routers.tpsi.client_for", return_value=tpsi_client), \
         patch("routers.tpsi.reads.check_balance", return_value=Decimal("1")), \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        client.get("/tpsi/balance?account_no=N1", headers=H)

    assert "TPSI_AUTH" not in events


def test_missing_credential_is_a_clean_400_not_a_500(client):
    with _super(), \
         patch("routers.tpsi.credentials.load_for_use", side_effect=LookupError("none")):
        response = client.get("/tpsi/balance?account_no=X", headers=H)
    assert response.status_code == 400


def test_password_expiry_persistence_failure_does_not_fail_the_request(client):
    """record_password_expiry is bookkeeping on top of an already-successful CR
    call, not part of it. If Supabase is unavailable when persisting the
    180-day expiry (DEV has been over-quota/read-only before), a balance read
    that already got its answer from CR must still return 200 — same
    never-raise discipline log_event already has."""
    from services.tpsi.tokens import AuthResult

    tpsi_client = MagicMock()
    tpsi_client.account_id = "ACCT"
    tpsi_client.last_auth = AuthResult("T", 1800, "2026-12-31 23:59:59")
    events = []

    async def fake_log(**kwargs):
        events.append(kwargs["action_type"])

    with _super(), \
         patch("routers.tpsi.client_for", return_value=tpsi_client), \
         patch("routers.tpsi.reads.check_balance", return_value=Decimal("1")), \
         patch("routers.tpsi.credentials.record_password_expiry",
               side_effect=RuntimeError("supabase unavailable")), \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        response = client.get("/tpsi/balance?account_no=N1", headers=H)

    assert response.status_code == 200
    assert response.json()["balance"] == "1"
    # audit_auth still fires TPSI_AUTH after swallowing the persistence error.
    assert "TPSI_AUTH" in events


def test_bad_case_status_criteria_is_a_clean_400_not_a_500(client):
    """reads.case_status raises ValueError on invalid/missing criteria; _handle
    maps ValueError -> 400 centrally so any future ValueError-raising check
    in the balance/doc-status call graph gets the same treatment, not a 500."""
    with _super(), \
         patch("routers.tpsi.client_for", return_value=MagicMock(last_auth=None)), \
         patch("routers.tpsi.reads.case_status", side_effect=ValueError("bad criteria")):
        response = client.get("/tpsi/doc-status", headers=H)
    assert response.status_code == 400


# ---- filings: POST /tpsi/filings --------------------------------------------

def test_create_filing_opens_a_draft_and_audits(client):
    row = {"id": "f1", "entity_id": "e1", "form_code": "Nar1", "stage": "draft"}
    logged = {}

    async def fake_log(**kwargs):
        logged.update(kwargs)

    with _super(), \
         patch("routers.tpsi.filings.create_filing", return_value=row), \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        response = client.post("/tpsi/filings", headers=H, json={
            "entity_id": "e1", "form_code": "Nar1", "form_xml": "<formCode>NAR1</formCode>",
        })
    assert response.status_code == 200
    assert response.json() == row
    assert logged["action_type"] == "TPSI_FILING_CREATED"
    assert logged["metadata"]["form_code"] == "Nar1"


def test_create_filing_requires_write_permission(client):
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb:
        # role_permissions query returns no rows -> insufficient
        msb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        response = client.post("/tpsi/filings", headers=H, json={
            "entity_id": "e1", "form_code": "Nar1", "form_xml": "<x/>",
        })
    assert response.status_code == 403


def test_create_filing_unknown_form_code_is_a_clean_400(client):
    with _super(), \
         patch("routers.tpsi.filings.create_filing", side_effect=KeyError("Zzz9")):
        response = client.post("/tpsi/filings", headers=H, json={
            "entity_id": "e1", "form_code": "Zzz9", "form_xml": "<x/>",
        })
    assert response.status_code == 400


def test_create_filing_other_failures_are_handled_not_a_500(client):
    """A Postgrest FK violation on a bad entity_id (or any other non-KeyError
    failure) is routed through _handle like every other TPSI endpoint,
    instead of surfacing as an unhandled 500."""
    with _super(), \
         patch("routers.tpsi.filings.create_filing", side_effect=RuntimeError("db exploded")):
        response = client.post("/tpsi/filings", headers=H, json={
            "entity_id": "bad", "form_code": "Nar1", "form_xml": "<x/>",
        })
    assert response.status_code == 502


# ---- filings: POST /tpsi/filings/{id}/validate ------------------------------

def test_validate_filing_advances_the_stage_and_audits(client):
    logged = {}

    async def fake_log(**kwargs):
        logged.update(kwargs)

    with _super(), \
         patch("routers.tpsi.client_for", return_value=MagicMock()), \
         patch("routers.tpsi.filings.validate", return_value={"stage": "validated"}), \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        response = client.post("/tpsi/filings/f1/validate", headers=H)
    assert response.status_code == 200
    assert response.json() == {"filing_id": "f1", "stage": "validated"}
    assert logged["action_type"] == "TPSI_VALIDATE"


def test_validate_filing_is_reachable_with_read_permission_only(client):
    """spec §6: validate has no CR-side effect and no charge, so it is
    deliberately gated tpsi:read, not tpsi:write — a read-only role must
    still reach it. Exercises the real require_permission codepath (role
    with exactly one permission row), not the super_admin bypass."""
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb, \
         patch("routers.tpsi.client_for", return_value=MagicMock()), \
         patch("routers.tpsi.filings.validate", return_value={"stage": "validated"}), \
         patch("routers.tpsi.log_event", new=AsyncMock()):
        msb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"permission": "read"}
        ]
        response = client.post("/tpsi/filings/f1/validate", headers=H)
    assert response.status_code == 200


def test_validate_filing_cr_fault_is_handled_not_a_500(client):
    from services.tpsi.errors import TpsiValidationError

    with _super(), \
         patch("routers.tpsi.client_for", return_value=MagicMock()), \
         patch("routers.tpsi.filings.validate",
               side_effect=TpsiValidationError([("ERR_MSG_REQUIRED", "brNo is required")])):
        response = client.post("/tpsi/filings/f1/validate", headers=H)
    assert response.status_code == 502


# ---- filings: POST /tpsi/filings/{id}/edrive --------------------------------

def test_edrive_filing_marks_the_filing_and_audits(client):
    logged = {}

    async def fake_log(**kwargs):
        logged.update(kwargs)

    with _super(), \
         patch("routers.tpsi.client_for", return_value=MagicMock()), \
         patch("routers.tpsi.filings.upload_edrive",
               return_value={"filing_id": "f1", "result": "Form submitted to E drive successfully."}), \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        response = client.post("/tpsi/filings/f1/edrive", headers=H)
    assert response.status_code == 200
    assert "successfully" in response.json()["result"]
    assert logged["action_type"] == "TPSI_EDRIVE"


def test_edrive_filing_requires_write_not_just_read(client):
    """e-Drive changes something at CR (spec §6), so a read-only role must be
    refused even though it can reach validate."""
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb:
        msb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"permission": "read"}
        ]
        response = client.post("/tpsi/filings/f1/edrive", headers=H)
    assert response.status_code == 403


def test_edrive_filing_wrong_stage_is_a_clean_400(client):
    with _super(), \
         patch("routers.tpsi.client_for", return_value=MagicMock()), \
         patch("routers.tpsi.filings.upload_edrive",
               side_effect=ValueError("filing must be validated before it can go to e-Drive")):
        response = client.post("/tpsi/filings/f1/edrive", headers=H)
    assert response.status_code == 400

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
    captured here — it is the only place CR tells us. Persisted against the
    SHARED presenter record (BE-5): the CR login is shared now, so its expiry
    belongs to the shared credential, not to whichever user triggered it."""
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
         patch("routers.tpsi.shared_credentials.record_password_expiry",
               side_effect=lambda e: expiry.update({"expires_at": e})), \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        client.get("/tpsi/balance?account_no=N1", headers=H)

    assert "TPSI_AUTH" in events
    assert expiry["expires_at"] == "2026-12-31 23:59:59"


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
    """client_for now loads the SHARED presenter (BE-5); load_for_use raising
    a bare LookupError (nothing configured yet) still maps to a clean 400."""
    with _super(), \
         patch("routers.tpsi.shared_credentials.load_for_use", side_effect=LookupError("none")):
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
         patch("routers.tpsi.shared_credentials.record_password_expiry",
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


# ---- filings: POST /tpsi/filings/prepare (BE-1) -----------------------------

def _prepare_patches(**overrides):
    """The four collaborators /filings/prepare drives, all mocked at the
    boundary. No test in this file may reach Supabase or CR."""
    defaults = {
        "load": AsyncMock(return_value={"entity": {"id": "e1"}}),
        "map": MagicMock(return_value={"brNo": "1"}),
        "build": MagicMock(return_value="<cr:brNo>1</cr:brNo>"),
        "create": MagicMock(return_value={"id": "f1", "stage": "draft"}),
        "log": AsyncMock(),
        # The case-side guard: prepare refuses to open a second filing on a
        # case CR already holds, or one completed off-portal. Mocked here like
        # every other collaborator so no test in this file reaches Supabase.
        "blocking": MagicMock(return_value=None),
        "case": MagicMock(return_value={"id": "c1", "entity_id": "e1",
                                        "manual_receipt": None}),
    }
    defaults.update(overrides)
    return defaults


def _with_prepare(p):
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(_super())
    stack.enter_context(
        patch("routers.tpsi.nar1_source.load_entity_graph", new=p["load"]))
    stack.enter_context(patch("routers.tpsi.nar1_mapper.map_entity", new=p["map"]))
    stack.enter_context(patch("routers.tpsi.nar1.build_nar1_xml", new=p["build"]))
    stack.enter_context(patch("routers.tpsi.filings.create_filing", new=p["create"]))
    stack.enter_context(patch("routers.tpsi.log_event", new=p["log"]))
    stack.enter_context(
        patch("routers.tpsi.nar1_cases.blocking_filing", new=p["blocking"]))
    stack.enter_context(
        patch("routers.tpsi.nar1_cases.get_case", new=p["case"]))
    return stack


def test_prepare_builds_the_xml_server_side(client):
    """The frontend posts identifiers, never XML. If it could post XML it could
    file a document nobody in G-FlowDesk ever saw."""
    p = _prepare_patches()
    with _with_prepare(p):
        response = client.post("/tpsi/filings/prepare", headers=H,
                               json={"entity_id": "e1", "nar1_case_id": "c1"})
    assert response.status_code == 201
    assert p["create"].call_args.kwargs["form_xml"] == "<cr:brNo>1</cr:brNo>"
    assert p["create"].call_args.kwargs["nar1_case_id"] == "c1"
    assert p["create"].call_args.kwargs["form_code"] == "Nar1"


def test_prepare_ignores_any_client_supplied_form_xml(client):
    """Belt and braces on the rule above: an extra `form_xml` in the body is not
    a field this endpoint has, and must not become the filed document."""
    p = _prepare_patches()
    with _with_prepare(p):
        response = client.post("/tpsi/filings/prepare", headers=H, json={
            "entity_id": "e1", "nar1_case_id": "c1",
            "form_xml": "<cr:brNo>SMUGGLED</cr:brNo>",
        })
    assert response.status_code == 201
    assert p["create"].call_args.kwargs["form_xml"] == "<cr:brNo>1</cr:brNo>"
    assert "SMUGGLED" not in response.text


def test_prepare_returns_every_mapping_problem_at_once(client):
    """CR returns a full fault list; so must we, or the user fixes one field per
    round trip against an API open six hours a day."""
    from services.tpsi.forms.nar1_mapper import MappingError

    p = _prepare_patches(
        map=MagicMock(side_effect=MappingError(["no BR number", "no address"])))
    with _with_prepare(p):
        response = client.post("/tpsi/filings/prepare", headers=H,
                               json={"entity_id": "e1", "nar1_case_id": "c1"})
    assert response.status_code == 400
    assert response.json()["detail"]["problems"] == ["no BR number", "no address"]
    # Nothing was opened: a filing row for an entity that cannot be filed is a
    # draft nobody can ever advance.
    p["create"].assert_not_called()


def test_prepare_unknown_entity_is_a_clean_400(client):
    p = _prepare_patches(load=AsyncMock(side_effect=LookupError("no entity e9")))
    with _with_prepare(p):
        response = client.post("/tpsi/filings/prepare", headers=H,
                               json={"entity_id": "e9", "nar1_case_id": "c1"})
    assert response.status_code == 400
    assert "e9" in response.text


def test_prepare_defaults_the_return_year_to_the_current_hk_year(client):
    p = _prepare_patches(map=MagicMock(return_value={}))
    with _with_prepare(p):
        client.post("/tpsi/filings/prepare", headers=H,
                    json={"entity_id": "e1", "nar1_case_id": "c1"})
    from datetime import datetime, timedelta, timezone
    hk_year = (datetime.now(timezone.utc) + timedelta(hours=8)).year
    assert p["map"].call_args.kwargs["year"] == hk_year


def test_prepare_honours_an_explicit_return_year(client):
    """A return prepared in January for last year's anniversary."""
    p = _prepare_patches()
    with _with_prepare(p):
        client.post("/tpsi/filings/prepare", headers=H,
                    json={"entity_id": "e1", "nar1_case_id": "c1", "year": 2024})
    assert p["map"].call_args.kwargs["year"] == 2024


def test_prepare_passes_the_signatory_through_verbatim(client):
    """map_entity distinguishes an ABSENT key from a null one -- `is_corporate`
    absent means natural person, and a natural person must supply an id. So the
    signatory reaches the mapper as the caller sent it, with no Pydantic
    None-filling in between (the same trap `_opt` exists for on credentials)."""
    p = _prepare_patches()
    sig = {"name": "GSHK Secretaries Ltd",
           "capacity": "Authorized Person of the Company Secretary (Body Corporate)",
           "is_corporate": True}
    with _with_prepare(p):
        response = client.post("/tpsi/filings/prepare", headers=H, json={
            "entity_id": "e1", "nar1_case_id": "c1", "signatory": sig})
    assert response.status_code == 201
    assert p["map"].call_args.kwargs["signatory"] == sig


def test_prepare_invents_no_signatory_when_none_is_given(client):
    """No capacity default anywhere in this endpoint. selectCapacityDesc for a
    body-corporate secretary is an undecided business question; the mapper
    refuses rather than guessing, and the router must not pre-empt it."""
    p = _prepare_patches()
    with _with_prepare(p):
        client.post("/tpsi/filings/prepare", headers=H,
                    json={"entity_id": "e1", "nar1_case_id": "c1"})
    assert p["map"].call_args.kwargs["signatory"] is None


def test_prepare_audits_the_filing_it_opened(client):
    logged = {}

    async def fake_log(**kwargs):
        logged.update(kwargs)

    p = _prepare_patches(log=AsyncMock(side_effect=fake_log))
    with _with_prepare(p):
        response = client.post("/tpsi/filings/prepare", headers=H,
                               json={"entity_id": "e1", "nar1_case_id": "c1"})
    assert response.status_code == 201
    assert logged["action_type"] == "TPSI_FILING_CREATED"
    assert logged["entity_id"] == "f1"
    assert logged["case_id"] == "c1"
    assert logged["metadata"]["form_code"] == "Nar1"
    # The built XML is not audit metadata: it is the whole statutory return and
    # it is already stored on the filing row.
    assert "cr:brNo" not in str(logged)


def test_prepare_survives_an_audit_failure(client):
    """CLAUDE.md: a log_event failure must never block the primary operation.
    The filing row already exists; failing the response would lose its id.

    The failure is injected INSIDE audit_service, at its Supabase boundary --
    patching `routers.tpsi.log_event` itself would replace the very try/except
    that provides the guarantee and prove nothing.
    """
    p = _prepare_patches()
    del p["log"]  # the real log_event, with its real swallow, must run
    from contextlib import ExitStack

    with ExitStack() as stack:
        stack.enter_context(_super())
        stack.enter_context(
            patch("routers.tpsi.nar1_source.load_entity_graph", new=p["load"]))
        stack.enter_context(patch("routers.tpsi.nar1_mapper.map_entity", new=p["map"]))
        stack.enter_context(patch("routers.tpsi.nar1.build_nar1_xml", new=p["build"]))
        stack.enter_context(
            patch("routers.tpsi.filings.create_filing", new=p["create"]))
        stack.enter_context(
            patch("routers.tpsi.nar1_cases.blocking_filing", new=p["blocking"]))
        stack.enter_context(
            patch("routers.tpsi.nar1_cases.get_case", new=p["case"]))
        stack.enter_context(patch("services.audit_service.get_supabase",
                                  side_effect=RuntimeError("audit down")))
        response = client.post("/tpsi/filings/prepare", headers=H,
                               json={"entity_id": "e1", "nar1_case_id": "c1"})
    assert response.status_code == 201
    assert response.json()["id"] == "f1"


def test_prepare_loader_transport_failure_is_a_502_naming_the_loader(client):
    """nar1_source has an observed transport failure mode (RemoteProtocolError /
    a Cloudflare 400 from Supabase's edge). It must reach the caller as a
    502 that names the loader, not as an unhandled 500."""
    import httpx

    p = _prepare_patches(
        load=AsyncMock(side_effect=httpx.RemoteProtocolError("Server disconnected")))
    with _with_prepare(p):
        response = client.post("/tpsi/filings/prepare", headers=H,
                               json={"entity_id": "e1", "nar1_case_id": "c1"})
    assert response.status_code == 502
    assert "load_entity_graph" in response.json()["detail"]
    # No blind retry: re-issuing the same concurrent read would not help and
    # could double real work.
    assert p["load"].await_count == 1


def test_prepare_filing_insert_failure_is_handled_not_a_500(client):
    p = _prepare_patches(create=MagicMock(side_effect=RuntimeError("db exploded")))
    with _with_prepare(p):
        response = client.post("/tpsi/filings/prepare", headers=H,
                               json={"entity_id": "e1", "nar1_case_id": "c1"})
    assert response.status_code == 502


def test_prepare_local_schema_failure_is_a_400(client):
    """nar1.build_nar1_xml raises ValueError when the mapped data fails the
    committed CR schema (max_length and friends)."""
    p = _prepare_patches(
        build=MagicMock(side_effect=ValueError("NAR1 validation failed: brNo too long")))
    with _with_prepare(p):
        response = client.post("/tpsi/filings/prepare", headers=H,
                               json={"entity_id": "e1", "nar1_case_id": "c1"})
    assert response.status_code == 400
    assert "brNo too long" in response.text


def test_prepare_drives_the_real_mapper_not_just_a_mock(client):
    """Every other prepare test mocks map_entity, so none of them would notice
    the router calling it with the wrong keyword. This one runs the real
    mapper over a real (deficient) graph and checks the router surfaces its
    real problem list."""
    # Every key load_entity_graph returns, so this exercises the mapper and not
    # a KeyError on a graph shape that cannot occur.
    graph = {"entity": {}, "registered_address": None, "officers": [],
             "secretaries": [], "share_classes": [], "shareholdings": [],
             "persons": {}, "addresses": {}, "identity_documents": {}}
    p = _prepare_patches(load=AsyncMock(return_value=graph))
    from contextlib import ExitStack

    with ExitStack() as stack:
        stack.enter_context(_super())
        stack.enter_context(
            patch("routers.tpsi.nar1_source.load_entity_graph", new=p["load"]))
        stack.enter_context(
            patch("routers.tpsi.filings.create_filing", new=p["create"]))
        stack.enter_context(patch("routers.tpsi.log_event", new=p["log"]))
        stack.enter_context(
            patch("routers.tpsi.nar1_cases.blocking_filing", new=p["blocking"]))
        stack.enter_context(
            patch("routers.tpsi.nar1_cases.get_case", new=p["case"]))
        response = client.post("/tpsi/filings/prepare", headers=H,
                               json={"entity_id": "e1", "nar1_case_id": "c1"})
    assert response.status_code == 400
    problems = response.json()["detail"]["problems"]
    assert any("BR number" in prob for prob in problems)
    p["create"].assert_not_called()


def test_prepare_requires_tpsi_write_not_merely_read(client):
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb:
        msb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        response = client.post("/tpsi/filings/prepare", headers=H,
                               json={"entity_id": "e1", "nar1_case_id": "c1"})
    assert response.status_code == 403


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
    body = response.json()
    assert body["filing_id"] == "f1"
    assert body["stage"] == "validated"
    # The FORM status travels with the response so the UI can report it beside
    # the workflow status without a second round trip (Levi 2026-08-02).
    assert body["form_status"] == {
        "code": "validated",
        "label": "Validated by CR",
        "failed": False,
        "terminal": False,
        "faults": [],
    }
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


# ---- filings: POST /tpsi/filings/{id}/sign ----------------------------------

def test_sign_filing_with_stored_credential_and_audits(client):
    """No body (or an empty one) falls back to the logged-in user's own
    stored e-Service password (spec D4). Since BE-5 that lookup is
    credentials.load_eservice, not load_for_use — the CR login is the shared
    presenter now; this table holds only the personal signing credential.
    Also proves the signing password never reaches the response body or the
    audit metadata."""
    logged = {}

    async def fake_log(**kwargs):
        logged.update(kwargs)

    with _super(), \
         patch("routers.tpsi.credentials.load_eservice",
               return_value=("DIRECTOR1", "es3cret")), \
         patch("routers.tpsi.client_for", return_value=MagicMock()), \
         patch("routers.tpsi.filings.sign",
               return_value={"filing_id": "f1", "result": "Pin Signature(s) Verified Successfully."}) as spy, \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        response = client.post("/tpsi/filings/f1/sign", headers=H, json={})

    assert response.status_code == 200
    assert response.json()["result"] == "Pin Signature(s) Verified Successfully."
    assert spy.call_args[0][1:] == ("f1", "DIRECTOR1", "es3cret")
    assert logged["action_type"] == "TPSI_SIGN"
    assert logged["metadata"] == {
        "signatory": "DIRECTOR1",
        "result": "Pin Signature(s) Verified Successfully.",
    }
    assert "es3cret" not in response.text
    assert "es3cret" not in str(logged)


def test_sign_filing_with_live_supplied_director_credentials(client):
    """A named director's own User ID + e-Service password, supplied live in
    the request body, bypasses the stored credential entirely and is never
    persisted (spec D4)."""
    logged = {}

    async def fake_log(**kwargs):
        logged.update(kwargs)

    with _super(), \
         patch("routers.tpsi.credentials.load_eservice") as load_spy, \
         patch("routers.tpsi.client_for", return_value=MagicMock()), \
         patch("routers.tpsi.filings.sign",
               return_value={"filing_id": "f1", "result": "Pin Signature(s) Verified Successfully."}) as spy, \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        response = client.post("/tpsi/filings/f1/sign", headers=H, json={
            "signatory_user_id": "DIRECTOR2",
            "eservice_password": "liveSecret",
        })

    assert response.status_code == 200
    assert spy.call_args[0][1:] == ("f1", "DIRECTOR2", "liveSecret")
    load_spy.assert_not_called()   # the stored credential is never consulted
    assert logged["metadata"]["signatory"] == "DIRECTOR2"
    assert "liveSecret" not in response.text
    assert "liveSecret" not in str(logged)


def test_sign_filing_requires_write_permission(client):
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb:
        msb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"permission": "read"}
        ]
        response = client.post("/tpsi/filings/f1/sign", headers=H, json={})
    assert response.status_code == 403


def test_sign_filing_missing_credential_is_a_clean_400_not_a_500(client):
    """credentials.load_eservice returns None (not an error) when nothing is
    stored — see services/tpsi/credentials.py. sign_filing must still map
    that to a clean 400, not surface an unhandled 500."""
    with _super(), \
         patch("routers.tpsi.credentials.load_eservice", return_value=None):
        response = client.post("/tpsi/filings/f1/sign", headers=H, json={})
    assert response.status_code == 400


def test_sign_filing_no_stored_eservice_password_is_a_clean_400(client):
    """A credential row exists but no e-Service (signing) password was ever
    set. load_eservice already collapses this into the same None as the
    no-row-at-all case above (it checks for the encrypted column itself), so
    the router-level outcome is identical — documented here as its own case
    for clarity."""
    with _super(), \
         patch("routers.tpsi.credentials.load_eservice", return_value=None):
        response = client.post("/tpsi/filings/f1/sign", headers=H, json={})
    assert response.status_code == 400


def test_sign_filing_cr_fault_is_handled_not_a_500(client):
    from services.tpsi.errors import TpsiSignatureError

    with _super(), \
         patch("routers.tpsi.credentials.load_eservice",
               side_effect=AssertionError("should not be called")), \
         patch("routers.tpsi.client_for", return_value=MagicMock()), \
         patch("routers.tpsi.filings.sign",
               side_effect=TpsiSignatureError([("ERR_MSG_SIGNATORY_NOT_AUTH", "not authorised")])):
        response = client.post("/tpsi/filings/f1/sign", headers=H, json={
            "signatory_user_id": "DIRECTOR2", "eservice_password": "pw",
        })
    assert response.status_code == 502


# ---------------------------------------------------------------------------
# Preview + submit (Block 6) — the chargeable, irreversible endpoint
# ---------------------------------------------------------------------------

_PREVIEW = {
    "filing_id": "f1", "form_code": "Nar1", "stage": "signed",
    "fee": "105.00", "balance": "999999", "sufficient": True, "ready": True,
}
_RESULT = {"filing_id": "f1", "receipt": {"caseNo": "180256934", "totalAmount": "105.0"}}


def test_preview_returns_fee_and_balance_and_audits(client):
    logged = {}

    async def fake_log(**kwargs):
        logged.update(kwargs)

    tpsi_client = MagicMock()
    tpsi_client.last_auth = None
    with _super(), \
         patch("routers.tpsi.client_for", return_value=tpsi_client), \
         patch("routers.tpsi.filings.preview", return_value=_PREVIEW), \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        response = client.get(
            "/tpsi/filings/f1/preview?deposit_account=ACC", headers=H
        )
    assert response.status_code == 200
    assert response.json()["fee"] == "105.00"
    assert logged["action_type"] == "TPSI_PREVIEWED"


def test_submit_happy_path_returns_receipt_and_audits_success(client):
    events = []

    async def fake_log(**kwargs):
        events.append(kwargs["action_type"])

    with _super(), \
         patch("routers.tpsi.client_for", return_value=MagicMock()), \
         patch("routers.tpsi.filings.submit", return_value=_RESULT), \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        response = client.post("/tpsi/filings/f1/submit", headers=H,
                               json={"deposit_account": "ACC", "confirm": True})
    assert response.status_code == 200
    assert response.json()["receipt"]["caseNo"] == "180256934"
    assert events == ["TPSI_SUBMISSION_ATTEMPTED", "TPSI_SUBMISSION_SUCCESS"]


def test_submit_audits_the_attempt_before_calling_cr(client):
    """The attempt must be on record even if the process dies mid-submit —
    otherwise a charge could land with nothing in the trail explaining it."""
    order = []

    async def fake_log(**kwargs):
        order.append(("log", kwargs["action_type"]))

    def fake_submit(*a, **k):
        order.append(("submit", None))
        return _RESULT

    with _super(), \
         patch("routers.tpsi.client_for", return_value=MagicMock()), \
         patch("routers.tpsi.filings.submit", side_effect=fake_submit), \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        client.post("/tpsi/filings/f1/submit", headers=H,
                    json={"deposit_account": "ACC", "confirm": True})
    assert order[0] == ("log", "TPSI_SUBMISSION_ATTEMPTED")
    assert order[1] == ("submit", None)


def test_submit_gate_refusal_is_409_not_500(client):
    from services.tpsi.filings import SubmitGateError

    events = []

    async def fake_log(**kwargs):
        events.append(kwargs["action_type"])

    with _super(), \
         patch("routers.tpsi.client_for", return_value=MagicMock()), \
         patch("routers.tpsi.filings.submit",
               side_effect=SubmitGateError("explicit confirmation is required")), \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        response = client.post("/tpsi/filings/f1/submit", headers=H,
                               json={"deposit_account": "ACC", "confirm": False})
    assert response.status_code == 409
    assert "TPSI_SUBMISSION_FAILED" in events


def test_submit_requires_the_submit_permission_not_merely_write(client):
    """A role that may prepare and sign a NAR1 must not thereby be able to
    spend from the deposit account."""
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb:
        # role holds tpsi:write but not tpsi:submit
        msb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        response = client.post("/tpsi/filings/f1/submit", headers=H,
                               json={"deposit_account": "ACC", "confirm": True})
    assert response.status_code == 403


def test_preview_requires_authentication(client):
    assert client.get(
        "/tpsi/filings/f1/preview?deposit_account=ACC"
    ).status_code in (401, 403)


def test_submit_requires_authentication(client):
    assert client.post(
        "/tpsi/filings/f1/submit", json={"deposit_account": "ACC", "confirm": True}
    ).status_code in (401, 403)


# ---------------------------------------------------------------------------
# Shared presenter credential + CR auth rewiring (BE-5 / Task 3)
# ---------------------------------------------------------------------------

def test_shared_credential_read_is_super_admin_only(client):
    """An ordinary tpsi:write holder must not see the GSHK filing identity."""
    with patch("middleware.auth._resolve_user", return_value=REGULAR):
        response = client.get("/tpsi/shared-credential", headers=H)
    assert response.status_code == 403


def test_shared_credential_write_is_super_admin_only(client):
    """The heart of BE-5: tpsi:write is NOT enough to change who GSHK files as."""
    with patch("middleware.auth._resolve_user", return_value=REGULAR):
        response = client.put("/tpsi/shared-credential", headers=H, json={
            "presentor_account_id": "EVIL", "tpsi_password": "x",
        })
    assert response.status_code == 403


def test_super_admin_can_write_the_shared_credential_and_it_is_audited(client):
    logged = {}

    async def fake_log(**kwargs):
        logged.update(kwargs)

    with _super(), \
         patch("routers.tpsi.shared_credentials.set_shared",
               return_value={"presentor_account_id": "ACCT"}), \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        response = client.put("/tpsi/shared-credential", headers=H, json={
            "presentor_account_id": "ACCT",
            "tpsi_password": "s3cret",
            "deposit_account_no": "N001",
        })
    assert response.status_code == 200
    assert "s3cret" not in response.text
    assert logged["action_type"] == "TPSI_CRED_CONFIG"
    assert "s3cret" not in str(logged)


def test_change_password_is_super_admin_only(client):
    """Rewiring client_for onto the shared presenter means this endpoint now
    rotates the ONE GSHK filing password, not the caller's own — same OQ-C
    rationale as PUT /tpsi/shared-credential, so tpsi:write is not enough."""
    with patch("middleware.auth._resolve_user", return_value=REGULAR):
        response = client.post("/tpsi/credentials/password", headers=H, json={
            "new_password": "newpw",
        })
    assert response.status_code == 403


def test_change_password_persists_the_rotation_without_touching_deposit_account(client):
    """A successful CR password change must be written back to
    tpsi_shared_presenter (rotated=True), or the next client_for() call
    authenticates with a password CR no longer accepts. deposit_account_no is
    deliberately omitted from the call — _UNSET, not None — so the stored
    value survives a routine password-only rotation."""
    shared = MagicMock(account_id="ACCT", tpsi_password="oldpw", deposit_account_no="N001")
    tpsi_client = MagicMock()
    tpsi_client.change_password.return_value = "Password changed successfully."
    with _super(), \
         patch("routers.tpsi.shared_credentials.load_for_use", return_value=shared), \
         patch("routers.tpsi.client_for", return_value=tpsi_client), \
         patch("routers.tpsi.shared_credentials.set_shared") as set_spy, \
         patch("routers.tpsi.log_event", new=AsyncMock()):
        response = client.post("/tpsi/credentials/password", headers=H, json={
            "new_password": "newpw",
        })
    assert response.status_code == 200
    assert set_spy.call_args.kwargs["presentor_account_id"] == "ACCT"
    assert set_spy.call_args.kwargs["tpsi_password"] == "newpw"
    assert set_spy.call_args.kwargs["rotated"] is True
    assert "deposit_account_no" not in set_spy.call_args.kwargs
    assert "newpw" not in response.text


def test_change_password_persistence_failure_is_a_loud_500_naming_the_recovery(client):
    """If CR accepts the new password but the write-back fails, this is NOT a
    log-to-stderr-and-carry-on case like log_event/record_password_expiry:
    CR and the store would silently disagree, and every subsequent
    client_for() call would authenticate with a stale password against an
    API that locks accounts on repeated failure. The admin must be told,
    loudly, to fix it via PUT /tpsi/shared-credential — without the password
    itself ever appearing in that message."""
    shared = MagicMock(account_id="ACCT", tpsi_password="oldpw", deposit_account_no=None)
    tpsi_client = MagicMock()
    tpsi_client.change_password.return_value = "Password changed successfully."
    with _super(), \
         patch("routers.tpsi.shared_credentials.load_for_use", return_value=shared), \
         patch("routers.tpsi.client_for", return_value=tpsi_client), \
         patch("routers.tpsi.shared_credentials.set_shared",
               side_effect=RuntimeError("supabase unavailable")):
        response = client.post("/tpsi/credentials/password", headers=H, json={
            "new_password": "s3cretNew",
        })
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "PUT /tpsi/shared-credential" in detail
    assert "s3cretNew" not in detail
    assert "s3cretNew" not in response.text


def test_client_for_uses_the_shared_presenter_not_the_callers_own(client):
    """The CR session opens under the shared GSHK account whoever is logged in."""
    from routers import tpsi as tpsi_router

    shared = MagicMock(account_id="SHARED-ACCT", tpsi_password="pw")
    with patch("routers.tpsi.shared_credentials.load_for_use", return_value=shared), \
         patch("routers.tpsi.TpsiClient") as ctor:
        tpsi_router.client_for(REGULAR)
    assert ctor.call_args.args[0] == "SHARED-ACCT"


def test_sign_still_uses_the_callers_own_eservice_credential(client):
    """W-7: authentication is shared, the SIGNATURE stays personal."""
    with _super(), \
         patch("routers.tpsi.credentials.load_eservice",
               return_value=("EUSER-42", "sign-pw")) as spy, \
         patch("routers.tpsi.client_for", return_value=MagicMock(last_auth=None)), \
         patch("routers.tpsi.filings.sign",
               return_value={"filing_id": "f1", "result": "OK"}), \
         patch("routers.tpsi.log_event", new=AsyncMock()):
        response = client.post("/tpsi/filings/f1/sign", headers=H, json={})
    assert response.status_code == 200
    assert spy.call_args.args[0] == SUPER["id"]


def test_submit_falls_back_to_the_shared_deposit_account(client):
    """The frontend no longer knows the deposit account — the server does."""
    shared = MagicMock(account_id="A", tpsi_password="p",
                       deposit_account_no="N00061980009")
    with _super(), \
         patch("routers.tpsi.shared_credentials.load_for_use", return_value=shared), \
         patch("routers.tpsi.client_for", return_value=MagicMock(last_auth=None)), \
         patch("routers.tpsi.filings.submit",
               return_value={"filing_id": "f1", "receipt": {"caseNo": "1"}}) as spy, \
         patch("routers.tpsi.log_event", new=AsyncMock()):
        response = client.post("/tpsi/filings/f1/submit", headers=H,
                               json={"confirm": True})
    assert response.status_code == 200
    assert spy.call_args.args[3] == "N00061980009"


def test_submit_is_refused_when_no_deposit_account_can_be_resolved(client):
    """Better a clean 400 than a CR call that spends from an unknown account."""
    shared = MagicMock(account_id="A", tpsi_password="p", deposit_account_no=None)
    with _super(), \
         patch("routers.tpsi.shared_credentials.load_for_use", return_value=shared), \
         patch("routers.tpsi.log_event", new=AsyncMock()):
        response = client.post("/tpsi/filings/f1/submit", headers=H,
                               json={"confirm": True})
    assert response.status_code == 400
    assert "deposit account" in response.json()["detail"].lower()


# ---- filings: GET /tpsi/filings/{id}/pdf (BE-2) -----------------------------

def test_pdf_is_refused_until_the_filing_is_validated(client):
    """The preview must render the CR-validated snapshot. A draft has none, and
    rendering anything else would show the admin something other than what CR
    is holding. 409 not 404: the filing exists, it just is not validated yet."""
    with _super(), \
         patch("routers.tpsi.filings.get_filing",
               return_value={"stage": "draft", "form_code": "Nar1",
                             "validated_xml": None}):
        response = client.get("/tpsi/filings/f1/pdf", headers=H)
    assert response.status_code == 409
    assert "validated" in response.json()["detail"].lower()


def test_pdf_refuses_a_form_code_it_has_no_renderer_for(client):
    """POST /tpsi/filings accepts every code in FORM_FEES — Nnc1, Nd2a, Nd4,
    Nsc1 and the rest. This renderer knows NAR1 and only NAR1.

    Rendering an Nd2a through it does not fail loudly: it produces a document
    headed "Form NAR1 — Annual Return" carrying the handful of tags whose names
    happen to coincide (brNo, the addresses) and silently dropping every ND2A
    particular. The admin then approves that before a chargeable, irreversible
    submit. A refusal naming the actual code is the only safe answer.
    """
    row = {"stage": "validated", "form_code": "Nd2a",
           "validated_xml": "<x/>", "nar1_case_id": "c1"}
    with _super(), \
         patch("routers.tpsi.filings.get_filing", return_value=row), \
         patch("routers.tpsi.nar1_pdf.render", return_value=b"%PDF-x") as spy, \
         patch("routers.tpsi.log_event", new=AsyncMock()):
        response = client.get("/tpsi/filings/f1/pdf", headers=H)
    assert response.status_code == 409
    assert "Nd2a" in response.json()["detail"]
    spy.assert_not_called()


def test_pdf_refuses_a_filing_whose_form_code_is_missing(client):
    """Absence is not a licence to assume NAR1 — that assumption is exactly the
    one that mislabels another form as an annual return."""
    row = {"stage": "validated", "validated_xml": "<x/>", "nar1_case_id": "c1"}
    with _super(), \
         patch("routers.tpsi.filings.get_filing", return_value=row), \
         patch("routers.tpsi.nar1_pdf.render", return_value=b"%PDF-x") as spy, \
         patch("routers.tpsi.log_event", new=AsyncMock()):
        response = client.get("/tpsi/filings/f1/pdf", headers=H)
    assert response.status_code == 409
    spy.assert_not_called()


def test_pdf_returns_pdf_bytes_and_audits_generation(client):
    logged = {}

    async def fake_log(**kwargs):
        logged.update(kwargs)

    row = {"stage": "validated", "form_code": "Nar1", "validated_xml": "<x/>",
           "nar1_case_id": "c1"}
    with _super(), \
         patch("routers.tpsi.filings.get_filing", return_value=row), \
         patch("routers.tpsi.nar1_pdf.render", return_value=b"%PDF-1.4 fake"), \
         patch("routers.tpsi.log_event", side_effect=fake_log):
        response = client.get("/tpsi/filings/f1/pdf", headers=H)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert logged["action_type"] == "DOCUMENT_GENERATED"
    assert logged["case_id"] == "c1"


def test_pdf_renders_the_validated_snapshot_not_the_request_xml(client):
    """The two differ the moment anyone edits the entity after validating, and
    CR only holds one of them. Pinned because both columns sit on the same row
    and picking the wrong one is a one-word mistake nothing else would catch."""
    row = {
        "stage": "validated",
        "form_code": "Nar1",
        "request_xml": "<the-draft-we-built/>",
        "validated_xml": "<what-cr-actually-holds/>",
        "nar1_case_id": "c1",
    }
    with _super(), \
         patch("routers.tpsi.filings.get_filing", return_value=row), \
         patch("routers.tpsi.nar1_pdf.render", return_value=b"%PDF-x") as spy, \
         patch("routers.tpsi.log_event", new=AsyncMock()):
        client.get("/tpsi/filings/f1/pdf", headers=H)
    assert spy.call_args.args[0] == "<what-cr-actually-holds/>"


def test_pdf_drives_the_real_renderer_not_just_a_mock(client):
    """Every other test here patches nar1_pdf.render, so none of them would
    notice the router handing the renderer something it cannot parse.

    The stored value is deliberately produced by `soap.extract_submission`, the
    same function `filings.validate` writes the column with — a verbatim slice
    whose xmlns:cr declaration was left behind on the enclosing element. Feeding
    the whole envelope here instead would exercise a shape production never
    stores.
    """
    from pathlib import Path

    from services.tpsi.soap import extract_submission

    sample = (
        Path(__file__).resolve().parents[1] / "fixtures" / "cr-examples"
        / "validateForm" / "validate_NAR1(Private Company, Schedule 1).xml"
    ).read_bytes()

    row = {"stage": "validated", "form_code": "Nar1",
           "validated_xml": extract_submission(sample), "nar1_case_id": "c1"}
    with _super(), \
         patch("routers.tpsi.filings.get_filing", return_value=row), \
         patch("routers.tpsi.log_event", new=AsyncMock()):
        response = client.get("/tpsi/filings/f1/pdf", headers=H)
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert response.content.rstrip().endswith(b"%%EOF")
    assert len(response.content) > 2000


def test_pdf_stamps_the_snapshot_age_onto_the_document(client):
    """`filings.validate` leaves `validated_xml` in place when CR rejects a
    re-validation, so a filing at validation_failed still has a renderable —
    but superseded — snapshot. The row knows both facts; the document has to
    carry them, or the reviewer has no way to tell a fresh preview from a stale
    one."""
    row = {"stage": "validation_failed", "form_code": "Nar1",
           "validated_xml": "<x/>", "validated_at": "2026-08-16T09:30:00+00:00",
           "nar1_case_id": "c1"}
    with _super(), \
         patch("routers.tpsi.filings.get_filing", return_value=row), \
         patch("routers.tpsi.nar1_pdf.render", return_value=b"%PDF-x") as spy, \
         patch("routers.tpsi.log_event", new=AsyncMock()):
        response = client.get("/tpsi/filings/f1/pdf", headers=H)
    assert response.status_code == 200
    assert spy.call_args.kwargs["validated_at"] == "2026-08-16T09:30:00+00:00"
    assert spy.call_args.kwargs["stage"] == "validation_failed"


def test_pdf_is_a_clean_422_when_the_stored_payload_has_no_form_model(client):
    """A stored payload CR accepted but we cannot parse is a data problem, not
    an unhandled 500 that reads like a crash in the renderer."""
    row = {"stage": "validated", "form_code": "Nar1",
           "validated_xml": "<soap:Envelope/>", "nar1_case_id": "c1"}
    with _super(), \
         patch("routers.tpsi.filings.get_filing", return_value=row), \
         patch("routers.tpsi.log_event", new=AsyncMock()):
        response = client.get("/tpsi/filings/f1/pdf", headers=H)
    assert response.status_code == 422


def test_pdf_without_a_token_is_rejected_before_the_db_is_touched(client):
    """The 401 half of CLAUDE.md's "401 and 403 on every route".

    Nothing auth-related is mocked — the real HTTPBearer and the real
    _resolve_user run, as in test_endpoints_require_authentication — and
    get_filing is asserted un-called, so this also pins that an anonymous
    request never reaches the database.
    """
    with patch("routers.tpsi.filings.get_filing") as spy:
        response = client.get("/tpsi/filings/f1/pdf")
    assert response.status_code in (401, 403)
    spy.assert_not_called()


def test_the_pdf_route_advertises_pdf_not_json_in_the_openapi_schema(client):
    """The route returns application/pdf and the generated schema said
    application/json, so every consumer reading it — client codegen, the API
    docs page — was told the wrong thing about the only binary endpoint here."""
    responses = client.get("/openapi.json").json()[
        "paths"]["/tpsi/filings/{filing_id}/pdf"]["get"]["responses"]
    assert list(responses["200"]["content"]) == ["application/pdf"]


def test_pdf_requires_tpsi_read(client):
    """A statutory return is data. No permission, no document."""
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb:
        msb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        response = client.get("/tpsi/filings/f1/pdf", headers=H)
    assert response.status_code == 403


def test_pdf_unknown_filing_is_handled_not_a_500(client):
    with _super(), \
         patch("routers.tpsi.filings.get_filing",
               side_effect=LookupError("no TPSI filing f1")):
        response = client.get("/tpsi/filings/f1/pdf", headers=H)
    assert response.status_code == 400


def test_pdf_survives_an_audit_failure(client):
    """CLAUDE.md: a log_event failure must never block the primary operation.
    The admin still gets the document they are about to sign off on.

    The failure is injected INSIDE audit_service, at its Supabase boundary --
    patching `routers.tpsi.log_event` itself would replace the very try/except
    that provides the guarantee and prove nothing.
    """
    row = {"stage": "validated", "form_code": "Nar1", "validated_xml": "<x/>",
           "nar1_case_id": "c1"}
    with _super(), \
         patch("routers.tpsi.filings.get_filing", return_value=row), \
         patch("routers.tpsi.nar1_pdf.render", return_value=b"%PDF-1.4 fake"), \
         patch("services.audit_service.get_supabase",
               side_effect=RuntimeError("audit down")):
        response = client.get("/tpsi/filings/f1/pdf", headers=H)
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")


def test_prepare_refuses_a_case_cr_already_holds(client):
    """The badge-corruption guard. Nothing writes stage 'superseded', so a new
    draft is simply the NEWEST row for the case: current_filing() returns it and
    case detail reports "Data Verification" for a return CR has registered,
    while nar1_case_registry -- which prefers a filed stage -- still reports
    "Completed". One case, two contradictory badges, and the live filing hidden
    behind a draft that can never advance."""
    p = _prepare_patches(
        blocking=MagicMock(return_value={"id": "f0", "stage": "submitted"}))
    with _with_prepare(p):
        response = client.post("/tpsi/filings/prepare", headers=H,
                               json={"entity_id": "e1", "nar1_case_id": "c1"})
    assert response.status_code == 409
    assert "already holds" in response.text
    p["create"].assert_not_called()
    # Refused before the entity is even loaded -- no work done for a filing
    # that was never going to be opened.
    p["load"].assert_not_awaited()


def test_prepare_refuses_a_case_completed_off_portal(client):
    """The mirror of the manual interlock: manual_receipt means the return was
    filed on paper, so a CR filing opened now would be a second filing in the
    register for one return."""
    p = _prepare_patches(
        case=MagicMock(return_value={"id": "c1", "entity_id": "e1",
                                     "manual_receipt": {"caseNo": "1234"}}))
    with _with_prepare(p):
        response = client.post("/tpsi/filings/prepare", headers=H,
                               json={"entity_id": "e1", "nar1_case_id": "c1"})
    assert response.status_code == 409
    assert "off-portal" in response.text
    p["create"].assert_not_called()


def test_prepare_still_allows_a_case_with_a_live_draft(client):
    """Only FILED stages block. Re-preparing after a failed validate is normal
    and must stay open, or a case whose first attempt CR rejected is stuck."""
    p = _prepare_patches(
        blocking=MagicMock(return_value={"id": "f0", "stage": "validation_failed"}))
    with _with_prepare(p):
        response = client.post("/tpsi/filings/prepare", headers=H,
                               json={"entity_id": "e1", "nar1_case_id": "c1"})
    assert response.status_code == 201
    p["create"].assert_called_once()

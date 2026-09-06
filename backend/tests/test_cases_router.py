"""backend/routers/cases.py — case create / composite read / patch.

Patches middleware.auth._resolve_user to a super_admin identity, as
test_tpsi_router.py and test_companies_router.py do.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

SUPER = {"id": "u1", "display_name": "Levi", "role_name": "super_admin", "role_id": "role-sa"}
NOBODY = {"id": "u2", "display_name": "Staff", "role_name": "staff", "role_id": "role-x"}
H = {"Authorization": "Bearer tok"}


def _super():
    return patch("middleware.auth._resolve_user", return_value=SUPER)


def _nobody():
    """A Supabase double that recognises no token, for the auth-gate tests.

    Patches ONLY the Supabase boundary, so the real _resolve_user still runs.
    Tests must never reach the live client (CLAUDE.md), and a test that does is
    green locally and red in CI -- see test_case_endpoints_require_authentication.
    """
    sb = MagicMock()
    sb.auth.get_user.return_value = MagicMock(user=None)
    return patch("middleware.auth.get_supabase", return_value=sb)


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
         patch("routers.cases.nar1_cases.current_filing", return_value=None), \
         patch("routers.cases.tpsi_filings.supersede", return_value=False), \
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


def test_restart_verification_on_a_never_sent_case_writes_no_audit_row(client):
    """audit_log is insert-only, so a restart that changes nothing must not
    record a status transition that did not happen. Every other branch in the
    handler compares against `before` first; this one used to fire regardless."""
    logged = []
    with _super(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "entity_id": "e1",
                             "verification_sent_at": None,
                             "client_approved": None,
                             "client_response_at": None}), \
         patch("routers.cases.nar1_cases.current_filing", return_value=None), \
         patch("routers.cases.tpsi_filings.supersede", return_value=False), \
         patch("routers.cases.nar1_cases.update_case") as spy, \
         patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}), \
         patch("routers.cases.log_event",
               new=AsyncMock(side_effect=lambda **kw: logged.append(kw))):
        response = client.patch("/cases/c1", headers=H,
                                json={"restart_verification": True})
    assert response.status_code == 200
    spy.assert_not_called()
    assert logged == []


def test_restart_verification_discards_the_cr_signed_snapshot(client):
    """THE DEFECT THIS EXISTS TO CLOSE.

    The confirmation the operator clicks through says "The case goes back to
    Data Verification. The CR-signed snapshot is discarded." Until this was
    wired, only the client-side fields were cleared: the filing stayed at
    'validated', so a case whose company details had just been corrected landed
    back on CLIENT Verification still holding CR's OLD signed XML — and the next
    send mailed the client a return that no longer matched the record.
    """
    with _super(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "entity_id": "e1",
                             "verification_sent_at": "2026-08-01T00:00:00Z",
                             "client_approved": True,
                             "client_response_at": "2026-08-02T00:00:00Z"}), \
         patch("routers.cases.nar1_cases.current_filing",
               return_value={"id": "f1", "stage": "validated"}), \
         patch("routers.cases.tpsi_filings.supersede", return_value=True) as sup, \
         patch("routers.cases.nar1_cases.update_case", return_value={"id": "c1"}), \
         patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.patch("/cases/c1", headers=H,
                                json={"restart_verification": True})
    assert response.status_code == 200
    sup.assert_called_once_with("f1")


def test_restarting_a_case_cr_already_holds_writes_nothing_at_all(client):
    """A restart cannot un-file a return. It is now refused outright (409), and
    the point this test has always protected still holds underneath: no row is
    updated and no audit event is written for a transition that never happened.

    `supersede()` remains the second line of defence — it filters on the stage
    inside the UPDATE — so a submit landing after the guard cannot be un-filed."""
    logged = []
    with _super(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "entity_id": "e1",
                             "verification_sent_at": None,
                             "client_approved": None,
                             "client_response_at": None}), \
         patch("routers.cases.nar1_cases.current_filing",
               return_value={"id": "f1", "stage": "submitted"}), \
         patch("routers.cases.tpsi_filings.supersede", return_value=False), \
         patch("routers.cases.nar1_cases.update_case") as spy, \
         patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}), \
         patch("routers.cases.log_event",
               new=AsyncMock(side_effect=lambda **kw: logged.append(kw))):
        response = client.patch("/cases/c1", headers=H,
                                json={"restart_verification": True})
    assert response.status_code == 409
    spy.assert_not_called()
    assert logged == []


def test_a_restart_that_only_retires_the_snapshot_still_records_it(client):
    """A case validated but never sent has nothing to clear on the case row —
    and a restart there DOES discard a CR-signed snapshot. Returning early on
    "no patch" would have made that change invisible in the trail."""
    logged = []
    with _super(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "entity_id": "e1",
                             "verification_sent_at": None,
                             "client_approved": None,
                             "client_response_at": None}), \
         patch("routers.cases.nar1_cases.current_filing",
               return_value={"id": "f1", "stage": "validated"}), \
         patch("routers.cases.tpsi_filings.supersede", return_value=True), \
         patch("routers.cases.nar1_cases.update_case") as spy, \
         patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}), \
         patch("routers.cases.log_event",
               new=AsyncMock(side_effect=lambda **kw: logged.append(kw))):
        client.patch("/cases/c1", headers=H, json={"restart_verification": True})
    # Nothing on the case row changed, so no UPDATE — but the trail must say
    # the snapshot went.
    spy.assert_not_called()
    assert [e["new_value"] for e in logged] == ["superseded"]


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
    """No identity patch: the real dependency runs against a Supabase double
    that recognises nobody.

    Mocked at the Supabase boundary and nowhere else -- the real _resolve_user,
    the real require_permission chain and the real HTTPBearer all run, which is
    the whole point of this test. Reaching the LIVE client instead would make
    the result depend on ambient env: backend/.env supplies a working key here,
    CI supplies none, so get_supabase() raised and the refusal arrived as a 500.
    """
    with _nobody():
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


# --------------------------------------------------------------------------- #
#  GET /cases?scope=dashboard — the case-level dashboard (BE-7)
# --------------------------------------------------------------------------- #

def _dashboard(rows, **extra):
    """A list_dashboard() return value. Async because the real one is —
    it fans its eight counts out concurrently."""
    payload = {"rows": rows, "total": len(rows), "page": 1, "page_size": 50,
               "counts": {"all": len(rows)}}
    payload.update(extra)
    return AsyncMock(return_value=payload)


def test_dashboard_returns_one_row_per_case(client):
    """A company with two open cases is two rows, not one. That is the whole
    difference between this and the company listing."""
    rows = [
        {"id": "c1", "case_no": "NAR-2026-0041", "entity_id": "e1",
         "company_name": "ACME LIMITED", "workflow_status": {"code": "signing"},
         "days_to_anniversary": 12},
        {"id": "c2", "case_no": "NAR-2026-0042", "entity_id": "e1",
         "company_name": "ACME LIMITED",
         "workflow_status": {"code": "data_verification"},
         "days_to_anniversary": 12},
    ]
    with _super(), patch("routers.cases.nar1_cases.list_dashboard", _dashboard(rows)):
        response = client.get("/cases?scope=dashboard", headers=H)
    assert response.status_code == 200
    body = response.json()
    assert len(body["rows"]) == 2
    assert {r["entity_id"] for r in body["rows"]} == {"e1"}
    assert body["counts"]["all"] == 2


def test_dashboard_passes_every_filter_through_to_the_query(client):
    """The filters have to reach the DATABASE. Applied to the page instead, the
    dashboard would filter the 50 rows it happened to be sent and quote a total
    for a different set."""
    spy = _dashboard([])
    with _super(), patch("routers.cases.nar1_cases.list_dashboard", spy):
        response = client.get(
            "/cases?scope=dashboard&search=acme&workflow_status=awaiting_client"
            "&anniv_op=lte&anniv_days=30&sort=case_no&dir=desc&page=2&page_size=10",
            headers=H,
        )
    assert response.status_code == 200
    kwargs = spy.call_args.kwargs
    assert kwargs["search"] == "acme"
    assert kwargs["workflow_statuses"] == ["awaiting_client"]
    assert kwargs["anniv_op"] == "lte"
    assert kwargs["anniv_days"] == 30
    assert kwargs["sort"] == "case_no"
    assert kwargs["direction"] == "desc"
    assert kwargs["page"] == 2
    assert kwargs["page_size"] == 10


def test_dashboard_takes_several_workflow_statuses_at_once(client):
    """"Action Required" is five badges, not one.

    The tile counts every case whose next move belongs to GSHK, so clicking it
    has to be able to ask for all five — otherwise the number on the tile and
    the rows it filters to are different sets.
    """
    spy = _dashboard([])
    with _super(), patch("routers.cases.nar1_cases.list_dashboard", spy):
        response = client.get(
            "/cases?scope=dashboard&workflow_status=signing,submission", headers=H)
    assert response.status_code == 200
    assert spy.call_args.kwargs["workflow_statuses"] == ["signing", "submission"]


def test_dashboard_rejects_an_unknown_status_inside_a_list(client):
    """One bad name refuses the whole request rather than being dropped from the
    list — a silently narrowed selection is a wrong answer told confidently."""
    with _super(), patch("routers.cases.nar1_cases.list_dashboard", _dashboard([])):
        response = client.get(
            "/cases?scope=dashboard&workflow_status=signing,not_a_status", headers=H)
    assert response.status_code == 422
    assert "not_a_status" in response.json()["detail"]


def test_dashboard_passes_column_filters_through_to_the_query(client):
    spy = _dashboard([])
    with _super(), patch("routers.cases.nar1_cases.list_dashboard", spy):
        response = client.get(
            "/cases?scope=dashboard&filter=company_name:contains:acme"
            "&filter=days_to_anniversary:lte:60",
            headers=H,
        )
    assert response.status_code == 200
    assert [(f.column, f.op, f.value) for f in spy.call_args.kwargs["filters"]] == [
        ("company_name", "contains", "acme"),
        ("days_to_anniversary", "lte", 60),
    ]


def test_dashboard_refuses_a_filter_on_an_unlisted_column(client):
    with _super(), patch("routers.cases.nar1_cases.list_dashboard", _dashboard([])):
        response = client.get(
            "/cases?scope=dashboard&filter=signing_method:contains:x", headers=H)
    assert response.status_code == 422
    assert "signing_method" in response.json()["detail"]


def test_dashboard_rejects_an_unknown_comparison(client):
    spy = _dashboard([])
    with _super(), patch("routers.cases.nar1_cases.list_dashboard", spy):
        response = client.get("/cases?scope=dashboard&anniv_op=near&anniv_days=5",
                              headers=H)
    assert response.status_code == 422
    spy.assert_not_awaited()


def test_dashboard_requires_both_halves_of_the_anniversary_filter(client):
    """A comparison with nothing to compare against is a caller bug worth
    surfacing, not a filter to silently ignore."""
    with _super(), patch("routers.cases.nar1_cases.list_dashboard", _dashboard([])):
        assert client.get("/cases?scope=dashboard&anniv_op=lte", headers=H).status_code == 422
        assert client.get("/cases?scope=dashboard&anniv_days=5", headers=H).status_code == 422


def test_dashboard_rejects_an_unknown_workflow_status(client):
    """Not one of the seven badges -> no rows could ever match, so answering 200
    with an empty list would read as "no cases in that state"."""
    with _super(), patch("routers.cases.nar1_cases.list_dashboard", _dashboard([])):
        response = client.get("/cases?scope=dashboard&workflow_status=nonsense",
                              headers=H)
    assert response.status_code == 422


def test_dashboard_rejects_a_sort_column_it_does_not_own(client):
    """`sort` reaches PostgREST's order clause. Anything not whitelisted is
    refused rather than quietly replaced by the default -- a listing that
    silently ignores the column you clicked looks sorted and is not."""
    with _super(), patch("routers.cases.nar1_cases.list_dashboard", _dashboard([])):
        response = client.get("/cases?scope=dashboard&sort=manual_receipt", headers=H)
    assert response.status_code == 422


def test_an_unknown_scope_is_rejected_rather_than_quietly_served(client):
    """`scope` was accepted and never read, so ?scope=garbage returned the
    dashboard anyway. That is the defect this endpoint's own validation block
    exists to prevent -- a caller asking for something we do not serve and
    getting something else with no indication."""
    with _super(), patch("routers.cases.nar1_cases.list_dashboard",
                        new=AsyncMock()) as spy:
        response = client.get("/cases?scope=nonsense", headers=H)
    assert response.status_code == 422
    assert "nonsense" in response.json()["detail"]
    spy.assert_not_called()  # refused before the query, not after


def test_omitting_scope_still_serves_the_dashboard(client):
    """The dashboard is this route's only listing, so a caller that never
    learned about `scope` must not be broken by validating it."""
    with _super(), patch("routers.cases.nar1_cases.list_dashboard",
                        new=AsyncMock(return_value={"rows": [], "total": 0})):
        response = client.get("/cases", headers=H)
    assert response.status_code == 200


def test_dashboard_caps_the_page_size(client):
    with _super(), patch("routers.cases.nar1_cases.list_dashboard", _dashboard([])):
        assert client.get("/cases?page_size=5000", headers=H).status_code == 422
        assert client.get("/cases?page=0", headers=H).status_code == 422


def test_dashboard_writes_nothing_to_the_audit_log(client):
    """Reads are outside audit scope (CLAUDE.md). A dashboard load per page view
    would drown the statutory events it shares the trail with."""
    with _super(), patch("routers.cases.nar1_cases.list_dashboard", _dashboard([])), \
         patch("routers.cases.log_event", new=AsyncMock()) as log_spy:
        assert client.get("/cases?scope=dashboard", headers=H).status_code == 200
    log_spy.assert_not_called()


def test_dashboard_requires_authentication(client):
    """As above: real auth chain, Supabase double that recognises nobody.

    The second assertion sends no Authorization header at all, so HTTPBearer
    refuses it before _resolve_user is ever reached.
    """
    with _nobody():
        assert client.get("/cases?scope=dashboard", headers=H).status_code in (401, 403)
    assert client.get("/cases").status_code in (401, 403)


def test_dashboard_is_gated_on_nar1_read(client):
    with patch("middleware.auth._resolve_user", return_value=NOBODY), \
         patch("middleware.auth._permissions_for", return_value=set()) as perms, \
         patch("routers.cases.nar1_cases.list_dashboard", _dashboard([])):
        response = client.get("/cases?scope=dashboard", headers=H)
    assert response.status_code == 403
    assert perms.call_args.args[1] == "nar1"


def test_the_dashboard_route_does_not_shadow_the_single_case_route(client):
    """`GET /cases` and `GET /cases/{case_id}` are different path shapes, but
    they share a router and a prefix. If the listing were ever declared with a
    trailing slash or a {case_id:path} converter, one would swallow the other."""
    with _super(), patch("routers.cases.nar1_cases.composite",
                         return_value={"id": "c1"}) as spy, \
         patch("routers.cases.nar1_cases.list_dashboard", _dashboard([])):
        assert client.get("/cases/c1", headers=H).status_code == 200
    assert spy.call_args.args[0] == "c1"


# --- restart is refused once CR holds the return ----------------------------
#
# WHY THIS EXISTS (Levi 2026-08-31). `supersede()` already declined to retire a
# filed filing, so the FILING was safe — but the handler went on to clear
# verification_sent_at, client_approved and client_response_at anyway. A
# completed case would lose the client's recorded approval and drop back to
# Client Verification while CR held the registered return: a case reporting it
# is waiting on a client whose answer was acted on days ago.


def _filed_case(**over):
    row = {"id": "c1", "entity_id": "e1", "verification_sent_at": "2026-08-31T11:52:00Z",
           "client_approved": True, "client_response_at": "2026-08-31T12:10:00Z",
           "manual_submitted_at": None, "manual_receipt": None}
    row.update(over)
    return row


def test_restart_is_refused_once_cr_holds_the_return(client):
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=_filed_case()), \
         patch("routers.cases.nar1_cases.current_filing",
               return_value={"id": "f1", "stage": "submitted"}), \
         patch("routers.cases.nar1_cases.update_case") as spy, \
         patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.patch("/cases/c1", headers=H,
                                json={"restart_verification": True})
    assert response.status_code == 409
    # The client's approval is a record of something that happened, and the
    # return built on it is in the register. Neither is ours to erase.
    spy.assert_not_called()
    assert "registry" in response.json()["detail"].lower()


def test_restart_is_refused_on_a_case_filed_off_portal(client):
    """The paper path reaches the register by a different road and arrives at
    the same place: a return that has been filed."""
    with _super(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value=_filed_case(manual_submitted_at="2026-08-30T09:00:00Z")), \
         patch("routers.cases.nar1_cases.current_filing", return_value=None), \
         patch("routers.cases.nar1_cases.update_case") as spy, \
         patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.patch("/cases/c1", headers=H,
                                json={"restart_verification": True})
    assert response.status_code == 409
    spy.assert_not_called()


def test_restart_still_works_on_a_return_cr_has_only_validated(client):
    """The guard is "has it been FILED", not "has CR seen it". A validated
    snapshot is exactly what Restart exists to discard."""
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=_filed_case()), \
         patch("routers.cases.nar1_cases.current_filing",
               return_value={"id": "f1", "stage": "validated"}), \
         patch("routers.cases.tpsi_filings.supersede", return_value=True), \
         patch("routers.cases.nar1_cases.update_case",
               return_value={"id": "c1"}) as spy, \
         patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.patch("/cases/c1", headers=H,
                                json={"restart_verification": True})
    assert response.status_code == 200
    assert spy.call_args.args[1]["client_approved"] is None

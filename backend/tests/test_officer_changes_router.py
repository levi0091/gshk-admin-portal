"""Officer-change routes: case, change list, documents, verification, close.

Happy path, 403 and an edge case per route group; services are patched at the
names the router calls, so nothing reaches Supabase, Resend, DNS or CR.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from routers import officer_changes as oc
from services.tpsi.forms.nar1_mapper import MappingError

client = TestClient(app)
ADMIN = {"id": "U1", "display_name": "Levi Z.", "role_name": "super_admin", "role_id": "r"}
STAFF = {"id": "U2", "display_name": "Staff", "role_name": "staff", "role_id": "x"}
H = {"Authorization": "Bearer tok"}
CASE = {"id": "K1", "case_no": "ND2A-2026-0001", "entity_id": "E1", "form_code": "Nd2a",
        "closed_at": None, "verification_sent_at": None, "client_approved": None}
COMPOSITE = {"id": "K1", "form_code": "Nd2a", "entries": [],
             "rules": {"blocking": False, "checks": [], "summary": ""}}


@pytest.fixture
def env():
    """An admin, a case and the services the router calls, all patched."""
    m = MagicMock()
    with patch("middleware.auth._resolve_user", return_value=ADMIN), \
         patch.object(oc.svc, "get_case", side_effect=lambda cid: dict(m.case)), \
         patch.object(oc.svc, "composite", new_callable=AsyncMock) as composite, \
         patch.object(oc.svc, "list_entries", return_value=[]), \
         patch.object(oc.nar1_cases, "current_filing", return_value=None), \
         patch.object(oc.nar1_cases, "update_case") as update, \
         patch.object(oc.nar1_cases, "entity_for", return_value={"company_name": "Kanenas"}), \
         patch.object(oc, "log_event", new_callable=AsyncMock) as audit:
        m.case = dict(CASE)
        composite.return_value = dict(COMPOSITE)
        m.composite, m.update, m.audit = composite, update, audit
        yield m


def _actions(audit):
    return [c.kwargs["action_type"] for c in audit.await_args_list]


# -- permissions ---------------------------------------------------------------------

ROUTES = [
    ("post", "/officer-changes", {"entity_id": "E1", "form_code": "Nd2a"}),
    ("get", "/officer-changes/K1", None),
    ("get", "/officer-changes/pending?entity_id=E1", None),
    ("patch", "/officer-changes/K1", {"signing_method": "manual"}),
    ("post", "/officer-changes/K1/entries", {"kind": "cessation"}),
    ("delete", "/officer-changes/K1/entries/N1", None),
    ("post", "/officer-changes/K1/entries/N1/kyc", {"cleared": True}),
    ("get", "/officer-changes/K1/preview", None),
    ("get", "/officer-changes/K1/verification/recipients", None),
    ("post", "/officer-changes/K1/verification/send", {"respond_by": "2026-10-10"}),
    ("post", "/officer-changes/K1/verification/response", {"approved": True}),
    ("post", "/officer-changes/K1/close", {"reason": "x"}),
    ("post", "/officer-changes/K1/validate", None),
    ("post", "/officer-changes/K1/sign", None),
    ("post", "/officer-changes/K1/submit", {"confirm": True}),
    ("post", "/officer-changes/K1/mark-checked", None),
    ("post", "/officer-changes/K1/record-filing",
     {"receipt": {"caseNo": "1", "transactionDate": "01/10/2026"}, "confirm": True}),
    ("post", "/officer-changes/K1/undo", {"confirm": True}),
]


@pytest.mark.parametrize("method, path, body", ROUTES)
def test_every_route_needs_a_permission(method, path, body):
    with patch("middleware.auth._resolve_user", return_value=STAFF), \
         patch("middleware.auth.get_supabase") as msb:
        chain = msb.return_value.table.return_value.select.return_value
        chain.eq.return_value.eq.return_value.execute.return_value.data = []
        chain.eq.return_value.execute.return_value.data = []
        kwargs = {"json": body} if body is not None else {}
        assert getattr(client, method)(path, headers=H, **kwargs).status_code == 403


def test_an_invalid_token_is_401():
    with patch("middleware.auth._resolve_user",
               side_effect=HTTPException(status_code=401, detail="x")):
        assert client.get("/officer-changes/K1", headers=H).status_code == 401


# -- the case ------------------------------------------------------------------------

def test_create_opens_a_case_and_audits_it(env):
    with patch.object(oc.svc, "create_case", return_value=(dict(CASE), False)):
        resp = client.post("/officer-changes", headers=H,
                           json={"entity_id": "E1", "form_code": "Nd2a"})
    assert resp.status_code == 201 and resp.json()["reused"] is False
    assert _actions(env.audit) == ["CASE_STATUS_CHANGED"]


def test_create_reuses_an_unsent_case_and_adds_the_entry(env):
    with patch.object(oc.svc, "create_case", return_value=(dict(CASE), True)), \
         patch.object(oc.svc, "add_entry", return_value={"id": "N1", "kind": "cessation"}):
        resp = client.post("/officer-changes", headers=H, json={
            "entity_id": "E1", "form_code": "Nd2a", "entry": {"kind": "cessation"}})
    assert resp.json()["reused"] is True
    assert _actions(env.audit) == ["OFFICER_CHANGE_ADDED"]


def test_create_refuses_a_bad_form_code(env):
    with patch.object(oc.svc, "create_case", side_effect=ValueError("not an officer form")):
        resp = client.post("/officer-changes", headers=H,
                           json={"entity_id": "E1", "form_code": "Nar1"})
    assert resp.status_code == 400


def test_a_nar1_case_is_not_found_here(env):
    with patch.object(oc.svc, "get_case", side_effect=LookupError("nar1")):
        assert client.get("/officer-changes/N1", headers=H).status_code == 404


def test_reading_an_editable_nd2b_refreshes_its_items(env):
    env.case = {**CASE, "form_code": "Nd2b"}
    with patch.object(oc.svc, "refresh_items") as refresh, \
         patch.object(oc.svc, "editable", return_value=True):
        assert client.get("/officer-changes/K1", headers=H).status_code == 200
    refresh.assert_called_once()


def test_pending_needs_a_company_or_a_person(env):
    assert client.get("/officer-changes/pending", headers=H).status_code == 400
    with patch.object(oc.svc, "open_cases_for", return_value=[{"id": "K1"}]):
        assert client.get("/officer-changes/pending?person_id=P1",
                          headers=H).json() == {"cases": [{"id": "K1"}]}


def test_esign_cannot_be_chosen_while_a_consent_credential_is_missing(env):
    plan = [{"ready": False, "reason": "HO New has no e-Registry account stored"}]
    with patch.object(oc.prepare, "consent_plan", new_callable=AsyncMock, return_value=plan):
        resp = client.patch("/officer-changes/K1", headers=H, json={"signing_method": "esign"})
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "esign_unavailable"
    assert "HO New" in resp.json()["detail"]["message"]


def test_restart_revokes_links_supersedes_filings_and_reopens_the_list(env):
    env.case = {**CASE, "verification_sent_at": "2026-10-01T00:00:00Z", "client_approved": True}
    with patch.object(oc.nar1_approvals, "supersede_outstanding", return_value=2) as links, \
         patch.object(oc.tpsi_filings, "supersede_all_for_case", return_value=1) as filings:
        resp = client.patch("/officer-changes/K1", headers=H,
                            json={"restart_verification": True})
    assert resp.status_code == 200
    links.assert_called_once_with("K1") and filings.assert_called_once_with("K1")
    patch_written = env.update.call_args.args[1]
    assert patch_written["verification_sent_at"] is None
    assert patch_written["client_approved"] is None


def test_a_closed_case_refuses_writes(env):
    env.case = {**CASE, "closed_at": "2026-10-01T00:00:00Z"}
    resp = client.post("/officer-changes/K1/entries", headers=H, json={"kind": "cessation"})
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "case_closed"


# -- the change list -----------------------------------------------------------------

def test_add_entry_audits_the_officer_not_their_particulars(env):
    entry = {"id": "N1", "kind": "appointment", "capacity": "director",
             "person_id": "P9", "items": []}
    with patch.object(oc.svc, "add_entry", return_value=entry):
        resp = client.post("/officer-changes/K1/entries", headers=H, json={"kind": "appointment"})
    assert resp.status_code == 200
    kwargs = env.audit.await_args.kwargs
    assert kwargs["action_type"] == "OFFICER_CHANGE_ADDED"
    assert kwargs["metadata"]["person_id"] == "P9"
    assert "promoted_from_register" not in kwargs["metadata"]


def test_ceasing_a_register_only_secretary_names_the_promotion_in_the_trail(env):
    entry = {"id": "N2", "kind": "cessation", "capacity": "company_secretary",
             "corporate_entity_id": "GSHK", "items": [],
             "promoted_from_register": {"secretary_id": "S1", "officer_id": "O9"}}
    with patch.object(oc.svc, "add_entry", return_value=entry):
        client.post("/officer-changes/K1/entries", headers=H,
                    json={"kind": "cessation", "secretary_id": "S1"})
    assert env.audit.await_args.kwargs["metadata"]["promoted_from_register"] == {
        "secretary_id": "S1", "officer_id": "O9"}


def test_entry_refusals_map_to_400_and_409(env):
    with patch.object(oc.svc, "add_entry", side_effect=ValueError("Enter the date")):
        assert client.post("/officer-changes/K1/entries", headers=H,
                           json={}).status_code == 400
    with patch.object(oc.svc, "add_entry",
                      side_effect=oc.svc.CaseRefused("not_editable", "sent")):
        resp = client.post("/officer-changes/K1/entries", headers=H, json={})
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "not_editable"


def test_update_entry_audits_only_what_changed(env):
    before = {"id": "N1", "kind": "cessation", "effective_date": "2026-09-28"}
    after = {**before, "effective_date": "2026-09-20"}
    with patch.object(oc.svc, "update_entry", return_value=(before, after)):
        client.patch("/officer-changes/K1/entries/N1", headers=H,
                     json={"effective_date": "2026-09-20"})
    kwargs = env.audit.await_args.kwargs
    assert kwargs["before_state"] == {"effective_date": "2026-09-28"}
    assert kwargs["after_state"] == {"effective_date": "2026-09-20"}


def test_remove_unknown_entry_is_404(env):
    with patch.object(oc.svc, "remove_entry", side_effect=LookupError("no")):
        assert client.delete("/officer-changes/K1/entries/NX", headers=H).status_code == 404


def test_supporting_document_upload_is_audited(env):
    with patch.object(oc.svc, "list_entries", return_value=[{"id": "N1", "case_id": "K1"}]), \
         patch.object(oc.documents, "upload", new_callable=AsyncMock,
                      return_value={"id": "D1", "file_name": "letter.pdf"}):
        resp = client.post("/officer-changes/K1/entries/N1/documents", headers=H,
                           files={"file": ("letter.pdf", b"%PDF", "application/pdf")},
                           data={"document_type_code": "resignation_letter"})
    assert resp.status_code == 200
    assert _actions(env.audit) == ["OFFICER_SUPPORT_DOC_UPLOADED"]


def test_a_filed_document_cannot_be_removed(env):
    with patch.object(oc.documents, "remove", side_effect=ValueError("on the profile")):
        resp = client.delete("/officer-changes/K1/documents/D1", headers=H)
    assert resp.status_code == 409


# -- the PDF ---------------------------------------------------------------------------

def test_preview_is_the_public_pages_by_default(env):
    with patch.object(oc.prepare, "build_form_xml", new_callable=AsyncMock,
                      return_value="<cr:brNo>1</cr:brNo>"), \
         patch.object(oc, "render_form", return_value=b"%PDF-1.7") as render:
        resp = client.get("/officer-changes/K1/preview", headers=H)
        client.get("/officer-changes/K1/preview?audience=staff", headers=H)
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/pdf"
    assert render.call_args_list[0].kwargs["public_only"] is True
    assert render.call_args_list[1].kwargs["public_only"] is False


def test_preview_reports_every_mapping_problem(env):
    with patch.object(oc.prepare, "build_form_xml", new_callable=AsyncMock,
                      side_effect=MappingError(["company: no BR number", "x: no date"])):
        resp = client.get("/officer-changes/K1/preview", headers=H)
    assert resp.status_code == 422
    assert resp.json()["detail"]["problems"] == ["company: no BR number", "x: no date"]


# -- verification ---------------------------------------------------------------------

def test_send_is_refused_while_a_company_rule_is_breached(env):
    env.composite.return_value = {**COMPOSITE, "rules": {"blocking": True, "checks": [
        {"code": "has_secretary", "ok": False, "level": "rule",
         "text": "The company would be left without a company secretary."}]}}
    resp = client.post("/officer-changes/K1/verification/send", headers=H,
                       json={"respond_by": "2026-10-10"})
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "rules_blocking"
    assert "secretary" in resp.json()["detail"]["message"]


def test_send_mails_each_recipient_with_their_own_officer_change_link(env):
    targets = [{"email": "a@example.com", "token": "tokA", "expires_at": None, "name": "A"},
               {"email": "b@example.com", "token": "tokB", "expires_at": None, "name": "B"}]
    sent = []

    def fake_send(**kwargs):
        sent.append(kwargs)
        return {"id": f"m{len(sent)}", "to": kwargs["to"], "intended_to": kwargs["to"]}

    with patch.object(oc.prepare, "build_form_xml", new_callable=AsyncMock,
                      return_value="<cr:brNo>1</cr:brNo>"), \
         patch.object(oc.tpsi_filings, "create_filing", return_value={"id": "F1"}), \
         patch.object(oc.nar1_router, "_undeliverable", new_callable=AsyncMock,
                      return_value={}), \
         patch.object(oc, "render_form", return_value=b"%PDF"), \
         patch.object(oc.recipients_svc, "default_recipients", return_value=[]), \
         patch.object(oc.nar1_router, "_approval_link_base", return_value="https://api.test"), \
         patch.object(oc.nar1_approvals, "issue", return_value=targets), \
         patch.object(oc.email_service, "send", side_effect=fake_send), \
         patch.object(oc.emails, "officer_change_email",
                      side_effect=lambda *a, **k: ("s", k["approval_url"])):
        resp = client.post("/officer-changes/K1/verification/send", headers=H, json={
            "emails": ["a@example.com", "b@example.com", "not an address"],
            "respond_by": "2099-01-01"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [s["to"] for s in sent] == [["a@example.com"], ["b@example.com"]]
    assert all(s["cc"] == [oc.email_service.CLIENT_CC] for s in sent)
    assert sent[0]["html"] == "https://api.test/public/officer-change-approval/tokA"
    assert body["failed_to"] == ["not an address"]
    assert [d["message_id"] for d in body["deliveries"]] == ["m1", "m2"]
    assert env.update.call_args.args[1]["verification_sent_at"]
    assert _actions(env.audit).count("CLIENT_APPROVAL_LINK_SENT") == 2
    email_row = next(c.kwargs for c in env.audit.await_args_list
                     if c.kwargs["action_type"] == "EMAIL_SENT")
    assert email_row["metadata"]["deliveries"][0]["email"] == "a@example.com"


def test_send_needs_a_reply_by_date(env):
    with patch.object(oc.prepare, "build_form_xml", new_callable=AsyncMock,
                      return_value="<x/>"), \
         patch.object(oc.tpsi_filings, "create_filing", return_value={"id": "F1"}):
        resp = client.post("/officer-changes/K1/verification/send", headers=H, json={})
    assert resp.status_code == 422


def test_recording_an_answer_needs_a_sent_request(env):
    assert client.post("/officer-changes/K1/verification/response", headers=H,
                       json={"approved": True}).status_code == 409
    env.case = {**CASE, "verification_sent_at": "2026-10-01T00:00:00Z"}
    resp = client.post("/officer-changes/K1/verification/response", headers=H,
                       json={"approved": True, "approved_by": "CHAN Tai Man"})
    assert resp.status_code == 200
    assert env.update.call_args.args[1]["client_approved"] is True
    assert _actions(env.audit) == ["CLIENT_APPROVAL_RECEIVED"]


# -- closing ---------------------------------------------------------------------------

def test_close_needs_a_reason_and_refuses_a_filed_case(env):
    assert client.post("/officer-changes/K1/close", headers=H,
                       json={"reason": " "}).status_code == 400
    env.case = {**CASE, "manual_receipt": {"caseNo": "1"}}
    resp = client.post("/officer-changes/K1/close", headers=H, json={"reason": "x"})
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "already_filed"


def test_close_supersedes_filings_and_revokes_links(env):
    with patch.object(oc.nar1_cases, "close_case", return_value={"id": "K1"}), \
         patch.object(oc.tpsi_filings, "supersede_all_for_case", return_value=1), \
         patch.object(oc.nar1_approvals, "supersede_outstanding", return_value=2):
        resp = client.post("/officer-changes/K1/close", headers=H,
                           json={"reason": "Client is not proceeding"})
    assert resp.status_code == 200
    meta = env.audit.await_args.kwargs["metadata"]
    assert meta["filings_superseded"] == 1 and meta["approval_links_revoked"] == 2

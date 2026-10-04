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
         patch.object(oc.svc, "mark_deferred", return_value=0) as deferred, \
         patch.object(oc.documents, "email_attachments", return_value=[]), \
         patch.object(oc, "log_event", new_callable=AsyncMock) as audit:
        m.case = dict(CASE)
        composite.return_value = dict(COMPOSITE)
        m.composite, m.update, m.audit, m.deferred = composite, update, audit, deferred
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
    ("put", "/officer-changes/K1/entries/N1/effective-date", {"effective_date": "2026-10-01"}),
    ("patch", "/officer-changes/K1/documents/D1", {"send_with_email": True}),
    ("get", "/officer-changes/K1/resolution", None),
    ("get", "/officer-changes/K1/preview", None),
    ("get", "/officer-changes/K1/verification/recipients", None),
    ("post", "/officer-changes/K1/verification/send", {"respond_by": "2026-10-10"}),
    ("post", "/officer-changes/K1/verification/response", {"approved": True}),
    ("post", "/officer-changes/K1/verification/proceed", {"reason": "x"}),
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


def test_the_signatory_capacity_must_fit_the_signer(env):
    # A natural-person secretary signs with an Individual capacity; a Body
    # Corporate one would be accepted by CR's schema and refused after filing.
    with patch.object(oc.svc, "_signatory_party", return_value=("CHAN Tai Man", False)):
        bad = client.patch("/officer-changes/K1", headers=H, json={
            "signatory_capacity": "Director of the Company Secretary (Body Corporate)"})
        good = client.patch("/officer-changes/K1", headers=H,
                            json={"signatory_capacity": "Company Secretary"})
    assert bad.status_code == 400 and "natural person" in bad.json()["detail"]
    assert good.status_code == 200


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

def test_preview_is_the_full_form_by_default(env):
    """Jacqueline A8/B2: the client checks the PI sheets too, so the client's
    copy is the full form."""
    with patch.object(oc.prepare, "build_form_xml", new_callable=AsyncMock,
                      return_value="<cr:brNo>1</cr:brNo>"), \
         patch.object(oc, "render_form", return_value=b"%PDF-1.7") as render:
        resp = client.get("/officer-changes/K1/preview", headers=H)
        client.get("/officer-changes/K1/preview?audience=staff", headers=H)
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/pdf"
    assert render.call_args_list[0].kwargs["public_only"] is False
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
    # Undated changes are deferred to Signing once the client has the draft.
    env.deferred.assert_called_once_with("K1")
    assert _actions(env.audit).count("CLIENT_APPROVAL_LINK_SENT") == 2
    email_row = next(c.kwargs for c in env.audit.await_args_list
                     if c.kwargs["action_type"] == "EMAIL_SENT")
    assert email_row["metadata"]["deliveries"][0]["email"] == "a@example.com"


@pytest.mark.parametrize("stage, supersedes", [
    ("validated", True), ("signed", True), ("draft", False), ("validation_failed", False)])
def test_a_re_send_after_cr_validation_starts_the_cr_steps_again(env, stage, supersedes):
    # The client must never approve one document while CR's frozen copy of an
    # earlier one is what gets signed and filed.
    with patch.object(oc.prepare, "build_form_xml", new_callable=AsyncMock, return_value="<x/>"), \
         patch.object(oc.nar1_cases, "current_filing", return_value={"id": "F0", "stage": stage}), \
         patch.object(oc.tpsi_filings, "supersede_all_for_case", return_value=1) as supersede, \
         patch.object(oc.tpsi_filings, "create_filing", return_value={"id": "F1"}) as create, \
         patch.object(oc.tpsi_filings, "rebuild_draft", return_value={"id": "F0"}) as rebuild, \
         patch.object(oc.nar1_router, "_undeliverable", new_callable=AsyncMock, return_value={}), \
         patch.object(oc, "render_form", return_value=b"%PDF"), \
         patch.object(oc.recipients_svc, "default_recipients", return_value=[]), \
         patch.object(oc.nar1_router, "_approval_link_base", return_value=None), \
         patch.object(oc.email_service, "send",
                      side_effect=lambda **k: {"id": "m1", "to": k["to"]}), \
         patch.object(oc.emails, "officer_change_email", return_value=("s", "h")):
        resp = client.post("/officer-changes/K1/verification/send", headers=H, json={
            "emails": ["a@example.com"], "respond_by": "2099-01-01"})
    assert resp.status_code == 200, resp.text
    assert supersede.called is supersedes
    assert create.called is supersedes and rebuild.called is not supersedes


def test_send_needs_a_reply_by_date(env):
    with patch.object(oc.prepare, "build_form_xml", new_callable=AsyncMock,
                      return_value="<x/>"), \
         patch.object(oc.tpsi_filings, "create_filing", return_value={"id": "F1"}):
        resp = client.post("/officer-changes/K1/verification/send", headers=H, json={})
    assert resp.status_code == 422


# -- revisions (Levi 2026-10-02, migration 051) ---------------------------------------

def _send_revision(env, *, send=None):
    """POST a send with the collaborators patched; return (resp, issue, letter, sent)."""
    sent = []

    def fake_send(**kwargs):
        sent.append(kwargs)
        return {"id": f"m{len(sent)}", "to": kwargs["to"]}

    issue = MagicMock(side_effect=lambda **kw: [
        {**r, "token": "tok", "expires_at": kw["expires_at"], "revision": kw.get("revision")}
        for r in kw["recipients"]])
    letter = MagicMock(return_value=("s", "h"))
    with patch.object(oc.prepare, "build_form_xml", new_callable=AsyncMock, return_value="<x/>"), \
         patch.object(oc.tpsi_filings, "create_filing", return_value={"id": "F1"}), \
         patch.object(oc.nar1_router, "_undeliverable", new_callable=AsyncMock, return_value={}), \
         patch.object(oc, "render_form", return_value=b"%PDF"), \
         patch.object(oc.recipients_svc, "default_recipients", return_value=[]), \
         patch.object(oc.nar1_router, "_approval_link_base", return_value="https://api.test"), \
         patch.object(oc.nar1_approvals, "issue", new=issue), \
         patch.object(oc.email_service, "send", side_effect=send or fake_send), \
         patch.object(oc.emails, "officer_change_email", new=letter):
        resp = client.post("/officer-changes/K1/verification/send", headers=H, json={
            "emails": ["a@example.com"], "respond_by": "2099-01-01"})
    return resp, issue, letter, sent


def test_the_first_send_is_revision_one_and_its_file_is_unmarked(env):
    env.case = {**CASE, "verification_revision": 0}
    resp, issue, letter, sent = _send_revision(env)
    assert resp.status_code == 200, resp.text
    assert issue.call_args.kwargs["revision"] == 1
    assert letter.call_args.kwargs["revision"] == 1
    assert "-Rev" not in sent[0]["attachments"][0][0]
    assert env.update.call_args.args[1]["verification_revision"] == 1


def test_a_resend_after_a_restart_is_the_next_revision(env):
    """A restart clears the send but not the count: the client still holds the
    first email, so the next is Rev. 2 — in the letter, on the links, on the
    file and on the case."""
    env.case = {**CASE, "verification_sent_at": None, "verification_revision": 1}
    resp, issue, letter, sent = _send_revision(env)
    assert resp.status_code == 200, resp.text
    assert resp.json()["revision"] == 2
    assert issue.call_args.kwargs["revision"] == 2
    assert letter.call_args.kwargs["revision"] == 2
    assert sent[0]["attachments"][0][0].endswith("-Rev2.pdf")
    assert env.update.call_args.args[1]["verification_revision"] == 2
    email_row = next(c.kwargs for c in env.audit.await_args_list
                     if c.kwargs["action_type"] == "EMAIL_SENT")
    assert email_row["metadata"]["revision"] == 2


def test_a_send_that_reached_nobody_does_not_use_up_a_revision(env):
    env.case = {**CASE, "verification_revision": 1}

    def refused(**_kwargs):
        raise oc.email_service.EmailError("resend refused it")

    resp, *_ = _send_revision(env, send=refused)
    assert resp.status_code == 502
    env.update.assert_not_called()


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


# -- deferred effective dates (Jacqueline A1) ---------------------------------------

def test_put_effective_date_fills_a_deferred_date_and_audits_it(env):
    before = {"id": "N1", "kind": "appointment", "effective_date": None}
    after = {**before, "effective_date": "2026-10-01"}
    with patch.object(oc.svc, "set_effective_date", return_value=(before, after)) as svc_set:
        resp = client.put("/officer-changes/K1/entries/N1/effective-date", headers=H,
                          json={"effective_date": "2026-10-01"})
    assert resp.status_code == 200, resp.text
    assert svc_set.call_args.kwargs["item_key"] is None
    row = env.audit.await_args_list[-1].kwargs
    assert row["action_type"] == "CASE_FIELD_UPDATED"
    assert row["metadata"]["field"] == "effective_date"
    assert row["old_value"] is None and row["new_value"] == "2026-10-01"


def test_put_effective_date_refusal_is_a_409_with_its_reason(env):
    with patch.object(oc.svc, "set_effective_date",
                      side_effect=oc.svc.CaseRefused("not_deferred", "The client was sent this date.")):
        resp = client.put("/officer-changes/K1/entries/N1/effective-date", headers=H,
                          json={"effective_date": "2026-10-01"})
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "not_deferred"


def test_put_effective_date_bad_value_is_a_400(env):
    with patch.object(oc.svc, "set_effective_date",
                      side_effect=ValueError("The effective date cannot be after today")):
        resp = client.put("/officer-changes/K1/entries/N1/effective-date", headers=H,
                          json={"effective_date": "2099-01-01"})
    assert resp.status_code == 400



# -- case documents, attachments and the written resolution (Jacqueline A3) ---------

def test_case_document_upload_holds_it_on_the_case_and_audits(env):
    row = {"id": "D1", "file_name": "resolution.pdf"}
    with patch.object(oc.documents, "upload", new_callable=AsyncMock, return_value=row) as up:
        resp = client.post("/officer-changes/K1/documents", headers=H,
                           data={"document_type_code": "board_resolution",
                                 "send_with_email": "true"},
                           files={"file": ("resolution.pdf", b"%PDF", "application/pdf")})
    assert resp.status_code == 200, resp.text
    assert up.await_args.args[1] is None and up.await_args.kwargs["send_with_email"] is True
    meta = env.audit.await_args.kwargs["metadata"]
    assert env.audit.await_args.kwargs["action_type"] == "OFFICER_SUPPORT_DOC_UPLOADED"
    assert meta["entry_id"] is None and meta["send_with_email"] is True


def test_case_document_upload_403_without_write():
    with patch("middleware.auth._resolve_user", return_value=STAFF), \
         patch("middleware.auth.get_supabase") as msb:
        chain = msb.return_value.table.return_value.select.return_value
        chain.eq.return_value.eq.return_value.execute.return_value.data = []
        chain.eq.return_value.execute.return_value.data = []
        resp = client.post("/officer-changes/K1/documents", headers=H,
                           data={"document_type_code": "board_resolution"},
                           files={"file": ("r.pdf", b"%PDF", "application/pdf")})
    assert resp.status_code == 403


def test_patch_document_send_with_email_audits_the_field(env):
    with patch.object(oc.documents, "set_send_with_email",
                      return_value={"id": "D1", "file_name": "r.pdf",
                                    "send_with_email": True}):
        resp = client.patch("/officer-changes/K1/documents/D1", headers=H,
                            json={"send_with_email": True})
    assert resp.status_code == 200
    row = env.audit.await_args.kwargs
    assert row["action_type"] == "CASE_FIELD_UPDATED"
    assert row["metadata"]["field"] == "send_with_email"


def test_patch_audits_each_changed_field(env):
    env.case = {**CASE, "signing_method": "esign", "client_approved": True,
                "verification_sent_at": "2026-10-01T00:00:00Z"}
    resp = client.patch("/officer-changes/K1", headers=H, json={"signing_method": "manual"})
    assert resp.status_code == 200, resp.text
    rows = [c.kwargs for c in env.audit.await_args_list
            if c.kwargs["action_type"] == "CASE_FIELD_UPDATED"]
    assert [r["metadata"]["field"] for r in rows][:1] == ["signing_method"]
    assert rows[0]["old_value"] == "esign" and rows[0]["new_value"] == "manual"


def test_patch_refuses_attach_resolution(env):
    """Levi 2026-10-05: the resolution always goes with an ND2A — no toggle."""
    resp = client.patch("/officer-changes/K1", headers=H, json={"attach_resolution": True})
    assert resp.status_code == 422
    env.update.assert_not_called()


def test_resolution_preview_is_a_pdf(env):
    env.composite.return_value = {**COMPOSITE, "officers": [], "entries": []}
    with patch.object(oc.resolution, "render", return_value=b"%PDF-res") as render:
        resp = client.get("/officer-changes/K1/resolution", headers=H)
    assert resp.status_code == 200 and resp.content == b"%PDF-res"
    assert resp.headers["content-type"] == "application/pdf"
    render.assert_called_once()


def test_resolution_is_nd2a_only(env):
    env.case = {**CASE, "form_code": "Nd2b"}
    resp = client.get("/officer-changes/K1/resolution", headers=H)
    assert resp.status_code == 409



# -- the send: PI sheets, attachments, consent wording (Jacqueline A3, A5, A8) --------

def _send_patches(sent, *, attachments=(), attach_error=None, plan=()):
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch.object(oc.prepare, "build_form_xml", new_callable=AsyncMock,
                                     return_value="<x/>"))
    stack.enter_context(patch.object(oc.prepare, "consent_plan", new_callable=AsyncMock,
                                     return_value=list(plan)))
    stack.enter_context(patch.object(oc.tpsi_filings, "create_filing", return_value={"id": "F1"}))
    stack.enter_context(patch.object(oc.nar1_router, "_undeliverable", new_callable=AsyncMock,
                                     return_value={}))
    render = stack.enter_context(patch.object(oc, "render_form", return_value=b"%PDF-form"))
    stack.enter_context(patch.object(oc.recipients_svc, "default_recipients", return_value=[
        {"email": "lee@example.com", "person_id": "P9", "name": "LEE Ka Ho"}]))
    stack.enter_context(patch.object(oc.nar1_router, "_approval_link_base", return_value=None))
    stack.enter_context(patch.object(oc.resolution, "render", return_value=b"%PDF-res"))
    if attach_error:
        stack.enter_context(patch.object(oc.documents, "email_attachments",
                                         side_effect=attach_error))
    else:
        stack.enter_context(patch.object(oc.documents, "email_attachments",
                                         return_value=list(attachments)))
    stack.enter_context(patch.object(oc.email_service, "send",
                                     side_effect=lambda **k: sent.append(k) or
                                     {"id": "m1", "to": k["to"]}))
    letter = stack.enter_context(patch.object(oc.emails, "officer_change_email",
                                              return_value=("s", "h")))
    return stack, render, letter


def test_send_attaches_full_form_resolution_and_ticked_docs(env):
    """Levi 2026-10-05: an ND2A always goes with its written resolution — the
    case carries no flag for it any more."""
    env.case = dict(CASE)
    sent = []
    stack, render, letter = _send_patches(sent, attachments=[("memo.pdf", b"%PDF-memo")])
    with stack:
        resp = client.post("/officer-changes/K1/verification/send", headers=H, json={
            "emails": ["lee@example.com"], "respond_by": "2099-01-01"})
    assert resp.status_code == 200, resp.text
    assert render.call_args.kwargs["public_only"] is False
    names = [n for n, _ in sent[0]["attachments"]]
    assert names == ["ND2A-ND2A-2026-0001.pdf", "Written-Resolution-ND2A-2026-0001.pdf",
                     "memo.pdf"]
    assert letter.call_args.kwargs["attachments"] == names
    email_row = next(c.kwargs for c in env.audit.await_args_list
                     if c.kwargs["action_type"] == "EMAIL_SENT")
    assert email_row["metadata"]["attachments"] == names


def test_an_nd2b_send_carries_no_resolution(env):
    env.case = {**CASE, "form_code": "Nd2b", "case_no": "ND2B-2026-0001"}
    sent = []
    stack, _render, _letter = _send_patches(sent)
    with stack:
        resp = client.post("/officer-changes/K1/verification/send", headers=H, json={
            "emails": ["lee@example.com"], "respond_by": "2099-01-01"})
    assert resp.status_code == 200, resp.text
    assert [n for n, _ in sent[0]["attachments"]] == ["ND2B-ND2B-2026-0001.pdf"]


def test_send_refuses_before_mailing_when_an_attachment_cannot_be_read(env):
    sent = []
    stack, _r, _l = _send_patches(sent, attach_error=oc.documents.AttachmentError("memo.pdf"))
    with stack:
        resp = client.post("/officer-changes/K1/verification/send", headers=H, json={
            "emails": ["lee@example.com"], "respond_by": "2099-01-01"})
    # 409, not 502 (finding 5): behind Cloudflare a 502's body never reaches
    # the screen, and naming the file is the point of this refusal.
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason"] == "attachment_unreadable"
    assert "memo.pdf" in resp.json()["detail"]["message"]
    assert sent == []
    env.update.assert_not_called()


def test_send_tells_an_esign_director_no_signature_is_needed(env):
    sent = []
    plan = [{"entry_id": "N1", "signer_person_id": "P9", "ready": True, "signer_name": "LEE"}]
    stack, _r, letter = _send_patches(sent, plan=plan)
    stack.enter_context(patch.object(oc.svc, "list_entries", return_value=[
        {"id": "N1", "kind": "appointment", "capacity": "director", "person_id": "P9"}]))
    with stack:
        client.post("/officer-changes/K1/verification/send", headers=H, json={
            "emails": ["lee@example.com"], "respond_by": "2099-01-01"})
    assert letter.call_args.kwargs["consent"]["mode"] == "esign"


def test_preview_public_audience_is_public_only(env):
    with patch.object(oc.prepare, "build_form_xml", new_callable=AsyncMock, return_value="<x/>"), \
         patch.object(oc, "render_form", return_value=b"%PDF") as render:
        client.get("/officer-changes/K1/preview?audience=public", headers=H)
        assert render.call_args.kwargs["public_only"] is True
        client.get("/officer-changes/K1/preview?audience=client", headers=H)
        assert render.call_args.kwargs["public_only"] is False



# -- no in-portal consent (Levi 2026-10-05) --------------------------------------

def test_consent_routes_are_gone():
    """CR's consent signature IS the consent (TPSI API v1.0.14 section 7.1.2):
    no consent link, no public consent page, no stamped consent PDF."""
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any("econsent" in p or "officer-consent" in p for p in paths)
    with patch("middleware.auth._resolve_user", return_value=ADMIN):
        resp = client.post("/officer-changes/K1/entries/N1/econsent-pdf", headers=H)
    assert resp.status_code in (404, 405)


# -- ND2B: proceed without the client's confirmation (Jacqueline BQ1) ---------------

ND2B_SENT = {**CASE, "form_code": "Nd2b", "case_no": "ND2B-2026-0003",
             "verification_sent_at": "2026-10-01T00:00:00Z"}


def test_proceed_sets_approved_with_waiver_source(env):
    env.case = dict(ND2B_SENT)
    resp = client.post("/officer-changes/K1/verification/proceed", headers=H,
                       json={"reason": "Filing deadline; client not responding"})
    assert resp.status_code == 200, resp.text
    patch_ = env.update.call_args.args[1]
    assert patch_["client_approved"] is True
    assert patch_["client_approval_source"] == "staff_waiver"
    assert patch_["client_approval_name"] == "Filing deadline; client not responding"
    row = env.audit.await_args.kwargs
    assert row["action_type"] == "OFFICER_CONFIRMATION_WAIVED"
    assert row["metadata"]["reason"] == "Filing deadline; client not responding"


def test_proceed_refused_on_nd2a(env):
    env.case = {**CASE, "verification_sent_at": "2026-10-01T00:00:00Z"}
    resp = client.post("/officer-changes/K1/verification/proceed", headers=H,
                       json={"reason": "x"})
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "nd2b_only"


def test_proceed_requires_a_reason(env):
    env.case = dict(ND2B_SENT)
    resp = client.post("/officer-changes/K1/verification/proceed", headers=H,
                       json={"reason": "   "})
    assert resp.status_code == 400


def test_proceed_needs_a_sent_unanswered_form(env):
    env.case = {**ND2B_SENT, "verification_sent_at": None}
    assert client.post("/officer-changes/K1/verification/proceed", headers=H,
                       json={"reason": "x"}).status_code == 409
    env.case = {**ND2B_SENT, "client_approved": True}
    assert client.post("/officer-changes/K1/verification/proceed", headers=H,
                       json={"reason": "x"}).status_code == 409


# -- review findings ------------------------------------------------------------------

def test_switching_route_clears_the_data_check(env):
    """Finding 1: a case marked checked for e-Sign and switched to manual must
    pass the manual route's checks (each new director's consent) again."""
    env.case = {**CASE, "signing_method": "esign", "data_checked_at": "2026-10-02T00:00:00Z",
                "data_checked_by": "U1", "client_approved": True,
                "verification_sent_at": "2026-10-01T00:00:00Z"}
    resp = client.patch("/officer-changes/K1", headers=H, json={"signing_method": "manual"})
    assert resp.status_code == 200, resp.text
    sent = env.update.call_args.args[1]
    assert sent["signing_method"] == "manual"
    assert sent["data_checked_at"] is None and sent["data_checked_by"] is None


def test_a_mixed_board_on_a_manual_only_case_is_never_told_no_signature_is_needed(env):
    """Finding 4: director A has an account, B has none — the case can only go
    manual, so nobody is told 'no signature needed' and nobody gets a link."""
    sent = []
    plan = [{"entry_id": "N1", "signer_person_id": "P9", "ready": True, "signer_name": "LEE"},
            {"entry_id": "N2", "signer_person_id": "P8", "ready": False, "signer_name": "HO",
             "reason": "HO has no e-Registry account stored on their profile"}]
    stack, _r, letter = _send_patches(sent, plan=plan)
    stack.enter_context(patch.object(oc.nar1_router, "_approval_link_base",
                                     return_value="https://api.test"))
    stack.enter_context(patch.object(oc.nar1_approvals, "issue", return_value=[
        {"email": "lee@example.com", "person_id": "P9", "name": "LEE Ka Ho",
         "token": "tokA", "expires_at": None}]))
    stack.enter_context(patch.object(oc.svc, "list_entries", return_value=[
        {"id": "N1", "kind": "appointment", "capacity": "director", "person_id": "P9"},
        {"id": "N2", "kind": "appointment", "capacity": "director", "person_id": "P8"}]))
    stack.enter_context(patch.object(oc.eservice, "metadata_for", return_value={
        "P9": {"eservice_user_id": "LKH1", "eservice_person_name": "LEE", "has_password": True}}))
    with stack:
        resp = client.post("/officer-changes/K1/verification/send", headers=H, json={
            "emails": ["lee@example.com"], "respond_by": "2099-01-01"})
    assert resp.status_code == 200, resp.text
    assert letter.call_args.kwargs["consent"] is None

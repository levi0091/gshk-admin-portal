"""The CR steps of an officer change: validate, sign, submit — and the manual
route, which must reach "filed" without ever constructing a CR client."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from routers import officer_change_filing as ocf
from services.tpsi.errors import TpsiError

client = TestClient(app)
ADMIN = {"id": "U1", "display_name": "Levi Z.", "role_name": "super_admin", "role_id": "r"}
H = {"Authorization": "Bearer tok"}
CASE = {"id": "K1", "case_no": "ND2A-2026-0001", "entity_id": "E1", "form_code": "Nd2a",
        "closed_at": None, "client_approved": True,
        "verification_sent_at": "2026-10-01T00:00:00Z"}
SECRET = "Director-Secret-1"


@pytest.fixture
def env():
    m = MagicMock()
    m.case, m.filing = dict(CASE), None

    def no_cr(*a, **k):
        raise AssertionError("the CR client was constructed")

    with patch("middleware.auth._resolve_user", return_value=ADMIN), \
         patch("routers.officer_changes.svc.get_case", side_effect=lambda cid: dict(m.case)), \
         patch.object(ocf.svc, "get_case", side_effect=lambda cid: dict(m.case)), \
         patch("routers.officer_changes.svc.composite", new_callable=AsyncMock,
               return_value={"id": "K1", "entries": []}), \
         patch.object(ocf.svc, "composite", new_callable=AsyncMock,
                      return_value={"id": "K1", "entries": []}), \
         patch.object(ocf.svc, "list_entries", return_value=[]), \
         patch.object(ocf.nar1_cases, "current_filing", side_effect=lambda cid: m.filing), \
         patch.object(ocf.nar1_cases, "blocking_filing", side_effect=lambda cid: m.filing), \
         patch.object(ocf.nar1_cases, "update_case") as update, \
         patch.object(ocf.tpsi_router, "client_for", side_effect=no_cr) as cr, \
         patch("routers.officer_changes.log_event", new_callable=AsyncMock) as audit:
        m.update, m.audit, m.cr = update, audit, cr
        yield m


def _actions(audit):
    return [c.kwargs["action_type"] for c in audit.await_args_list]


# -- validate -----------------------------------------------------------------------

def test_validate_needs_the_clients_confirmation(env):
    env.case = {**CASE, "client_approved": None}
    resp = client.post("/officer-changes/K1/validate", headers=H)
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "not_approved"


def test_validate_is_refused_while_a_consent_credential_is_missing(env):
    plan = [{"ready": False, "reason": "HO New has no e-Registry account stored"}]
    with patch.object(ocf.prepare, "consent_plan", new_callable=AsyncMock, return_value=plan):
        resp = client.post("/officer-changes/K1/validate", headers=H)
    assert resp.status_code == 409 and "HO New" in resp.json()["detail"]["message"]
    env.cr.assert_not_called()


def test_validate_builds_for_esign_and_asks_cr(env):
    env.cr.side_effect = None
    with patch.object(ocf.prepare, "consent_plan", new_callable=AsyncMock, return_value=[]), \
         patch.object(ocf.prepare, "build_form_xml", new_callable=AsyncMock,
                      return_value="<x/>") as build, \
         patch.object(ocf.credentials, "load_signatory_identity", return_value={"x": 1}), \
         patch.object(ocf.filings, "create_filing", return_value={"id": "F1", "stage": "draft"}), \
         patch.object(ocf.filings, "validate") as validate:
        resp = client.post("/officer-changes/K1/validate", headers=H)
    assert resp.status_code == 200, resp.text
    assert build.await_args.kwargs["for_esign"] is True
    validate.assert_called_once()
    assert env.update.call_args.args[1] == {"signing_method": "esign"}
    assert "TPSI_VALIDATE" in _actions(env.audit)


def test_a_cr_fault_on_validate_comes_back_as_its_fault_list(env):
    env.cr.side_effect = None
    with patch.object(ocf.prepare, "consent_plan", new_callable=AsyncMock, return_value=[]), \
         patch.object(ocf.prepare, "build_form_xml", new_callable=AsyncMock, return_value="<x/>"), \
         patch.object(ocf.credentials, "load_signatory_identity", return_value=None), \
         patch.object(ocf.filings, "create_filing", return_value={"id": "F1", "stage": "draft"}), \
         patch.object(ocf.filings, "validate", side_effect=TpsiError("Br No does not exist.")):
        resp = client.post("/officer-changes/K1/validate", headers=H)
    assert resp.status_code in (400, 422, 502)
    assert "Br No does not exist." in resp.text


# -- sign ----------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    {"eservice_password": SECRET},
    # Not an object: a declared `dict` body answered these with FastAPI's 422,
    # which echoes the input.
    [SECRET],
    SECRET,
])
def test_sign_refuses_any_body_without_echoing_it(env, payload):
    resp = client.post("/officer-changes/K1/sign", headers=H, json=payload)
    assert resp.status_code == 400 and SECRET not in resp.text


def test_sign_accepts_an_empty_object_as_an_empty_body(env):
    # `{}` is what the frontend sends; it must reach the gates, not the refusal.
    resp = client.post("/officer-changes/K1/sign", headers=H, json={})
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "not_validated"


@pytest.mark.parametrize("cr_says, hint", [
    # Each measured on CR TEST, 2026-10-02.
    ("signer does not match with officer.", "must match their e-Registry account"),
    ("No matched individual officier.", "cannot find the officer on its register"),
    ("Please check selectPersonId field.", "does not accept the signing account"),
])
def test_crs_refusals_are_explained_in_an_officer_changes_words(env, cr_says, hint):
    from services.tpsi.errors import TpsiValidationError
    env.cr.side_effect = None
    with patch.object(ocf.prepare, "consent_plan", new_callable=AsyncMock, return_value=[]), \
         patch.object(ocf.prepare, "build_form_xml", new_callable=AsyncMock, return_value="<x/>"), \
         patch.object(ocf.credentials, "load_signatory_identity", return_value={"x": 1}), \
         patch.object(ocf.filings, "create_filing", return_value={"id": "F1", "stage": "draft"}), \
         patch.object(ocf.filings, "validate",
                      side_effect=TpsiValidationError([("ERROR", cr_says)])):
        resp = client.post("/officer-changes/K1/validate", headers=H)
    detail = resp.json()["detail"]
    assert resp.status_code == 422
    assert detail["message"] == "The Companies Registry rejected this form."
    assert any(hint in h for h in detail["hints"])
    assert detail["problems"] == [["ERROR", cr_says]]      # CR's own words kept


def test_sign_needs_a_validated_filing_and_the_users_own_credential(env):
    assert client.post("/officer-changes/K1/sign", headers=H).status_code == 409
    env.filing = {"id": "F1", "stage": "validated"}
    with patch.object(ocf.credentials, "load_eservice", return_value=None):
        resp = client.post("/officer-changes/K1/sign", headers=H)
    assert resp.json()["detail"]["reason"] == "no_signing_credential"


def test_sign_applies_each_directors_stored_consent_then_the_overall(env):
    env.cr.side_effect = None
    env.filing = {"id": "F1", "stage": "validated"}
    plan = [{"entry_id": "N1", "bean_id": "S1", "signer_person_id": "P9",
             "signer_name": "HO New", "ready": True}]
    with patch.object(ocf.credentials, "load_eservice", return_value=("STAFF-1", "pw")), \
         patch.object(ocf.prepare, "consent_plan", new_callable=AsyncMock, return_value=plan), \
         patch.object(ocf.eservice, "load_for_signing",
                      return_value=("ER-P9", "HO, NEW", SECRET)), \
         patch.object(ocf.signing, "sign", return_value={"result": "OK"}) as sign, \
         patch.object(ocf.svc, "get_supabase") as sb:
        resp = client.post("/officer-changes/K1/sign", headers=H)
    assert resp.status_code == 200, resp.text
    kwargs = sign.call_args.kwargs
    assert kwargs["signatory_user_id"] == "STAFF-1"
    assert kwargs["consents"] == [{"bean_id": "S1", "user_id": "ER-P9", "password": SECRET}]
    assert _actions(env.audit) == ["OFFICER_CONSENT_SIGNED", "TPSI_SIGN"]
    assert SECRET not in str(env.audit.await_args_list)
    sb.return_value.table.assert_called_with("officer_change_entries")


def test_sign_names_a_director_without_a_stored_credential(env):
    env.filing = {"id": "F1", "stage": "validated"}
    plan = [{"entry_id": "N1", "bean_id": "S1", "signer_person_id": "P9",
             "signer_name": "HO New", "ready": False}]
    with patch.object(ocf.credentials, "load_eservice", return_value=("STAFF-1", "pw")), \
         patch.object(ocf.prepare, "consent_plan", new_callable=AsyncMock, return_value=plan), \
         patch.object(ocf.eservice, "load_for_signing", return_value=None):
        resp = client.post("/officer-changes/K1/sign", headers=H)
    assert resp.status_code == 409 and "HO New" in resp.json()["detail"]["message"]
    env.cr.assert_not_called()


# -- submit ----------------------------------------------------------------------------

def test_submit_needs_confirm_and_a_signed_filing(env):
    assert client.post("/officer-changes/K1/submit", headers=H,
                       json={"confirm": False}).status_code == 400
    assert client.post("/officer-changes/K1/submit", headers=H,
                       json={"confirm": True}).status_code == 409


def test_a_write_back_failure_never_turns_a_filing_into_an_error(env):
    env.cr.side_effect = None
    env.filing = {"id": "F1", "stage": "signed"}
    with patch.object(ocf.signing, "submit", return_value={"receipt": {"caseNo": "9"}}), \
         patch.object(ocf.apply, "apply_changes", new_callable=AsyncMock,
                      return_value={"applied": [], "errors": ["HO New: timeout"]}), \
         patch.object(ocf.documents, "file_to_profiles", new_callable=AsyncMock,
                      return_value=[{"id": "D1", "error": "storage down"}]):
        resp = client.post("/officer-changes/K1/submit", headers=H, json={"confirm": True})
    assert resp.status_code == 200
    assert resp.json()["write_back"]["errors"] == ["HO New: timeout"]
    assert resp.json()["documents_filed"][0]["error"] == "storage down"
    assert _actions(env.audit) == ["TPSI_SUBMISSION_ATTEMPTED", "TPSI_SUBMISSION_SUCCESS",
                                   "OFFICER_CHANGES_APPLIED"]


def test_a_cr_refusal_on_submit_is_audited_as_failed(env):
    env.cr.side_effect = None
    env.filing = {"id": "F1", "stage": "signed"}
    with patch.object(ocf.signing, "submit", side_effect=TpsiError("refused")):
        resp = client.post("/officer-changes/K1/submit", headers=H, json={"confirm": True})
    assert resp.status_code >= 400
    assert _actions(env.audit) == ["TPSI_SUBMISSION_ATTEMPTED", "TPSI_SUBMISSION_FAILED"]


# -- the manual route: no CR call, ever (Review Focus 5) ---------------------------------

def test_the_manual_route_reaches_filed_without_a_cr_client(env):
    resp = client.post("/officer-changes/K1/mark-checked", headers=H)
    assert resp.status_code == 200
    assert env.update.call_args.args[1]["signing_method"] == "manual"
    env.case = {**CASE, "data_checked_at": "2026-10-01T00:00:00Z"}
    with patch.object(ocf.document_service, "upload_document", new_callable=AsyncMock,
                      return_value={"id": "DOC1", "current_version": 1}) as upload:
        assert client.post("/officer-changes/K1/signed-form", headers=H, files={
            "file": ("signed.pdf", b"%PDF", "application/pdf")}).status_code == 201
        assert upload.await_args.kwargs["document_type_code"] == "nd2a"
        assert upload.await_args.kwargs["owner_kind"] == "entity"
        assert client.post("/officer-changes/K1/receipt", headers=H, files={
            "file": ("receipt.pdf", b"%PDF", "application/pdf")}).status_code == 201
        assert upload.await_args.kwargs["owner_kind"] == "receipt"
    env.case = {**env.case, "manual_signed_document_id": "DOC1",
                "manual_receipt_document_id": "DOC2"}
    with patch.object(ocf.nar1_cases, "claim_manual_submission", return_value={"id": "K1"}) as claim, \
         patch.object(ocf.apply, "apply_changes", new_callable=AsyncMock,
                      return_value={"applied": [{"entry_id": "N1"}], "errors": []}), \
         patch.object(ocf.documents, "file_to_profiles", new_callable=AsyncMock,
                      return_value=[]):
        resp = client.post("/officer-changes/K1/record-filing", headers=H, json={
            "receipt": {"caseNo": " 123456 ", "transactionDate": "2026-09-30",
                        "refNo": "ND2A-REF"}, "confirm": True})
    assert resp.status_code == 200, resp.text
    receipt = claim.call_args.args[1]["manual_receipt"]
    assert receipt == {"caseNo": "123456", "transactionDate": "30/09/2026",
                       "transactionTime": None, "refNo": "ND2A-REF", "totalAmount": "0.00"}
    env.cr.assert_not_called()
    assert "OFFICER_FILING_RECORDED" in _actions(env.audit)


def test_record_filing_refuses_a_future_date_and_a_second_record(env):
    env.case = {**CASE, "manual_signed_document_id": "D1", "manual_receipt_document_id": "D2"}
    body = {"receipt": {"caseNo": "1", "transactionDate": "01/01/2099"}, "confirm": True}
    assert client.post("/officer-changes/K1/record-filing", headers=H,
                       json=body).status_code == 400
    body["receipt"]["transactionDate"] = "01/09/2026"
    with patch.object(ocf.nar1_cases, "claim_manual_submission", return_value=None):
        resp = client.post("/officer-changes/K1/record-filing", headers=H, json=body)
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "already_filed"


def test_record_filing_needs_the_signed_form_and_the_receipt(env):
    body = {"receipt": {"caseNo": "1", "transactionDate": "01/09/2026"}, "confirm": True}
    assert client.post("/officer-changes/K1/record-filing", headers=H,
                       json=body).json()["detail"]["reason"] == "not_signed"
    env.case = {**CASE, "manual_signed_document_id": "D1"}
    assert client.post("/officer-changes/K1/record-filing", headers=H,
                       json=body).json()["detail"]["reason"] == "no_receipt"


def test_signed_form_needs_mark_checked_first_and_a_pdf(env):
    resp = client.post("/officer-changes/K1/signed-form", headers=H,
                       files={"file": ("x.pdf", b"%PDF", "application/pdf")})
    assert resp.json()["detail"]["reason"] == "not_checked"
    env.case = {**CASE, "data_checked_at": "2026-10-01T00:00:00Z"}
    resp = client.post("/officer-changes/K1/signed-form", headers=H,
                       files={"file": ("x.docx", b"PK", "application/msword")})
    assert resp.status_code == 400


# -- undo -------------------------------------------------------------------------------

def test_undo_only_after_a_cr_rejection(env):
    assert client.post("/officer-changes/K1/undo", headers=H,
                       json={"confirm": True}).json()["detail"]["reason"] == "not_rejected"
    env.case = {**CASE, "cr_doc_status_code": "cr_rejected",
                "changes_applied_at": "2026-10-01T00:00:00Z"}
    applied = {"id": "K1", "entries": [{"id": "N1", "kind": "cessation",
                                        "applied": {"officer": {"id": "O1", "before": {}}}}]}
    with patch.object(ocf.svc, "composite", new_callable=AsyncMock, return_value=applied), \
         patch.object(ocf.apply, "undo_changes", new_callable=AsyncMock,
                      return_value={"applied": [{"entry_id": "N1"}], "errors": []}):
        resp = client.post("/officer-changes/K1/undo", headers=H, json={"confirm": True})
    assert resp.status_code == 200
    assert _actions(env.audit) == ["OFFICER_CHANGES_UNDONE"]


def test_undo_reaches_a_write_back_that_stopped_part_way(env):
    # changes_applied_at is set only when EVERY entry applied; an ND2A whose
    # appointment failed after its cessation applied must still be undoable.
    env.case = {**CASE, "cr_doc_status_code": "cr_rejected", "changes_applied_at": None}
    partial = {"id": "K1", "entries": [
        {"id": "N1", "kind": "cessation", "applied": {"officer": {"id": "O1", "before": {}}}},
        {"id": "N2", "kind": "appointment", "applied": None}]}
    with patch.object(ocf.svc, "composite", new_callable=AsyncMock, return_value=partial), \
         patch.object(ocf.apply, "undo_changes", new_callable=AsyncMock,
                      return_value={"applied": [{"entry_id": "N1"}], "errors": []}) as undo:
        resp = client.post("/officer-changes/K1/undo", headers=H, json={"confirm": True})
    assert resp.status_code == 200 and undo.await_count == 1


def test_undo_with_nothing_applied_is_refused(env):
    env.case = {**CASE, "cr_doc_status_code": "cr_rejected"}
    resp = client.post("/officer-changes/K1/undo", headers=H, json={"confirm": True})
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "nothing_to_undo"


# -- retrying an unfinished profile update -------------------------------------------------

def test_retry_completes_an_unfinished_write_back_of_a_filed_form(env):
    env.case = {**CASE, "manual_receipt": {"caseNo": "1"}, "changes_applied_at": None}
    with patch.object(ocf.apply, "apply_changes", new_callable=AsyncMock,
                      return_value={"applied": [{"entry_id": "N2"}], "errors": []}) as apply, \
         patch.object(ocf.documents, "file_to_profiles", new_callable=AsyncMock, return_value=[]):
        resp = client.post("/officer-changes/K1/apply", headers=H, json={"confirm": True})
    assert resp.status_code == 200 and resp.json()["write_back"]["errors"] == []
    apply.assert_awaited_once()
    assert _actions(env.audit) == ["OFFICER_CHANGES_APPLIED"]


@pytest.mark.parametrize("case, reason", [
    ({}, "not_filed"),
    ({"manual_receipt": {"caseNo": "1"}, "changes_applied_at": "2026-10-01"}, "already_applied"),
    ({"manual_receipt": {"caseNo": "1"}, "changes_undone_at": "2026-10-02"}, "undone"),
])
def test_retry_is_refused_unless_filed_and_unfinished(env, case, reason):
    env.case = {**CASE, **case}
    resp = client.post("/officer-changes/K1/apply", headers=H, json={"confirm": True})
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == reason


def test_a_failed_re_read_after_filing_still_answers_200(env):
    env.cr.side_effect = None
    env.filing = {"id": "F1", "stage": "signed"}
    with patch.object(ocf.signing, "submit", return_value={"receipt": {"caseNo": "9"}}), \
         patch.object(ocf.apply, "apply_changes", new_callable=AsyncMock,
                      return_value={"applied": [], "errors": []}), \
         patch.object(ocf.documents, "file_to_profiles", new_callable=AsyncMock, return_value=[]), \
         patch.object(ocf, "respond", new_callable=AsyncMock, side_effect=RuntimeError("db")):
        resp = client.post("/officer-changes/K1/submit", headers=H, json={"confirm": True})
    assert resp.status_code == 200 and resp.json()["filed"] is True


# -- the e-filing / manual conflict ---------------------------------------------------------

def test_record_filing_is_refused_when_cr_already_holds_the_e_filing(env):
    env.case = {**CASE, "manual_signed_document_id": "D1", "manual_receipt_document_id": "D2"}
    env.filing = {"id": "F1", "stage": "submitted"}
    body = {"receipt": {"caseNo": "1", "transactionDate": "01/09/2026"}, "confirm": True}
    with patch.object(ocf.nar1_cases, "claim_manual_submission") as claim:
        resp = client.post("/officer-changes/K1/record-filing", headers=H, json=body)
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "efiling_conflict"
    claim.assert_not_called()


def test_a_recorded_receipt_cannot_be_replaced(env):
    env.case = {**CASE, "manual_receipt": {"caseNo": "1"}}
    resp = client.post("/officer-changes/K1/receipt", headers=H,
                       files={"file": ("r.pdf", b"%PDF", "application/pdf")})
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "already_filed"


# -- deferred effective dates (Jacqueline A1) ---------------------------------------

MISSING = ["HO New"]


def test_record_filing_refuses_while_a_date_is_missing(env):
    env.case = {**CASE, "manual_signed_document_id": "D1", "manual_receipt_document_id": "R1"}
    with patch.object(ocf.svc, "dates_missing_for", return_value=MISSING):
        resp = client.post("/officer-changes/K1/record-filing", headers=H, json={
            "receipt": {"caseNo": "1", "transactionDate": "01/10/2026"}, "confirm": True})
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason"] == "dates_missing"
    assert "HO New" in resp.json()["detail"]["message"]


def test_signed_form_upload_refuses_while_a_date_is_missing(env):
    env.case = {**CASE, "data_checked_at": "2026-10-01T00:00:00Z"}
    with patch.object(ocf.svc, "dates_missing_for", return_value=MISSING):
        resp = client.post("/officer-changes/K1/signed-form", headers=H,
                           files={"file": ("signed.pdf", b"%PDF-1", "application/pdf")})
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "dates_missing"


def test_validate_refuses_while_a_date_is_missing(env):
    with patch.object(ocf.svc, "dates_missing_for", return_value=MISSING), \
         patch.object(ocf.prepare, "consent_plan", new_callable=AsyncMock, return_value=[]):
        resp = client.post("/officer-changes/K1/validate", headers=H)
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "dates_missing"
    env.cr.assert_not_called()


def test_mark_checked_esign_keeps_the_route(env):
    """With a deferred date, e-Sign leaves Data Verification without CR (the
    dates are entered and CR validates at Signing — spec §2.1)."""
    with patch.object(ocf.prepare, "consent_plan", new_callable=AsyncMock, return_value=[]):
        resp = client.post("/officer-changes/K1/mark-checked", headers=H,
                           json={"signing_method": "esign"})
    assert resp.status_code == 200, resp.text
    patch_ = env.update.call_args.args[1]
    assert patch_["signing_method"] == "esign" and patch_["data_checked_at"]
    env.cr.assert_not_called()


def test_mark_checked_esign_needs_every_consent_ready(env):
    plan = [{"ready": False, "reason": "HO New has no e-Registry account stored"}]
    with patch.object(ocf.prepare, "consent_plan", new_callable=AsyncMock, return_value=plan):
        resp = client.post("/officer-changes/K1/mark-checked", headers=H,
                           json={"signing_method": "esign"})
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "esign_unavailable"


def test_mark_checked_defaults_to_the_manual_route(env):
    resp = client.post("/officer-changes/K1/mark-checked", headers=H)
    assert resp.status_code == 200
    assert env.update.call_args.args[1]["signing_method"] == "manual"

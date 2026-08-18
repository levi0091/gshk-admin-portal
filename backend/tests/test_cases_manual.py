"""BE-6 — the manual (wet-signature, off-portal) path.

The invariant under test throughout: this path NEVER calls CR. If any test here
can be made to pass while a TPSI client is constructed, the feature is wrong.

Second invariant, D-6: a manual receipt is not a CR fact, so it lands on
`nar1_cases.manual_receipt` and never on `tpsi_filings`. `composite()` merges
the two into one `receipt` key so the Confirmation screen does not care which
path produced it.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from services import nar1_cases
from services.tpsi import filings as tpsi_filings

SUPER = {"id": "u1", "display_name": "Levi", "role_name": "super_admin", "role_id": "role-sa"}
REGULAR = {"id": "u2", "display_name": "Staff", "role_name": "staff", "role_id": "role-x"}
H = {"Authorization": "Bearer tok"}


def _super():
    return patch("middleware.auth._resolve_user", return_value=SUPER)


def _no_filing():
    """No TPSI filing behind this case — the pure off-portal case.

    Patched explicitly in every router test: both endpoints consult the filing
    ledger before touching anything, and an unpatched read would go to the real
    Supabase client.
    """
    return patch("routers.cases.nar1_cases.blocking_filing", return_value=None)


@pytest.fixture
def client():
    return TestClient(app)


def full_receipt(**over):
    receipt = {
        "caseNo": "180256934", "brNo": "00000001", "accNo": "N00061980009",
        "chiCoyName": "測試有限公司", "engCoyName": "TEST COMPANY LIMITED",
        "docCodesWithBarcode": "NAR1", "pymtNo": "P001", "pymtRefNo": "R001",
        "transactionDate": "2026-08-16", "transactionTime": "10:30:00",
        "pymtMtd": "DEPOSIT", "totalAmount": "105.00",
        "paymentRcptList": [
            {"rcptNo": "RC1", "revCode": "AR", "docShtFrm": "NAR1",
             "revDesc": "Annual return", "amtChrg": "105.00"},
        ],
    }
    receipt.update(over)
    return receipt


# ---- receipt validation ----------------------------------------------------

def test_a_complete_receipt_has_no_problems():
    assert nar1_cases.validate_receipt(full_receipt()) == []


@pytest.mark.parametrize("missing", [
    "caseNo", "brNo", "accNo", "engCoyName", "pymtNo", "pymtRefNo",
    "transactionDate", "transactionTime", "pymtMtd", "totalAmount",
])
def test_every_required_receipt_field_is_checked(missing):
    """A half-entered receipt is worse than none: it looks like proof of filing
    and cannot be reconciled against CR."""
    receipt = full_receipt()
    receipt.pop(missing)
    assert any(missing in p for p in nar1_cases.validate_receipt(receipt))


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_a_field_present_but_blank_is_still_missing(blank):
    """A UI that posts every key with an empty string must not read as complete."""
    assert nar1_cases.validate_receipt(full_receipt(caseNo=blank)) != []


def test_the_optional_fields_really_are_optional():
    """A company with no Chinese name genuinely has none, and neither the
    barcode string nor refNo appears on the paper receipt."""
    receipt = full_receipt()
    for optional in ("chiCoyName", "docCodesWithBarcode"):
        receipt.pop(optional)
    assert nar1_cases.validate_receipt(receipt) == []


def test_a_receipt_needs_at_least_one_payment_line():
    assert nar1_cases.validate_receipt(full_receipt(paymentRcptList=[])) != []


def test_a_payment_line_must_be_complete_too():
    receipt = full_receipt(paymentRcptList=[{"rcptNo": "RC1"}])
    assert nar1_cases.validate_receipt(receipt) != []


def test_every_problem_is_reported_at_once():
    """The user is copying off a paper receipt and should not discover the
    fields one round trip at a time."""
    problems = nar1_cases.validate_receipt({"caseNo": "1"})
    assert len(problems) >= len(nar1_cases.RECEIPT_REQUIRED)


def test_a_key_that_is_not_a_receipt_field_is_a_problem_not_a_silent_drop():
    """manual_receipt is a statutory record rendered by the same template as
    CR's own. Accepting arbitrary JSON into it would store something the
    Confirmation screen cannot render and the audit trail cannot be trusted to
    have scrubbed."""
    problems = nar1_cases.validate_receipt(full_receipt(password="hunter2"))
    assert any("password" in p for p in problems)


def test_a_stray_key_inside_a_payment_line_is_a_problem_too():
    line = {"rcptNo": "RC1", "revCode": "AR", "docShtFrm": "NAR1",
            "amtChrg": "105.00", "token": "abc"}
    problems = nar1_cases.validate_receipt(full_receipt(paymentRcptList=[line]))
    assert any("token" in p for p in problems)


def test_the_manual_receipt_shape_matches_the_e_signed_one():
    """Spec §5 BE-6: Confirmation renders the same either way, so the two
    shapes cannot be allowed to drift apart."""
    assert set(nar1_cases.RECEIPT_REQUIRED) <= set(tpsi_filings.RECEIPT_FIELDS)
    assert set(nar1_cases.RECEIPT_LINE_REQUIRED) <= set(tpsi_filings.RECEIPT_LINE_FIELDS)
    assert nar1_cases.RECEIPT_ALLOWED == set(tpsi_filings.RECEIPT_FIELDS) | {"paymentRcptList"}
    assert nar1_cases.RECEIPT_LINE_ALLOWED == set(tpsi_filings.RECEIPT_LINE_FIELDS)


def test_a_receipt_cr_itself_produced_validates():
    """The strongest shape check available without CR: run a receipt built by
    the e-Sign path's own parser through the manual path's validator."""
    receipt = {f: "x" for f in tpsi_filings.RECEIPT_FIELDS}
    receipt["paymentRcptList"] = [{f: "x" for f in tpsi_filings.RECEIPT_LINE_FIELDS}]
    assert nar1_cases.validate_receipt(receipt) == []


# ---- which filings may go down the manual path -----------------------------

def _filing_table(*, filed: list, current: list) -> MagicMock:
    """A tpsi_filings double answering blocking_filing's TWO different queries.

    `filed`   -> select().eq().in_().limit()          (any attempt CR holds)
    `current` -> select().eq().neq().order().limit()  (the live attempt)
    A single fixed return_value cannot tell them apart and would hand one
    query's answer to the other.
    """
    table = MagicMock()
    select = table.select.return_value.eq.return_value
    select.in_.return_value.limit.return_value.execute.return_value.data = filed
    (select.neq.return_value.order.return_value.limit.return_value
     .execute.return_value.data) = current
    return table


def test_a_submitted_filing_hidden_behind_a_newer_draft_still_blocks():
    """The gate current_filing() could not close. Nothing marks the old attempt
    superseded today, so POST /tpsi/filings/prepare on an already-submitted case
    opens a fresh draft that sorts first — and current_filing() would report the
    case as unfiled, letting the same return be recorded as filed twice.
    """
    submitted = {"id": "f1", "stage": tpsi_filings.STAGE_SUBMITTED}
    newer_draft = {"id": "f2", "stage": tpsi_filings.STAGE_DRAFT}
    table = _filing_table(filed=[submitted], current=[newer_draft])

    with patch("services.nar1_cases.get_supabase",
               return_value=MagicMock(table=MagicMock(return_value=table))):
        blocking = nar1_cases.blocking_filing("c1")

    assert blocking["id"] == "f1"
    assert nar1_cases.manual_conflict(blocking, step="submit") is not None


def test_with_nothing_filed_the_gate_falls_back_to_the_live_attempt():
    """Otherwise the 'signed' guard would never see the armed e-Sign chain."""
    signed = {"id": "f1", "stage": tpsi_filings.STAGE_SIGNED}
    table = _filing_table(filed=[], current=[signed])

    with patch("services.nar1_cases.get_supabase",
               return_value=MagicMock(table=MagicMock(return_value=table))):
        blocking = nar1_cases.blocking_filing("c1")

    assert blocking["id"] == "f1"
    assert nar1_cases.manual_conflict(blocking, step="submit") is not None
    assert nar1_cases.manual_conflict(blocking, step="sign") is None


@pytest.mark.parametrize("stage", [
    tpsi_filings.STAGE_SUBMITTED,
    tpsi_filings.STAGE_REGISTERED,
    tpsi_filings.STAGE_EDRIVE,
])
@pytest.mark.parametrize("step", ["sign", "submit"])
def test_a_return_already_lodged_at_cr_can_never_go_manual(stage, step):
    """Two filings for one return is a false statutory record, and nothing
    downstream can tell which one CR actually holds."""
    assert nar1_cases.manual_conflict({"stage": stage}, step=step) is not None


def test_a_signed_filing_blocks_the_manual_submit_but_not_the_upload():
    """`signed` is the loaded gun: filings._check_gate PASSES on a signed row,
    so a case completed on paper while a signed filing sits live is one
    chargeable call away from filing the same return twice. Uploading the
    wet-signed scan is harmless preparation, so only the submit is refused."""
    signed = {"stage": tpsi_filings.STAGE_SIGNED}
    assert nar1_cases.manual_conflict(signed, step="submit") is not None
    assert nar1_cases.manual_conflict(signed, step="sign") is None


@pytest.mark.parametrize("stage", [
    None,
    tpsi_filings.STAGE_DRAFT,
    tpsi_filings.STAGE_VALIDATED,
    tpsi_filings.STAGE_VALIDATION_FAILED,
    tpsi_filings.STAGE_SIGNING_FAILED,
    tpsi_filings.STAGE_SUBMISSION_FAILED,
])
@pytest.mark.parametrize("step", ["sign", "submit"])
def test_every_unfiled_stage_may_fall_back_to_paper(stage, step):
    """signing_failed and submission_failed are the canonical reasons to file on
    paper — refusing them would strand exactly the cases this path exists for."""
    filing = None if stage is None else {"stage": stage}
    assert nar1_cases.manual_conflict(filing, step=step) is None


# ---- manual sign -----------------------------------------------------------

def test_manual_sign_stores_the_document_and_audits(client):
    logged = {}

    async def fake_log(**kwargs):
        logged.update(kwargs)

    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "entity_id": "e1", "case_no": "NAR-2026-0041"}), \
         patch("routers.cases.document_service.upload_document",
               new=AsyncMock(return_value={"id": "d1"})) as upload, \
         patch("routers.cases.nar1_cases.update_case", return_value={"id": "c1"}) as spy, \
         patch("routers.cases.log_event", side_effect=fake_log):
        response = client.post(
            "/cases/c1/manual-sign", headers=H,
            files={"file": ("signed.pdf", b"%PDF-1.4 signed", "application/pdf")},
        )
    assert response.status_code == 201
    assert response.json() == {"document_id": "d1"}
    assert spy.call_args.args[1]["manual_signed_document_id"] == "d1"
    # The upload is what makes this case a manual one; leaving signing_method
    # unset would keep the case looking like an e-Sign case in every listing.
    assert spy.call_args.args[1]["signing_method"] == "manual"
    assert logged["action_type"] == "NAR1_MANUAL_SIGN_UPLOADED"
    assert logged["case_id"] == "c1"
    # Filed against the COMPANY, not the case: documents are owned by entities.
    assert upload.await_args.kwargs["owner_id"] == "e1"
    assert upload.await_args.kwargs["content"] == b"%PDF-1.4 signed"


def test_manual_sign_requires_documents_write(client):
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth._permissions_for", return_value=set()):
        response = client.post(
            "/cases/c1/manual-sign", headers=H,
            files={"file": ("signed.pdf", b"%PDF", "application/pdf")},
        )
    assert response.status_code == 403


def test_manual_sign_404s_on_an_unknown_case(client):
    with _super(), \
         patch("routers.cases.nar1_cases.get_case",
               side_effect=LookupError("no NAR1 case c9")):
        response = client.post(
            "/cases/c9/manual-sign", headers=H,
            files={"file": ("signed.pdf", b"%PDF", "application/pdf")},
        )
    assert response.status_code == 404


def test_manual_sign_refuses_an_empty_file(client):
    """A zero-byte upload would store a document that proves nothing and satisfy
    the manual-submit gate."""
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "entity_id": "e1"}), \
         patch("routers.cases.document_service.upload_document",
               new=AsyncMock()) as upload:
        response = client.post(
            "/cases/c1/manual-sign", headers=H,
            files={"file": ("signed.pdf", b"", "application/pdf")},
        )
    assert response.status_code == 400
    upload.assert_not_awaited()


def test_manual_sign_refuses_a_case_already_filed_at_cr(client):
    with _super(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "entity_id": "e1"}), \
         patch("routers.cases.nar1_cases.blocking_filing",
               return_value={"stage": tpsi_filings.STAGE_SUBMITTED}), \
         patch("routers.cases.document_service.upload_document",
               new=AsyncMock()) as upload:
        response = client.post(
            "/cases/c1/manual-sign", headers=H,
            files={"file": ("signed.pdf", b"%PDF", "application/pdf")},
        )
    assert response.status_code == 409
    upload.assert_not_awaited()


def test_manual_sign_refuses_a_case_whose_submission_is_already_recorded(client):
    """The signed form behind a completed case is fixed. A corrected scan goes
    through the ordinary document upload, which versions it."""
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "entity_id": "e1",
                             "manual_receipt": full_receipt()}), \
         patch("routers.cases.document_service.upload_document",
               new=AsyncMock()) as upload:
        response = client.post(
            "/cases/c1/manual-sign", headers=H,
            files={"file": ("signed.pdf", b"%PDF", "application/pdf")},
        )
    assert response.status_code == 409
    upload.assert_not_awaited()


# ---- manual submit ---------------------------------------------------------

def test_manual_submit_records_the_receipt_and_completes_the_case(client):
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "manual_signed_document_id": "d1"}), \
         patch("routers.cases.nar1_cases.update_case", return_value={"id": "c1"}) as spy, \
         patch("routers.cases.nar1_cases.composite",
               return_value={"id": "c1", "workflow_status": {"code": "completed"}}), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post("/cases/c1/manual-submit", headers=H,
                               json={"receipt": full_receipt()})
    assert response.status_code == 200
    assert response.json()["workflow_status"]["code"] == "completed"
    written = spy.call_args.args[1]
    assert written["manual_receipt"]["caseNo"] == "180256934"
    assert written["manual_submitted_at"] is not None
    # One clock reading for both columns: two calls to _now() would stamp two
    # different instants on one event.
    assert written["submitted_at"] == written["manual_submitted_at"]
    assert written["submitted_by"] == "u1"
    assert written["signing_method"] == "manual"


def test_manual_submit_writes_nothing_to_the_filing_ledger(client):
    """D-6: tpsi_filings owns CR-side facts only. A receipt for a filing CR
    never saw is not a CR fact."""
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "manual_signed_document_id": "d1"}), \
         patch("routers.cases.nar1_cases.update_case", return_value={"id": "c1"}), \
         patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", new=AsyncMock()), \
         patch("services.tpsi.filings._update") as filing_write, \
         patch("services.tpsi.filings._insert") as filing_insert:
        client.post("/cases/c1/manual-submit", headers=H,
                    json={"receipt": full_receipt()})
    filing_write.assert_not_called()
    filing_insert.assert_not_called()


def test_manual_submit_never_calls_cr(client):
    """The whole point of the manual path. A CR call here would charge the
    deposit account for a filing already made on paper."""
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "manual_signed_document_id": "d1"}), \
         patch("routers.cases.nar1_cases.update_case", return_value={"id": "c1"}), \
         patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", new=AsyncMock()), \
         patch("services.tpsi.client.TpsiClient") as cr, \
         patch("services.tpsi.filings.submit") as cr_submit:
        response = client.post("/cases/c1/manual-submit", headers=H,
                               json={"receipt": full_receipt()})
    assert response.status_code == 200
    cr.assert_not_called()
    cr_submit.assert_not_called()


def test_manual_submit_rejects_an_incomplete_receipt_with_every_problem(client):
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "manual_signed_document_id": "d1"}), \
         patch("routers.cases.nar1_cases.update_case") as spy:
        response = client.post("/cases/c1/manual-submit", headers=H,
                               json={"receipt": {"caseNo": "1"}})
    assert response.status_code == 400
    assert len(response.json()["detail"]["problems"]) > 1
    spy.assert_not_called()


def test_manual_submit_requires_the_signed_form_first(client):
    """Recording a submission for a form nobody signed puts a false completion
    in the register."""
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "manual_signed_document_id": None}), \
         patch("routers.cases.nar1_cases.update_case") as spy:
        response = client.post("/cases/c1/manual-submit", headers=H,
                               json={"receipt": full_receipt()})
    assert response.status_code == 409
    spy.assert_not_called()


def test_manual_submit_is_gated_on_tpsi_submit_not_nar1_write(client):
    """Recording a filing stays privileged even when no money moves through us:
    it is the act that declares the return filed."""
    seen = []
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth._permissions_for",
               side_effect=lambda u, m: seen.append(m) or set()):
        response = client.post("/cases/c1/manual-submit", headers=H,
                               json={"receipt": full_receipt()})
    assert response.status_code == 403
    assert "tpsi" in seen
    assert "nar1" not in seen


def test_manual_submit_needs_submit_not_merely_write_on_tpsi(client):
    """A role holding tpsi:write can prepare and validate. Declaring the return
    filed is the separate, privileged act."""
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth._permissions_for", return_value={"read", "write"}):
        response = client.post("/cases/c1/manual-submit", headers=H,
                               json={"receipt": full_receipt()})
    assert response.status_code == 403


def test_manual_submit_is_idempotent_on_a_completed_case(client):
    """A double-clicked "Verify receipt" must not write a second completion."""
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "manual_signed_document_id": "d1",
                             "manual_receipt": full_receipt()}), \
         patch("routers.cases.nar1_cases.update_case") as spy:
        response = client.post("/cases/c1/manual-submit", headers=H,
                               json={"receipt": full_receipt()})
    assert response.status_code == 409
    spy.assert_not_called()


@pytest.mark.parametrize("stage", [
    tpsi_filings.STAGE_SIGNED,
    tpsi_filings.STAGE_SUBMITTED,
    tpsi_filings.STAGE_REGISTERED,
])
def test_manual_submit_refuses_while_the_e_sign_path_is_live_or_done(client, stage):
    with _super(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "manual_signed_document_id": "d1"}), \
         patch("routers.cases.nar1_cases.blocking_filing",
               return_value={"stage": stage}), \
         patch("routers.cases.nar1_cases.update_case") as spy:
        response = client.post("/cases/c1/manual-submit", headers=H,
                               json={"receipt": full_receipt()})
    assert response.status_code == 409
    spy.assert_not_called()


def test_manual_submit_404s_on_an_unknown_case(client):
    with _super(), \
         patch("routers.cases.nar1_cases.get_case",
               side_effect=LookupError("no NAR1 case c9")):
        response = client.post("/cases/c9/manual-submit", headers=H,
                               json={"receipt": full_receipt()})
    assert response.status_code == 404


def test_manual_submit_audits_the_receipt_and_the_completion(client):
    calls = []

    async def fake_log(**kwargs):
        calls.append(kwargs)

    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "manual_signed_document_id": "d1"}), \
         patch("routers.cases.nar1_cases.update_case", return_value={"id": "c1"}), \
         patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", side_effect=fake_log):
        client.post("/cases/c1/manual-submit", headers=H,
                    json={"receipt": full_receipt()})

    types = [c["action_type"] for c in calls]
    assert types == ["NAR1_MANUAL_RECEIPT_ENTERED", "NAR1_MANUAL_SUBMISSION_RECORDED"]
    # The receipt is the only evidence the return was filed — the trail carries
    # it whole, not a summary of it.
    assert calls[0]["after_state"]["manual_receipt"]["caseNo"] == "180256934"
    assert calls[1]["new_value"] == "Completed"
    assert calls[1]["metadata"]["cr_called"] is False
    assert all(c["event_code"] == c["action_type"] for c in calls)


def test_the_manual_audit_codes_are_the_ones_migration_021_seeded():
    """Migration 021 already seeds these three into audit_event_types. A
    constant that does not match a seeded code leaves action_label unset and
    the audit UI shows no action name."""
    import re
    from pathlib import Path

    from services import audit_events as ev

    text = (Path(__file__).resolve().parents[1]
            / "alembic" / "versions" / "021_nar1_case_workflow.py").read_text()
    seeded = set(re.findall(r'\("(NAR1_MANUAL_[A-Z_]+)"', text))
    assert {ev.NAR1_MANUAL_SIGN_UPLOADED,
            ev.NAR1_MANUAL_SUBMISSION_RECORDED,
            ev.NAR1_MANUAL_RECEIPT_ENTERED} <= seeded


def test_manual_endpoints_require_authentication(client):
    """No identity patch: the real dependency runs against a Supabase double
    that recognises nobody."""
    sb = MagicMock()
    sb.auth.get_user.return_value = MagicMock(user=None)
    with patch("middleware.auth.get_supabase", return_value=sb):
        assert client.post("/cases/c1/manual-submit", headers=H,
                           json={"receipt": full_receipt()}).status_code in (401, 403)
        assert client.post(
            "/cases/c1/manual-sign", headers=H,
            files={"file": ("s.pdf", b"%PDF", "application/pdf")},
        ).status_code in (401, 403)


# ---- the real thing, mocked only at the Supabase boundary ------------------

def test_a_manual_submit_really_drives_the_case_to_completed(client):
    """The one test here that mocks nothing between the route and the database.

    Everything above patches nar1_cases wholesale, which proves the router calls
    it but nothing about what it does. This drives the REAL validate_receipt,
    update_case, blocking_filing, composite and nar1_case_status.derive against a
    Supabase double, so it would catch a manual receipt written to the wrong
    column or a badge that never reaches Completed.
    """
    stored: dict = {"id": "c1", "manual_signed_document_id": "d1",
                    "manual_receipt": None, "client_approved": None}

    case_table = MagicMock()
    case_table.select.return_value.eq.return_value.execute.return_value.data = [stored]

    def _apply_update(patch_dict):
        stored.update(patch_dict)
        chain = MagicMock()
        chain.eq.return_value.execute.return_value.data = [stored]
        return chain

    case_table.update.side_effect = _apply_update

    filing_table = _filing_table(filed=[], current=[])

    sb = MagicMock()
    sb.table.side_effect = lambda name: case_table if name == "nar1_cases" else filing_table

    with _super(), \
         patch("services.nar1_cases.get_supabase", return_value=sb), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post("/cases/c1/manual-submit", headers=H,
                               json={"receipt": full_receipt()})

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_status"]["code"] == "completed"
    assert body["workflow_status"]["label"] == "Completed"
    assert body["workflow_status"]["overdue"] is False
    # The unified receipt (D-6): one key, whichever path produced it.
    assert body["receipt"]["caseNo"] == "180256934"
    assert body["form_status"] is None
    # ...and it went to the case, not the filing ledger.
    assert stored["manual_receipt"]["caseNo"] == "180256934"
    filing_table.update.assert_not_called()
    filing_table.insert.assert_not_called()


def test_the_router_really_calls_the_validator_not_a_copy_of_it(client):
    """If the route ever grows its own inline check, this fails: the 400 must
    come from nar1_cases.validate_receipt itself."""
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "manual_signed_document_id": "d1"}), \
         patch("routers.cases.nar1_cases.validate_receipt",
               return_value=["sentinel: injected by the test"]):
        response = client.post("/cases/c1/manual-submit", headers=H,
                               json={"receipt": full_receipt()})
    assert response.status_code == 400
    assert response.json()["detail"]["problems"] == ["sentinel: injected by the test"]


def test_an_audit_failure_does_not_undo_a_recorded_submission():
    """The REAL log_event against a broken database — the router does not wrap
    it, so this is the only thing standing between a dead audit table and a 500
    that tells the user their off-portal submission was not saved when it was.

    Deliberately not a mock of log_event: mocking it would test the mock's
    swallow, not audit_service's.
    """
    from services import audit_service

    saved_labels = audit_service._LABELS
    audit_service._LABELS = {}  # skip the registry lookup, not what is under test

    broken = MagicMock(side_effect=RuntimeError("audit table unreachable"))
    try:
        with TestClient(app) as fresh, _super(), _no_filing(), \
             patch("routers.cases.nar1_cases.get_case",
                   return_value={"id": "c1", "manual_signed_document_id": "d1"}), \
             patch("routers.cases.nar1_cases.update_case", return_value={"id": "c1"}), \
             patch("routers.cases.nar1_cases.composite",
                   return_value={"id": "c1", "workflow_status": {"code": "completed"}}), \
             patch("services.audit_service.get_supabase", new=broken):
            response = fresh.post("/cases/c1/manual-submit", headers=H,
                                  json={"receipt": full_receipt()})
    finally:
        audit_service._LABELS = saved_labels

    assert response.status_code == 200
    assert broken.called  # the audit really was attempted, not skipped


def test_an_http_error_from_the_upload_is_not_swallowed(client):
    """document_service raises HTTPException(502) when Storage fails. The case
    must not be marked manually signed off the back of a failed upload."""
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value={"id": "c1", "entity_id": "e1"}), \
         patch("routers.cases.document_service.upload_document",
               new=AsyncMock(side_effect=HTTPException(502, "Storage upload failed"))), \
         patch("routers.cases.nar1_cases.update_case") as spy:
        response = client.post(
            "/cases/c1/manual-sign", headers=H,
            files={"file": ("signed.pdf", b"%PDF", "application/pdf")},
        )
    assert response.status_code == 502
    spy.assert_not_called()

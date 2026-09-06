"""Spec §4 — the CR filing receipt as a FILE, on the manual path only.

The invariant: an off-portal submission cannot be declared complete on typed
figures alone. Before this, `manual-submit` accepted a receipt somebody keyed
in and nothing proved CR had ever issued one. The typed fields stay — they are
what the audit trail and fee reconciliation read, and nothing here parses
values out of a scan — but they are no longer sufficient on their own.

Like the rest of the manual path: NO CR CALL anywhere in this file.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from tests.test_cases_manual import (H, REGULAR, SUPER, _no_filing, _super,
                                     full_receipt)


@pytest.fixture
def client():
    return TestClient(app)


def _case(**over):
    case = {"id": "c1", "entity_id": "e1", "case_no": "NAR-2026-0041"}
    case.update(over)
    return case


PDF = ("receipt.pdf", b"%PDF-1.4 cr receipt", "application/pdf")


# --------------------------------------------------------------------------- #
#  The upload
# --------------------------------------------------------------------------- #

def test_the_receipt_upload_stores_the_file_and_points_the_case_at_it(client):
    logged = {}

    async def fake_log(**kwargs):
        logged.update(kwargs)

    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case", return_value=_case()), \
         patch("routers.cases.document_service.upload_document",
               new=AsyncMock(return_value={"id": "r1", "current_version": 1,
                                           "file_name": "receipt.pdf"})) as upload, \
         patch("routers.cases.nar1_cases.update_case",
               return_value={"id": "c1"}) as spy, \
         patch("routers.cases.log_event", side_effect=fake_log):
        response = client.post("/cases/c1/manual-receipt", headers=H,
                               files={"file": PDF})

    assert response.status_code == 201
    assert response.json() == {"document_id": "r1", "document_version": 1,
                               "file_name": "receipt.pdf"}
    # The CASE owns it, not the company. upload_document versions in place on
    # (owner, type), so an entity-owned receipt would have the 2027 return
    # overwrite the row the 2026 case points at.
    assert upload.await_args.kwargs["owner_kind"] == "receipt"
    assert upload.await_args.kwargs["owner_id"] == "c1"
    assert upload.await_args.kwargs["document_type_code"] == "cr_receipt"
    assert upload.await_args.kwargs["content"] == b"%PDF-1.4 cr receipt"

    assert spy.call_args.args[1]["manual_receipt_document_id"] == "r1"
    assert spy.call_args.args[1]["manual_receipt_document_version"] == 1


def test_the_receipt_upload_does_not_flip_the_case_onto_the_manual_path(client):
    """`manual-sign` sets `signing_method`, because uploading a wet signature IS
    the choice of route. Uploading a receipt is not: it is evidence for a route
    already chosen, and writing the field here would let this endpoint move a
    case sideways without the signed form the manual path requires."""
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case", return_value=_case()), \
         patch("routers.cases.document_service.upload_document",
               new=AsyncMock(return_value={"id": "r1", "current_version": 1})), \
         patch("routers.cases.nar1_cases.update_case",
               return_value={"id": "c1"}) as spy, \
         patch("routers.cases.log_event", new=AsyncMock()):
        client.post("/cases/c1/manual-receipt", headers=H, files={"file": PDF})

    assert "signing_method" not in spy.call_args.args[1]


def test_a_row_with_no_current_version_counts_as_version_one(client):
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case", return_value=_case()), \
         patch("routers.cases.document_service.upload_document",
               new=AsyncMock(return_value={"id": "r1"})), \
         patch("routers.cases.nar1_cases.update_case",
               return_value={"id": "c1"}) as spy, \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post("/cases/c1/manual-receipt", headers=H,
                               files={"file": PDF})

    assert response.json()["document_version"] == 1
    assert spy.call_args.args[1]["manual_receipt_document_version"] == 1


def test_the_receipt_upload_audits_against_the_company_not_the_case(client):
    logged = {}

    async def fake_log(**kwargs):
        logged.update(kwargs)

    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case", return_value=_case()), \
         patch("routers.cases.document_service.upload_document",
               new=AsyncMock(return_value={"id": "r1", "current_version": 2})), \
         patch("routers.cases.nar1_cases.update_case", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", side_effect=fake_log):
        client.post("/cases/c1/manual-receipt", headers=H, files={"file": PDF})

    assert logged["action_type"] == "NAR1_MANUAL_RECEIPT_ENTERED"
    # audit_log.case_id holds the ENTITY id (routers/cases.py::_audit_target).
    assert logged["case_id"] == "e1"
    assert logged["entity_id"] == "c1"
    assert logged["entity_type"] == "nar1_case"
    # Two acts share this code — the scan and the figures typed off it. Without
    # `source` the trail shows two identical events for two different things.
    assert logged["metadata"]["source"] == "upload"
    assert logged["metadata"]["document_id"] == "r1"
    assert logged["metadata"]["version"] == 2


def test_the_typed_receipt_row_says_it_is_the_typed_one(client):
    """The other half of the pair above. If either row loses `source` the two
    become indistinguishable in the trail."""
    logged = []

    async def fake_log(**kwargs):
        logged.append(kwargs)

    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value=_case(manual_signed_document_id="d1",
                                  manual_receipt_document_id="r1")), \
         patch("routers.cases.nar1_cases.claim_manual_submission",
               return_value={"id": "c1"}), \
         patch("routers.cases.nar1_cases.composite",
               return_value={"id": "c1"}), \
         patch("routers.cases.log_event", side_effect=fake_log):
        response = client.post("/cases/c1/manual-submit", headers=H,
                               json={"receipt": full_receipt()})

    assert response.status_code == 200
    entered = [e for e in logged
               if e["action_type"] == "NAR1_MANUAL_RECEIPT_ENTERED"]
    assert len(entered) == 1
    assert entered[0]["metadata"].get("source") != "upload"


# --------------------------------------------------------------------------- #
#  What the upload refuses
# --------------------------------------------------------------------------- #

def test_the_receipt_upload_refuses_an_empty_file(client):
    """A zero-byte upload proves nothing and would still satisfy the gate."""
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case", return_value=_case()), \
         patch("routers.cases.document_service.upload_document",
               new=AsyncMock()) as upload:
        response = client.post(
            "/cases/c1/manual-receipt", headers=H,
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"]
    upload.assert_not_awaited()


@pytest.mark.parametrize("mime", [
    "application/pdf", "image/jpeg", "image/png", "image/tiff",
    # A browser sends the charset on some platforms; the parameter must not
    # turn an acceptable type into a refusal.
    "application/pdf; charset=binary",
    "APPLICATION/PDF",
])
def test_the_receipt_upload_accepts_pdfs_and_images(client, mime):
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case", return_value=_case()), \
         patch("routers.cases.document_service.upload_document",
               new=AsyncMock(return_value={"id": "r1", "current_version": 1})), \
         patch("routers.cases.nar1_cases.update_case", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post("/cases/c1/manual-receipt", headers=H,
                               files={"file": ("r", b"bytes", mime)})
    assert response.status_code == 201


@pytest.mark.parametrize("mime", [
    "application/zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/html",
    "application/octet-stream",
])
def test_the_receipt_upload_refuses_anything_that_is_not_a_pdf_or_an_image(
    client, mime
):
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case", return_value=_case()), \
         patch("routers.cases.document_service.upload_document",
               new=AsyncMock()) as upload:
        response = client.post("/cases/c1/manual-receipt", headers=H,
                               files={"file": ("r", b"bytes", mime)})
    assert response.status_code == 400
    assert "PDF or an image" in response.json()["detail"]
    upload.assert_not_awaited()


def test_the_receipt_upload_404s_on_an_unknown_case(client):
    with _super(), \
         patch("routers.cases.nar1_cases.get_case",
               side_effect=LookupError("no case c9")):
        response = client.post("/cases/c9/manual-receipt", headers=H,
                               files={"file": PDF})
    assert response.status_code == 404


def test_the_receipt_upload_refuses_a_case_already_recorded_as_submitted(client):
    """Once the submission is recorded its evidence is fixed. A later upload
    would version over the file the completed record points at."""
    with _super(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value=_case(manual_receipt=full_receipt())), \
         patch("routers.cases.document_service.upload_document",
               new=AsyncMock()) as upload:
        response = client.post("/cases/c1/manual-receipt", headers=H,
                               files={"file": PDF})
    assert response.status_code == 409
    assert "already recorded" in response.json()["detail"]
    upload.assert_not_awaited()


def test_the_receipt_upload_refuses_a_case_cr_already_holds(client):
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=_case()), \
         patch("routers.cases.nar1_cases.blocking_filing",
               return_value={"id": "f1", "stage": "submitted"}), \
         patch("routers.cases.document_service.upload_document",
               new=AsyncMock()) as upload:
        response = client.post("/cases/c1/manual-receipt", headers=H,
                               files={"file": PDF})
    assert response.status_code == 409
    upload.assert_not_awaited()


def test_the_receipt_upload_requires_tpsi_submit(client):
    """Matching manual-submit, not manual-sign. This file is half of the gate
    that lets a case be declared filed; a role that could not record the
    submission must not be able to satisfy its precondition either."""
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth._permissions_for",
               side_effect=lambda user, module:
                   {"read", "write"} if module in ("nar1", "documents") else set()):
        response = client.post("/cases/c1/manual-receipt", headers=H,
                               files={"file": PDF})
    assert response.status_code == 403


def test_the_receipt_upload_is_closed_to_an_unauthenticated_caller(client):
    """403, not 401: FastAPI's HTTPBearer refuses a missing credential itself,
    before `require_permission` runs. Asserted as "not 2xx and not 5xx" so the
    test says what matters — nobody without a token gets in — rather than
    pinning a status the framework owns."""
    response = client.post("/cases/c1/manual-receipt", files={"file": PDF})
    assert response.status_code in (401, 403)


# --------------------------------------------------------------------------- #
#  The gate on manual-submit
# --------------------------------------------------------------------------- #

def test_manual_submit_refuses_without_an_uploaded_receipt(client):
    events = []

    async def log(**kwargs):
        events.append(kwargs)

    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value=_case(manual_signed_document_id="d1",
                                  manual_receipt_document_id=None)), \
         patch("routers.cases.nar1_cases.claim_manual_submission") as claim, \
         patch("routers.cases.log_event", side_effect=log):
        response = client.post("/cases/c1/manual-submit", headers=H,
                               json={"receipt": full_receipt()})

    assert response.status_code == 409
    assert "CR filing receipt" in response.json()["detail"]
    # Nothing written, nothing logged: the case is not filed.
    claim.assert_not_called()
    assert events == []


def test_manual_submit_still_refuses_without_the_signed_form_first(client):
    """Gate order: most specific first, so the answer names the real obstacle.
    A case missing BOTH halves must be told about the signed form, which is the
    earlier step, rather than about the receipt."""
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value=_case(manual_signed_document_id=None,
                                  manual_receipt_document_id=None)), \
         patch("routers.cases.nar1_cases.claim_manual_submission") as claim:
        response = client.post("/cases/c1/manual-submit", headers=H,
                               json={"receipt": full_receipt()})

    assert response.status_code == 409
    assert "wet-signed NAR1" in response.json()["detail"]
    claim.assert_not_called()


def test_manual_submit_refuses_the_uploaded_receipt_without_typed_figures(client):
    """The two halves are independent. Nothing parses values out of the scan, so
    a file alone leaves the audit trail and fee reconciliation with nothing to
    read."""
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value=_case(manual_signed_document_id="d1",
                                  manual_receipt_document_id="r1")), \
         patch("routers.cases.nar1_cases.claim_manual_submission") as claim:
        response = client.post("/cases/c1/manual-submit", headers=H,
                               json={"receipt": {}})

    assert response.status_code == 400
    assert "incomplete" in response.json()["detail"]["message"]
    claim.assert_not_called()


def test_manual_submit_passes_with_both_halves(client):
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case",
               return_value=_case(manual_signed_document_id="d1",
                                  manual_receipt_document_id="r1")), \
         patch("routers.cases.nar1_cases.claim_manual_submission",
               return_value={"id": "c1"}) as claim, \
         patch("routers.cases.nar1_cases.composite",
               return_value={"id": "c1", "workflow_status": {"code": "completed"}}), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post("/cases/c1/manual-submit", headers=H,
                               json={"receipt": full_receipt()})

    assert response.status_code == 200
    claim.assert_called_once()


def test_the_receipt_upload_never_constructs_a_tpsi_client(client):
    """The invariant for this whole path: nothing here talks to CR."""
    with _super(), _no_filing(), \
         patch("routers.cases.nar1_cases.get_case", return_value=_case()), \
         patch("routers.cases.document_service.upload_document",
               new=AsyncMock(return_value={"id": "r1", "current_version": 1})), \
         patch("routers.cases.nar1_cases.update_case", return_value={"id": "c1"}), \
         patch("routers.cases.log_event", new=AsyncMock()), \
         patch("routers.tpsi.client_for",
               side_effect=AssertionError("the manual path must never call CR")):
        response = client.post("/cases/c1/manual-receipt", headers=H,
                               files={"file": PDF})
    assert response.status_code == 201


def test_super_admin_is_still_the_identity_the_other_tests_assume():
    """A guard on the shared fixture: these tests import SUPER from the BE-6
    suite, and a change there that silently dropped super_admin would make
    every permission assertion above pass for the wrong reason."""
    assert SUPER["role_name"] == "super_admin"

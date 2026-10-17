"""services/officer_changes/filed_form — the e-Sign route's signed ND2A / ND2B,
saved to the company's documents where the manual route's upload goes
(Levi 2026-10-18)."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services.officer_changes import filed_form

USER = {"id": "U1", "display_name": "Staff"}
CASE = {"id": "K1", "case_no": "ND2A-2026-0001", "entity_id": "E1", "form_code": "Nd2a"}
FILING = {"id": "F1", "stage": "submitted", "validated_xml": "<nd2a/>",
          "submitted_at": "2026-10-17T07:31:05+00:00"}
ENTITY = {"id": "E1", "company_name": "Kanenas Holding Limited", "company_name_zh": "卡內納斯"}


def _save(case=CASE, filing=FILING, render=b"%PDF-1", upload=None):
    upload = upload or AsyncMock(return_value={"id": "DOC9", "current_version": 3})
    with patch.object(filed_form.nar1_cases, "current_filing", return_value=filing), \
         patch.object(filed_form.nar1_cases, "entity_for", return_value=ENTITY), \
         patch.object(filed_form, "render_form",
                      **({"side_effect": render} if isinstance(render, Exception)
                         else {"return_value": render})) as rendered, \
         patch.object(filed_form.document_service, "upload_document", upload), \
         patch.object(filed_form.nar1_cases, "update_case") as update:
        out = asyncio.run(filed_form.save(case, USER))
    return out, rendered, upload, update


def test_it_stores_crs_copy_on_the_company_as_the_forms_own_type():
    out, rendered, upload, update = _save()
    assert out == {"document_id": "DOC9", "version": 3,
                   "file_name": "ND2A-ND2A-2026-0001-signed.pdf"}
    kwargs = upload.await_args.kwargs
    assert kwargs["owner_kind"] == "entity" and kwargs["owner_id"] == "E1"
    assert kwargs["document_type_code"] == "nd2a"
    assert kwargs["content"] == b"%PDF-1" and kwargs["mime_type"] == "application/pdf"
    assert kwargs["title"] == "ND2A-2026-0001 — signed ND2A (e-Sign)"
    # The (id, version) pair, as the manual route keeps its upload.
    update.assert_called_once_with("K1", {"filed_form_document_id": "DOC9",
                                          "filed_form_document_version": 3})


def test_it_renders_the_whole_form_crs_copy_dated_the_day_cr_received_it():
    _, rendered, _, _ = _save()
    assert rendered.call_args.args == ("Nd2a", "<nd2a/>")
    kwargs = rendered.call_args.kwargs
    assert kwargs["public_only"] is False
    assert kwargs["company_name"] == "Kanenas Holding Limited  卡內納斯"
    assert kwargs["submitted_on"] == FILING["submitted_at"]


def test_an_nd2b_is_filed_as_an_nd2b():
    out, _, upload, _ = _save(case={**CASE, "form_code": "Nd2b", "case_no": "ND2B-2026-0002"})
    assert upload.await_args.kwargs["document_type_code"] == "nd2b"
    assert out["file_name"] == "ND2B-ND2B-2026-0002-signed.pdf"


@pytest.mark.parametrize("over", [
    {"filing": None},
    {"filing": {**FILING, "validated_xml": None}},
    {"render": RuntimeError("font missing")},
    {"upload": AsyncMock(side_effect=RuntimeError("storage down"))},
])
def test_nothing_it_does_can_raise(over):
    out, _, _, update = _save(**over)
    assert set(out) == {"error"} and out["error"]
    update.assert_not_called()

from unittest.mock import MagicMock, patch

import pytest

from services.tpsi import errors, filings

VALIDATE_OK = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
 <soap:Body><cr:validateFormResponse
   xmlns:ds="http://www.w3.org/2000/09/xmldsig#"
   xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">
  <cr:submission>
   <cr:EForm id="eForm"><cr:formModel id="formData">
     <cr:formCode>NAR1</cr:formCode><cr:brNo>00011651</cr:brNo>
   </cr:formModel></cr:EForm>
   <cr:EFormSignatures><ds:Signature id="CR">
     <ds:SignatureValue>SIGVALUE123</ds:SignatureValue>
   </ds:Signature></cr:EFormSignatures>
  </cr:submission>
 </cr:validateFormResponse></soap:Body></soap:Envelope>"""

FAULT = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
 <soap:Body><soap:Fault><faultcode>soap:Server</faultcode>
 <faultstring>err</faultstring><detail>
 <cr:EfilingWebServiceError xmlns:cr="http://x/"><webServiceFaultBeans>
 <faultCode>ERR_MSG_REQUIRED</faultCode><faultString>brNo is required</faultString>
 </webServiceFaultBeans></cr:EfilingWebServiceError></detail>
 </soap:Fault></soap:Body></soap:Envelope>"""

EDRIVE_OK = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
 <soap:Body><cr:uploadToEdriveResponse
   xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">
   <cr:submission><cr:result>Form submitted to E drive successfully.</cr:result>
   </cr:submission></cr:uploadToEdriveResponse></soap:Body></soap:Envelope>"""


def _row(**over):
    row = {
        "id": "f1", "entity_id": "e1", "form_code": "Nar1",
        "stage": filings.STAGE_DRAFT, "request_xml": "<formCode>NAR1</formCode>",
        "validated_xml": None, "signed_xml": None,
        "presenter_user_id": "u1", "presentor_account_id": "ACCT",
    }
    row.update(over)
    return row


def test_validate_posts_the_right_operation_and_form_code():
    client = MagicMock()
    client.post_form.return_value = VALIDATE_OK
    with patch.object(filings, "get_filing", return_value=_row()), \
         patch.object(filings, "_update", return_value=None):
        filings.validate(client, "f1")
    assert client.post_form.call_args[0][0] == "validateForm"
    assert client.post_form.call_args[0][1] == "Nar1"


def test_validate_stores_the_cr_signed_payload_and_advances_stage():
    client = MagicMock()
    client.post_form.return_value = VALIDATE_OK
    saved = {}
    with patch.object(filings, "get_filing", return_value=_row()), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        filings.validate(client, "f1")
    assert saved["stage"] == filings.STAGE_VALIDATED
    assert "SIGVALUE123" in saved["validated_xml"]
    assert saved["validated_at"] is not None


def test_validated_payload_is_stored_verbatim():
    """Request and response share one namespace convention, so the payload is
    carried forward unchanged — CR's digest covers these exact bytes."""
    client = MagicMock()
    client.post_form.return_value = VALIDATE_OK
    saved = {}
    with patch.object(filings, "get_filing", return_value=_row()), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        filings.validate(client, "f1")
    assert saved["validated_xml"] in VALIDATE_OK.decode()
    assert saved["validated_xml"].startswith("<cr:submission>")


def test_validate_failure_records_the_errors_and_marks_failed():
    client = MagicMock()
    client.post_form.return_value = FAULT
    saved = {}
    with patch.object(filings, "get_filing", return_value=_row()), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        with pytest.raises(errors.TpsiValidationError):
            filings.validate(client, "f1")
    # Step-specific, not a generic "failed": a validation failure is free
    # and retryable, and the status has to say so (migration 018).
    assert saved["stage"] == filings.STAGE_VALIDATION_FAILED
    assert "brNo is required" in str(saved["cr_error"])


def test_validate_refuses_a_submitted_filing():
    """The money invariant: the double-charge guard is the partial unique
    index on stage='submitted'. Walking a submitted row back to 'validated'
    would drop it from that index's coverage and let it be resubmitted."""
    client = MagicMock()
    with patch.object(filings, "get_filing", return_value=_row(stage=filings.STAGE_SUBMITTED)), \
         patch.object(filings, "_update") as updated:
        with pytest.raises(ValueError, match="submitted"):
            filings.validate(client, "f1")
    updated.assert_not_called()
    client.post_form.assert_not_called()


def test_validate_refuses_a_signed_filing():
    client = MagicMock()
    with patch.object(filings, "get_filing", return_value=_row(stage=filings.STAGE_SIGNED)), \
         patch.object(filings, "_update") as updated:
        with pytest.raises(ValueError, match="signed"):
            filings.validate(client, "f1")
    updated.assert_not_called()
    client.post_form.assert_not_called()


def test_validate_refuses_an_edrive_filing():
    client = MagicMock()
    with patch.object(filings, "get_filing", return_value=_row(stage=filings.STAGE_EDRIVE)), \
         patch.object(filings, "_update") as updated:
        with pytest.raises(ValueError, match="edrive"):
            filings.validate(client, "f1")
    updated.assert_not_called()
    client.post_form.assert_not_called()


def test_validate_allows_redoing_a_draft_filing():
    """The existing default-stage fixture case, made explicit: a fresh draft
    must still be validatable."""
    client = MagicMock()
    client.post_form.return_value = VALIDATE_OK
    saved = {}
    with patch.object(filings, "get_filing", return_value=_row(stage=filings.STAGE_DRAFT)), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        filings.validate(client, "f1")
    assert saved["stage"] == filings.STAGE_VALIDATED


def test_validate_allows_redoing_an_already_validated_filing():
    """A user fixing field errors after a first validate and retrying is
    legitimate — only signed/submitted/edrive are refused."""
    client = MagicMock()
    client.post_form.return_value = VALIDATE_OK
    saved = {}
    with patch.object(filings, "get_filing",
                      return_value=_row(stage=filings.STAGE_VALIDATED,
                                        validated_xml="<cr:submission>old</cr:submission>")), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        filings.validate(client, "f1")
    assert saved["stage"] == filings.STAGE_VALIDATED
    assert "SIGVALUE123" in saved["validated_xml"]


def test_edrive_requires_a_validated_filing():
    """e-Drive takes the validated payload; a draft has no CR signature yet."""
    client = MagicMock()
    with patch.object(filings, "get_filing", return_value=_row(stage=filings.STAGE_DRAFT)):
        with pytest.raises(ValueError, match="validated"):
            filings.upload_edrive(client, "f1")


def test_edrive_marks_the_filing_and_is_terminal():
    """CR: 'The Web-Form is inconvertible to TPSI format after submitting to
    e-Drive' — it must not then be submitted through TPSI."""
    client = MagicMock()
    client.post_form.return_value = EDRIVE_OK
    saved = {}
    with patch.object(filings, "get_filing",
                      return_value=_row(stage=filings.STAGE_VALIDATED,
                                        validated_xml="<submission/>")), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        result = filings.upload_edrive(client, "f1")
    assert saved["stage"] == filings.STAGE_EDRIVE
    assert "successfully" in result["result"]


def test_create_filing_starts_at_draft():
    with patch.object(filings, "_insert", side_effect=lambda p: p):
        row = filings.create_filing(
            entity_id="e1", form_code="Nar1",
            form_xml="<formCode>NAR1</formCode>", user_id="u1",
        )
    assert row["stage"] == filings.STAGE_DRAFT
    assert row["form_code"] == "Nar1"


def test_unknown_form_code_is_rejected_before_any_call():
    with patch.object(filings, "_insert", side_effect=lambda p: p):
        with pytest.raises(KeyError):
            filings.create_filing(
                entity_id="e1", form_code="Zzz9", form_xml="<x/>", user_id="u1"
            )


# ---- sign ---------------------------------------------------------------

SIGN_OK = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
 <soap:Body><cr:verifyPinSigningResponse
   xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">
   <cr:result>Pin Signature(s) Verified Successfully.</cr:result>
 </cr:verifyPinSigningResponse></soap:Body></soap:Envelope>"""

VALIDATED_XML = (
    '<cr:submission><cr:EForm id="eForm"><cr:formModel id="formData">'
    "<cr:formCode>NAR1</cr:formCode></cr:formModel></cr:EForm>"
    '<cr:EFormSignatures><cr:Signature id="CR"/></cr:EFormSignatures>'
    "</cr:submission>"
)


def test_sign_requires_a_validated_filing():
    with patch.object(filings, "get_filing", return_value=_row(stage=filings.STAGE_DRAFT)):
        with pytest.raises(ValueError, match="validated"):
            filings.sign(MagicMock(), "f1", "U", "pw")


def test_sign_places_pinsign_inside_eformsignatures_below_cr_signature():
    client = MagicMock()
    client.post_form.return_value = SIGN_OK
    saved = {}
    with patch.object(filings, "get_filing",
                      return_value=_row(stage=filings.STAGE_VALIDATED,
                                        validated_xml=VALIDATED_XML)), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        filings.sign(client, "f1", "USERID", "pw")

    signed = saved["signed_xml"]
    assert signed.index('id="CR"') < signed.index("PinSign")
    assert signed.index("PinSign") < signed.index("</cr:EFormSignatures>")
    assert saved["stage"] == filings.STAGE_SIGNED


def test_sign_signs_the_eform_element_only_not_the_signatures():
    """The overall signature's scope is EForm (URI='#eForm')."""
    captured = {}
    client = MagicMock()
    client.post_form.return_value = SIGN_OK
    with patch.object(filings, "get_filing",
                      return_value=_row(stage=filings.STAGE_VALIDATED,
                                        validated_xml=VALIDATED_XML)), \
         patch.object(filings, "_update"), \
         patch("services.tpsi.crypto.build_pin_sign",
               side_effect=lambda eform, *a, **k: captured.setdefault("eform", eform) or "<cr:PinSign/>"):
        filings.sign(client, "f1", "USERID", "pw")
    assert captured["eform"].startswith("<cr:EForm")
    assert captured["eform"].endswith("</cr:EForm>")
    assert "EFormSignatures" not in captured["eform"]


def test_sign_never_stores_the_password():
    client = MagicMock()
    client.post_form.return_value = SIGN_OK
    saved = {}
    with patch.object(filings, "get_filing",
                      return_value=_row(stage=filings.STAGE_VALIDATED,
                                        validated_xml=VALIDATED_XML)), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        filings.sign(client, "f1", "USERID", "sup3rs3cret")
    assert "sup3rs3cret" not in str(saved)


# ── Form status vocabulary (migration 018) ──────────────────────────────────
# The point of splitting `failed` is that a caller can tell a FREE, retryable
# validation failure from a rejected CHARGEABLE submission without opening
# cr_error. These lock that in.


def test_sign_failure_records_signing_failed_not_a_generic_failure(monkeypatch):
    from services.tpsi import errors

    saved = {}
    filing = {
        "id": "f1", "form_code": "Nar1", "stage": filings.STAGE_VALIDATED,
        # EFormSignatures must be present: the overall signature is spliced in
        # just before its closing tag, so sign() fails earlier without it.
        "validated_xml": (
            "<cr:submission><cr:EForm>x</cr:EForm>"
            "<cr:EFormSignatures></cr:EFormSignatures></cr:submission>"
        ),
    }
    monkeypatch.setattr(filings, "get_filing", lambda _id: filing)
    monkeypatch.setattr(filings, "_update", lambda _id, payload: saved.update(payload))
    monkeypatch.setattr(
        "services.tpsi.crypto.build_pin_sign", lambda *a, **k: "<cr:PinSign/>"
    )
    monkeypatch.setattr(
        "services.tpsi.config.get_config",
        lambda: type("C", (), {"cr_public_key_pem": "pem"})(),
    )

    client = MagicMock()
    client.post_form.side_effect = errors.TpsiValidationError([("ERR_SIG", "bad pin")])

    with pytest.raises(errors.TpsiValidationError):
        filings.sign(client, "f1", "CHANTM01", "pw")

    assert saved["stage"] == filings.STAGE_SIGNING_FAILED
    assert saved["stage"] != filings.STAGE_VALIDATION_FAILED


def test_form_statuses_are_the_nine_the_ui_reports():
    # edrive is a valid stored value but is not offered in the UI, so it must
    # not appear in the reported vocabulary.
    assert len(filings.FORM_STATUSES) == 9
    assert filings.STAGE_EDRIVE not in filings.FORM_STATUSES
    # Every reported status needs a label, or the UI renders a raw enum.
    for status in filings.FORM_STATUSES:
        assert filings.FORM_STATUS_LABELS.get(status)


def test_a_submitted_filing_cannot_be_walked_back_by_revalidating(monkeypatch):
    # The double-charge guard is a partial unique index on stage='submitted';
    # re-validating would drop the row out of its coverage.
    for terminal in filings.TERMINAL_STAGES:
        monkeypatch.setattr(
            filings, "get_filing", lambda _id, s=terminal: {"id": "f1", "stage": s}
        )
        with pytest.raises(ValueError):
            filings.validate(MagicMock(), "f1")

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
    assert saved["stage"] == filings.STAGE_FAILED
    assert "brNo is required" in str(saved["cr_error"])


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

import re

import pytest

from services.tpsi import errors, soap

VALIDATE_RESPONSE = b"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <cr:validateFormResponse xmlns:ds="http://www.w3.org/2000/09/xmldsig#"
        xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">
      <cr:submission>
        <cr:EForm id="eForm">
          <cr:formModel id="formData">
            <cr:formCode>NAR1</cr:formCode>
            <cr:language>E</cr:language>
            <cr:brNo>00011651</cr:brNo>
            <cr:compNameE>PEAK TRAMWAYS COMPANY, LIMITED</cr:compNameE>
          </cr:formModel>
        </cr:EForm>
        <cr:EFormSignatures>
          <ds:Signature id="CR">
            <ds:SignedInfo>
              <ds:CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>
              <ds:SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"/>
              <ds:Reference URI="#formData">
                <ds:DigestValue>wJmzROIWOU01pWVHSVDGvMfoNzq94wYIvKgdbRYI67o=</ds:DigestValue>
              </ds:Reference>
            </ds:SignedInfo>
            <ds:SignatureValue>LlbNGrhrKOCkvSk7mmsMF3Z4BIZRcI3J</ds:SignatureValue>
          </ds:Signature>
        </cr:EFormSignatures>
      </cr:submission>
    </cr:validateFormResponse>
  </soap:Body>
</soap:Envelope>"""

BALANCE_RESPONSE = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <cr:enquireDepositAccountResponse
        xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">
      <cr:result><cr:accountBalance>1831538.0</cr:accountBalance></cr:result>
    </cr:enquireDepositAccountResponse>
  </soap:Body>
</soap:Envelope>"""


def test_request_envelope_is_soap_11_with_no_encoding_style():
    """Verified against
    tests/fixtures/cr-examples/submission/submit_NAR1.xml."""
    out = soap.build_envelope("submitForm", "<cr:submission/>").decode()
    assert 'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"' in out
    assert "encodingStyle" not in out
    assert "2003/05/soap-envelope" not in out


def test_body_carries_the_operation_wrapper():
    out = soap.build_envelope("submitForm", "<cr:submission/>").decode()
    assert "<cr:submitForm " in out
    assert 'xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/"' in out
    assert 'xmlns:ds="http://www.w3.org/2000/09/xmldsig#"' in out


def test_edrive_wrapper_name_differs_from_its_url_path():
    """Path segment is uploadToEdriveForm; the body element is uploadToEdrive."""
    out = soap.build_envelope("uploadToEdriveForm", "<cr:submission/>").decode()
    assert "<cr:uploadToEdrive " in out
    assert "uploadToEdriveForm" not in out


def test_submission_elements_are_cr_prefixed():
    out = soap.build_submission("<cr:formCode>NAR1</cr:formCode>")
    assert '<cr:EForm id="eForm">' in out
    assert '<cr:formModel id="formData">' in out
    assert "<cr:formCode>NAR1</cr:formCode>" in out


def test_validate_request_carries_an_empty_signatures_element():
    """CR's own validate examples all include an empty <cr:EFormSignatures>."""
    out = soap.build_submission("<cr:formCode>NAR1</cr:formCode>")
    assert "<cr:EFormSignatures></cr:EFormSignatures>" in out


def test_deposit_account_present_only_when_given():
    """<cr:depositAccountNo> appears on submitForm and nowhere else."""
    assert "depositAccountNo" not in soap.build_submission("<cr:x/>")
    out = soap.build_submission("<cr:x/>", deposit_account_no="010000204551")
    assert "<cr:depositAccountNo>010000204551</cr:depositAccountNo>" in out


def test_parse_is_namespace_aware_not_prefix_based():
    """Same document, different prefixes — must still parse."""
    renamed = (VALIDATE_RESPONSE
               .replace(b"xmlns:soap=", b"xmlns:env=")
               .replace(b"soap:", b"env:")
               .replace(b"<cr:", b"<reg:").replace(b"</cr:", b"</reg:")
               .replace(b"xmlns:cr=", b"xmlns:reg="))
    el = soap.parse_response(renamed, "validateFormResponse")
    assert el is not None


def test_parse_raises_on_fault():
    fault = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
      <soap:Body><soap:Fault><faultcode>soap:Server</faultcode>
      <faultstring>boom</faultstring><detail>
      <cr:EfilingWebServiceError xmlns:cr="http://x/"><webServiceFaultBeans>
      <faultCode>ERR_MSG_REQUIRED</faultCode><faultString>x is required</faultString>
      </webServiceFaultBeans></cr:EfilingWebServiceError></detail>
      </soap:Fault></soap:Body></soap:Envelope>"""
    with pytest.raises(errors.TpsiValidationError):
        soap.parse_response(fault, "validateFormResponse")


def test_text_of_reads_a_nested_value():
    el = soap.parse_response(BALANCE_RESPONSE, "enquireDepositAccountResponse")
    assert soap.text_of(el, "accountBalance") == "1831538.0"


def test_extract_submission_returns_the_slice_verbatim():
    """Byte-for-byte: CR's digest covers the exact content, so the carry-forward
    must not reformat, re-indent or renormalise namespaces."""
    out = soap.extract_submission(VALIDATE_RESPONSE)
    assert out.startswith("<cr:submission>")
    assert out.endswith("</cr:submission>")
    assert out in VALIDATE_RESPONSE.decode()          # a literal substring
    assert "wJmzROIWOU01pWVHSVDGvMfoNzq94wYIvKgdbRYI67o=" in out
    assert "LlbNGrhrKOCkvSk7mmsMF3Z4BIZRcI3J" in out
    assert 'URI="#formData"' in out


def test_extract_submission_discovers_the_prefix_rather_than_assuming_it():
    renamed = (VALIDATE_RESPONSE
               .replace(b"<cr:", b"<reg:").replace(b"</cr:", b"</reg:")
               .replace(b"xmlns:cr=", b"xmlns:reg="))
    out = soap.extract_submission(renamed)
    assert out.startswith("<reg:submission>")
    assert out.endswith("</reg:submission>")


def test_extract_submission_raises_on_a_fault():
    fault = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
      <soap:Body><soap:Fault><faultcode>soap:Server</faultcode>
      <faultstring>x</faultstring><detail>
      <cr:EfilingWebServiceError xmlns:cr="http://x/"><webServiceFaultBeans>
      <faultCode>ERR_MSG_REQUIRED</faultCode><faultString>y</faultString>
      </webServiceFaultBeans></cr:EfilingWebServiceError></detail>
      </soap:Fault></soap:Body></soap:Envelope>"""
    with pytest.raises(errors.TpsiValidationError):
        soap.extract_submission(fault)


def test_append_to_signatures_places_the_fragment_below_cr_signature():
    """CR requires the overall signature LAST inside EFormSignatures."""
    submission = soap.extract_submission(VALIDATE_RESPONSE)
    out = soap.append_to_signatures(submission, "<cr:PinSign URI='#eForm'/>")
    assert out.index('id="CR"') < out.index("PinSign")
    assert out.index("PinSign") < out.index("</cr:EFormSignatures>")


def test_append_to_signatures_handles_a_self_closing_element():
    out = soap.append_to_signatures(
        "<cr:submission><cr:EFormSignatures/></cr:submission>", "<cr:PinSign/>"
    )
    assert "<cr:EFormSignatures><cr:PinSign/></cr:EFormSignatures>" in out


def test_append_to_signatures_does_not_disturb_signed_content():
    submission = soap.extract_submission(VALIDATE_RESPONSE)
    out = soap.append_to_signatures(submission, "<cr:PinSign/>")
    # everything up to the insertion point is untouched
    assert out.startswith(submission[: submission.index("</cr:EFormSignatures>")])


def test_append_deposit_account_is_the_last_child_of_submission():
    out = soap.append_deposit_account(
        "<cr:submission><cr:EForm/></cr:submission>", "010000204551"
    )
    assert out == (
        "<cr:submission><cr:EForm/>"
        "<cr:depositAccountNo>010000204551</cr:depositAccountNo>"
        "</cr:submission>"
    )

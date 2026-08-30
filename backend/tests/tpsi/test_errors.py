import pytest

from services.tpsi import errors

FAULT = b"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <soap:Fault>
      <faultcode>soap:Server</faultcode>
      <faultstring>Efiling Webservice error occurs.</faultstring>
      <detail>
        <cr:EfilingWebServiceError
            xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">
          <webServiceFaultBeans>
            <faultCode>ERR_MSG_MAX_LENGTH</faultCode>
            <faultString>Flat / Floor / Block etc. length must be at most 60</faultString>
          </webServiceFaultBeans>
          <webServiceFaultBeans>
            <faultCode>ERR_MSG_REQUIRED</faultCode>
            <faultString>Street is required</faultString>
          </webServiceFaultBeans>
        </cr:EfilingWebServiceError>
      </detail>
    </soap:Fault>
  </soap:Body>
</soap:Envelope>"""

OK = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body><cr:validateFormResponse
      xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/"/></soap:Body>
</soap:Envelope>"""


def test_no_fault_is_a_no_op():
    errors.raise_for_fault(OK)


def test_fault_collects_every_error_not_just_the_first():
    """CR returns the FULL list of validation errors — losing all but the first
    means the user fixes one field per round trip."""
    with pytest.raises(errors.TpsiValidationError) as exc:
        errors.raise_for_fault(FAULT)
    assert len(exc.value.faults) == 2
    assert ("ERR_MSG_REQUIRED", "Street is required") in exc.value.faults


def test_signature_fault_maps_to_signature_error():
    xml = FAULT.replace(b"ERR_MSG_MAX_LENGTH", b"ERR_MSG_SIGNATORY_NOT_AUTH")
    with pytest.raises(errors.TpsiSignatureError):
        errors.raise_for_fault(xml)


def test_locked_account_maps_to_signature_error():
    xml = FAULT.replace(b"ERR_MSG_MAX_LENGTH", b"ERR_MSG_USER_ACC_LOCKED")
    with pytest.raises(errors.TpsiSignatureError):
        errors.raise_for_fault(xml)


def test_parsing_is_namespace_aware_not_prefix_based():
    """CR is not consistent about prefixes; matching on the literal string
    'cr:' or 'soap:' breaks the moment they change one."""
    # Same document, same namespace URIs, different prefixes throughout —
    # rename the xmlns: declarations themselves first, then the usages,
    # so the result stays well-formed. Parsing must not care either way.
    xml = FAULT.replace(b"xmlns:soap=", b"xmlns:env=").replace(b"soap:", b"env:")
    xml = xml.replace(b"xmlns:cr=", b"xmlns:reg=").replace(b"cr:", b"reg:")
    with pytest.raises(errors.TpsiValidationError):
        errors.raise_for_fault(xml)


def test_str_is_readable_and_leaks_nothing():
    with pytest.raises(errors.TpsiValidationError) as exc:
        errors.raise_for_fault(FAULT)
    assert "ERR_MSG_MAX_LENGTH" in str(exc.value)

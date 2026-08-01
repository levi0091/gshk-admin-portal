from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from services.tpsi import reads

BALANCE = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
 <soap:Body><cr:enquireDepositAccountResponse
   xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">
   <cr:result><cr:accountBalance>1831538.0</cr:accountBalance></cr:result>
 </cr:enquireDepositAccountResponse></soap:Body></soap:Envelope>"""

STATUS = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
 <soap:Body><cr:enquireDocStatusResponse
   xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">
   <cr:result>
     <cr:caseNo>180256934</cr:caseNo><cr:brNo>00011651</cr:brNo>
     <cr:documentRefNo>NAR1(731)</cr:documentRefNo>
     <cr:documentName>Annual Return</cr:documentName>
     <cr:documentStatus>Registered</cr:documentStatus>
     <cr:submissionDate>28/06/2022</cr:submissionDate>
   </cr:result>
   <cr:result>
     <cr:caseNo>180256935</cr:caseNo><cr:brNo>00011651</cr:brNo>
     <cr:documentRefNo>NAR1(732)</cr:documentRefNo>
     <cr:documentName>Annual Return</cr:documentName>
     <cr:documentStatus>Pending</cr:documentStatus>
     <cr:submissionDate>29/06/2022</cr:submissionDate>
   </cr:result>
 </cr:enquireDocStatusResponse></soap:Body></soap:Envelope>"""


def _client(payload):
    c = MagicMock()
    c.post_soap.return_value = payload
    return c


def test_balance_returns_decimal_not_float():
    """Money compared with a float is a bug waiting to happen; the balance gate
    depends on this comparison."""
    result = reads.check_balance(_client(BALANCE), "N00061980009")
    assert result == Decimal("1831538.0")
    assert isinstance(result, Decimal)


def test_balance_request_carries_the_account_number():
    client = _client(BALANCE)
    reads.check_balance(client, "N00061980009")
    body = client.post_soap.call_args[0][1]
    assert "N00061980009" in body
    assert "accountNo" in body


def test_status_returns_one_dict_per_result():
    rows = reads.case_status(_client(STATUS), case_no="180256934")
    assert len(rows) == 2
    assert rows[0]["documentStatus"] == "Registered"
    assert rows[1]["caseNo"] == "180256935"


def test_status_requires_at_least_one_criterion():
    """CR requires BR+date-range, or case no, or document ref. Sending none
    would return everything or error server-side."""
    with pytest.raises(ValueError):
        reads.case_status(_client(STATUS))


def test_status_br_number_requires_a_date_range():
    with pytest.raises(ValueError):
        reads.case_status(_client(STATUS), br_no="00011651")


def test_status_omits_empty_criteria_from_the_request():
    client = _client(STATUS)
    reads.case_status(client, case_no="180256934")
    body = client.post_soap.call_args[0][1]
    assert "caseNo" in body
    assert "documentRefNo" not in body

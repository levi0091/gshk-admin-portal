from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from services.tpsi import reads

BALANCE = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
 <soap:Body><cr:enquireDepositAccountResponse
   xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">
   <cr:result><cr:accountBalance>1831538.0</cr:accountBalance></cr:result>
 </cr:enquireDepositAccountResponse></soap:Body></soap:Envelope>"""

# CR'S OWN SHAPE, from §6.5.5 of TPSI API Interface v1.0.14 — result wraps a
# documentList which wraps one `document` per row, and the BR number is spelt
# `brno` here where the REQUEST spells it `brNo`.
#
# The fixture this replaced was invented from our own code: repeated
# `<cr:result>` siblings, `brNo` in the reply. It passed for a shape CR has
# never sent, which is exactly how the request went out wrong too. A second
# document is added to CR's single-document sample, because one row cannot tell
# a per-document reader apart from one that stitches the first value of every
# field out of the whole reply.
STATUS = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
 <soap:Body><cr:enquireDocStatusResponse
   xmlns:ds="http://www.w3.org/2000/09/xmldsig#"
   xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">
   <cr:result>
     <cr:documentList>
       <cr:document>
         <cr:caseNo>180256934</cr:caseNo><cr:brno>00011651</cr:brno>
         <cr:companyEngName>PEAK TRAMWAYS COMPANY, LIMITED</cr:companyEngName>
         <cr:submissionDate>28/06/2022</cr:submissionDate>
         <cr:documentRefNo>NAR1(731)</cr:documentRefNo>
         <cr:documentName>Annual Return</cr:documentName>
         <cr:documentStatus>Registered</cr:documentStatus>
       </cr:document>
       <cr:document>
         <cr:caseNo>180256935</cr:caseNo><cr:brno>00011651</cr:brno>
         <cr:companyEngName>PEAK TRAMWAYS COMPANY, LIMITED</cr:companyEngName>
         <cr:submissionDate>29/06/2022</cr:submissionDate>
         <cr:documentRefNo>NAR1(732)</cr:documentRefNo>
         <cr:documentName>Annual Return</cr:documentName>
         <cr:documentStatus>Pending</cr:documentStatus>
       </cr:document>
     </cr:documentList>
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


def test_status_returns_one_dict_per_document():
    """Per DOCUMENT, not per `result` — CR sends exactly one `result`.

    Reading rows off `result` returned a single row per reply whose every field
    was the first one found anywhere in it, so a case carrying a NAR1 and an
    NR1 reported one invented document. `pick_document` refuses an ambiguous
    reply precisely so another form's rejection is never written onto this
    return; it can only do that if it is given both rows.
    """
    rows = reads.case_status(_client(STATUS), case_no="180256934")
    assert len(rows) == 2
    assert rows[0]["documentStatus"] == "Registered"
    assert rows[1]["documentStatus"] == "Pending"
    assert rows[1]["caseNo"] == "180256935"


def test_status_reads_crs_lowercase_brno_from_the_reply():
    """CR's request spells it `brNo` and its reply spells it `brno`. Matching is
    by exact local name, so the reply's spelling has to be named somewhere."""
    rows = reads.case_status(_client(STATUS), case_no="180256934")
    assert rows[0]["brNo"] == "00011651"


def test_status_asks_for_the_operation_cr_actually_publishes():
    """The soap:Body element is `enquireDocStatus`; the URL segment is
    `docStatusEnquiry`. Sending the URL's word as the operation is what CR
    answered "was not recognized. (Does it exist in service WSDL?)" to, for
    every filed case, on 2026-09-16."""
    client = _client(STATUS)
    reads.case_status(client, case_no="180256934")
    path, body = client.post_soap.call_args[0]
    assert path == "/tpsi/docStatusEnquiry"
    assert "<cr:enquireDocStatus " in body
    assert "<cr:criteria>" in body
    assert "docStatusEnquiry>" not in body       # never as the operation
    assert "statusRequest" not in body           # nor our invented wrapper


def test_status_requires_at_least_one_criterion():
    """CR requires BR+date-range, or case no, or document ref. Sending none
    would return everything or error server-side."""
    with pytest.raises(ValueError):
        reads.case_status(_client(STATUS))


def test_status_br_number_requires_a_date_range():
    with pytest.raises(ValueError):
        reads.case_status(_client(STATUS), br_no="00011651")


def test_status_sends_every_criterion_in_crs_order_empty_when_unused():
    """CR's §6.5.3 example sends all five, empty ones included, in this order.

    We used to omit the unused ones — our invention, and one we have no way to
    check against a WSDL we cannot see. After a fault that read "was not
    recognized", the request is CR's sample element for element.
    """
    client = _client(STATUS)
    reads.case_status(client, case_no="180256934")
    body = client.post_soap.call_args[0][1]
    assert "<cr:caseNo>180256934</cr:caseNo>" in body
    assert "<cr:documentRefNo></cr:documentRefNo>" in body
    order = [body.index(f"<cr:{f}>") for f in
             ("brNo", "caseNo", "submissionDateStart",
              "submissionDateEnd", "documentRefNo")]
    assert order == sorted(order)

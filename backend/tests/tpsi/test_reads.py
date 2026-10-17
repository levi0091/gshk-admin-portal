from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from services.tpsi import reads

BALANCE = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
 <soap:Body><cr:enquireDepositAccountResponse
   xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">
   <cr:result><cr:accountBalance>1831538.0</cr:accountBalance></cr:result>
 </cr:enquireDepositAccountResponse></soap:Body></soap:Envelope>"""

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


def test_there_is_no_case_status_read():
    """docStatusEnquiry went with the CR status poll (Levi 2026-10-17)."""
    assert not hasattr(reads, "case_status")

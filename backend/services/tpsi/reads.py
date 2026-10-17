"""The free, side-effect-free TPSI read: the deposit balance.

`docStatusEnquiry` (case status) was the other, until Levi 2026-10-17: CR will
not report a document's status after filing through it, so the CR status poll
and every caller of it were removed.
"""
from decimal import Decimal

from services.tpsi.soap import parse_response, text_of


def check_balance(client, account_no: str) -> Decimal:
    """Live deposit-account balance.

    Returned as Decimal, never float: this value is compared against a statutory
    fee in the submit gate, and binary floating point has no business there.
    """
    body = (
        "<cr:enquireDepositAccount "
        'xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">'
        f"<cr:depositRequest><cr:accountNo>{account_no}</cr:accountNo>"
        "</cr:depositRequest></cr:enquireDepositAccount>"
    )
    raw = client.post_soap("/tpsi/enquireDepositAccount", body)
    element = parse_response(raw, "enquireDepositAccountResponse")
    return Decimal(text_of(element, "accountBalance") or "0")

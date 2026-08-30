"""The two free, side-effect-free TPSI reads: deposit balance and case status."""
from decimal import Decimal

from services.tpsi.soap import find_all, parse_response, text_of

_STATUS_FIELDS = (
    "caseNo",
    "brNo",
    "companyEngName",
    "companyChiName",
    "submissionDate",
    "documentRefNo",
    "documentName",
    "documentStatus",
)


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


def case_status(
    client,
    br_no: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    case_no: str | None = None,
    document_ref_no: str | None = None,
) -> list[dict]:
    """Case/document status.

    CR accepts exactly one of: BR number WITH a submission-date range, a case
    number, or a document reference number. Dates are dd/mm/yyyy.
    """
    if br_no and not (date_start and date_end):
        raise ValueError("br_no requires both date_start and date_end (dd/mm/yyyy)")
    if not any([br_no, case_no, document_ref_no]):
        raise ValueError(
            "one of br_no+date range, case_no, or document_ref_no is required"
        )

    fields = {
        "brNo": br_no,
        "submissionDateStart": date_start,
        "submissionDateEnd": date_end,
        "caseNo": case_no,
        "documentRefNo": document_ref_no,
    }
    inner = "".join(
        f"<cr:{name}>{value}</cr:{name}>"
        for name, value in fields.items()
        if value
    )
    body = (
        "<cr:docStatusEnquiry "
        'xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">'
        f"<cr:statusRequest>{inner}</cr:statusRequest></cr:docStatusEnquiry>"
    )
    raw = client.post_soap("/tpsi/docStatusEnquiry", body)
    element = parse_response(raw, "enquireDocStatusResponse")

    rows = []
    for result in find_all(element, "result"):
        rows.append({f: text_of(result, f) for f in _STATUS_FIELDS})
    return rows

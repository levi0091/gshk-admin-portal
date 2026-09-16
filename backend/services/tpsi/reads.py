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

    THE PATH AND THE OPERATION ARE DIFFERENT WORDS, and getting that wrong is
    how this shipped broken on 2026-09-16. The URL segment is
    `docStatusEnquiry` (§6.5.1) and the soap:Body element is
    `cr:enquireDocStatus` (§6.5.3) — the same split `soap.OPERATIONS` already
    records for e-Drive. Sending `cr:docStatusEnquiry` reached CR, authenticated
    and came back

        Message part {…icris3e.cr.gov.hk/}docStatusEnquiry was not recognized.
        (Does it exist in service WSDL?)

    for every case in the book. The response tag was the clue all along: nothing
    called `docStatusEnquiry` answers with `enquireDocStatusResponse`.

    THE REQUEST IS CR'S OWN EXAMPLE, ELEMENT FOR ELEMENT. All five criteria are
    sent in CR's order, EMPTY when unused, because that is what §6.5.3's sample
    does and the service is a JAX-WS bean whose sequence we cannot see. Omitting
    the unused ones was our invention — and after a fault whose text is "was not
    recognized", guessing at a shape CR documents verbatim is not a risk worth
    re-taking.
    """
    if br_no and not (date_start and date_end):
        raise ValueError("br_no requires both date_start and date_end (dd/mm/yyyy)")
    if not any([br_no, case_no, document_ref_no]):
        raise ValueError(
            "one of br_no+date range, case_no, or document_ref_no is required"
        )

    # CR'S ORDER, not ours — see the docstring.
    fields = (
        ("brNo", br_no),
        ("caseNo", case_no),
        ("submissionDateStart", date_start),
        ("submissionDateEnd", date_end),
        ("documentRefNo", document_ref_no),
    )
    inner = "".join(f"<cr:{name}>{value or ''}</cr:{name}>" for name, value in fields)
    body = (
        "<cr:enquireDocStatus "
        'xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">'
        f"<cr:criteria>{inner}</cr:criteria></cr:enquireDocStatus>"
    )
    raw = client.post_soap("/tpsi/docStatusEnquiry", body)
    element = parse_response(raw, "enquireDocStatusResponse")

    # ONE ROW PER <cr:document>, not per <cr:result>. CR nests
    # result > documentList > document, so there is exactly ONE `result` in
    # every reply — reading rows off it collapsed a multi-document case into a
    # single row stitched together from the first value of each field found
    # anywhere in the reply. With one document that is indistinguishable from
    # correct, which is why it survived review.
    rows = []
    for doc in find_all(element, "document"):
        row = {f: text_of(doc, f) for f in _STATUS_FIELDS}
        if row["brNo"] is None:
            # CR'S RESPONSE SPELLS IT `brno`, ITS REQUEST SPELLS IT `brNo`
            # (§6.5.3 vs §6.5.5 — both are CR's own examples). Matching is by
            # exact local name and must stay that way, so the alternative
            # spelling is named here rather than by making every lookup
            # case-insensitive.
            row["brNo"] = text_of(doc, "brno")
        rows.append(row)
    return rows

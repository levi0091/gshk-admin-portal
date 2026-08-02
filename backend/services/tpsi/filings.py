"""The filing ledger: per-attempt chain state for a TPSI submission.

Why this exists at all: CR's order is validate -> sign -> submit, and each step
consumes the previous step's CR-signed payload. Holding that chain server-side
is what makes the submit gate real — a client cannot assert "already validated"
and skip straight to the chargeable call.
"""
import sys
from datetime import datetime, timezone

from db.supabase import get_supabase
from services.tpsi.config import FORM_FEES
from services.tpsi.errors import TpsiError
from services.tpsi.soap import extract_submission, parse_response, text_of

_TABLE = "tpsi_filings"

# The FORM status vocabulary (migration 018). Distinct from the WORKFLOW status,
# which lives on nar1_cases and answers a different question: this says where the
# document is in CR's process, not where the case is in GSHK's.
#
# Failure is split per step on purpose. "validation_failed" means fix the data
# and retry for free; "submission_failed" means CR rejected a chargeable call.
# Collapsing both into one `failed`, as the original vocabulary did, loses the
# only distinction that changes what the user should do next.
STAGE_DRAFT = "draft"
STAGE_VALIDATED = "validated"
STAGE_VALIDATION_FAILED = "validation_failed"
STAGE_SIGNED = "signed"
STAGE_SIGNING_FAILED = "signing_failed"
STAGE_SUBMITTED = "submitted"
STAGE_SUBMISSION_FAILED = "submission_failed"
STAGE_REGISTERED = "registered"
STAGE_SUPERSEDED = "superseded"
STAGE_EDRIVE = "edrive"

#: The nine the UI reports, in lifecycle order. `edrive` is a valid stored value
#: (upload_edrive() still works) but is not offered in the UI, so it is not here.
FORM_STATUSES = (
    STAGE_DRAFT,
    STAGE_VALIDATED,
    STAGE_VALIDATION_FAILED,
    STAGE_SIGNED,
    STAGE_SIGNING_FAILED,
    STAGE_SUBMITTED,
    STAGE_SUBMISSION_FAILED,
    STAGE_REGISTERED,
    STAGE_SUPERSEDED,
)

#: Human labels for the form status. The UI shows these beside — never merged
#: with — the workflow status.
FORM_STATUS_LABELS = {
    STAGE_DRAFT: "Not yet sent to CR",
    STAGE_VALIDATED: "Validated by CR",
    STAGE_VALIDATION_FAILED: "Rejected at validation",
    STAGE_SIGNED: "Signed",
    STAGE_SIGNING_FAILED: "Rejected at signing",
    STAGE_SUBMITTED: "Filed with CR",
    STAGE_SUBMISSION_FAILED: "Rejected at submission",
    STAGE_REGISTERED: "Registered by CR",
    STAGE_SUPERSEDED: "Superseded by a later attempt",
    STAGE_EDRIVE: "Sent to CR e-Drive",
}

#: Stages a filing can never move on from.
TERMINAL_STAGES = (STAGE_SUBMITTED, STAGE_REGISTERED, STAGE_EDRIVE, STAGE_SUPERSEDED)

#: A failure at any step. Kept as a tuple so callers test membership rather than
#: string-matching a suffix.
FAILURE_STAGES = (
    STAGE_VALIDATION_FAILED, STAGE_SIGNING_FAILED, STAGE_SUBMISSION_FAILED,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert(payload: dict) -> dict:
    return get_supabase().table(_TABLE).insert(payload).execute().data[0]


def _update(filing_id: str, payload: dict) -> None:
    get_supabase().table(_TABLE).update(payload).eq("id", filing_id).execute()


def get_filing(filing_id: str) -> dict:
    rows = get_supabase().table(_TABLE).select("*").eq("id", filing_id).execute().data
    if not rows:
        raise LookupError(f"no TPSI filing {filing_id}")
    return rows[0]


def create_filing(
    *,
    entity_id: str,
    form_code: str,
    form_xml: str,
    user_id: str,
    nar1_case_id: str | None = None,
    form_filing_id: str | None = None,
) -> dict:
    """Open a filing attempt. Rejects an unknown form code before any CR call."""
    FORM_FEES[form_code]  # KeyError here beats a 400 from CR later
    return _insert(
        {
            "entity_id": entity_id,
            "form_code": form_code,
            "request_xml": form_xml,
            "presenter_user_id": user_id,
            "nar1_case_id": nar1_case_id,
            "form_filing_id": form_filing_id,
            "stage": STAGE_DRAFT,
        }
    )


def validate(client, filing_id: str) -> dict:
    """validateForm{Code}. No charge, no CR-side effect.

    On success CR returns the form with its own XML signature over it. That
    payload is carried forward VERBATIM — request and response share one
    namespace convention, so no rewriting is needed or wanted.

    Stage guard: refuses signed/submitted/edrive. This is the money invariant
    — the double-charge guard is the partial unique index
    `uq_tpsi_filings_submitted ... WHERE stage = 'submitted'`. Walking a
    submitted row's stage back to 'validated' would drop it from that index's
    coverage and let it be submitted again, so it must be impossible to reach
    from here, not just unlikely given call order. Re-validating a draft or an
    already-validated filing is legitimate (a user fixing field errors and
    retrying) and stays allowed.
    """
    from services.tpsi.soap import build_submission

    filing = get_filing(filing_id)
    if filing["stage"] in (STAGE_SIGNED,) + TERMINAL_STAGES:
        raise ValueError(
            f"filing is already {filing['stage']} and cannot be re-validated"
        )
    submission = build_submission(filing["request_xml"])

    try:
        raw = client.post_form("validateForm", filing["form_code"], submission)
        validated = extract_submission(raw)
    except TpsiError as exc:
        _update(
            filing_id,
            {
                "stage": STAGE_VALIDATION_FAILED,
                "cr_error": {"faults": getattr(exc, "faults", []), "message": str(exc)},
            },
        )
        raise

    _update(
        filing_id,
        {
            "stage": STAGE_VALIDATED,
            "validated_xml": validated,
            "validated_at": _now(),
            "cr_error": None,
        },
    )
    return get_filing(filing_id)


def _extract_eform(submission_xml: str) -> str:
    """The overall signature signs the <EForm> element, not the whole document.

    Sliced as text, prefix discovered from the document: the digest is over
    these exact bytes, so it must not be re-serialised.
    """
    import re as _re

    open_match = _re.search(r"<(\w+:)?EForm[\s>]", submission_xml)
    if not open_match:
        raise TpsiError("no <EForm> in the validated payload")
    prefix = open_match.group(1) or ""
    close = f"</{prefix}EForm>"
    end = submission_xml.find(close)
    if end == -1:
        raise TpsiError("unterminated <EForm> in the validated payload")
    return submission_xml[open_match.start() : end + len(close)]


def sign(client, filing_id: str, signatory_user_id: str, eservice_password: str) -> dict:
    """verifyPinSigning{Code}. No charge.

    NAR1 carries ONE overall signature by a single authorised individual — a
    director OR the company secretary. No consent signatures (spec D2).
    """
    from services.tpsi.config import get_config
    from services.tpsi.crypto import build_pin_sign
    from services.tpsi.soap import append_to_signatures

    filing = get_filing(filing_id)
    if filing["stage"] != STAGE_VALIDATED:
        raise ValueError("filing must be validated before it can be signed")

    validated = filing["validated_xml"]
    pin_sign = build_pin_sign(
        _extract_eform(validated),
        signatory_user_id,
        eservice_password,
        get_config().cr_public_key_pem,
    )
    # CR: the overall signature goes inside EFormSignatures, BELOW its own.
    signed = append_to_signatures(validated, pin_sign)

    try:
        raw = client.post_form("verifyPinSigning", filing["form_code"], signed)
        element = parse_response(raw, "verifyPinSigningResponse")
        result = text_of(element, "result") or ""
    except TpsiError as exc:
        _update(
            filing_id,
            {"stage": STAGE_SIGNING_FAILED,
             "cr_error": {"faults": getattr(exc, "faults", []), "message": str(exc)}},
        )
        raise

    _update(
        filing_id,
        {"stage": STAGE_SIGNED, "signed_xml": signed,
         "signed_at": _now(), "cr_error": None},
    )
    return {"filing_id": filing_id, "result": result}


def upload_edrive(client, filing_id: str) -> dict:
    """uploadToEdriveForm{Code}. No charge.

    Terminal for TPSI: CR states the form is "inconvertible to TPSI format after
    submitting to e-Drive" — it must be finished in the Web Guided Wizard, so
    this filing can never go on to submitForm.
    """
    filing = get_filing(filing_id)
    if filing["stage"] not in (STAGE_VALIDATED, STAGE_SIGNED):
        raise ValueError("filing must be validated before it can go to e-Drive")

    payload = filing.get("signed_xml") or filing["validated_xml"]
    raw = client.post_form("uploadToEdriveForm", filing["form_code"], payload)
    element = parse_response(raw, "uploadToEdriveResponse")
    result = text_of(element, "result") or ""

    _update(filing_id, {"stage": STAGE_EDRIVE})
    return {"filing_id": filing_id, "result": result}


# ---------------------------------------------------------------------------
# Submit — CHARGEABLE AND IRREVERSIBLE
# ---------------------------------------------------------------------------


class SubmitGateError(Exception):
    """A guard on the chargeable, irreversible submit refused."""


_RECEIPT_FIELDS = (
    "caseNo", "brNo", "accNo", "chiCoyName", "engCoyName",
    "docCodesWithBarcode", "pymtNo", "pymtRefNo", "pymtMtd",
    "transactionDate", "transactionTime", "totalAmount", "refNo",
)
_RECEIPT_LINE_FIELDS = ("rcptNo", "revCode", "docShtFrm", "revDesc", "amtChrg")


def parse_receipt(xml_bytes: bytes) -> dict:
    """CR's submitForm receipt — the only proof the filing landed."""
    from services.tpsi.soap import find_all

    element = parse_response(xml_bytes, "submitFormResponse")
    receipt = {f: text_of(element, f) for f in _RECEIPT_FIELDS}
    receipt["paymentRcptList"] = [
        {f: text_of(line, f) for f in _RECEIPT_LINE_FIELDS}
        for line in find_all(element, "paymentRcptList")
    ]
    return receipt


def _check_gate(filing: dict, confirm: bool, balance, fee) -> None:
    """The four conditions, in CR's own order. Server-side, always.

    Every one is checked against state this service holds, never against
    something the caller asserted — a client must not be able to claim it
    already validated and jump straight to the charge.
    """
    if filing["stage"] != STAGE_SIGNED:
        raise SubmitGateError(
            f"filing is '{filing['stage']}' — it must be signed "
            "(validate then sign, in that order) before it can be submitted"
        )
    if not filing.get("signed_xml"):
        raise SubmitGateError("no signed payload stored for this filing")
    if balance < fee:
        raise SubmitGateError(
            f"deposit balance {balance} is below the {fee} fee for "
            f"{filing['form_code']}"
        )
    if confirm is not True:
        raise SubmitGateError("explicit confirmation is required to submit")


def preview(client, filing_id: str, deposit_account: str) -> dict:
    """Fee and live balance, with nothing sent to CR.

    Audited separately from the confirm, per CLAUDE.md — the preview and the
    decision to spend are two distinct events in the trail.
    """
    from services.tpsi import reads
    from services.tpsi.config import fee_for

    filing = get_filing(filing_id)
    fee = fee_for(filing["form_code"])
    balance = reads.check_balance(client, deposit_account)
    return {
        "filing_id": filing_id,
        "form_code": filing["form_code"],
        "stage": filing["stage"],
        "fee": str(fee),
        "balance": str(balance),
        "sufficient": balance >= fee,
        "ready": filing["stage"] == STAGE_SIGNED and bool(filing.get("signed_xml")),
    }


def submit(client, filing_id: str, confirm: bool, deposit_account: str) -> dict:
    """submitForm{Code} — CHARGEABLE AND IRREVERSIBLE.

    The fee leaves the deposit account and there is no un-submit. The stage
    guard also refuses a filing already at 'submitted' or parked in 'edrive'
    (CR: a form sent to e-Drive is "inconvertible to TPSI format"), so neither
    can be charged a second time or filed twice.
    """
    from services.tpsi import reads
    from services.tpsi.config import fee_for
    from services.tpsi.soap import append_deposit_account

    filing = get_filing(filing_id)
    fee = fee_for(filing["form_code"])
    balance = reads.check_balance(client, deposit_account)  # LIVE, never cached
    _check_gate(filing, confirm, balance, fee)

    signed = filing["signed_xml"]
    body = (
        signed
        if "depositAccountNo" in signed
        else append_deposit_account(signed, deposit_account)
    )

    try:
        raw = client.post_form("submitForm", filing["form_code"], body)
        receipt = parse_receipt(raw)
    except TpsiError as exc:
        _update(
            filing_id,
            {
                "stage": STAGE_SUBMISSION_FAILED,
                "cr_error": {"faults": getattr(exc, "faults", []), "message": str(exc)},
            },
        )
        raise

    _update(
        filing_id,
        {
            "stage": STAGE_SUBMITTED,
            "receipt": receipt,
            "fee_amount": str(fee),
            "balance_at_submit": str(balance),
            "submitted_at": _now(),
            "cr_error": None,
        },
    )
    _write_back_receipt(filing, receipt)
    return {"filing_id": filing_id, "receipt": receipt}


def _write_back_receipt(filing: dict, receipt: dict) -> None:
    """Mirror the receipt onto the existing form_filings row.

    The case UI already reads form_filings, so the receipt lands where it is
    already looked for — no new columns on nar1_cases. Never raises: the filing
    has been submitted and charged by this point, and a bookkeeping failure must
    not turn a successful, irreversible submission into an error response.
    """
    if not filing.get("form_filing_id"):
        return
    try:
        get_supabase().table("form_filings").update(
            {
                "filed_with_cr": True,
                "filed_date": _now()[:10],
                "field_details": {"receipt": receipt},
            }
        ).eq("id", filing["form_filing_id"]).execute()
    except Exception as exc:  # noqa: BLE001 - see docstring
        print(
            f"[tpsi.filings] WARN: receipt write-back failed for filing "
            f"{filing.get('id')}: {exc}",
            file=sys.stderr,
        )

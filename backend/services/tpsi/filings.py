"""The filing ledger: per-attempt chain state for a TPSI submission.

Why this exists at all: CR's order is validate -> sign -> submit, and each step
consumes the previous step's CR-signed payload. Holding that chain server-side
is what makes the submit gate real — a client cannot assert "already validated"
and skip straight to the chargeable call.
"""
from datetime import datetime, timezone

from db.supabase import get_supabase
from services.tpsi.config import FORM_FEES
from services.tpsi.errors import TpsiError
from services.tpsi.soap import extract_submission, parse_response, text_of

_TABLE = "tpsi_filings"

STAGE_DRAFT = "draft"
STAGE_VALIDATED = "validated"
STAGE_SIGNED = "signed"
STAGE_SUBMITTED = "submitted"
STAGE_EDRIVE = "edrive"
STAGE_FAILED = "failed"


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
    if filing["stage"] in (STAGE_SIGNED, STAGE_SUBMITTED, STAGE_EDRIVE):
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
                "stage": STAGE_FAILED,
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
            {"stage": STAGE_FAILED,
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

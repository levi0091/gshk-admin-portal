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
    """
    from services.tpsi.soap import build_submission

    filing = get_filing(filing_id)
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

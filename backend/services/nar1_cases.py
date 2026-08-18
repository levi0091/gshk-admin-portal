"""NAR1 case rows — the GSHK-side half of the case (D-6).

This module owns the client facts and the off-portal facts. It never writes a CR
fact: tpsi_filings owns those, and nar1_case_status.derive() reads both to
produce the badge.
"""
from datetime import datetime, timezone

from db.supabase import get_supabase
from services import nar1_case_status
from services.tpsi import filings as tpsi_filings
from services.tpsi.filings import form_status

_TABLE = "nar1_cases"

#: R1 ships NAR1 only. NNC1 cases arrive with R3 and their own workflow.
SUPPORTED_FORM_CODES = ("Nar1",)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_case(case_id: str) -> dict:
    rows = get_supabase().table(_TABLE).select("*").eq("id", case_id).execute().data
    if not rows:
        raise LookupError(f"no NAR1 case {case_id}")
    return rows[0]


def create_case(*, entity_id: str, form_code: str, user_id: str) -> dict:
    """Open a case. The case number is allocated by the DB, not here -- two
    concurrent creates must not be handed the same NAR-2026-0041."""
    if form_code not in SUPPORTED_FORM_CODES:
        raise ValueError(
            f"{form_code} cases are not supported yet — R1 is NAR1 only"
        )
    sb = get_supabase()
    prefix = f"NAR-{datetime.now(timezone.utc).year}"
    case_no = sb.rpc("next_case_no", {"p_prefix": prefix}).execute().data
    return (
        sb.table(_TABLE)
        .insert({
            "entity_id": entity_id,
            "case_no": case_no,
            "nar1_type": "annual_return",
            "created_by": user_id,
            "assigned_to": user_id,
        })
        .execute()
        .data[0]
    )


def update_case(case_id: str, patch: dict) -> dict:
    patch = {**patch, "updated_at": _now()}
    return (
        get_supabase().table(_TABLE).update(patch).eq("id", case_id).execute().data[0]
    )


def current_filing(case_id: str) -> dict | None:
    """The filing that represents this case right now.

    Newest first and superseded rows excluded: a Restart marks the old attempt
    'superseded' and opens a new one, and the badge must follow the live attempt,
    not whichever row happens to sort first.
    """
    rows = (
        get_supabase().table("tpsi_filings")
        .select("*")
        .eq("nar1_case_id", case_id)
        .neq("stage", tpsi_filings.STAGE_SUPERSEDED)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# The manual (wet-signature, off-portal) path — BE-6
# ---------------------------------------------------------------------------
#
# The receipt fields a manual entry must carry. A SUBSET of tpsi_filings'
# RECEIPT_FIELDS by construction (test_the_manual_receipt_shape_matches_the_
# e_signed_one enforces it), because Confirmation renders one template for both
# paths -- and a manual receipt missing a field an e-Signed one has would render
# a blank box that looks like missing data rather than a different route.
#
# chiCoyName, docCodesWithBarcode and refNo are NOT required: a company with no
# Chinese name genuinely has none, and neither the barcode string nor refNo is
# printed on the paper receipt.
RECEIPT_REQUIRED = (
    "caseNo", "brNo", "accNo", "engCoyName", "pymtNo", "pymtRefNo",
    "transactionDate", "transactionTime", "pymtMtd", "totalAmount",
)
RECEIPT_LINE_REQUIRED = ("rcptNo", "revCode", "docShtFrm", "amtChrg")

#: Everything a receipt MAY carry -- CR's own vocabulary, nothing else. Anything
#: outside it is a problem, not a silently-dropped key: manual_receipt is a
#: statutory record rendered by the same template as CR's, and audit_service
#: scrubs `metadata` but not `after_state`, so arbitrary caller JSON must never
#: reach either.
RECEIPT_ALLOWED = set(tpsi_filings.RECEIPT_FIELDS) | {"paymentRcptList"}
RECEIPT_LINE_ALLOWED = set(tpsi_filings.RECEIPT_LINE_FIELDS)

#: Stages that mean CR already holds this return. Recording an off-portal
#: submission on top would put a second statutory filing in the register for one
#: return, and nothing downstream could say which one CR actually has.
CR_FILED_STAGES = (
    tpsi_filings.STAGE_SUBMITTED,
    tpsi_filings.STAGE_REGISTERED,
    tpsi_filings.STAGE_EDRIVE,
)


def blocking_filing(case_id: str) -> dict | None:
    """The filing that decides whether the manual path is still open.

    Deliberately NOT current_filing(). That returns the NEWEST non-superseded
    attempt, and nothing stops POST /tpsi/filings/prepare opening a second draft
    against a case that has already been submitted — no restart marks the old
    row superseded today, so the fresh draft would sort first and hide a filing
    CR is already holding. The manual gate asks "has this return been filed?",
    which is a question about ANY attempt, not the latest one.

    Falls back to the current attempt so the 'signed' guard still sees a live
    e-Sign chain.
    """
    filed = (
        get_supabase().table("tpsi_filings")
        .select("*")
        .eq("nar1_case_id", case_id)
        .in_("stage", list(CR_FILED_STAGES))
        .limit(1)
        .execute()
        .data
    )
    return filed[0] if filed else current_filing(case_id)


def validate_receipt(receipt: dict) -> list[str]:
    """Every problem at once — the user is copying off a paper receipt and
    should not discover the fields one round trip at a time."""
    problems = [
        f"{field}: required" for field in RECEIPT_REQUIRED
        if not str(receipt.get(field) or "").strip()
    ]
    problems += [
        f"{key}: not a receipt field"
        for key in sorted(set(receipt) - RECEIPT_ALLOWED)
    ]

    lines = receipt.get("paymentRcptList") or []
    if not lines:
        problems.append("paymentRcptList: at least one payment line is required")
    for index, line in enumerate(lines):
        line = line or {}
        problems += [
            f"paymentRcptList[{index}].{field}: required"
            for field in RECEIPT_LINE_REQUIRED
            if not str(line.get(field) or "").strip()
        ]
        problems += [
            f"paymentRcptList[{index}].{key}: not a receipt field"
            for key in sorted(set(line) - RECEIPT_LINE_ALLOWED)
        ]
    return problems


def manual_conflict(filing: dict | None, *, step: str) -> str | None:
    """Why the manual path must not run against this filing, or None.

    `step` is "sign" (uploading the wet-signed form) or "submit" (declaring the
    return filed off-portal). The two are gated differently on purpose.
    """
    stage = (filing or {}).get("stage")

    if stage in CR_FILED_STAGES:
        return (
            f"this case is already filed with CR (form status '{stage}') — "
            "recording an off-portal submission as well would put two filings "
            "in the register for one return"
        )

    # 'signed' is the loaded gun. filings._check_gate PASSES on a signed row, so
    # a case completed on paper while a signed filing sits live is ONE
    # chargeable, irreversible call away from filing the same return twice. The
    # upload is harmless preparation and stays allowed; the declaration is not.
    if step == "submit" and stage == tpsi_filings.STAGE_SIGNED:
        return (
            "a CR-signed filing is waiting to be submitted — completing this "
            "case on paper would leave that filing one chargeable call away "
            "from filing the same return again. Restart the filing first."
        )
    return None


def composite(case_id: str) -> dict:
    """The case plus BOTH statuses — the shape the v11 case header needs."""
    case = get_case(case_id)
    filing = current_filing(case_id)
    return {
        **case,
        "filing_id": (filing or {}).get("id"),
        "workflow_status": nar1_case_status.derive(case, filing),
        "form_status": form_status(filing) if filing else None,
        "receipt": (filing or {}).get("receipt") or case.get("manual_receipt"),
    }

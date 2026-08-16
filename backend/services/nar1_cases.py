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

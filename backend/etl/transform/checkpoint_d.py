"""PBI-40 Block 3 — Checkpoint D transforms (pure functions, dict rows).

Builds `entities` rows for non-client corporate parties. The repoint of
corporate_entity_id and the is_corporate_party flag are set-based UPDATEs and
live in load/checkpoint_d.py.
"""
from datetime import datetime

from etl.reconciliation import ReconciliationReport

_MIN = datetime(1900, 1, 1)  # sorts None/oldest Effective last when picking current address


def pick_current_address_nr(addr_rows: list[dict]) -> int | None:
    """Given all RefAddress rows for one RefCode, pick the AddrNr of the current
    address: prefer not-cancelled, then latest Effective. Only a single address
    is needed to identify a corporate party on a form."""
    if not addr_rows:
        return None

    def sort_key(r: dict):
        not_cancelled = 1 if r.get("Cancelled") is None else 0
        eff = r.get("Effective")
        # None-effective sorts oldest so a dated row wins
        return (not_cancelled, eff is not None, eff or _MIN)

    best = max(addr_rows, key=sort_key)
    return best.get("AddrNr")


def _resolve_name(row: dict) -> str:
    """Corporate name from RefMaster.Name (CompName is empty for this
    population); fall back to CompName / SearchName, else 'UNKNOWN'."""
    for key in ("Name", "CompName", "SearchName"):
        val = row.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return "UNKNOWN"


def transform_nonclient_corporate(
    row: dict,
    addr_nr: int | None,
    address_id_by_vp_key: dict[str, str],
    party_refcodes: set[str],
    report: ReconciliationReport,
) -> dict:
    """VP RefMaster (RefType='C', non-client) row -> `entities` insert dict.

    is_client=false always; is_corporate_party=true iff the RefCode actually acts
    as a party (referenced in Officers/EntityOwners/Share_Transactions) — the 8
    unreferenced orphans load as neither (registry-only). Never drops: a missing
    address just yields registered_address_id=NULL."""
    refcode = row["RefCode"]
    registered_address_id = (
        address_id_by_vp_key.get(str(addr_nr)) if addr_nr is not None else None
    )
    if addr_nr is not None and registered_address_id is None:
        report.record_error(
            "nonclient_corporate_entities", refcode,
            f"RefAddress AddrNr={addr_nr} not found in addresses (address left NULL)")
    chinese = row.get("ChnsName")
    return {
        "vp_source_key": refcode,
        "company_name": _resolve_name(row),
        "company_name_zh": str(chinese).strip() if chinese and str(chinese).strip() else None,
        "is_client": False,
        "is_corporate_party": refcode in party_refcodes,
        "status": "live",
        "registered_address_id": registered_address_id,
    }

"""Which case and company a CR filing event is about, for the audit trail.

Moved out of routers/tpsi.py so a SERVICE can write an audit row about a filing
(`filings.settle_stale_claim`) without importing a router, and so the two
routers that need it do not import each other (code review 01, S-2).
"""
import sys
from typing import Optional

from db.supabase import get_supabase
from services import audit_subject
from services.tpsi import filings


def filing_subject(
    row: Optional[dict] = None,
    *,
    filing_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    nar1_case_id: Optional[str] = None,
) -> dict:
    """Which case and which company a CR filing event is about.

    Every `tpsi_filing` audit row used to carry a filing uuid and nothing else,
    so the whole CR half of the trail rendered with an empty subject — you could
    see that a return was validated, signed and submitted without being able to
    tell for whom. `tpsi_filings` already knows: it holds the entity and, for a
    NAR1, the case.

    ALSO FIXES WHAT WENT INTO `case_id`. Two routes wrote `nar1_case_id` there,
    but that column holds an ENTITY id by repo convention (routers/cases.py
    ::_audit_target) — a case id in it is invisible to every company-scoped
    query, which is exactly the trail these rows belong in. The case id now goes
    where it belongs, in `subject_id`.

    TWO STAGES, and the split is the point. The IDS come from what the caller
    already has and cost nothing; the NAMES need a lookup and are best-effort.
    So a Supabase failure downgrades the row to ids without a company name,
    rather than dropping the subject altogether.

    TOTALLY DEFENSIVE, and that is not belt-and-braces. This is spread into a
    `log_event(**...)` call, so it is evaluated by the CALLER — outside the
    try/except that makes an audit write unable to fail its operation. A raise
    here would turn a successful, chargeable CR submission into a 500.
    """
    try:
        if row is None and filing_id:
            row = filings.get_filing(filing_id)
    except Exception:  # noqa: BLE001
        row = None
    row = row or {}

    entity_id = entity_id or row.get("entity_id")
    case_id = nar1_case_id or row.get("nar1_case_id")
    if not entity_id and not case_id:
        return {}

    company: dict = {"id": entity_id} if entity_id else {}
    case: dict = {"id": case_id} if case_id else {}
    try:
        sb = get_supabase()
        if entity_id:
            company = (sb.table("entities").select("id, company_name, br_number")
                       .eq("id", entity_id).single().execute()).data or company
        if case_id:
            case = (sb.table("nar1_cases").select("id, case_no")
                    .eq("id", case_id).single().execute()).data or case
    except Exception as exc:  # noqa: BLE001
        print(f"[tpsi.audit_context] WARN: could not name the audit subject for filing "
              f"{filing_id or row.get('id')}: {exc}", file=sys.stderr)

    out = {"case_id": entity_id, "company_name": company.get("company_name")}
    if case_id:
        return {**out, **audit_subject.for_case(case, module=audit_subject.CR_FILING)}
    return {**out, **audit_subject.for_company(
        company, module=audit_subject.CR_FILING)}

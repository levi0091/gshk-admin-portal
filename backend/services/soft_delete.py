"""Soft delete of companies (`entities`) and natural persons (`persons`).

Migration 049 and `PRD/Pending/prd-soft-delete-companies-and-persons-2026-09-20.md`.
A deleted record stays in the database with `deleted_at`, `deleted_by` and
`deleted_reason` set, and disappears from every screen: the registry views
filter it out, the by-id routes answer 404, and it cannot be linked to a
company or have a case opened for it.

TWO REFUSALS DECIDE WHETHER A RECORD MAY GO (Levi 2026-09-20):

  * it is still a CURRENT director, secretary, shareholder or beneficial owner
    of a company that is not itself deleted. Deleting it would take it off
    that company's register, and the next NAR1 would go to CR without it --
    a statutory return changed by somebody who never looked at it. The user
    ends each appointment first, on the company it belongs to.
  * (a company) it has a NAR1 case CR has not registered and nobody closed. A
    case still being worked, or waiting on CR, is a statutory filing in
    flight, and a hidden company is somewhere nobody would see CR's answer.

Every function takes `sb` from its caller rather than calling get_supabase()
itself, so a router test that patches the router's client patches these
queries too, and never reaches a live project by accident.
"""
from datetime import datetime, timezone
from typing import Optional

#: Long enough to explain, short enough to be a reason and not a document.
REASON_MAX = 500

#: A case in any state but these still needs somebody to see it.
FINISHED_CASE_STATES = frozenset({"closed", "cr_registered"})

_RELATION_LABELS = {
    "director": "Director",
    "company_secretary": "Company secretary",
    "reserve_director": "Reserve director",
    "authorised_rep": "Authorised representative",
}

#: (table, label for a row, column holding the officer role if any)
_LINK_TABLES = (
    ("entity_officers", None, "role"),
    ("shareholdings", "Shareholder", None),
    ("beneficial_owners", "Beneficial owner", None),
)


def _rows(data) -> list:
    """PostgREST returns a list. Anything else is not an answer about a row.

    Said explicitly because the whole routers' test suites hand every query a
    MagicMock, whose attributes are all truthy: `data[0].get("deleted_at")` on
    one of those would call every record in the suite deleted.
    """
    return data if isinstance(data, list) else []


def is_deleted(sb, table: str, record_id: str) -> bool:
    """True only when the row exists AND carries a deletion."""
    rows = _rows(sb.table(table).select("id, deleted_at")
                 .eq("id", record_id).execute().data)
    return bool(rows) and rows[0].get("deleted_at") is not None


def clean_reason(raw: Optional[str]) -> str:
    """The reason, trimmed, or ValueError saying what is wrong with it."""
    reason = (raw or "").strip()
    if not reason:
        raise ValueError("Say why this record is being deleted.")
    if len(reason) > REASON_MAX:
        raise ValueError(
            f"The reason is {len(reason)} characters; keep it to {REASON_MAX}.")
    return reason


#: PostgREST's row cap. A query that could match more is read page by page.
_PAGE = 1000

#: How many blocking companies the dialog is given by name. GSHK's own entity
#: is the current secretary of ~5,600 companies; a list of 5,600 is not
#: something anybody reads, and fetching their names by id would put 5,600
#: uuids in one URL. The rest are COUNTED (`links_total`), never dropped.
SHOWN_LINKS = 50


def _paged(build) -> list:
    """Every row a query matches, `_PAGE` at a time. `build()` makes a fresh
    query each time, so no page inherits the last one's range."""
    rows: list = []
    start = 0
    while True:
        page = _rows(build().range(start, start + _PAGE - 1).execute().data)
        rows += page
        if len(page) < _PAGE:
            return rows
        start += _PAGE


def _deleted_entity_ids(sb) -> set[str]:
    """Every deleted company's id -- a short list, where the companies a record
    is linked to can be thousands, so this is the cheap side to ask about."""
    return {r["id"] for r in _paged(
        lambda: sb.table("entities").select("id").not_.is_("deleted_at", "null"))}


def _group(sb, links: list[tuple[str, str]]) -> tuple[list[dict], int]:
    """[(entity_id, role label)] -> the LIVE companies, roles merged.

    Returns up to SHOWN_LINKS of them by name, and how many there are in all.
    """
    deleted = _deleted_entity_ids(sb) if links else set()
    roles: dict[str, list[str]] = {}
    for entity_id, label in links:
        if entity_id in deleted:
            continue
        held = roles.setdefault(entity_id, [])
        if label not in held:
            held.append(label)
    if not roles:
        return [], 0

    shown = sorted(roles)[:SHOWN_LINKS]
    details = {r["id"]: r for r in _rows(
        sb.table("entities").select("id, company_name, br_number")
        .in_("id", shown).execute().data)}
    entries = [{
        "company_id": entity_id,
        "company_name": (details.get(entity_id) or {}).get("company_name"),
        "br_number": (details.get(entity_id) or {}).get("br_number"),
        "roles": roles[entity_id],
    } for entity_id in shown]
    entries.sort(key=lambda e: (e["company_name"] or "").lower())
    return entries, len(roles)


def _current_links(sb, column: str, value: str) -> list[tuple[str, str]]:
    """Every CURRENT appointment or holding where `column` = `value`.

    Current means `is_current` -- the column `nar1_source` reads to decide who
    is on a return, so this refuses exactly what the return would lose.
    """
    links: list[tuple[str, str]] = []
    for table, label, role_col in _LINK_TABLES:
        cols = "entity_id" + (f", {role_col}" if role_col else "")
        rows = _paged(lambda: sb.table(table).select(cols).eq(column, value)
                      .eq("is_current", True))
        for r in rows:
            role = (_RELATION_LABELS.get(r.get(role_col), "Officer")
                    if role_col else label)
            links.append((r["entity_id"], role))
    return links


def _blockers(sb, links, cases) -> dict:
    shown, total = _group(sb, links)
    return {"links": shown, "links_total": total, "cases": cases}


def person_blockers(sb, person_id: str) -> dict:
    """What stops a person being deleted: their current appointments."""
    links = _current_links(sb, "person_id", person_id)
    # The ETL's secretary register holds natural-person secretaries by id.
    rows = _paged(lambda: sb.table("company_secretaries").select("entity_id")
                  .eq("person_id", person_id).eq("is_current", True))
    links += [(r["entity_id"], "Company secretary") for r in rows]
    return _blockers(sb, links, [])


def _escape_like(text: str) -> str:
    return (text.replace("\\", "\\\\").replace("%", "\\%")
            .replace("_", "\\_"))


def _register_secretaryships(sb, company: dict) -> list[tuple[str, str]]:
    """Companies whose secretary REGISTER names this company, and would lose it.

    `company_secretaries` holds a corporate secretary by NAME only -- it has no
    corporate_entity_id -- and `nar1_source` resolves that name to exactly one
    live entity. If another live company has the same name the resolution is
    already ambiguous, and deleting this one is what fixes it, so that is not a
    reason to refuse.
    """
    name = (company.get("company_name") or "").strip()
    if not name:
        return []
    pattern = _escape_like(name)
    rows = _paged(lambda: sb.table("company_secretaries").select("entity_id")
                  .is_("person_id", "null").eq("is_current", True)
                  .ilike("secretary_name", pattern))
    if not rows:
        return []
    twins = _rows(sb.table("entities").select("id")
                  .ilike("company_name", pattern).is_("deleted_at", "null")
                  .neq("id", company["id"]).execute().data)
    if twins:
        return []
    return [(r["entity_id"], "Company secretary") for r in rows]


def company_blockers(sb, company: dict) -> dict:
    """What stops a company being deleted: its roles elsewhere, its live cases."""
    company_id = company["id"]
    links = [(e, role) for e, role in
             _current_links(sb, "corporate_entity_id", company_id)
             + _register_secretaryships(sb, company)
             if e != company_id]

    cases = _rows(sb.table("nar1_case_registry")
                  .select("id, case_no, workflow_status")
                  .eq("entity_id", company_id).execute().data)
    open_cases = [
        {"case_id": c["id"], "case_no": c.get("case_no"),
         "workflow_status": c.get("workflow_status")}
        for c in cases if c.get("workflow_status") not in FINISHED_CASE_STATES
    ]
    return _blockers(sb, links, open_cases)


def has_blockers(blockers: dict) -> bool:
    return bool(blockers.get("links") or blockers.get("cases"))


def describe(blockers: dict) -> str:
    """One sentence for a 409, naming what has to happen first."""
    parts = []
    links = blockers.get("links") or []
    if links:
        total = blockers.get("links_total") or len(links)
        names = ", ".join(e["company_name"] or e["company_id"] for e in links[:5])
        more = f" and {total - 5} more" if total > 5 else ""
        parts.append(f"it is still a current officer, shareholder or beneficial "
                     f"owner of {names}{more}; end those first")
    cases = blockers.get("cases") or []
    if cases:
        nos = ", ".join(c["case_no"] or c["case_id"] for c in cases)
        parts.append(f"case {nos} is still open; close it first, or wait until "
                     f"the Companies Registry has registered it")
    return "Cannot delete: " + "; and ".join(parts) + "."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mark_deleted(sb, table: str, record_id: str, *, user_id: str,
                 reason: str) -> Optional[dict]:
    """Delete, but only a row that is not deleted already.

    Conditional, like closing a case (nar1_cases.close_case): two people
    pressing Delete together must not both succeed, or the trail records two
    deletions and the second overwrites the first's reason.
    """
    rows = _rows(sb.table(table).update({
        "deleted_at": _now(), "deleted_by": user_id, "deleted_reason": reason,
    }).eq("id", record_id).is_("deleted_at", "null").execute().data)
    return rows[0] if rows else None


def restore(sb, table: str, record_id: str) -> Optional[dict]:
    """Undelete, but only a row that is deleted."""
    rows = _rows(sb.table(table).update({
        "deleted_at": None, "deleted_by": None, "deleted_reason": None,
    }).eq("id", record_id).not_.is_("deleted_at", "null").execute().data)
    return rows[0] if rows else None


def with_deleter_names(sb, rows: list[dict]) -> list[dict]:
    """Add `deleted_by_name` -- who pressed Delete, for the banner and the list."""
    ids = {r["deleted_by"] for r in rows if r.get("deleted_by")}
    names: dict[str, str] = {}
    if ids:
        users = _rows(sb.table("users").select("id, display_name, email")
                      .in_("id", sorted(ids)).execute().data)
        names = {u["id"]: u.get("display_name") or u.get("email") for u in users}
    for r in rows:
        r["deleted_by_name"] = names.get(r.get("deleted_by"))
    return rows


def list_deleted(sb, table: str, *, cols: str, search_or: Optional[str],
                 page: int, page_size: int) -> tuple[list[dict], int]:
    """One page of deleted rows, most recently deleted first."""
    q = (sb.table(table).select(cols, count="exact")
         .not_.is_("deleted_at", "null"))
    if search_or:
        q = q.or_(search_or)
    offset = (page - 1) * page_size
    res = (q.order("deleted_at", desc=True)
           .range(offset, offset + page_size - 1).execute())
    return with_deleter_names(sb, _rows(res.data)), (res.count or 0)

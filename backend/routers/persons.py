"""Persons CRUD + person-scoped documents (PBI-39 Block 1).

Gated by require_permission("persons"/"documents", ...). Every mutation audits.
Person Profile carries fields, identity documents, residential address, a role
roll-up (read-only from the link tables), and document history.
"""
import asyncio
import sys
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from pydantic import BaseModel

from middleware.auth import require_permission, has_permission
from db.supabase import get_supabase
from services.audit_service import log_event, log_events
from services import audit_subject
from services import (
    audit_events, document_service, document_sections, address_service,
    table_filters as tf, soft_delete,
)
from routers.companies import AddressIn, _address_audit_entries
from services.hkid import is_valid_hkid
from services.officer_changes import eservice, particulars
from services import person_particulars
from services.tpsi.forms.cr_vocabularies import resolve_country

router = APIRouter()

#: The same words for a deleted person as for one that never existed.
PERSON_NOT_FOUND = "Person not found"


def live_person(permission: str):
    """`require_permission("persons", permission)`, then 404 a DELETED person.

    See `routers.companies.live_company`, which this mirrors.
    """
    guard = require_permission("persons", permission)

    async def live_person_check(person_id: str, user=Depends(guard)) -> dict:
        if soft_delete.is_deleted(get_supabase(), "persons", person_id):
            raise HTTPException(status_code=404, detail=PERSON_NOT_FOUND)
        return user

    live_person_check.refuses_deleted = "persons"
    return live_person_check

_EDITABLE_FIELDS = {
    "full_name", "given_names", "surname", "full_name_zh", "former_name",
    # CR asks for Previous Names in both languages and Alias separately from
    # them -- a previous name is one you no longer use, an alias one you also
    # use. The ETL used to merge them into `former_name` (migration 028).
    "former_name_zh", "alias_en", "alias_zh",
    "email", "phone", "date_of_birth", "gender", "nationality",
    "nationality_code", "nationality_origin", "occupation", "place_of_birth",
    "marital_status", "date_of_death", "residential_address_id",
    # A trust-or-company-service-provider licence held by an INDIVIDUAL
    # (migration 038). The Company Secretary tile printed this field and could
    # only ever read it off a corporate party, so a licensed person showed an
    # em dash and no screen in the portal could set it.
    "tcsp_licence_no", "tcsp_exemption_reason",
    # The two STORED inputs to a client's VIP status (migration 041). The
    # verdict itself is derived on read — see `vip_status`.
    "is_affiliated_agent", "is_vip_marked",
}

#: "VIP clients are those who have more than three companies with us" (GSHK
#: mock-up feedback, 16 July). More than, not at least: three is standard.
VIP_COMPANY_THRESHOLD = 3


def vip_status(person: dict, rollup: list[dict]) -> dict:
    """Is this client a VIP, and why — the rule wireframe v11 draws.

    VIP if an affiliated agent ("agents are considered VIP clients"), OR holding
    roles in more than `VIP_COMPANY_THRESHOLD` companies with GSHK, OR marked
    VIP by a colleague.

    DERIVED, never stored (migration 041). The company count comes off the same
    roll-up the profile header counts, so the bar and the role pills beside it
    cannot disagree; a stored verdict would stay true after a client dropped to
    two companies.

    COMPANIES, not appointments: a director who is also a shareholder of the
    same company holds two roles in ONE company. Only current roles count — a
    resigned directorship is not business GSHK still has with them. An absent
    `is_current` (beneficial owners carry none) reads as current.

    `automatic` is what the screen locks the manual switch on: a client who is
    VIP by rule cannot be switched off by hand, because the rule would only say
    so again on the next read.
    """
    companies = {
        r["entity_id"] for r in rollup
        if r.get("entity_id") and r.get("is_current") is not False
    }
    reasons = []
    if person.get("is_affiliated_agent") is True:
        reasons.append("affiliated_agent")
    if len(companies) > VIP_COMPANY_THRESHOLD:
        reasons.append("companies")
    automatic = bool(reasons)
    marked = person.get("is_vip_marked") is True
    if marked:
        reasons.append("marked")
    return {
        "is_vip": automatic or marked,
        "automatic": automatic,
        "reasons": reasons,
        "company_count": len(companies),
        "threshold": VIP_COMPANY_THRESHOLD,
    }


class IdentityDocumentIn(BaseModel):
    """One identity document, as `POST /persons/{id}/identity-documents` takes it.

    Both NAR1 and NNC1 carry an individual's HKID or passport number for every
    director; a person without one blocks the return at
    `nar1_mapper._individual_id`. The number is recorded on the PROFILE, in the
    Identity Documents section, where the scan and the type-specific fields
    live — creating a person does not ask for one (Levi 2026-09-04).
    """

    class Config:
        extra = "forbid"

    id_type: str
    id_number: str
    issuing_country: Optional[str] = None
    issue_date: Optional[str] = None
    expiry_date: Optional[str] = None
    is_primary: bool = True


class CreatePersonRequest(BaseModel):
    # Matches `UpdatePersonRequest`. A field this model does not declare is
    # REFUSED rather than dropped on the floor: `identity_document` used to be
    # here and is not any more, and a caller still sending one has to be told
    # so, not have the number silently discarded on the way to the database.
    class Config:
        extra = "forbid"

    full_name: str
    given_names: Optional[str] = None
    surname: Optional[str] = None
    full_name_zh: Optional[str] = None
    former_name: Optional[str] = None
    former_name_zh: Optional[str] = None
    alias_en: Optional[str] = None
    alias_zh: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None
    nationality_code: Optional[str] = None
    # CR asks for nationality of ORIGIN separately from current nationality
    # (`persons.nationality_origin`, migration 007). It was editable on the
    # profile and absent from creation, so it could only ever be filled in on a
    # second visit.
    nationality_origin: Optional[str] = None
    occupation: Optional[str] = None
    place_of_birth: Optional[str] = None
    marital_status: Optional[str] = None
    residential_address_id: Optional[str] = None
    # A TCSP licence held by an INDIVIDUAL (migration 038). Same parity rule as
    # `nationality_origin` above -- and it has to be DECLARED, not merely
    # allowed: `extra = "forbid"` above means an undeclared field is a 422, so
    # the New Person form could not send one at all.
    tcsp_licence_no: Optional[str] = None
    tcsp_exemption_reason: Optional[str] = None
    # Declared for add/edit parity (migration 041): an agent is often known to
    # be one on the day they are entered, and `extra = "forbid"` would 422 it.
    is_affiliated_agent: Optional[bool] = None
    is_vip_marked: Optional[bool] = None


class UpdatePersonRequest(BaseModel):
    class Config:
        extra = "forbid"

    full_name: Optional[str] = None
    given_names: Optional[str] = None
    surname: Optional[str] = None
    full_name_zh: Optional[str] = None
    former_name: Optional[str] = None
    former_name_zh: Optional[str] = None
    alias_en: Optional[str] = None
    alias_zh: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None
    nationality_code: Optional[str] = None
    nationality_origin: Optional[str] = None
    occupation: Optional[str] = None
    place_of_birth: Optional[str] = None
    marital_status: Optional[str] = None
    date_of_death: Optional[str] = None
    residential_address_id: Optional[str] = None
    tcsp_licence_no: Optional[str] = None
    tcsp_exemption_reason: Optional[str] = None
    # `False` is an answer, not an absence: update_person filters on `is not
    # None`, so un-flagging an agent or un-marking a VIP reaches the database.
    is_affiliated_agent: Optional[bool] = None
    is_vip_marked: Optional[bool] = None


def _person_subject(sb, person_id: str) -> dict:
    """The person an audit row is about, for routes that hold only their id.

    Failure is swallowed: a row edit must not be turned into a 500 by the
    lookup that only makes its audit entry nicer to read.
    """
    try:
        row = (
            sb.table("persons").select("id, full_name")
            .eq("id", person_id).single().execute()
        ).data
    except Exception:  # noqa: BLE001
        return {"id": person_id}
    return row or {"id": person_id}


def _role_rollup(sb, person_id: str) -> list[dict]:
    """Read-only 'Director of X, Shareholder of Y' roll-up from the link tables."""
    roll: list[dict] = []
    specs = [
        ("entity_officers", "officer", "role"),
        ("shareholdings", "shareholder", None),
        ("beneficial_owners", "beneficial_owner", "owner_type"),
    ]
    entity_ids: set[str] = set()
    collected: list[dict] = []
    for table, kind, role_col in specs:
        rows = (sb.table(table).select("*").eq("person_id", person_id).execute().data) or []
        for r in rows:
            entity_ids.add(r["entity_id"])
            collected.append({
                "relation": kind,
                "entity_id": r["entity_id"],
                "role": r.get(role_col) if role_col else "shareholder",
                "is_current": r.get("is_current"),
                "appointed_date": r.get("appointed_date"),
                "resigned_date": r.get("resigned_date"),
            })
    names: dict[str, str] = {}
    gone: set[str] = set()
    if entity_ids:
        ents = (
            sb.table("entities").select("id, company_name, deleted_at")
            .in_("id", list(entity_ids)).execute().data
        ) or []
        names = {e["id"]: e["company_name"] for e in ents}
        gone = {e["id"] for e in ents if e.get("deleted_at")}
    for c in collected:
        # A role at a DELETED company is not shown, and so not counted towards
        # VIP status either (migration 049).
        if c["entity_id"] in gone:
            continue
        c["company_name"] = names.get(c["entity_id"])
        roll.append(c)
    return roll


# Persons Registry role tabs (wireframe_v7 s10) -> person_registry view flags.
_ROLE_FLAGS = {
    "director": "is_director",
    "shareholder": "is_shareholder",
    "secretary": "is_secretary",
    "beneficial_owner": "is_beneficial_owner",
}
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200

# Whitelisted — `sort` reaches PostgREST's order clause.
_SORTABLE = {
    "full_name", "full_name_zh", "email", "nationality", "date_of_birth",
    "primary_id_type", "primary_id_number", "created_at", "updated_at",
}

#: `id_document_type` (migration 003). The Identity column shows the type and
#: the number together, so its filter offers both: pick the types, or search the
#: number.
_ID_TYPES = {"hkid", "passport", "china_id", "other"}

#: Columns the per-column header filters may narrow on. The four role flags are
#: NOT here — the role tabs already own them, and two controls writing the same
#: filter through different grammars is how they drift apart.
_FILTERABLE = {
    "full_name": tf.text(),
    "full_name_zh": tf.text(),
    "email": tf.text(),
    "nationality": tf.text(),
    "primary_id_type": tf.enum(_ID_TYPES),
    "primary_id_number": tf.text(),
    "date_of_birth": tf.date(),
    "created_at": tf.timestamp(),
    "updated_at": tf.timestamp(),
}


def _people_with_id_number(sb, search: str) -> list[str]:
    """Person ids holding ANY identity document whose number contains `search`
    (the registry view carries only the primary one). Never raises."""
    try:
        rows = (sb.table("person_identity_documents").select("person_id")
                .ilike("id_number", f"%{search}%").limit(200).execute().data) or []
        return sorted({str(r["person_id"]) for r in rows if r.get("person_id")})
    except Exception as exc:  # noqa: BLE001
        print(f"[persons] identity-number search skipped: {exc!r}", file=sys.stderr)
        return []


def _attach_id_counts(sb, rows: list[dict]) -> None:
    """`id_count` on each row, so the list can say a person holds more than one
    identity document. Never raises: without it the row reads as before."""
    ids = [r["id"] for r in rows if r.get("id")]
    if not ids:
        return
    try:
        docs = (sb.table("person_identity_documents").select("person_id")
                .in_("person_id", ids).execute().data) or []
    except Exception as exc:  # noqa: BLE001
        print(f"[persons] identity counts skipped: {exc!r}", file=sys.stderr)
        return
    counts: dict[str, int] = {}
    for doc in docs:
        counts[str(doc.get("person_id"))] = counts.get(str(doc.get("person_id")), 0) + 1
    for row in rows:
        row["id_count"] = counts.get(str(row.get("id")), 0)


@router.get("")
async def list_persons(
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
    dir: str = Query("asc"),
    filter_: list[str] = Query(
        default_factory=list, alias="filter",
        description="repeatable column:op:value — see services/table_filters",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
    user=Depends(require_permission("persons", "read")),
):
    """Persons Registry — served by the `person_registry` view (migration 009).

    The view flattens the four link tables into per-person role flags, so role
    filtering and *distinct-person* counts are a plain query. Counting rows on
    the link tables directly would over-count (one person, many companies).
    """
    if role and role not in _ROLE_FLAGS:
        raise HTTPException(status_code=422, detail=f"Unknown role: {role}")
    if sort and sort not in _SORTABLE:
        raise HTTPException(status_code=422, detail=f"Cannot sort by '{sort}'")
    try:
        col_filters = tf.parse(filter_, _FILTERABLE)
    except tf.FilterError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    sb = get_supabase()
    # Any of the person's ID numbers, not only the primary (Levi 2026-10-05: "We
    # do have clients holding 2 passports"). Best-effort: a failed read leaves
    # the search as it was rather than failing the list.
    also = _people_with_id_number(sb, search) if search else []

    def base(cols: str, count: Optional[str] = None):
        q = (sb.table("person_registry").select(cols, count=count) if count
             else sb.table("person_registry").select(cols))
        # Inside base(), so the role-tab counts and the pager describe the same
        # set the rows are drawn from.
        q = tf.apply(q, col_filters)
        if search:
            q = q.or_(
                f"full_name.ilike.%{search}%,"
                f"full_name_zh.ilike.%{search}%,"
                f"email.ilike.%{search}%,"
                f"primary_id_number.ilike.%{search}%"
                + (f",id.in.({','.join(also)})" if also else "")
            )
        return q

    def count_of(flag: Optional[str]) -> int:
        q = base("id", count="exact")
        if flag:
            q = q.eq(flag, True)
        return q.limit(1).execute().count or 0

    q = base("*")
    if role:
        q = q.eq(_ROLE_FLAGS[role], True)
    offset = (page - 1) * page_size

    # The 5 role counts and the page query are independent of one another. Run
    # sequentially they were 6 x ~200ms of pure round-trip latency on every load.
    names = list(_ROLE_FLAGS)
    results = await asyncio.gather(
        asyncio.to_thread(count_of, None),
        *[asyncio.to_thread(count_of, _ROLE_FLAGS[n]) for n in names],
        asyncio.to_thread(
            lambda: (q.order(sort or "full_name", desc=(dir == "desc"))
                     .range(offset, offset + page_size - 1).execute().data) or []
        ),
    )
    role_counts = {"all": results[0]}
    for n, v in zip(names, results[1:-1]):
        role_counts[n] = v
    rows = results[-1]
    _attach_id_counts(sb, rows)

    total = role_counts[role] if role else role_counts["all"]
    return {
        "persons": rows,
        "role_counts": role_counts,
        "page": page,
        "page_size": page_size,
        "total": total,
    }


_DELETED_COLS = (
    "id, full_name, full_name_zh, email, nationality, date_of_birth, "
    "created_at, deleted_at, deleted_by, deleted_reason"
)


@router.get("/deleted")
async def list_deleted_persons(
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
    user=Depends(require_permission("persons", "delete")),
):
    """The Persons Registry's Deleted tab, for a role that could restore one.

    Declared BEFORE `/{person_id}`, or "deleted" would be read as an id. Reads
    `persons`, not `person_registry`, which hides exactly these rows.
    """
    sb = get_supabase()
    search_or = None
    if search:
        search_or = (f"full_name.ilike.%{search}%,"
                     f"full_name_zh.ilike.%{search}%,"
                     f"email.ilike.%{search}%")
    rows, total = soft_delete.list_deleted(
        sb, "persons", cols=_DELETED_COLS, search_or=search_or,
        page=page, page_size=page_size)
    return {"persons": rows, "page": page, "page_size": page_size,
            "total": total}


@router.get("/{person_id}")
async def get_person(
    person_id: str,
    user=Depends(require_permission("persons", "read")),
):
    sb = get_supabase()
    person = (
        sb.table("persons").select("*").eq("id", person_id).single().execute()
    ).data
    if not person:
        raise HTTPException(status_code=404, detail=PERSON_NOT_FOUND)
    # 404 to anybody who could not restore it; read-only to somebody who could.
    if person.get("deleted_at"):
        if not has_permission(user, "persons", "delete"):
            raise HTTPException(status_code=404, detail=PERSON_NOT_FOUND)
        soft_delete.with_deleter_names(sb, [person])

    identity_docs = (
        sb.table("person_identity_documents").select("*")
        .eq("person_id", person_id).execute().data
    ) or []
    address = None
    if person.get("residential_address_id"):
        address = (
            sb.table("addresses").select("*")
            .eq("id", person["residential_address_id"]).single().execute()
        ).data
        if address:
            address["shared_by"] = address_service.count_references(sb, address["id"])
    # Removed documents come back too — they are dropped from their section and
    # kept, marked, in Document History.
    documents = document_service.list_documents(
        owner_kind="person", owner_id=person_id, include_deleted=True)

    rollup = _role_rollup(sb, person_id)
    return {
        **person,
        "identity_documents": identity_docs,
        "residential_address": address,
        "role_rollup": rollup,
        "vip": vip_status(person, rollup),
        "documents": documents,
    }


@router.post("", status_code=201)
async def create_person(
    body: CreatePersonRequest,
    user=Depends(require_permission("persons", "write")),
):
    sb = get_supabase()
    row = {k: v for k, v in body.model_dump().items() if v is not None}
    created = sb.table("persons").insert(row).execute().data
    if not created:
        raise HTTPException(status_code=400, detail="Person insert failed")
    person = created[0]

    await log_event(
        case_id=None, user_id=user["id"],
        user_display_name=user["display_name"], action_type="PERSON_CREATED",
        event_code=audit_events.VP_NEW_MASTER_FILE,   # Viewpoint: New Master File
        company_name=person["full_name"],             # subject of the event
        # A person is quoted by an identity number, and a brand-new record has
        # none: their documents are added on the profile, in the section that
        # owns them. The reference fills itself in on the first one.
        **audit_subject.for_person(person),
        entity_type="person", entity_id=str(person["id"]),
        new_value=person["full_name"], after_state=row,
    )
    return person


@router.patch("/{person_id}")
async def update_person(
    person_id: str,
    body: UpdatePersonRequest,
    user=Depends(live_person("write")),
):
    updates = {k: v for k, v in body.model_dump().items()
               if v is not None and k in _EDITABLE_FIELDS}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    sb = get_supabase()
    current = (
        sb.table("persons").select("*").eq("id", person_id).single().execute()
    ).data
    if not current:
        raise HTTPException(status_code=404, detail="Person not found")

    # What CR holds, taken BEFORE the write (spec §4): the first edit of a
    # tracked particular is what an ND2B will later be diffed against.
    if particulars.TRACKED_PERSON_FIELDS & updates.keys():
        particulars.capture_before_edit(person_id=person_id, user_id=user["id"])

    updated = (
        sb.table("persons").update(updates).eq("id", person_id).execute()
    ).data[0]

    subject = audit_subject.for_person(
        current, id_number=audit_subject.primary_id_number(sb, person_id))
    await log_events([
        dict(
            case_id=None, user_id=user["id"],
            user_display_name=user["display_name"], action_type="PERSON_FIELD_UPDATED",
            # KYC fields are Compliance (CPC) in Viewpoint; names/contact are ADC.
            event_code=audit_events.person_field_code(field),
            company_name=current.get("full_name"),
            **subject,
            entity_type="person", entity_id=str(person_id),
            old_value=old_val, new_value=new_val,
            before_state={"field": field, "old": old_val},
            after_state={"field": field, "new": new_val},
        )
        for field, new_val in updates.items()
        for old_val in [current.get(field)]
        if old_val != new_val
    ])
    return updated


# --------------------------------------------------------------------------- #
#  Soft delete (migration 049) -- `persons:delete`. Rules: services/soft_delete.
# --------------------------------------------------------------------------- #

class DeleteRequest(BaseModel):
    class Config:
        extra = "forbid"

    reason: str


def _deletion_target(sb, person_id: str) -> dict:
    rows = (sb.table("persons").select("id, full_name, deleted_at")
            .eq("id", person_id).execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail=PERSON_NOT_FOUND)
    return rows[0]


@router.get("/{person_id}/deletion-check")
async def person_deletion_check(
    person_id: str,
    user=Depends(live_person("delete")),
):
    """What would stop this person being deleted, for the dialog to show
    before anybody types a reason. The delete itself asks again."""
    sb = get_supabase()
    _deletion_target(sb, person_id)
    blockers = soft_delete.person_blockers(sb, person_id)
    return {"can_delete": not soft_delete.has_blockers(blockers), **blockers}


@router.post("/{person_id}/delete")
async def delete_person(
    person_id: str,
    body: DeleteRequest,
    user=Depends(live_person("delete")),
):
    try:
        reason = soft_delete.clean_reason(body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    sb = get_supabase()
    person = _deletion_target(sb, person_id)
    blockers = soft_delete.person_blockers(sb, person_id)
    if soft_delete.has_blockers(blockers):
        raise HTTPException(status_code=409, detail=soft_delete.describe(blockers))

    deleted = soft_delete.mark_deleted(
        sb, "persons", person_id, user_id=user["id"], reason=reason)
    if not deleted:
        raise HTTPException(status_code=404, detail=PERSON_NOT_FOUND)

    await log_event(
        case_id=None, user_id=user["id"],
        user_display_name=user["display_name"], action_type="PERSON_DELETED",
        event_code=audit_events.GF_PERSON_DELETED,
        company_name=person.get("full_name"),
        **audit_subject.for_person(
            person, id_number=audit_subject.primary_id_number(sb, person_id)),
        entity_type="person", entity_id=str(person_id),
        new_value=reason,
        before_state={"deleted_at": None},
        after_state={"deleted_at": deleted.get("deleted_at"),
                     "deleted_reason": reason},
    )
    return deleted


@router.post("/{person_id}/restore")
async def restore_person(
    person_id: str,
    user=Depends(require_permission("persons", "delete")),
):
    """Undelete. Not `live_person` -- a deleted person is the whole point."""
    sb = get_supabase()
    person = _deletion_target(sb, person_id)
    if not person.get("deleted_at"):
        raise HTTPException(status_code=409, detail="This person is not deleted.")
    restored = soft_delete.restore(sb, "persons", person_id)
    if not restored:
        raise HTTPException(status_code=409, detail="This person is not deleted.")

    await log_event(
        case_id=None, user_id=user["id"],
        user_display_name=user["display_name"], action_type="PERSON_RESTORED",
        event_code=audit_events.GF_PERSON_RESTORED,
        company_name=person.get("full_name"),
        **audit_subject.for_person(
            person, id_number=audit_subject.primary_id_number(sb, person_id)),
        entity_type="person", entity_id=str(person_id),
        new_value="Restored",
        before_state={"deleted_at": person.get("deleted_at")},
        after_state={"deleted_at": None},
    )
    return restored


class UpdateIdentityDocumentRequest(BaseModel):
    class Config:
        extra = "forbid"

    id_number: Optional[str] = None
    issuing_country: Optional[str] = None
    issue_date: Optional[str] = None
    expiry_date: Optional[str] = None
    is_primary: Optional[bool] = None


#: `reminder_date` is gone from here and from the screen (Levi 2026-09-04:
#: "remove the renewal reminder, it is not required, i didnt ask for this").
#: The COLUMN is kept, as `place_of_issue` was — Viewpoint's ReminderDate values
#: survive and the decision is reversible; nothing writes it any more.
_ID_DOC_FIELDS = {"id_number", "issuing_country", "issue_date", "expiry_date",
                  "is_primary"}

#: CR gives the passport number 25 characters (indvPptNo / passportNo).
_PASSPORT_MAX = 25


def _clean_id_number(id_type: str, raw: str) -> str:
    """CR's rules for an identity number, or a 422 saying which one it broke.

    Shared by the create and the edit path so the two cannot disagree — the
    same argument the CR form contract makes for lengths (CLAUDE.md §3). What
    differs between them is only WHEN it runs: editing checks the number only
    when the number is itself being written (grandfathering, PRD D4), creating
    always checks, because a new row has no legacy to protect.
    """
    number = str(raw or "").strip()
    if id_type == "hkid" and not is_valid_hkid(number):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{number!r} is not a valid HKID: the check digit does not "
                "match. If this is not a Hong Kong identity card, change "
                "the document type instead."
            ),
        )
    if id_type == "passport" and len(number) > _PASSPORT_MAX:
        raise HTTPException(
            status_code=422,
            detail=f"CR allows {_PASSPORT_MAX} characters for a passport "
                   f"number; this is {len(number)}",
        )
    return number


def _clean_issuing_country(raw) -> Optional[str]:
    """`indvPptIssCtry` takes CR's codes, not Viewpoint's.

    The same defect as the address country, where picking the Chinese "Hong
    Kong" stored 'HK-CH' and killed the return.
    """
    country = str(raw or "").strip()
    if country and resolve_country(country) is None:
        raise HTTPException(
            status_code=422,
            detail=(f"{country!r} is not a country or region the Companies "
                    "Registry has a code for. Pick one from the list."),
        )
    return country or None


#: Why a required identity field matters, in the words of the thing that will
#: refuse it later. A message that says only "required" leaves the operator
#: guessing whether it is our rule or CR's.
_MISSING_IDENTITY_FIELD = {
    ("passport", "issuing_country"): (
        "CR refuses a passport number without its issuing country — pick the "
        "country or region that issued this passport."
    ),
}


def _validated_identity_row(body: IdentityDocumentIn) -> dict:
    """A `person_identity_documents` row from a create request, CR-checked.

    Runs BEFORE the person is inserted on the create path, so a bad passport
    number cannot leave a half-made person behind.
    """
    id_type = str(body.id_type or "").strip()
    if id_type not in document_sections.CODE_BY_ID_TYPE:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown identity document type {id_type!r}. "
                   f"Expected one of: "
                   f"{', '.join(sorted(document_sections.CODE_BY_ID_TYPE))}",
        )

    row = {
        "id_type": id_type,
        "id_number": _clean_id_number(id_type, body.id_number),
        "is_primary": bool(body.is_primary),
    }
    if not row["id_number"]:
        raise HTTPException(
            status_code=422, detail="An identity document needs a number")

    allowed = document_sections.identity_fields(id_type)
    if "issuing_country" in allowed:
        row["issuing_country"] = _clean_issuing_country(body.issuing_country)
    if "issue_date" in allowed and body.issue_date:
        row["issue_date"] = body.issue_date
    if "expiry_date" in allowed and body.expiry_date:
        row["expiry_date"] = body.expiry_date

    for field in document_sections.required_identity_fields(id_type):
        if not row.get(field):
            raise HTTPException(
                status_code=422,
                detail=_MISSING_IDENTITY_FIELD.get(
                    (id_type, field),
                    f"{field.replace('_', ' ').title()} is required for this "
                    "identity document type",
                ),
            )
    return row


@router.patch("/{person_id}/identity-documents/{document_id}")
async def update_identity_document(
    person_id: str,
    document_id: str,
    body: UpdateIdentityDocumentRequest,
    user=Depends(live_person("write")),
):
    """Edit one identity document.

    An HKID carries its own check digit, so a transposed digit is caught here
    rather than by CR after a chargeable submit. The check runs **only when
    `id_number` is itself being written** (PRD D4): 31 rows in DEV would fail
    it -- 29 of them Mainland China ID numbers mis-typed as HKID -- and
    freezing those records over a field nobody is touching would punish the
    wrong person. Correcting the number is what forces the number to be right.

    A passport gets length and non-emptiness only. Passports have no check
    digit outside the machine-readable zone, and a validator that cannot
    validate should not pretend to.
    """
    updates = {k: v for k, v in body.model_dump().items()
               if v is not None and k in _ID_DOC_FIELDS}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    sb = get_supabase()
    current = (
        sb.table("person_identity_documents").select("*")
        .eq("id", document_id).eq("person_id", person_id).single().execute()
    ).data
    if not current:
        raise HTTPException(status_code=404, detail="Identity document not found")

    if "id_number" in updates:
        updates["id_number"] = _clean_id_number(
            current.get("id_type"), updates["id_number"])

    if "issuing_country" in updates:
        updates["issuing_country"] = _clean_issuing_country(
            updates["issuing_country"])

    # An identity number is ND2B items (g)/(h): baseline first (spec §4).
    particulars.capture_before_edit(person_id=person_id, user_id=user["id"])

    updated = (
        sb.table("person_identity_documents").update(updates)
        .eq("id", document_id).execute()
    ).data[0]

    # Promoting one demotes the rest. Without this, "Make primary" produced a
    # SECOND primary: `person_registry` and `audit_subject.primary_id_number`
    # both order on `is_primary DESC, created_at ASC`, so the person would keep
    # being quoted by whichever row was older — the button would appear to do
    # nothing. Demotion is never written directly; it is only ever a
    # consequence of a promotion.
    if updates.get("is_primary"):
        (sb.table("person_identity_documents").update({"is_primary": False})
         .eq("person_id", person_id).neq("id", document_id).execute())

    # WHOSE document. These rows carried no subject name at all, so an edit to
    # a passport number read as "Change Compliance Details" against nothing.
    # The number quoted is the one AFTER the edit — the trail says which record
    # the reader will find if they go looking now.
    person = _person_subject(sb, person_id)
    await log_events([
        dict(
            case_id=None, user_id=user["id"],
            user_display_name=user["display_name"],
            action_type="PERSON_FIELD_UPDATED",
            event_code=audit_events.VP_COMPLIANCE,
            company_name=person.get("full_name"),
            **audit_subject.for_person(
                person, id_number=audit_subject.primary_id_number(sb, person_id)),
            entity_type="person", entity_id=str(person_id),
            old_value=old_val, new_value=new_val,
            before_state={"field": field, "old": old_val},
            after_state={"field": field, "new": new_val},
        )
        for field, new_val in updates.items()
        for old_val in [current.get(field)]
        if old_val != new_val
    ])
    return updated


@router.post("/{person_id}/identity-documents", status_code=201)
async def save_identity_document(
    person_id: str,
    id_type: str = Form(...),
    id_number: str = Form(...),
    issuing_country: Optional[str] = Form(None),
    issue_date: Optional[str] = Form(None),
    expiry_date: Optional[str] = Form(None),
    is_primary: bool = Form(False),
    title: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    user=Depends(live_person("write")),
):
    """Record an identity document, and optionally the scan that evidences it.

    THE DEFECT THIS FIXES (Levi 2026-09-04): "when i upload a passport it does
    not overwrite the existing passport record ... it only simply adds a record
    into the document history section". Both halves were true and neither was
    an accident of storage:

      * the upload wrote a `documents` row and NEVER TOUCHED
        `person_identity_documents`, which is the table NAR1 and NNC1 are
        actually filed from — so a passport scan and the passport number it
        shows had no relationship at all; and
      * every identity scan shared one document type, `id_scan`, and
        `upload_document` versions in place on `(owner, type)`, so a passport
        uploaded after an HKID became **version 2 of the HKID**.

    Migration 036 splits the type per `id_document_type`; this route is the
    other half. It UPSERTS on `(person_id, id_type)` — one passport row per
    person, replaced in place — while the FILE still versions, so the number is
    overwritten and the scan's history is preserved. Those are different
    questions and they now get different answers.

    The file is OPTIONAL here and required in every other section. A passport
    recorded from a number GSHK already holds is filable; refusing to store it
    until somebody finds a scan would block a return over evidence CR never asks
    to see.
    """
    row = _validated_identity_row(IdentityDocumentIn(
        id_type=id_type, id_number=id_number, issuing_country=issuing_country,
        issue_date=issue_date, expiry_date=expiry_date, is_primary=is_primary,
    ))

    sb = get_supabase()
    person = (
        sb.table("persons").select("id, full_name")
        .eq("id", person_id).single().execute()
    ).data
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    # A new or replaced HKID / passport is ND2B item (g)/(h): baseline first.
    particulars.capture_before_edit(person_id=person_id, user_id=user["id"])

    held = (
        sb.table("person_identity_documents").select("*")
        .eq("person_id", person_id).execute().data
    ) or []
    current = next((d for d in held if d.get("id_type") == row["id_type"]), None)

    # The first document a person holds is their primary one whatever the form
    # said. The profile header and `audit_subject.primary_id_number` both quote
    # the primary, and a person whose only identity document is not primary
    # reads as a person with none.
    if not held:
        row["is_primary"] = True
    # `is_primary` PROMOTES and never demotes. Re-recording the passport a
    # person is quoted by must not quietly stop them being quoted by it —
    # demotion happens as a consequence of promoting something else, below.
    elif current and not row["is_primary"]:
        row["is_primary"] = bool(current.get("is_primary"))

    # The scan first: if Storage refuses, nothing has been changed yet, and the
    # operator retries one action rather than discovering a number saved against
    # a file that never arrived.
    scan = None
    if file is not None and (file.filename or ""):
        content = await file.read()
        # No file is fine; an EMPTY one is not. Ignoring it would report a
        # successful save of a scan that does not exist.
        if not content:
            raise HTTPException(
                status_code=422,
                detail=f"{file.filename!r} is empty — attach the scan again, or "
                       "save the number on its own.",
            )
        scan = await document_service.upload_document(
            owner_kind="person", owner_id=person_id,
            document_type_code=document_sections.CODE_BY_ID_TYPE[row["id_type"]],
            file_name=file.filename, content=content,
            mime_type=file.content_type, title=title, user=user,
        )
        row["scan_document_id"] = scan["id"]

    if current:
        saved = (
            sb.table("person_identity_documents").update(row)
            .eq("id", current["id"]).execute()
        ).data[0]
    else:
        saved = (
            sb.table("person_identity_documents")
            .insert({**row, "person_id": person_id}).execute()
        ).data[0]

    # One primary per person, or the header quotes whichever row came back
    # first. Only enforced on write — a legacy person with two is left alone
    # until somebody touches one of them.
    if row.get("is_primary"):
        (sb.table("person_identity_documents").update({"is_primary": False})
         .eq("person_id", person_id).neq("id", saved["id"]).execute())

    # `scan_document_id` is excluded: `upload_document` has already written its
    # own DOCUMENT_UPLOADED / DOCUMENT_VERSION_ADDED row, and logging the id a
    # second time here would report one upload as two events.
    subject = audit_subject.for_person(person, id_number=row["id_number"])
    entries = [
        dict(
            case_id=None, user_id=user["id"],
            user_display_name=user["display_name"],
            action_type="PERSON_FIELD_UPDATED",
            event_code=audit_events.VP_COMPLIANCE,
            company_name=person.get("full_name"),
            **subject,
            entity_type="person", entity_id=str(person_id),
            old_value=old_val, new_value=new_val,
            before_state={"field": f"{row['id_type']}.{field}", "old": old_val},
            after_state={"field": f"{row['id_type']}.{field}", "new": new_val},
        )
        for field, new_val in row.items()
        if field != "scan_document_id"
        for old_val in [(current or {}).get(field)]
        if old_val != new_val
    ]
    if entries:
        await log_events(entries)
    return {**saved, "scan": scan}


@router.delete("/{person_id}/identity-documents/{document_id}")
async def delete_identity_document(
    person_id: str,
    document_id: str,
    user=Depends(live_person("write")),
):
    """Remove one identity document. Its scan is kept, in Document History.

    THE RECORD IS DELETED OUTRIGHT AND THAT IS THE SAFE OPTION, which is worth
    saying because everything else in this repo soft-deletes. A
    `person_identity_documents` row is read by `nar1_mapper._identity`, by the
    `person_registry` view and by `audit_subject.primary_id_number`, none of
    which know about a deleted flag — a soft-deleted row would go on being FILED
    WITH CR after an operator had removed it, which is the failure this is
    avoiding, not risking. The row's full before-state goes to the audit log,
    which is insert-only, so the number is recoverable from the trail.

    The SCAN is a document like any other and follows the documents rule: soft
    deleted (`status='deleted'`, object retained), so it leaves the section and
    stays in Document History marked as removed.
    """
    sb = get_supabase()
    current = (
        sb.table("person_identity_documents").select("*")
        .eq("id", document_id).eq("person_id", person_id).single().execute()
    ).data
    if not current:
        raise HTTPException(status_code=404, detail="Identity document not found")

    person = _person_subject(sb, person_id)

    # Removing a number CR holds is an ND2B item too: baseline first.
    particulars.capture_before_edit(person_id=person_id, user_id=user["id"])

    # The scan first. If Storage or the documents table refuses, the identity
    # row is still here and the operator retries one action — rather than
    # finding the number gone and the file still listed as current.
    if current.get("scan_document_id"):
        await document_service.soft_delete_document(
            document_id=current["scan_document_id"], user=user)

    sb.table("person_identity_documents").delete().eq("id", document_id).execute()

    # If the removed one was primary, the person now has no primary at all and
    # would be quoted by whichever row is oldest. Promote the oldest survivor
    # explicitly, so the header and the audit reference agree with each other.
    if current.get("is_primary"):
        survivors = (
            sb.table("person_identity_documents").select("id")
            .eq("person_id", person_id).order("created_at").limit(1).execute().data
        ) or []
        if survivors:
            (sb.table("person_identity_documents").update({"is_primary": True})
             .eq("id", survivors[0]["id"]).execute())

    await log_event(
        case_id=None, user_id=user["id"],
        user_display_name=user["display_name"],
        action_type="PERSON_FIELD_UPDATED",
        event_code=audit_events.VP_COMPLIANCE,
        company_name=person.get("full_name"),
        **audit_subject.for_person(
            person, id_number=audit_subject.primary_id_number(sb, person_id)),
        entity_type="person", entity_id=str(person_id),
        old_value=f"{current.get('id_type')} {current.get('id_number')}",
        new_value="removed",
        # The whole row, because the row is gone: this entry is the only record
        # of what the number was.
        before_state={k: v for k, v in current.items()
                      if k not in ("id", "person_id", "vp_source_key")},
        after_state={"removed": True},
    )
    return {"deleted": True, "id": document_id}


@router.put("/{person_id}/residential-address")
async def update_residential_address(
    person_id: str,
    body: AddressIn,
    user=Depends(live_person("write")),
):
    """Set this person's residential address.

    This is the one that unblocks NAR1. A return carries every director's
    residential address, and 815 of 6,853 people had a line over CR's 60-char
    cap with no screen on which to fix it. Copy-on-write applies here too:
    directors of the same family company can share an address row.
    """
    sb = get_supabase()
    current = (
        sb.table("persons").select("id, full_name, residential_address_id")
        .eq("id", person_id).single().execute()
    ).data
    if not current:
        raise HTTPException(status_code=404, detail="Person not found")

    before = None
    if current.get("residential_address_id"):
        before = (
            sb.table("addresses").select("*")
            .eq("id", current["residential_address_id"]).single().execute()
        ).data

    # ND2B items (d) and (e): the address as CR holds it, before it moves.
    particulars.capture_before_edit(person_id=person_id, user_id=user["id"])

    try:
        result = address_service.save(
            sb,
            owner_table="persons", owner_id=person_id,
            owner_column="residential_address_id",
            current_address_id=current.get("residential_address_id"),
            payload=body.model_dump(),
        )
    except address_service.AddressError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    await log_events(_address_audit_entries(
        entity_id=person_id, user=user, subject_name=current.get("full_name"),
        event_code=audit_events.VP_MASTER_DETAILS, before=before, result=result,
        # An address is polymorphic — it hangs off a company OR a person — so
        # the caller has to say which, or the row classifies as a company edit.
        subject=audit_subject.for_person(
            current, id_number=audit_subject.primary_id_number(sb, person_id)),
    ))
    return {
        **result["address"],
        "shared_by": address_service.count_references(sb, result["address"]["id"]),
    }


# --------------------------------------------------------------------------- #
#  Person-scoped documents
#
#  GATED ON `persons`, NOT ON A `documents` MODULE (Levi 2026-09-07) — see the
#  same note over the company routes. The identity documents below were always
#  `persons:write`; this makes the ordinary documents agree with them, which is
#  what an operator already assumed was true.
# --------------------------------------------------------------------------- #

@router.get("/{person_id}/documents")
async def list_person_documents(
    person_id: str,
    user=Depends(live_person("read")),
):
    return document_service.list_documents(owner_kind="person", owner_id=person_id)


@router.post("/{person_id}/documents", status_code=201)
async def upload_person_document(
    person_id: str,
    file: UploadFile = File(...),
    document_type_code: str = Form(...),
    title: Optional[str] = Form(None),
    user=Depends(live_person("write")),
):
    content = await file.read()
    return await document_service.upload_document(
        owner_kind="person", owner_id=person_id,
        document_type_code=document_type_code, file_name=file.filename,
        content=content, mime_type=file.content_type, title=title, user=user,
    )


# --------------------------------------------------------------------------- #
#  The person's own CR e-Registry account (Levi 2026-09-30, answers 1, 2, 8)
#
#  GSHK sets up a new director's e-Registry account and keeps it, so the ND2A
#  consent signature can be applied from it. The password goes in and never
#  comes back out of any route — not even masked (spec B-9).
# --------------------------------------------------------------------------- #

_ESERVICE_FIELDS = ("eservice_user_id", "eservice_person_name", "password",
                    # The identity document the account was opened with
                    # (Jacqueline, note 1 of 1 Oct 2026). Optional.
                    "registered_id_type", "registered_id_number")


async def _eservice_body(request: Request) -> dict:
    """The PUT body, read by hand: NO PYDANTIC MODEL, ON PURPOSE.

    FastAPI's 422 echoes the rejected input, so a model refusing a missing name
    or a stale key (`eservice_password`) answered with the password in the
    response body — the leak `tpsi.SignIn` documents. Every refusal here is a
    fixed sentence naming at most a FIELD, never a value."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — any unreadable body is the same answer
        raise HTTPException(400, "Send the account as a JSON object")
    if not isinstance(body, dict):
        raise HTTPException(400, "Send the account as a JSON object")
    unknown = sorted(k for k in body if k not in _ESERVICE_FIELDS)
    if unknown:
        raise HTTPException(400, f"Unknown field(s): {', '.join(map(str, unknown))}. "
                                 f"Send {', '.join(_ESERVICE_FIELDS)}.")
    for key in ("eservice_user_id", "eservice_person_name"):
        if not isinstance(body.get(key), str):
            raise HTTPException(400, f"{key} is required and must be text")
    if body.get("password") is not None and not isinstance(body["password"], str):
        raise HTTPException(400, "password must be text")
    kind = body.get("registered_id_type")
    if kind is not None and (not isinstance(kind, str)
                             or (kind.strip() and kind.strip().lower()
                                 not in eservice.REGISTERED_ID_TYPES)):
        raise HTTPException(400, "registered_id_type must be hkid or passport")
    if body.get("registered_id_number") is not None \
            and not isinstance(body["registered_id_number"], str):
        raise HTTPException(400, "registered_id_number must be text")
    return body


async def _audit_person(sb, user: dict, person_id: str, action: str, **fields):
    person = _person_subject(sb, person_id)
    await log_event(
        case_id=None, user_id=user["id"], user_display_name=user["display_name"],
        action_type=action, event_code=action,
        company_name=person.get("full_name"),
        **audit_subject.for_person(
            person, id_number=audit_subject.primary_id_number(sb, person_id)),
        entity_type="person", entity_id=str(person_id), **fields,
    )


def _with_mismatch(sb, person_id: str, meta: dict) -> dict:
    """The metadata plus whether the profile still holds the identity document
    the account was opened with (Jacqueline, note 1)."""
    try:
        docs = (sb.table("person_identity_documents").select("*")
                .eq("person_id", person_id).execute().data) or []
    except Exception:  # noqa: BLE001 — a warning is decoration, never a 500
        docs = []
    return {**meta, "registered_id_mismatch": eservice.identity_mismatch(meta, docs)}


@router.get("/{person_id}/eservice-credential")
async def get_eservice_credential(person_id: str, user=Depends(live_person("read"))):
    return _with_mismatch(get_supabase(), person_id, eservice.metadata(person_id))


@router.put("/{person_id}/eservice-credential")
async def put_eservice_credential(
    person_id: str,
    request: Request,
    user=Depends(live_person("write")),
):
    body = await _eservice_body(request)
    password = body.get("password")
    sb = get_supabase()
    before = eservice.metadata(person_id)
    try:
        meta = eservice.save(
            person_id, eservice_user_id=body["eservice_user_id"],
            eservice_person_name=body["eservice_person_name"],
            password=password if password is not None else eservice.UNSET,
            user_id=user["id"],
            registered_id_type=body.get("registered_id_type", eservice.UNSET),
            registered_id_number=body.get("registered_id_number", eservice.UNSET))
    except ValueError as exc:
        # The message names the field, never the value (eservice.save).
        raise HTTPException(status_code=400, detail=str(exc))
    await _audit_person(
        sb, user, person_id, audit_events.PERSON_ESERVICE_CRED_SET,
        old_value=before.get("eservice_user_id"), new_value=meta["eservice_user_id"],
        # The account, never the password, its length or a hint of it.
        # Nor the registered identity NUMBER: only which kind of document.
        metadata={"eservice_user_id": meta["eservice_user_id"],
                  "password_changed": password is not None,
                  "first_set": not before["configured"],
                  "registered_id_type": meta.get("registered_id_type")})
    return _with_mismatch(sb, person_id, meta)


@router.delete("/{person_id}/eservice-credential")
async def delete_eservice_credential(person_id: str, user=Depends(live_person("write"))):
    sb = get_supabase()
    before = eservice.metadata(person_id)
    removed = eservice.clear(person_id)
    if removed:
        await _audit_person(
            sb, user, person_id, audit_events.PERSON_ESERVICE_CRED_SET,
            old_value=before.get("eservice_user_id"), new_value="removed",
            metadata={"eservice_user_id": before.get("eservice_user_id"),
                      "removed": True})
    return {"removed": removed, **eservice.metadata(person_id)}


# --------------------------------------------------------------------------- #
#  "Changed on the profile, CR not told yet" (spec §4, answers 14 and 16)
# --------------------------------------------------------------------------- #

def _change_rows(rows: list[dict]) -> list[dict]:
    """The pending rows as the alert reads them: items carry no dates yet."""
    return [{**row, "items": [
        {k: v for k, v in item.items() if k not in ("effective_date", "omitted")}
        for item in row["items"]]} for row in rows]


@router.get("/{person_id}/particulars-changes")
async def get_particulars_changes(person_id: str, user=Depends(live_person("read"))):
    return {"changes": _change_rows(particulars.pending_for_person(person_id))}


class DismissIn(BaseModel):
    class Config:
        extra = "forbid"

    #: One company only (Jacqueline BQ2); absent means every appointment.
    entity_id: Optional[str] = None


@router.post("/{person_id}/particulars-changes/dismiss")
async def dismiss_particulars_changes(person_id: str, body: Optional[DismissIn] = None,
                                      user=Depends(live_person("write"))):
    """'This was data loading, not a real-world change' (answer 16). Moves the
    baseline for every appointment — or, given `entity_id`, for that company's
    only (Jacqueline BQ2: "we would not assume that the change applies to all
    the companies"). The trail keeps what was dismissed."""
    sb = get_supabase()
    entity_id = body.entity_id if body else None
    pending = [r for r in particulars.pending_for_person(person_id)
               if not entity_id or r["entity_id"] == entity_id]
    dismissed = particulars.dismiss(person_id=person_id, user_id=user["id"],
                                    entity_id=entity_id)
    if dismissed:
        await _audit_person(
            sb, user, person_id, audit_events.OFFICER_PARTICULARS_DISMISSED,
            new_value=f"{dismissed} appointment(s)",
            metadata={"appointments": dismissed, "entity_id": entity_id, "dismissed": [
                {"entity_id": r["entity_id"], "company_name": r.get("company_name"),
                 "capacity": r["capacity"],
                 "items": [i["label"] for i in r["items"]]} for r in pending]})
    return {"dismissed": dismissed}


# --------------------------------------------------------------------------- #
#  The correspondence address belongs to each appointment (Jacqueline AQ5, B4)
# --------------------------------------------------------------------------- #

def _correspondence_rows(sb, person_id: str) -> list[dict]:
    rows = particulars.appointment_correspondence(person_id)
    ids = sorted({r["entity_id"] for r in rows})
    names = {}
    if ids:
        names = {e["id"]: e.get("company_name") for e in (
            sb.table("entities").select("id, company_name").in_("id", ids)
            .execute().data or [])}
    return [{**r, "company_name": names.get(r["entity_id"])} for r in rows]


def _address_line(address: Optional[dict]) -> Optional[str]:
    if not address:
        return None
    return ", ".join(str(address.get(k)) for k in
                     ("line1", "line2", "line3", "city", "state_region", "postal_code",
                      "country") if address.get(k))


@router.get("/{person_id}/correspondence-addresses")
async def get_correspondence_addresses(person_id: str, user=Depends(live_person("read"))):
    """Each current directorship's and secretaryship's correspondence address —
    None meaning "same as the residential address"."""
    return {"correspondence_addresses": _correspondence_rows(get_supabase(), person_id)}


@router.put("/{person_id}/appointments/{officer_id}/correspondence-address")
async def put_correspondence_address(person_id: str, officer_id: str, request: Request,
                                     user=Depends(live_person("write"))):
    """Set one appointment's correspondence address, or `{"same_as_residential":
    true}`. The ND2B baseline for THAT company is captured first, so the change
    is reported as item (e) on that company only.

    Always written to a NEW address row: `address_service.count_references`
    does not count officer rows, and a Viewpoint correspondence id may share
    the person's residential row — editing that in place would move their home
    address too."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Send the address as a JSON object")
    if not isinstance(body, dict):
        raise HTTPException(400, "Send the address as a JSON object")
    sb = get_supabase()
    rows = (sb.table("entity_officers").select("*").eq("id", officer_id)
            .execute().data) or []
    officer = rows[0] if rows else None
    if (not officer or officer.get("person_id") != person_id
            or officer.get("is_current") is False
            or officer.get("role") not in ("director", "company_secretary")):
        raise HTTPException(404, "That is not a current appointment of this person")
    before = None
    if officer.get("correspondence_address_id"):
        found = (sb.table("addresses").select("*")
                 .eq("id", officer["correspondence_address_id"]).execute().data) or []
        before = found[0] if found else None
    same = body.get("same_as_residential") is True
    if same and len(body) != 1:
        raise HTTPException(400, "Send either the address or same_as_residential, not both")
    payload = None
    if not same:
        try:
            payload = AddressIn(**body).model_dump()
        except Exception:  # noqa: BLE001 — pydantic's message names the fields
            raise HTTPException(422, "Send the address fields line1, line2, line3, city, "
                                     "state_region, postal_code and country")
    particulars.capture_before_edit(person_id=person_id, user_id=user["id"],
                                    entity_id=officer["entity_id"])
    if same:
        sb.table("entity_officers").update({"correspondence_address_id": None}) \
            .eq("id", officer_id).execute()
        after = None
    else:
        try:
            result = address_service.save(
                sb, owner_table="entity_officers", owner_id=officer_id,
                owner_column="correspondence_address_id", current_address_id=None,
                payload=payload)
        except address_service.AddressError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        after = result["address"]
    await _audit_person(
        sb, user, person_id, audit_events.CASE_FIELD_UPDATED,
        old_value=_address_line(before) or "same as residential address",
        new_value=_address_line(after) or "same as residential address",
        metadata={"field": "correspondence_address", "officer_id": officer_id,
                  "entity_id": officer["entity_id"], "role": officer.get("role"),
                  "same_as_residential": after is None})
    return {"correspondence_addresses": _correspondence_rows(sb, person_id)}


# --------------------------------------------------------------------------- #
#  Identification and addresses per company (Levi 2026-10-05, migration 053)
#
#  "the residential address field can be a list of addresses now and clicking
#  on new button allows adding a new residential address. and in each
#  residential address in the list it shows which companies is using those
#  addresses. same design applied to correspondence address.. same for
#  identification". The rules are `services.person_particulars`'; these routes
#  guard, translate refusals, and audit one CASE_FIELD_UPDATED row per company
#  whose particulars moved — the ND2B baseline was captured before the write.
# --------------------------------------------------------------------------- #

class NewAddressIn(AddressIn):
    kind: str
    entity_ids: list[str] = []
    make_default: bool = False


class CompaniesIn(BaseModel):
    class Config:
        extra = "forbid"

    kind: Optional[str] = None
    entity_ids: list[str] = []


_UNLINKED = {"residential_address": "the person's default residential address",
             "correspondence_address": "same as residential address",
             "identity_document": "the person's primary document",
             "default_residential_address": "none"}


def _describe(sb, field: str, value) -> Optional[str]:
    """An audit value as staff read it: an address in one line, a document by
    type and number — never a bare uuid."""
    if value is None:
        return _UNLINKED.get(field)
    if isinstance(value, dict):
        return _address_line(value)
    if field == "identity_document":
        rows = (sb.table("person_identity_documents").select("*").eq("id", value)
                .execute().data) or []
        if rows:
            return f"{str(rows[0].get('id_type') or '').upper()} {rows[0].get('id_number')}"
        return str(value)
    rows = sb.table("addresses").select("*").eq("id", value).execute().data or []
    return _address_line(rows[0]) if rows else str(value)


async def _audit_changes(sb, user: dict, person_id: str, changes: list[dict]) -> None:
    for change in changes:
        field = change["field"]
        await _audit_person(
            sb, user, person_id, audit_events.CASE_FIELD_UPDATED,
            old_value=_describe(sb, field, change.get("old")),
            new_value=_describe(sb, field, change.get("new")),
            metadata={"field": field, "entity_id": change.get("entity_id"),
                      **({"companies": change["companies"]} if "companies" in change else {}),
                      **({"kind": change["kind"]} if "kind" in change else {})})


def _refused(exc: "person_particulars.Refused") -> HTTPException:
    return HTTPException(exc.status, {"message": str(exc), "reason": exc.reason})


@router.get("/{person_id}/particulars-by-company")
async def get_particulars_by_company(person_id: str, user=Depends(live_person("read"))):
    try:
        return person_particulars.book(person_id)
    except person_particulars.Refused as exc:
        raise _refused(exc)


@router.post("/{person_id}/addresses", status_code=201)
async def add_person_address(person_id: str, body: NewAddressIn,
                             user=Depends(live_person("write"))):
    payload = {k: v for k, v in body.model_dump().items()
               if k not in ("kind", "entity_ids", "make_default")}
    sb = get_supabase()
    try:
        result = person_particulars.add_address(
            person_id, kind=body.kind, payload=payload, entity_ids=body.entity_ids,
            make_default=body.make_default, user_id=user["id"])
    except person_particulars.Refused as exc:
        raise _refused(exc)
    await _audit_changes(sb, user, person_id, result["changes"])
    return {**person_particulars.book(person_id), "address": result["address"]}


@router.put("/{person_id}/addresses/{address_id}")
async def correct_person_address(person_id: str, address_id: str, body: AddressIn,
                                 user=Depends(live_person("write"))):
    sb = get_supabase()
    try:
        result = person_particulars.correct_address(
            person_id, address_id, payload=body.model_dump(), user_id=user["id"])
    except person_particulars.Refused as exc:
        raise _refused(exc)
    await _audit_changes(sb, user, person_id, result["changes"])
    return {**person_particulars.book(person_id), "address": result["address"]}


@router.put("/{person_id}/addresses/{address_id}/companies")
async def set_person_address_companies(person_id: str, address_id: str, body: CompaniesIn,
                                       user=Depends(live_person("write"))):
    sb = get_supabase()
    try:
        changes = person_particulars.set_address_companies(
            person_id, address_id, kind=body.kind or "", entity_ids=body.entity_ids,
            user_id=user["id"])
    except person_particulars.Refused as exc:
        raise _refused(exc)
    await _audit_changes(sb, user, person_id, changes)
    return person_particulars.book(person_id)


@router.post("/{person_id}/addresses/{address_id}/default")
async def make_person_address_default(person_id: str, address_id: str,
                                      user=Depends(live_person("write"))):
    sb = get_supabase()
    try:
        changes = person_particulars.make_default(person_id, address_id, user_id=user["id"])
    except person_particulars.Refused as exc:
        raise _refused(exc)
    await _audit_changes(sb, user, person_id, changes)
    return person_particulars.book(person_id)


@router.delete("/{person_id}/addresses/{address_id}")
async def remove_person_address(person_id: str, address_id: str,
                                kind: str = Query(...),
                                user=Depends(live_person("write"))):
    sb = get_supabase()
    try:
        changes = person_particulars.remove_address(person_id, address_id, kind=kind)
    except person_particulars.Refused as exc:
        raise _refused(exc)
    await _audit_changes(sb, user, person_id, changes)
    return person_particulars.book(person_id)


@router.put("/{person_id}/identity-documents/{document_id}/companies")
async def set_identity_document_companies(person_id: str, document_id: str, body: CompaniesIn,
                                          user=Depends(live_person("write"))):
    sb = get_supabase()
    try:
        changes = person_particulars.set_document_companies(
            person_id, document_id, entity_ids=body.entity_ids, user_id=user["id"])
    except person_particulars.Refused as exc:
        raise _refused(exc)
    await _audit_changes(sb, user, person_id, changes)
    return person_particulars.book(person_id)

"""Persons CRUD + person-scoped documents (PBI-39 Block 1).

Gated by require_permission("persons"/"documents", ...). Every mutation audits.
Person Profile carries fields, identity documents, residential address, a role
roll-up (read-only from the link tables), and document history.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel

from middleware.auth import require_permission
from db.supabase import get_supabase
from services.audit_service import log_event
from services import audit_events, document_service

router = APIRouter()

_EDITABLE_FIELDS = {
    "full_name", "given_names", "surname", "full_name_zh", "former_name",
    "email", "phone", "date_of_birth", "gender", "nationality",
    "nationality_code", "nationality_origin", "occupation", "place_of_birth",
    "marital_status", "date_of_death", "residential_address_id",
}


class CreatePersonRequest(BaseModel):
    full_name: str
    given_names: Optional[str] = None
    surname: Optional[str] = None
    full_name_zh: Optional[str] = None
    former_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None
    nationality_code: Optional[str] = None
    occupation: Optional[str] = None
    place_of_birth: Optional[str] = None
    marital_status: Optional[str] = None
    residential_address_id: Optional[str] = None


class UpdatePersonRequest(BaseModel):
    class Config:
        extra = "forbid"

    full_name: Optional[str] = None
    given_names: Optional[str] = None
    surname: Optional[str] = None
    full_name_zh: Optional[str] = None
    former_name: Optional[str] = None
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
    if entity_ids:
        ents = (
            sb.table("entities").select("id, company_name")
            .in_("id", list(entity_ids)).execute().data
        ) or []
        names = {e["id"]: e["company_name"] for e in ents}
    for c in collected:
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


@router.get("")
async def list_persons(
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
    dir: str = Query("asc"),
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

    sb = get_supabase()

    def base(cols: str, count: Optional[str] = None):
        q = (sb.table("person_registry").select(cols, count=count) if count
             else sb.table("person_registry").select(cols))
        if search:
            q = q.or_(
                f"full_name.ilike.%{search}%,"
                f"full_name_zh.ilike.%{search}%,"
                f"email.ilike.%{search}%,"
                f"primary_id_number.ilike.%{search}%"
            )
        return q

    def count_of(flag: Optional[str]) -> int:
        q = base("id", count="exact")
        if flag:
            q = q.eq(flag, True)
        return q.limit(1).execute().count or 0

    role_counts = {"all": count_of(None)}
    for name, flag in _ROLE_FLAGS.items():
        role_counts[name] = count_of(flag)

    q = base("*")
    if role:
        q = q.eq(_ROLE_FLAGS[role], True)
    offset = (page - 1) * page_size
    rows = (
        q.order(sort or "full_name", desc=(dir == "desc"))
        .range(offset, offset + page_size - 1).execute().data
    ) or []

    total = role_counts[role] if role else role_counts["all"]
    return {
        "persons": rows,
        "role_counts": role_counts,
        "page": page,
        "page_size": page_size,
        "total": total,
    }


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
        raise HTTPException(status_code=404, detail="Person not found")

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
    documents = document_service.list_documents(owner_kind="person", owner_id=person_id)

    return {
        **person,
        "identity_documents": identity_docs,
        "residential_address": address,
        "role_rollup": _role_rollup(sb, person_id),
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
        entity_type="person", entity_id=str(person["id"]),
        new_value=person["full_name"], after_state=row,
    )
    return person


@router.patch("/{person_id}")
async def update_person(
    person_id: str,
    body: UpdatePersonRequest,
    user=Depends(require_permission("persons", "write")),
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

    updated = (
        sb.table("persons").update(updates).eq("id", person_id).execute()
    ).data[0]

    for field, new_val in updates.items():
        old_val = current.get(field)
        if old_val == new_val:
            continue
        await log_event(
            case_id=None, user_id=user["id"],
            user_display_name=user["display_name"], action_type="PERSON_FIELD_UPDATED",
            # KYC fields are Compliance (CPC) in Viewpoint; names/contact are ADC.
            event_code=audit_events.person_field_code(field),
            company_name=current.get("full_name"),
            entity_type="person", entity_id=str(person_id),
            old_value=old_val, new_value=new_val,
            before_state={"field": field, "old": old_val},
            after_state={"field": field, "new": new_val},
        )
    return updated


@router.get("/{person_id}/documents")
async def list_person_documents(
    person_id: str,
    user=Depends(require_permission("documents", "read")),
):
    return document_service.list_documents(owner_kind="person", owner_id=person_id)


@router.post("/{person_id}/documents", status_code=201)
async def upload_person_document(
    person_id: str,
    file: UploadFile = File(...),
    document_type_code: str = Form(...),
    title: Optional[str] = Form(None),
    user=Depends(require_permission("documents", "write")),
):
    content = await file.read()
    return await document_service.upload_document(
        owner_kind="person", owner_id=person_id,
        document_type_code=document_type_code, file_name=file.filename,
        content=content, mime_type=file.content_type, title=title, user=user,
    )

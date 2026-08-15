"""Companies (entities) CRUD + party-linking + company-scoped documents (PBI-39).

All routes gated by require_permission("companies", ...). Every mutation audits
before returning (PBI-11). Company = row in `entities` (PBI-40 superset).
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel

from middleware.auth import require_permission
from db.supabase import get_supabase
from services.audit_service import log_event, log_events
from services import audit_events, document_service

router = APIRouter()

# Create-time status is restricted to pre_incorporation / live (OQ-3).
_CREATE_STATUSES = {"pre_incorporation", "live"}

# Company fields editable via PATCH /companies/{id}. Flags go through /flags only.
_EDITABLE_FIELDS = {
    "company_name", "company_name_zh", "name_language", "company_type",
    "br_number", "cr_number", "status", "active_workflow",
    "registered_address_id", "incorporation_date", "incorporation_place",
    "tcsp_licence_no", "tcsp_exemption_reason",
    "ar_last_date", "ar_next_date", "ar_due_date", "agm_next_date",
    "aoa_director_min", "aoa_director_max", "aoa_agm_waived",
    "previous_name", "date_name_changed", "case_notes", "assigned_to",
}

# Dashboard tiles (wireframe_v7 s2) + which statuses count as unfinished work.
_TILE_ACTION = {"pending_aml", "to_verify", "client_rejected"}
_TILE_PENDING = {"pending_client", "submitted_to_cr"}
_TERMINAL = {"live", "ceased", "cr_approved", "client_approved"}
# Everything not terminal is "pending work" and sorts first on the Dashboard.
# (Today all real rows are live/ceased, so this set is empty in practice — it
# populates once the NAR1/NNC1 case workflows land.)
_PENDING = ["pre_incorporation", "pending_aml", "pending_client", "to_verify",
            "revision_required", "submitted_to_cr", "client_rejected"]
# The 6 status filter tabs on the Dashboard (wireframe_v7 s2), besides "All".
_TAB_STATUSES = ["pending_aml", "to_verify", "client_rejected",
                 "pending_client", "submitted_to_cr", "cr_approved"]

_LIST_COLS = (
    "id, vp_source_key, company_name, company_name_zh, br_number, cr_number, "
    "status, active_workflow, company_type, is_client, is_corporate_party, "
    "incorporation_date, created_at, updated_at, days_to_anniversary"
)

# The list reads the `company_registry` VIEW, not `entities` — it is entities
# plus days_to_anniversary, computed on read and stored nowhere (migration 019).
# It has to be server-side: the registry paginates over ~5,930 rows, so sorting
# the 50 rows a page happens to hold answers the wrong question. Writes still go
# to `entities`; a view is not an update target.
_LIST_RELATION = "company_registry"

# Signed: negative means the anniversary has passed and the return is still
# inside the 42-day statutory window. See migration 019 and PRD §6 W-3.
_ANNIV_OPS = {"lte", "gte", "eq"}
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200

# Columns the table headers may sort by. Whitelisted — `sort` reaches PostgREST's
# order clause, so it must never be caller-controlled free text.
_SORTABLE = {
    "vp_source_key", "company_name", "br_number", "cr_number", "status",
    "active_workflow", "company_type", "created_at", "updated_at",
    "incorporation_date", "is_client", "is_corporate_party",
    "days_to_anniversary",
}

_SECRETARY_ROLE = "company_secretary"

# Party-linking: URL relation segment -> table + editable attribute columns.
# `secretaries` is entity_officers scoped to role='company_secretary' — that table
# is the corporate-party-aware source (it carries corporate_entity_id, which
# company_secretaries does not). `fixed` values are forced on insert and filtered
# on read so a secretary can never be created as a plain director, or vice versa.
_RELATIONS = {
    "officers": {
        "table": "entity_officers",
        "fields": {"role", "position", "appointed_date", "resigned_date",
                   "resignation_reason", "is_current"},
    },
    "secretaries": {
        "table": "entity_officers",
        "fields": {"position", "appointed_date", "resigned_date",
                   "resignation_reason", "is_current"},
        "fixed": {"role": _SECRETARY_ROLE},
    },
    "shareholders": {
        "table": "shareholdings",
        "fields": {"share_class_id", "shares_held", "amount_paid", "is_current"},
    },
    "beneficial-owners": {
        "table": "beneficial_owners",
        "fields": {"owner_type", "percent_interest", "percent_vote",
                   "date_from", "date_to", "is_current"},
    },
}


class CreateCompanyRequest(BaseModel):
    company_name: str
    company_name_zh: Optional[str] = None
    name_language: Optional[str] = None
    company_type: Optional[str] = None
    br_number: Optional[str] = None
    cr_number: Optional[str] = None
    status: Optional[str] = "pre_incorporation"
    is_client: Optional[bool] = True
    is_corporate_party: Optional[bool] = False
    incorporation_date: Optional[str] = None
    incorporation_place: Optional[str] = None
    tcsp_licence_no: Optional[str] = None
    tcsp_exemption_reason: Optional[str] = None
    registered_address_id: Optional[str] = None
    assigned_to: Optional[str] = None
    case_notes: Optional[str] = None
    # Add Company form (wireframe_v7): these live in `addresses` / `contacts`,
    # not on `entities` — created alongside the company below.
    registered_address: Optional[str] = None
    company_phone: Optional[str] = None


class UpdateCompanyRequest(BaseModel):
    class Config:
        extra = "forbid"

    company_name: Optional[str] = None
    company_name_zh: Optional[str] = None
    name_language: Optional[str] = None
    company_type: Optional[str] = None
    br_number: Optional[str] = None
    cr_number: Optional[str] = None
    status: Optional[str] = None
    active_workflow: Optional[str] = None
    registered_address_id: Optional[str] = None
    incorporation_date: Optional[str] = None
    incorporation_place: Optional[str] = None
    tcsp_licence_no: Optional[str] = None
    tcsp_exemption_reason: Optional[str] = None
    ar_last_date: Optional[str] = None
    ar_next_date: Optional[str] = None
    ar_due_date: Optional[str] = None
    agm_next_date: Optional[str] = None
    aoa_director_min: Optional[int] = None
    aoa_director_max: Optional[int] = None
    aoa_agm_waived: Optional[bool] = None
    previous_name: Optional[str] = None
    date_name_changed: Optional[str] = None
    case_notes: Optional[str] = None
    assigned_to: Optional[str] = None


class FlagsRequest(BaseModel):
    is_client: Optional[bool] = None
    is_corporate_party: Optional[bool] = None


class LinkPartyRequest(BaseModel):
    class Config:
        extra = "allow"

    person_id: Optional[str] = None
    corporate_entity_id: Optional[str] = None
    corporate_name: Optional[str] = None
    role: Optional[str] = None
    position: Optional[str] = None
    appointed_date: Optional[str] = None
    resigned_date: Optional[str] = None
    resignation_reason: Optional[str] = None
    share_class_id: Optional[str] = None
    shares_held: Optional[float] = None
    amount_paid: Optional[float] = None
    owner_type: Optional[str] = None
    percent_interest: Optional[float] = None
    percent_vote: Optional[float] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None


# --------------------------------------------------------------------------- #
#  Companies CRUD
# --------------------------------------------------------------------------- #

@router.get("")
async def list_companies(
    scope: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    flag: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
    dir: str = Query("asc"),
    anniv_op: Optional[str] = Query(None, description="lte | gte | eq"),
    anniv_days: Optional[int] = Query(None, description="signed day count"),
    page: int = Query(1, ge=1),
    page_size: int = Query(_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
    user=Depends(require_permission("companies", "read")),
):
    """Company Registry (all) or Dashboard (?scope=dashboard, client-only).

    Server-side paginated. Dashboard sorts pending-work first, then updated_at
    DESC — done as two ordered queries (the pending set is small and bounded by
    active workflows) because PostgREST cannot order by a computed expression.
    """
    sb = get_supabase()

    def apply_flag(q, f: Optional[str]):
        if scope == "dashboard" or f == "client":
            return q.eq("is_client", True)
        if f == "corporate_party":
            return q.eq("is_corporate_party", True)
        if f == "non_client":
            return q.eq("is_client", False)
        return q

    if anniv_op is not None and anniv_op not in _ANNIV_OPS:
        raise HTTPException(status_code=422, detail=f"Unknown comparison '{anniv_op}'")
    # Both halves or neither — a comparison with nothing to compare against, or a
    # number with no comparison, is a caller bug worth surfacing.
    if (anniv_op is None) != (anniv_days is None):
        raise HTTPException(
            status_code=422,
            detail="anniv_op and anniv_days must be supplied together",
        )

    def base(cols: str, count: Optional[str] = None, f: Optional[str] = ...):
        q = (sb.table(_LIST_RELATION).select(cols, count=count) if count
             else sb.table(_LIST_RELATION).select(cols))
        q = apply_flag(q, flag if f is ... else f)
        if search:
            q = q.or_(
                f"company_name.ilike.%{search}%,"
                f"br_number.ilike.%{search}%,"
                f"cr_number.ilike.%{search}%"
            )
        # Applied inside base() so it reaches the COUNT queries too. Filtering
        # only the page query would leave the pager and the tab counts quoting
        # totals for a set the user is not looking at.
        if anniv_op:
            col = "days_to_anniversary"
            q = getattr(q, anniv_op)(col, anniv_days)
            # A company with no incorporation_date has a NULL day count and
            # cannot answer a numeric question. PostgREST would drop it anyway;
            # being explicit means the intent survives the next edit.
            q = q.not_.is_(col, "null")
        return q

    def count_of(**eq) -> int:
        q = base("id", count="exact")
        for k, v in eq.items():
            q = q.eq(k, v)
        return q.limit(1).execute().count or 0

    # Counts / tiles cover the whole filtered set, not just the page. Use exact
    # COUNT queries — PostgREST caps returned rows at 1000, so counting fetched
    # rows would silently under-report on a 5.9k-row table.
    #
    # These 7 counts are independent; run concurrently. Sequentially they were
    # 7 x ~200ms of pure round-trip latency on every dashboard load.
    count_values = await asyncio.gather(
        asyncio.to_thread(count_of),
        *[asyncio.to_thread(lambda s=s: count_of(status=s)) for s in _TAB_STATUSES],
    )
    counts: dict[str, int] = {"all": count_values[0]}
    for s, v in zip(_TAB_STATUSES, count_values[1:]):
        counts[s] = v
    action = sum(counts.get(s, 0) for s in _TILE_ACTION)
    pending_n = sum(counts.get(s, 0) for s in _TILE_PENDING)

    if sort and sort not in _SORTABLE:
        raise HTTPException(status_code=422, detail=f"Cannot sort by '{sort}'")

    offset = (page - 1) * page_size

    if sort:
        # An explicit column sort replaces the default pending-work-first
        # grouping — the user asked for that order, so honour it exactly.
        total = counts.get(status) if status else counts["all"]
        if total is None:
            total = count_of(status=status) if status else counts["all"]
        q = base(_LIST_COLS)
        if status:
            q = q.eq("status", status)
        # nullsfirst=False explicitly: Postgres puts NULLs FIRST on a DESC sort,
        # which would open "furthest from anniversary" with the 473 companies
        # that have no incorporation date and therefore no answer.
        rows = (
            q.order(sort, desc=(dir == "desc"), nullsfirst=False)
            .range(offset, offset + page_size - 1).execute().data
        ) or []
    elif status:
        total = counts.get(status) or count_of(status=status)
        rows = (
            base(_LIST_COLS).eq("status", status)
            .order("updated_at", desc=True)
            .range(offset, offset + page_size - 1).execute().data
        ) or []
    else:
        total = counts["all"]
        # 1) pending-work rows first (small set), 2) then terminal rows.
        pend = (
            base(_LIST_COLS).in_("status", _PENDING)
            .order("updated_at", desc=True).execute().data
        ) or []
        rows = pend[offset:offset + page_size]
        remaining = page_size - len(rows)
        if remaining > 0:
            t_offset = max(0, offset - len(pend))
            term = (
                base(_LIST_COLS).not_.in_("status", _PENDING)
                .order("updated_at", desc=True)
                .range(t_offset, t_offset + remaining - 1).execute().data
            ) or []
            rows = rows + term

    for r in rows:
        r["has_pending_case"] = r.get("status") not in _TERMINAL

    payload = {
        "companies": rows,
        "page": page,
        "page_size": page_size,
        "total": total,
    }
    if scope == "dashboard":
        payload["tiles"] = {"action_required": action, "pending": pending_n}
        payload["status_counts"] = counts
    else:
        # Company Registry flag tabs (wireframe_v7 s9), counted over the search set.
        def flag_count(f: Optional[str]) -> int:
            return base("id", count="exact", f=f).limit(1).execute().count or 0

        payload["flag_counts"] = {
            "all": flag_count(None),
            "client": flag_count("client"),
            "corporate_party": flag_count("corporate_party"),
            "non_client": flag_count("non_client"),
        }
    return payload


@router.get("/{company_id}")
async def get_company(
    company_id: str,
    user=Depends(require_permission("companies", "read")),
):
    sb = get_supabase()
    entity = (
        sb.table("entities").select("*").eq("id", company_id).single().execute()
    ).data
    if not entity:
        raise HTTPException(status_code=404, detail="Company not found")

    # Party rows embed the linked person; corporate parties are resolved by a
    # second lookup (entity_id AND corporate_entity_id both FK `entities`, so a
    # PostgREST embed on `entities` would be ambiguous).
    person_cols = ("persons(id, full_name, full_name_zh, email, phone, "
                   "nationality, date_of_birth, residential_address_id)")
    # Officers and secretaries both live in entity_officers, split by role.
    # (company_secretaries is a denormalized ETL mirror of the same rows and is
    # NOT corporate-party aware — it has no corporate_entity_id — so the profile
    # reads entity_officers instead.)
    #
    # These are independent of each other and each is a ~200ms round trip to
    # Supabase, so running them sequentially made the profile take ~2s. The
    # supabase client is synchronous — to_thread lets them overlap.
    async def q(fn):
        return await asyncio.to_thread(fn)

    officers, secretaries, shareholders, ben_owners, contacts, documents = await asyncio.gather(
        q(lambda: (sb.table("entity_officers").select(f"*, {person_cols}")
                   .eq("entity_id", company_id).neq("role", _SECRETARY_ROLE)
                   .execute().data) or []),
        q(lambda: (sb.table("entity_officers").select(f"*, {person_cols}")
                   .eq("entity_id", company_id).eq("role", _SECRETARY_ROLE)
                   .execute().data) or []),
        q(lambda: (sb.table("shareholdings")
                   .select(f"*, {person_cols}, share_classes(class_name, currency)")
                   .eq("entity_id", company_id).execute().data) or []),
        q(lambda: (sb.table("beneficial_owners").select(f"*, {person_cols}")
                   .eq("entity_id", company_id).execute().data) or []),
        q(lambda: (sb.table("contacts").select("*")
                   .eq("entity_id", company_id).execute().data) or []),
        q(lambda: document_service.list_documents(owner_kind="entity", owner_id=company_id)),
    )

    linked = officers + secretaries + shareholders + ben_owners
    corp_ids = {r["corporate_entity_id"] for r in linked if r.get("corporate_entity_id")}
    corp_names: dict[str, dict] = {}
    if corp_ids:
        rows = (sb.table("entities")
                .select("id, company_name, br_number, cr_number, tcsp_licence_no")
                .in_("id", list(corp_ids)).execute().data) or []
        corp_names = {r["id"]: r for r in rows}
    for r in linked:
        cid = r.get("corporate_entity_id")
        if cid:
            r["corporate_entity"] = corp_names.get(cid)

    address = None
    if entity.get("registered_address_id"):
        address = await asyncio.to_thread(
            lambda: (sb.table("addresses").select("*")
                     .eq("id", entity["registered_address_id"]).single().execute()).data
        )

    result = {
        **entity,
        "registered_address": address,
        "contacts": contacts,
        "documents": documents,
        "officers": officers,
        "shareholders": shareholders,
        "beneficial_owners": ben_owners,
        "secretaries": secretaries,
    }
    # Cases pane only for client entities (§6 visibility).
    if entity.get("is_client"):
        nar1, nnc1 = await asyncio.gather(
            q(lambda: (sb.table("nar1_cases").select("*").eq("entity_id", company_id).execute().data) or []),
            q(lambda: (sb.table("nnc1_cases").select("*").eq("entity_id", company_id).execute().data) or []),
        )
        result["cases"] = {"nar1": nar1, "nnc1": nnc1}
    return result


@router.post("", status_code=201)
async def create_company(
    body: CreateCompanyRequest,
    user=Depends(require_permission("companies", "write")),
):
    if body.status not in _CREATE_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Create-time status must be one of {sorted(_CREATE_STATUSES)}",
        )
    sb = get_supabase()
    payload = body.model_dump()
    address_line = payload.pop("registered_address", None)
    phone = payload.pop("company_phone", None)
    row = {k: v for k, v in payload.items() if v is not None}

    # The form's free-text registered address becomes an `addresses` row that the
    # entity points at (structured line1; the profile can refine it later).
    if address_line and not row.get("registered_address_id"):
        addr = sb.table("addresses").insert(
            {"line1": address_line, "country": "HK", "is_hk_address": True}
        ).execute().data
        if addr:
            row["registered_address_id"] = addr[0]["id"]

    created = sb.table("entities").insert(row).execute().data
    if not created:
        raise HTTPException(status_code=400, detail="Company insert failed")
    company = created[0]

    if phone:
        sb.table("contacts").insert({
            "entity_id": company["id"], "contact_type": "phone",
            "contact_value": phone, "is_preferred": True,
        }).execute()

    await log_event(
        case_id=company["id"], user_id=user["id"],
        user_display_name=user["display_name"], action_type="COMPANY_CREATED",
        event_code=audit_events.VP_NEW_MASTER_FILE,
        company_name=company["company_name"],
        entity_type="entity", entity_id=str(company["id"]),
        new_value=company["company_name"],
        after_state={**row, **({"company_phone": phone} if phone else {})},
    )
    return company


@router.patch("/{company_id}")
async def update_company(
    company_id: str,
    body: UpdateCompanyRequest,
    user=Depends(require_permission("companies", "write")),
):
    updates = {k: v for k, v in body.model_dump().items()
               if v is not None and k in _EDITABLE_FIELDS}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    sb = get_supabase()
    current = (
        sb.table("entities").select("*").eq("id", company_id).single().execute()
    ).data
    if not current:
        raise HTTPException(status_code=404, detail="Company not found")

    updated = (
        sb.table("entities").update(updates).eq("id", company_id).execute()
    ).data[0]

    # One entry per changed field, but a SINGLE insert — a form save changes
    # several fields and one round trip per field is most of the save latency.
    await log_events([
        dict(
            case_id=company_id, user_id=user["id"],
            user_display_name=user["display_name"], action_type="CASE_FIELD_UPDATED",
            # Which Viewpoint folder owns the field decides the code — the same
            # way Viewpoint logs it (ADC / COC / CMA / CGC / LRO).
            event_code=audit_events.company_field_code(field),
            company_name=current.get("company_name"),
            entity_type="entity", entity_id=str(company_id),
            old_value=old_val, new_value=new_val,
            before_state={"field": field, "old": old_val},
            after_state={"field": field, "new": new_val},
        )
        for field, new_val in updates.items()
        for old_val in [current.get(field)]
        if old_val != new_val
    ])
    return updated


@router.patch("/{company_id}/flags")
async def update_flags(
    company_id: str,
    body: FlagsRequest,
    user=Depends(require_permission("companies", "write")),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No flags to update")

    sb = get_supabase()
    current = (
        sb.table("entities").select("company_name, is_client, is_corporate_party")
        .eq("id", company_id).single().execute()
    ).data
    if not current:
        raise HTTPException(status_code=404, detail="Company not found")

    updated = (
        sb.table("entities").update(updates).eq("id", company_id).execute()
    ).data[0]

    before = {k: current.get(k) for k in updates}
    await log_event(
        case_id=company_id, user_id=user["id"],
        user_display_name=user["display_name"], action_type="COMPANY_FLAG_CHANGED",
        event_code=audit_events.GF_FLAGS_CHANGED,   # no Viewpoint equivalent
        company_name=current.get("company_name"),
        entity_type="entity", entity_id=str(company_id),
        old_value="; ".join(f"{k}={v}" for k, v in before.items()),
        new_value="; ".join(f"{k}={v}" for k, v in updates.items()),
        before_state=before,
        after_state=updates,
    )
    return updated


# --------------------------------------------------------------------------- #
#  Company-scoped documents
#  (declared BEFORE the /{relation} catch-all so "documents" isn't matched as a
#   relation segment)
# --------------------------------------------------------------------------- #

@router.get("/{company_id}/documents")
async def list_company_documents(
    company_id: str,
    user=Depends(require_permission("documents", "read")),
):
    return document_service.list_documents(owner_kind="entity", owner_id=company_id)


@router.post("/{company_id}/documents", status_code=201)
async def upload_company_document(
    company_id: str,
    file: UploadFile = File(...),
    document_type_code: str = Form(...),
    title: Optional[str] = Form(None),
    user=Depends(require_permission("documents", "write")),
):
    content = await file.read()
    return await document_service.upload_document(
        owner_kind="entity", owner_id=company_id,
        document_type_code=document_type_code, file_name=file.filename,
        content=content, mime_type=file.content_type, title=title, user=user,
    )


# --------------------------------------------------------------------------- #
#  Party linking  (officers / shareholders / beneficial-owners)
# --------------------------------------------------------------------------- #

def _scope_to_relation(q, relation: str, cfg: dict):
    """officers and secretaries share entity_officers — keep them from crossing over."""
    fixed_role = cfg.get("fixed", {}).get("role")
    if fixed_role:
        return q.eq("role", fixed_role)
    if relation == "officers":
        return q.neq("role", _SECRETARY_ROLE)
    return q


def _resolve_party_type(person_id: Optional[str], corporate_entity_id: Optional[str]) -> str:
    """Exactly one of person_id / corporate_entity_id must be set (backend-enforced)."""
    if bool(person_id) == bool(corporate_entity_id):
        raise HTTPException(
            status_code=422,
            detail="Provide exactly one of person_id or corporate_entity_id",
        )
    return "individual" if person_id else "corporate"


def _company_name(sb, company_id: str) -> Optional[str]:
    row = (
        sb.table("entities").select("company_name").eq("id", company_id)
        .single().execute()
    ).data
    return (row or {}).get("company_name")


def _party_name(sb, person_id: Optional[str], corporate_entity_id: Optional[str],
                corporate_name: Optional[str] = None) -> str:
    """Human name of the linked party — so the audit says WHO was linked."""
    if person_id:
        row = (sb.table("persons").select("full_name").eq("id", person_id)
               .single().execute()).data
        return (row or {}).get("full_name") or person_id
    if corporate_entity_id:
        return _company_name(sb, corporate_entity_id) or corporate_entity_id
    return corporate_name or "—"


def _party_summary(name: str, row: dict) -> str:
    """e.g. 'John Smith (director)' — what the link actually is."""
    role = row.get("role") or row.get("owner_type")
    return f"{name} ({role})" if role else name


@router.post("/{company_id}/{relation}", status_code=201)
async def link_party(
    company_id: str,
    relation: str,
    body: LinkPartyRequest,
    user=Depends(require_permission("companies", "write")),
):
    if relation not in _RELATIONS:
        raise HTTPException(status_code=404, detail="Unknown relation")
    party_type = _resolve_party_type(body.person_id, body.corporate_entity_id)
    cfg = _RELATIONS[relation]

    payload = body.model_dump()
    row = {
        "entity_id": company_id,
        "party_type": party_type,
        "person_id": body.person_id,
        "corporate_entity_id": body.corporate_entity_id,
        "corporate_name": body.corporate_name,
    }
    for f in cfg["fields"]:
        if payload.get(f) is not None:
            row[f] = payload[f]
    row = {k: v for k, v in row.items() if v is not None}
    row.update(cfg.get("fixed", {}))  # e.g. secretaries always role=company_secretary

    if relation == "shareholders" and not row.get("share_class_id"):
        raise HTTPException(status_code=422, detail="share_class_id is required for shareholders")

    sb = get_supabase()
    created = sb.table(cfg["table"]).insert(row).execute().data
    if not created:
        raise HTTPException(status_code=400, detail="Link insert failed")
    link = created[0]

    party = _party_name(sb, body.person_id, body.corporate_entity_id, body.corporate_name)
    await log_event(
        case_id=company_id, user_id=user["id"],
        user_display_name=user["display_name"], action_type="PARTY_LINKED",
        event_code=audit_events.party_code(relation, "link"),
        company_name=_company_name(sb, company_id),
        entity_type="entity", entity_id=str(company_id),
        # Linking has no "old" — the new value is the party that now holds the role.
        new_value=_party_summary(party, row),
        after_state={"relation": relation, "link_id": link["id"], **row},
    )
    return link


@router.patch("/{company_id}/{relation}/{link_id}")
async def update_link(
    company_id: str,
    relation: str,
    link_id: str,
    body: LinkPartyRequest,
    user=Depends(require_permission("companies", "write")),
):
    if relation not in _RELATIONS:
        raise HTTPException(status_code=404, detail="Unknown relation")
    cfg = _RELATIONS[relation]

    payload = body.model_dump()
    updates = {f: payload[f] for f in cfg["fields"] if payload.get(f) is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No attributes to update")

    sb = get_supabase()
    q = sb.table(cfg["table"]).select("*").eq("id", link_id).eq("entity_id", company_id)
    current = _scope_to_relation(q, relation, cfg).single().execute().data
    if not current:
        raise HTTPException(status_code=404, detail="Link not found")

    updated = (
        sb.table(cfg["table"]).update(updates).eq("id", link_id).execute()
    ).data[0]

    party = _party_name(sb, current.get("person_id"), current.get("corporate_entity_id"),
                        current.get("corporate_name"))
    company = _company_name(sb, company_id)
    await log_events([
        dict(
            case_id=company_id, user_id=user["id"],
            user_display_name=user["display_name"], action_type="PARTY_UPDATED",
            event_code=audit_events.party_code(relation, "update"),
            company_name=company,
            entity_type="entity", entity_id=str(company_id),
            old_value=f"{party} — {field}: {old_val}",
            new_value=f"{party} — {field}: {new_val}",
            before_state={"relation": relation, "link_id": link_id, "party": party,
                          "field": field, "old": old_val},
            after_state={"relation": relation, "link_id": link_id, "party": party,
                         "field": field, "new": new_val},
        )
        for field, new_val in updates.items()
        for old_val in [current.get(field)]
        if old_val != new_val
    ])
    return updated


@router.delete("/{company_id}/{relation}/{link_id}")
async def unlink_party(
    company_id: str,
    relation: str,
    link_id: str,
    user=Depends(require_permission("companies", "write")),
):
    if relation not in _RELATIONS:
        raise HTTPException(status_code=404, detail="Unknown relation")
    cfg = _RELATIONS[relation]

    sb = get_supabase()
    q = sb.table(cfg["table"]).select("*").eq("id", link_id).eq("entity_id", company_id)
    current = _scope_to_relation(q, relation, cfg).single().execute().data
    if not current:
        raise HTTPException(status_code=404, detail="Link not found")

    party = _party_name(sb, current.get("person_id"), current.get("corporate_entity_id"),
                        current.get("corporate_name"))
    sb.table(cfg["table"]).delete().eq("id", link_id).execute()

    await log_event(
        case_id=company_id, user_id=user["id"],
        user_display_name=user["display_name"], action_type="PARTY_UNLINKED",
        event_code=audit_events.party_code(relation, "unlink"),
        company_name=_company_name(sb, company_id),
        entity_type="entity", entity_id=str(company_id),
        # Removal has no "new" — the old value is the party that held the role.
        old_value=_party_summary(party, current),
        before_state={"relation": relation, "link_id": link_id, "party": party,
                      **{k: current.get(k) for k in ("person_id", "corporate_entity_id")}},
    )
    return {"message": "Unlinked", "link_id": link_id}

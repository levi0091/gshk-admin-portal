"""Companies (entities) CRUD + party-linking + company-scoped documents (PBI-39).

All routes gated by require_permission("companies", ...). Every mutation audits
before returning (PBI-11). Company = row in `entities` (PBI-40 superset).
"""
import asyncio
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel

from middleware.auth import require_permission
from db.supabase import get_supabase
from services.audit_service import log_event, log_events
from services import audit_subject
from services import (
    audit_events, document_service, address_service, table_filters as tf)
from services.tpsi.forms.cr_vocabularies import (
    BUSINESS_NATURE, COMPANY_TYPE, CURRENCY)
from services.cr_forms.readiness import filing_problems
from services.cr_forms import record_types

router = APIRouter()

#: CR's `coyType` codes, for the write check below.
_COMPANY_TYPE_CODES = {code for code, _ in COMPANY_TYPE}


class AddressIn(BaseModel):
    """The five fields CR accepts, and nothing else.

    `extra = "forbid"` because a typo'd key that is silently ignored looks
    exactly like a save that worked.
    """
    class Config:
        extra = "forbid"

    line1: Optional[str] = None
    line2: Optional[str] = None
    line3: Optional[str] = None
    city: Optional[str] = None
    state_region: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None

# Create-time status is restricted to pre_incorporation / live (OQ-3).
_CREATE_STATUSES = {"pre_incorporation", "live"}

# Company fields editable via PATCH /companies/{id}. Flags go through /flags only.
_EDITABLE_FIELDS = {
    "company_name", "company_name_zh", "name_language", "company_type",
    "br_number", "cr_number", "status", "active_workflow",
    "registered_address_id", "incorporation_date", "incorporation_place",
    "tcsp_licence_no", "tcsp_exemption_reason",
    # NAR1 s2/s3/s9 (migration 028). `business_nature_desc` is written by the
    # handler from the code, never accepted from the client -- CR derives it
    # the same way after web-form validation.
    "business_nature_code", "business_nature_desc", "mortgages_total",
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
    # `company_name_zh` is sortable because the registry list shows it as its
    # own column (Brian's B2). Postgres collates it by code point, which is not
    # stroke order -- but it does group a company's Chinese name next to
    # itself, which is what someone scanning the list is after.
    "vp_source_key", "company_name", "company_name_zh", "br_number",
    "cr_number", "status",
    "active_workflow", "company_type", "created_at", "updated_at",
    "incorporation_date", "is_client", "is_corporate_party",
    "days_to_anniversary",
}

#: Every entity_status the enum can hold (migration 003). Named here rather than
#: derived from `_TAB_STATUSES`, which is the six the Dashboard tabs show —
#: a column filter must offer every value the column can actually contain, or it
#: silently makes `live` and `ceased` rows unreachable, and those are all 5,930
#: of the real ones.
_ALL_STATUSES = {
    "pre_incorporation", "pending_aml", "pending_client", "to_verify",
    "revision_required", "submitted_to_cr", "cr_approved", "client_approved",
    "client_rejected", "live", "ceased",
}

#: Columns the per-column header filters may narrow on (services/table_filters).
#: A separate whitelist from `_SORTABLE`: what you can usefully order by and
#: what you can usefully filter by are different questions, and this one also
#: fixes each column's KIND, which decides the ops it will accept.
_FILTERABLE = {
    "company_name": tf.text(),
    "company_name_zh": tf.text(),
    "br_number": tf.text(),
    "cr_number": tf.text(),
    "status": tf.enum(_ALL_STATUSES),
    "company_type": tf.enum(_COMPANY_TYPE_CODES),
    "days_to_anniversary": tf.number(),
    "incorporation_date": tf.date(),
    "created_at": tf.timestamp(),
    "updated_at": tf.timestamp(),
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
    business_nature_code: Optional[str] = None
    mortgages_total: Optional[str] = None
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


#: CR's section 11, per class. `max` is CHARACTERS as CR counts them, taking
#: the STRICTER of NAR1 and NNC1 where they differ (NNC1 caps the money
#: figures at 14 to NAR1's 16) — a value that fits one form and not the other
#: is one CR would refuse in the second context.
_SHARE_CLASS_FIELDS = {
    "class_name": {"max": 100, "numeric": False},
    "currency": {"max": 3, "numeric": False},
    "total_issued": {"max": 16, "numeric": True},
    "issued_amount": {"max": 14, "numeric": True},
    "total_paid": {"max": 14, "numeric": True},
}


class ShareClassRequest(BaseModel):
    """One class of shares. Every field optional so a PATCH can send one."""
    class_name: Optional[str] = None
    currency: Optional[str] = None
    total_issued: Optional[str] = None
    issued_amount: Optional[str] = None
    total_paid: Optional[str] = None


def _validate_share_class(values: dict) -> dict:
    """Refuse here what CR would refuse after taking the fee.

    Money and share counts arrive as STRINGS because CR counts characters,
    not magnitude: `issuedCapital` is 14 characters on an NNC1, and a float
    that round-trips through JSON as 1.0000000001e14 is a different value from
    the one somebody typed.
    """
    out = {}
    for field, value in values.items():
        rule = _SHARE_CLASS_FIELDS[field]
        text = "" if value is None else str(value).strip()
        if not text:
            out[field] = None
            continue
        if len(text) > rule["max"]:
            raise HTTPException(
                status_code=422,
                detail=(f"{field} is {len(text)} characters; the Companies "
                        f"Registry accepts {rule['max']}."),
            )
        if rule["numeric"]:
            try:
                number = Decimal(text)
            except InvalidOperation:
                raise HTTPException(
                    status_code=422,
                    detail=f"{field} must be a number; got {text!r}.",
                )
            # Zero is a real answer — a class with nothing paid up exists —
            # so only NEGATIVE is refused.
            if number < 0:
                raise HTTPException(
                    status_code=422,
                    detail=f"{field} cannot be negative.",
                )
        if field == "currency":
            code = text.upper()
            if code not in CURRENCY:
                raise HTTPException(
                    status_code=422,
                    detail=(f"{code!r} is not a currency the Companies "
                            "Registry accepts. Its list is not ISO 4217 — "
                            "renminbi is 'RMB', not 'CNY'."),
                )
            text = code
        out[field] = text
    return out


class RecordLocationRequest(BaseModel):
    """Where one statutory register is kept, or that it is kept nowhere.

    `None` is a real answer and must survive the round trip, so this cannot
    use the "drop the nulls" convention the field-patch models use — clearing
    a location and not mentioning it would become the same request.
    """
    address_id: Optional[str] = None


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
    filter_: list[str] = Query(
        default_factory=list, alias="filter",
        description="repeatable column:op:value — see services/table_filters",
    ),
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

    try:
        col_filters = tf.parse(filter_, _FILTERABLE)
    except tf.FilterError as exc:
        # 422, never a silently dropped filter: on a paginated listing a filter
        # the server ignored looks exactly like a filter that matched everything.
        raise HTTPException(status_code=422, detail=str(exc))

    def base(cols: str, count: Optional[str] = None, f: Optional[str] = ...):
        q = (sb.table(_LIST_RELATION).select(cols, count=count) if count
             else sb.table(_LIST_RELATION).select(cols))
        q = apply_flag(q, flag if f is ... else f)
        # Inside base() so the flag tabs and the pager count the same set the
        # rows come from — see the note on the anniversary filter below.
        q = tf.apply(q, col_filters)
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

    (officers, secretaries, shareholders, ben_owners, contacts, documents,
     share_classes, business_names, record_rows) = await asyncio.gather(
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
        # Removed documents come back too — dropped from their section, kept in
        # Document History, marked (Levi 2026-09-04).
        q(lambda: document_service.list_documents(
            owner_kind="entity", owner_id=company_id, include_deleted=True)),
        # CR's section 11 in its own right, not just the class names hanging
        # off each shareholding: the return states the company's share capital
        # whether or not anyone currently holds it.
        q(lambda: (sb.table("share_classes").select("*")
                   .eq("entity_id", company_id).execute().data) or []),
        # Brian's B9. 5,026 rows have sat here since the ETL and no screen has
        # ever read one; CR asks for `brName` on both forms.
        q(lambda: (sb.table("business_names").select("*")
                   .eq("entity_id", company_id).execute().data) or []),
        # NAR1 s16 (PRD §7.6 / OQ-3).
        q(lambda: (sb.table("entity_record_locations").select("*")
                   .eq("entity_id", company_id).execute().data) or []),
    )

    linked = officers + secretaries + shareholders + ben_owners
    corp_ids = {r["corporate_entity_id"] for r in linked if r.get("corporate_entity_id")}
    corp_names: dict[str, dict] = {}
    if corp_ids:
        rows = (sb.table("entities")
                .select("id, company_name, company_name_zh, br_number, cr_number, "
                        "tcsp_licence_no, registered_address_id")
                .in_("id", list(corp_ids)).execute().data) or []
        corp_names = {r["id"]: r for r in rows}
    for r in linked:
        cid = r.get("corporate_entity_id")
        if cid:
            r["corporate_entity"] = corp_names.get(cid)

    # Every address the profile shows, in ONE query.
    #
    # Brian's B4 ("shareholders need an address") and D2 (a director's
    # correspondence address) both turned out to be data already in Postgres
    # that nothing ever sent to the screen. Resolving them per row is what
    # made that expensive: a profile with eight directors, four shareholders
    # and thirteen registers is twenty-five sequential ~200ms round trips.
    # `registered_address` itself stays separate because it also needs its
    # share count.
    wanted: set[str] = set()
    for r in linked:
        for key in ("correspondence_address_id",):
            if r.get(key):
                wanted.add(r[key])
        person = r.get("persons") or {}
        if person.get("residential_address_id"):
            wanted.add(person["residential_address_id"])
    for corp in corp_names.values():
        if corp.get("registered_address_id"):
            wanted.add(corp["registered_address_id"])
    for row in record_rows:
        if row.get("address_id"):
            wanted.add(row["address_id"])

    by_id: dict[str, dict] = {}
    if wanted:
        rows = await asyncio.to_thread(
            lambda: (sb.table("addresses").select("*")
                     .in_("id", list(wanted)).execute().data) or []
        )
        by_id = {r["id"]: r for r in rows}

    for r in linked:
        # A director gives CR both: where they live and where they take post.
        r["correspondence_address"] = by_id.get(r.get("correspondence_address_id"))
        person = r.get("persons") or {}
        if person:
            person["residential_address"] = by_id.get(
                person.get("residential_address_id"))
    for corp in corp_names.values():
        # A body corporate's address IS its registered office — it does not
        # have a residence, and labelling it one on the screen would be wrong.
        corp["registered_address"] = by_id.get(corp.get("registered_address_id"))

    # Every register CR asks about, whether or not one has been recorded. A
    # register with nowhere kept is the answer s16 needs to *show* — dropping
    # the row would render an unanswered question as an answered one.
    seeded = {row["record_type"]: row for row in record_rows}
    record_locations = [
        {
            **seeded.get(code, {"record_type": code, "address_id": None}),
            "record_type": code,
            "label": label,
            "address": by_id.get((seeded.get(code) or {}).get("address_id")),
        }
        for code, label in record_types.RECORD_TYPES
    ]

    address = None
    if entity.get("registered_address_id"):
        address = await asyncio.to_thread(
            lambda: (sb.table("addresses").select("*")
                     .eq("id", entity["registered_address_id"]).single().execute()).data
        )
        if address:
            # How many records share this row, so the form can say what a save
            # will and will not touch BEFORE it is pressed. 4,446 companies sit
            # on GSHK's registered office; an edit box with no warning on it
            # would read as "this changes my company".
            address["shared_by"] = await asyncio.to_thread(
                lambda: address_service.count_references(sb, address["id"])
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
        "share_classes": share_classes,
        "business_names": business_names,
        "record_locations": record_locations,
    }
    # Whether a return can be produced from this profile at all. Computed here
    # so the screen and the API agree, and so the Open case button can say why
    # it is refusing rather than just being grey (PRD OQ-2).
    result["filing_problems"] = filing_problems(result)
    # Cases pane only for client entities (§6 visibility).
    if entity.get("is_client"):
        # `nar1_case_registry` (024) rather than the raw table: it carries
        # `workflow_status` and `filing_stage`, so the profile can tell whether
        # a case has FROZEN A SNAPSHOT of this company's data. Editing under a
        # live case leaves the profile and the validated return disagreeing,
        # and the raw rows cannot see that — they know nothing about filings.
        nar1, nnc1 = await asyncio.gather(
            q(lambda: (sb.table("nar1_case_registry").select("*")
                       .eq("entity_id", company_id).execute().data) or []),
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
    # No grandfathering here, unlike the edit path: a company being created now
    # has no legacy value to protect, and accepting free text would just mint
    # another row that has to be grandfathered later.
    if body.company_type and body.company_type not in _COMPANY_TYPE_CODES:
        raise HTTPException(
            status_code=422,
            detail=(f"{body.company_type!r} is not a company type CR "
                    f"recognises. The annual return takes "
                    f"{', '.join(f'{c} ({l})' for c, l in COMPANY_TYPE)}."),
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
        **audit_subject.for_company(company),
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

    # Business nature is a closed list of CR's, and the description follows the
    # code rather than being typed -- so an unknown code is refused here rather
    # than reaching CR, and the description is derived rather than trusted.
    if "business_nature_code" in updates:
        code = str(updates["business_nature_code"]).strip()
        description = BUSINESS_NATURE.get(code)
        if description is None:
            raise HTTPException(
                status_code=422,
                detail=f"{code!r} is not a CR business nature code",
            )
        updates["business_nature_code"] = code
        updates["business_nature_desc"] = description

    sb = get_supabase()
    current = (
        sb.table("entities").select("*").eq("id", company_id).single().execute()
    ).data
    if not current:
        raise HTTPException(status_code=404, detail="Company not found")

    # CR takes P, N or G on `coyType` and nothing else -- but this column held
    # Viewpoint's free text ("Private company limited by shares") long before
    # CR's codes reached it. Grandfathered the same way a legacy HKID is (D4):
    # the value already on the row is always allowed back, so re-saving an
    # untouched profile can never be refused. Only a NEW value must be CR's.
    if "company_type" in updates:
        value = str(updates["company_type"]).strip()
        if value not in _COMPANY_TYPE_CODES and value != (current.get("company_type") or ""):
            raise HTTPException(
                status_code=422,
                detail=(f"{value!r} is not a company type CR recognises. The "
                        f"annual return takes "
                        f"{', '.join(f'{c} ({l})' for c, l in COMPANY_TYPE)}."),
            )
        updates["company_type"] = value

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
            **audit_subject.for_company(current),
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


@router.put("/{company_id}/registered-address")
async def update_registered_address(
    company_id: str,
    body: AddressIn,
    user=Depends(require_permission("companies", "write")),
):
    """Set this company's registered office.

    COPY-ON-WRITE. 4,446 companies point at GSHK's own registered office,
    because GSHK provides registered-office services. Editing that row to
    correct ONE company would change the registered office of all of them, so
    a shared row is copied and only this company is repointed. See
    `services/address_service.py`.
    """
    sb = get_supabase()
    current = (
        sb.table("entities").select("id, company_name, registered_address_id")
        .eq("id", company_id).single().execute()
    ).data
    if not current:
        raise HTTPException(status_code=404, detail="Company not found")

    before = None
    if current.get("registered_address_id"):
        before = (
            sb.table("addresses").select("*")
            .eq("id", current["registered_address_id"]).single().execute()
        ).data

    try:
        result = address_service.save(
            sb,
            owner_table="entities", owner_id=company_id,
            owner_column="registered_address_id",
            current_address_id=current.get("registered_address_id"),
            payload=body.model_dump(),
        )
    except address_service.AddressError as exc:
        # 422, not 400: the request was well-formed, its content is what CR
        # will not take.
        raise HTTPException(status_code=422, detail=str(exc))

    await log_events(_address_audit_entries(
        entity_id=company_id, user=user, subject_name=current.get("company_name"),
        event_code=audit_events.VP_REG_OFFICE, before=before, result=result,
        subject=audit_subject.for_company(current),
    ))
    return {**result["address"], "shared_by": _shared_by(sb, result["address"]["id"])}


def _shared_by(sb, address_id: str) -> int:
    return address_service.count_references(sb, address_id)


def _address_audit_entries(*, entity_id, user, subject_name, event_code,
                           before, result, subject=None):
    """One entry per changed line — the `CASE_FIELD_UPDATED` contract.

    `copied_from` rides in the metadata because a copy-on-write save changes
    this record's address while deliberately leaving every other referent
    alone. Without it the trail shows an address changing and gives no account
    of why the other 4,445 companies did not change too.
    """
    after = result["address"]
    fields = address_service.LINE_FIELDS + address_service.DISTRICT_FIELDS + ("country",)
    entries = []
    for field in fields:
        old_val = (before or {}).get(field)
        new_val = after.get(field)
        if old_val == new_val:
            continue
        entries.append(dict(
            case_id=entity_id, user_id=user["id"],
            user_display_name=user["display_name"],
            action_type="CASE_FIELD_UPDATED", event_code=event_code,
            company_name=subject_name,
            **(subject or {}),
            entity_type="address", entity_id=str(after["id"]),
            old_value=old_val, new_value=new_val,
            before_state={"field": field, "old": old_val},
            after_state={"field": field, "new": new_val},
            metadata={
                "copied_from": result["copied_from"],
                "shared_by": result["shared_by"],
            },
        ))
    return entries


@router.patch("/{company_id}/share-classes/{share_class_id}")
async def update_share_class(
    company_id: str,
    share_class_id: str,
    body: ShareClassRequest,
    user=Depends(require_permission("companies", "write")),
):
    """Edit one class of shares — CR's section 11.

    The Share Capital card shipped read-only, badge and all, so a company
    whose Total Amount was blank displayed "1 to fix" and offered nothing
    that could fix it.
    """
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates = _validate_share_class(updates)

    sb = get_supabase()
    company = (
        sb.table("entities").select("company_name")
        .eq("id", company_id).single().execute()
    ).data
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Scoped to the company as well as the id: without the second filter a
    # share class belonging to another company could be edited through this
    # route just by knowing its id.
    current = (
        sb.table("share_classes").select("*")
        .eq("id", share_class_id).eq("entity_id", company_id)
        .single().execute()
    ).data
    if not current:
        raise HTTPException(status_code=404, detail="Share class not found")

    updated = (
        sb.table("share_classes").update(updates)
        .eq("id", share_class_id).execute()
    ).data
    updated = updated[0] if updated else {**current, **updates}

    await log_events([
        dict(
            case_id=company_id, user_id=user["id"],
            user_display_name=user["display_name"],
            action_type="CASE_FIELD_UPDATED",
            event_code=audit_events.company_field_code("share_capital"),
            company_name=company.get("company_name"),
            **audit_subject.for_company(company),
            entity_type="share_class", entity_id=str(share_class_id),
            old_value=old, new_value=new,
            before_state={"field": f"share_class.{field}", "old": old},
            after_state={"field": f"share_class.{field}", "new": new},
        )
        for field, new in updates.items()
        for old in [current.get(field)]
        if str(old if old is not None else "") != str(new if new is not None else "")
    ])
    return updated


@router.post("/{company_id}/share-classes", status_code=201)
async def create_share_class(
    company_id: str,
    body: ShareClassRequest,
    user=Depends(require_permission("companies", "write")),
):
    """Give a company its share capital.

    219 client companies hold none at all, which is what stops them filing
    (PRD §11.1). Editing alone would never unblock one of them, so this is
    the other half of the same fix.
    """
    values = _validate_share_class(
        {k: v for k, v in body.model_dump().items() if v is not None})

    # Every column CR marks Mandatory=Y, or the new row just moves the block
    # rather than clearing it.
    missing = [f for f in _SHARE_CLASS_FIELDS if not values.get(f)
               # 0 is a real answer for a paid-up figure.
               and values.get(f) != "0"]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(f"A class of shares needs {', '.join(sorted(missing))} — "
                    "the Companies Registry requires all of them on the "
                    "return."),
        )

    sb = get_supabase()
    company = _company_subject(sb, company_id)
    if not company.get("company_name"):
        raise HTTPException(status_code=404, detail="Company not found")

    created = (
        sb.table("share_classes")
        .insert({**values, "entity_id": company_id}).execute()
    ).data
    if not created:
        raise HTTPException(status_code=500, detail="Share class not created")

    # ONE ENTRY PER FIELD, exactly as the edit route does — the
    # `CASE_FIELD_UPDATED` contract, and the reason it matters here twice over.
    #
    # This used to write the whole `values` dict into `after_state.new`. Two
    # consequences: `new_value` was left NULL, so the row could not be found by
    # the search box or the What-changed filter, which read that column; and the
    # Audit Log CRASHED on it, because React will not render an object as a
    # child and a throw during render blanks the entire screen rather than one
    # cell. The frontend now coerces whatever it is given (`asText`), so the
    # page can no longer be taken down by history — but the row it was choking
    # on was genuinely malformed, and this is where that is fixed.
    await log_events([
        dict(
            case_id=company_id, user_id=user["id"],
            user_display_name=user["display_name"],
            action_type="CASE_FIELD_UPDATED",
            event_code=audit_events.company_field_code("share_capital"),
            company_name=company.get("company_name"),
            **audit_subject.for_company(company),
            entity_type="share_class", entity_id=str(created[0]["id"]),
            new_value=value,
            after_state={"field": f"share_class.{field}", "new": value},
        )
        for field, value in values.items()
    ])
    return created[0]


@router.put("/{company_id}/record-locations/{record_type}")
async def set_record_location(
    company_id: str,
    record_type: str,
    body: RecordLocationRequest,
    user=Depends(require_permission("companies", "write")),
):
    """Point one statutory register at an address, or at nothing (OQ-3).

    One row per register per company, so this is an upsert on the unique
    (entity_id, record_type) — an operator correcting a location twice must
    not leave two answers to the same NAR1 question.
    """
    if not record_types.is_known(record_type):
        raise HTTPException(
            status_code=422,
            detail=(f"'{record_type}' is not a register the annual return asks "
                    f"about. CR's section 16 covers: "
                    f"{', '.join(record_types.RECORD_TYPE_CODES)}."),
        )

    sb = get_supabase()
    company = (
        sb.table("entities").select("company_name")
        .eq("id", company_id).single().execute()
    ).data
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    existing = next(
        (r for r in (sb.table("entity_record_locations").select("*")
                     .eq("entity_id", company_id).execute().data or [])
         if r.get("record_type") == record_type),
        None,
    )
    old_value = (existing or {}).get("address_id")
    new_value = body.address_id

    row = {"entity_id": company_id, "record_type": record_type,
           "address_id": new_value}
    saved = (
        sb.table("entity_record_locations")
        .upsert(row, on_conflict="entity_id,record_type").execute()
    ).data
    saved = saved[0] if saved else row

    # No new action_type (PRD §12b): this is a field edit on the company, and
    # `record_location` earns its own event code so the trail says WHICH
    # register moved rather than "General".
    await log_events([
        dict(
            case_id=company_id, user_id=user["id"],
            user_display_name=user["display_name"],
            action_type="CASE_FIELD_UPDATED",
            event_code=audit_events.company_field_code("record_location"),
            company_name=company.get("company_name"),
            **audit_subject.for_company(company),
            entity_type="entity_record_location", entity_id=str(company_id),
            old_value=old_value, new_value=new_value,
            before_state={"field": f"record_location.{record_type}",
                          "old": old_value},
            after_state={"field": f"record_location.{record_type}",
                         "new": new_value},
            metadata={"register": record_types.label_for(record_type)},
        )
    ] if old_value != new_value else [])

    return {**saved, "label": record_types.label_for(record_type)}


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
        **audit_subject.for_company(current),
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


def _company_subject(sb, company_id: str) -> dict:
    """The company an audit row is about — the name to show, the BRN to quote.

    One select for both halves. The audit trail renders a body corporate as
    "name (BRN)", and fetching the name alone is what left the reference blank
    on every party link in the trail.
    """
    row = (
        sb.table("entities").select("id, company_name, br_number")
        .eq("id", company_id).single().execute()
    ).data
    return row or {"id": company_id}


def _company_name(sb, company_id: str) -> Optional[str]:
    return _company_subject(sb, company_id).get("company_name")


def _company_subject_audit(sb, company_id: str) -> dict:
    """`company_name` plus the subject keys, in one call, for a single-use site."""
    subject = _company_subject(sb, company_id)
    return {"company_name": subject.get("company_name"),
            **audit_subject.for_company(subject)}


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
        **_company_subject_audit(sb, company_id),
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
    subject = _company_subject_audit(sb, company_id)
    await log_events([
        dict(
            case_id=company_id, user_id=user["id"],
            user_display_name=user["display_name"], action_type="PARTY_UPDATED",
            event_code=audit_events.party_code(relation, "update"),
            **subject,
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
        **_company_subject_audit(sb, company_id),
        entity_type="entity", entity_id=str(company_id),
        # Removal has no "new" — the old value is the party that held the role.
        old_value=_party_summary(party, current),
        before_state={"relation": relation, "link_id": link_id, "party": party,
                      **{k: current.get(k) for k in ("person_id", "corporate_entity_id")}},
    )
    return {"message": "Unlinked", "link_id": link_id}

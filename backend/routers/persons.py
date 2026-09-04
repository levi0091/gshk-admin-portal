"""Persons CRUD + person-scoped documents (PBI-39 Block 1).

Gated by require_permission("persons"/"documents", ...). Every mutation audits.
Person Profile carries fields, identity documents, residential address, a role
roll-up (read-only from the link tables), and document history.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel

from middleware.auth import require_permission
from db.supabase import get_supabase
from services.audit_service import log_event, log_events
from services import audit_subject
from services import (
    audit_events, document_service, document_sections, address_service,
    table_filters as tf,
)
from routers.companies import AddressIn, _address_audit_entries
from services.hkid import is_valid_hkid
from services.tpsi.forms.cr_vocabularies import resolve_country

router = APIRouter()

_EDITABLE_FIELDS = {
    "full_name", "given_names", "surname", "full_name_zh", "former_name",
    # CR asks for Previous Names in both languages and Alias separately from
    # them -- a previous name is one you no longer use, an alias one you also
    # use. The ETL used to merge them into `former_name` (migration 028).
    "former_name_zh", "alias_en", "alias_zh",
    "email", "phone", "date_of_birth", "gender", "nationality",
    "nationality_code", "nationality_origin", "occupation", "place_of_birth",
    "marital_status", "date_of_death", "residential_address_id",
}


class IdentityDocumentIn(BaseModel):
    """An identity document supplied alongside a new person.

    THE FIELD THAT WAS MISSING. A person could be created with names, a
    nationality and a date of birth, and no way at all to record the number CR
    files them by — the profile could only EDIT identity documents, so a person
    created here had none and no screen offered to add one. Both NAR1 and NNC1
    carry an individual's HKID or passport number for every director; a person
    without one blocks the return at `nar1_mapper._individual_id`.
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
    identity_document: Optional[IdentityDocumentIn] = None


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
        if address:
            address["shared_by"] = address_service.count_references(sb, address["id"])
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
    # Validated BEFORE the person is inserted: a mistyped HKID must refuse the
    # whole creation, not leave a person behind with no identity document and
    # an error message the operator has already navigated away from.
    id_doc = _validated_identity_row(body.identity_document) if body.identity_document else None

    sb = get_supabase()
    row = {k: v for k, v in body.model_dump(exclude={"identity_document"}).items()
           if v is not None}
    created = sb.table("persons").insert(row).execute().data
    if not created:
        raise HTTPException(status_code=400, detail="Person insert failed")
    person = created[0]

    if id_doc:
        sb.table("person_identity_documents").insert(
            {**id_doc, "person_id": person["id"]}).execute()

    await log_event(
        case_id=None, user_id=user["id"],
        user_display_name=user["display_name"], action_type="PERSON_CREATED",
        event_code=audit_events.VP_NEW_MASTER_FILE,   # Viewpoint: New Master File
        company_name=person["full_name"],             # subject of the event
        # A person is quoted by their identity number, which now exists at
        # creation when one was supplied — previously it could not, because
        # there was no field to type it into.
        **audit_subject.for_person(
            person, id_number=(id_doc or {}).get("id_number")),
        entity_type="person", entity_id=str(person["id"]),
        new_value=person["full_name"],
        after_state={**row, **({"identity_document": id_doc} if id_doc else {})},
    )
    # The screen needs the document back to render the card it just created.
    return {**person, "identity_documents": [id_doc] if id_doc else []}


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
    user=Depends(require_permission("persons", "write")),
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

    updated = (
        sb.table("person_identity_documents").update(updates)
        .eq("id", document_id).execute()
    ).data[0]

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
    user=Depends(require_permission("persons", "write")),
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


@router.put("/{person_id}/residential-address")
async def update_residential_address(
    person_id: str,
    body: AddressIn,
    user=Depends(require_permission("persons", "write")),
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

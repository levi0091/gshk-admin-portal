"""Document storage service (PBI-39 Block 1).

Owns the upload / versioning / signed-URL / soft-delete logic shared by the
company- and person-scoped document routes. Binaries live in a private Supabase
Storage bucket; the `documents` / `document_versions` tables hold metadata + the
storage locator only (schema.sql Â§9).

Rules enforced here:
- Polymorphic owner: exactly one of entity_id / person_id is set (owner_kind).
- Re-uploading an existing (owner, document_type) creates a NEW version â€” the
  documents row is updated in place (current_version++), a document_versions row
  is appended, and history is preserved. Never a destructive overwrite.
- Soft-delete only: status -> 'deleted' (OQ-2). The object is retained.
- Every mutation audits via audit_service (PBI-11); audit never blocks the op.
"""
import hashlib
from typing import Optional

from fastapi import HTTPException

from db.supabase import get_supabase
from services.audit_service import log_event
from services import audit_subject
from services import audit_events

BUCKET = "gflowdesk-documents"
_SIGNED_URL_TTL = 3600  # seconds

#: `receipt` is a NAR1 CASE, not a company and not a person (migration 029).
#: A CR filing receipt belongs to one annual return: owning it by entity would
#: make next year's upload version over this year's evidence, because
#: upload_document versions in place on (owner, document_type).
_OWNER_KINDS = {"entity", "person", "receipt"}

#: Owner kinds whose id is a `nar1_cases.id`. Kept as a set rather than an
#: `== "receipt"` test so a second case-owned section does not have to find
#: every branch again.
_CASE_OWNER_KINDS = {"receipt"}

_OWNER_COLUMN = {
    "entity": "entity_id",
    "person": "person_id",
    "receipt": "nar1_case_id",
}


def _storage_path(owner_kind: str, owner_id: str, document_type_code: str,
                  version: int, file_name: str) -> str:
    """Path convention (OQ-5): /{entity|person}/{id}/{document_type}/{version}/{file}.

    `receipt` is the exception spec §4 specifies literally:
    `receipt/{nar1_case_id}/{version}/{file}` — no type segment, because a case
    section carries exactly one document type (`cr_receipt`) and a constant
    directory between the id and the version says nothing.
    """
    safe_name = (file_name or "file").replace("/", "_")
    if owner_kind in _CASE_OWNER_KINDS:
        return f"{owner_kind}/{owner_id}/{version}/{safe_name}"
    return f"{owner_kind}/{owner_id}/{document_type_code}/{version}/{safe_name}"


def _upload_bytes(sb, path: str, content: bytes, mime_type: Optional[str]) -> None:
    try:
        sb.storage.from_(BUCKET).upload(
            path,
            content,
            {"content-type": mime_type or "application/octet-stream", "upsert": "true"},
        )
    except Exception as exc:  # storage failure must surface (unlike audit)
        raise HTTPException(status_code=502, detail=f"Storage upload failed: {exc}")


def _case_row(sb, case_id: str) -> dict:
    """The NAR1 case a document hangs off — its company, and its case number.

    `audit_log.case_id` holds an ENTITY id (routers/cases.py::_audit_target), so
    a case-owned document has to resolve through to the entity or its audit row
    lands in an id space no company query returns — the defect _audit_target
    exists to document. The case number comes back in the same select because
    the trail quotes it beside the company name.
    """
    try:
        row = (sb.table("nar1_cases").select("id, entity_id, case_no")
               .eq("id", case_id).single().execute()).data
        return row or {"id": case_id}
    except Exception:  # noqa: BLE001
        return {"id": case_id}


def _case_entity_id(sb, case_id: str) -> Optional[str]:
    return _case_row(sb, case_id).get("entity_id")


def _entity_subject(sb, entity_id: Optional[str]) -> dict:
    if not entity_id:
        return {}
    try:
        row = (sb.table("entities").select("id, company_name, br_number")
               .eq("id", entity_id).single().execute()).data
    except Exception:  # noqa: BLE001
        return {}
    return row or {}


def _audit_owner(sb, owner_kind: str, owner_id: Optional[str]) -> dict:
    """Everything an audit row needs to say WHICH record a document belongs to.

    One helper, one pass, because the three answers are the same lookup:

      case_id        the ENTITY id, never a case id (routers/cases.py
                     ::_audit_target) — this is how a company's whole trail is
                     queried, and a case id there is invisible to it.
      company_name   the company or person the document hangs off.
      subject_*      module, kind, id and the reference a human quotes, so the
                     trail reads "Kanenas Holding Limited (69123456)" rather
                     than naming nothing.

    A CASE-owned document (a CR receipt, a wet-signed return) is filed under its
    CASE, not its company: it is an artefact of one filing of one year. The
    company still appears, as the name beside the case number.

    THE MODULE IS THE OWNER'S MODULE, not a `documents` module (Levi
    2026-09-04). None of the three calls below passes one, so each takes the
    default for its kind: an id scan on a director is a Natural Person change,
    a certificate against a company is a Body Corporate change, and a CR receipt
    on a case is Post-incorporation. A director's history is then one filter
    away instead of two.

    Swallows every failure — a document upload must not fail because the audit
    row could not be made prettier.
    """
    if not owner_id:
        return {}

    if owner_kind in _CASE_OWNER_KINDS:
        case = _case_row(sb, owner_id)
        entity = _entity_subject(sb, case.get("entity_id"))
        return {
            "case_id": case.get("entity_id"),
            "company_name": entity.get("company_name"),
            **audit_subject.for_case(case),
        }

    if owner_kind == "entity":
        entity = _entity_subject(sb, owner_id)
        return {
            "case_id": owner_id,
            "company_name": entity.get("company_name"),
            **audit_subject.for_company(entity or {"id": owner_id}),
        }

    try:
        person = (sb.table("persons").select("id, full_name")
                  .eq("id", owner_id).single().execute()).data or {}
    except Exception:  # noqa: BLE001
        person = {"id": owner_id}
    return {
        "case_id": None,
        "company_name": person.get("full_name"),
        **audit_subject.for_person(
            person,
            id_number=audit_subject.primary_id_number(sb, owner_id),
        ),
    }


def _owner_columns(owner_kind: str, owner_id: str) -> dict:
    return {_OWNER_COLUMN[owner_kind]: owner_id}


def _owner_kind_of(doc: dict) -> str:
    """Which of the three owner columns a stored row actually uses."""
    for kind, column in _OWNER_COLUMN.items():
        if doc.get(column):
            return kind
    return "entity"


async def upload_document(
    *,
    owner_kind: str,
    owner_id: str,
    document_type_code: str,
    file_name: str,
    content: bytes,
    mime_type: Optional[str],
    title: Optional[str],
    user: dict,
) -> dict:
    if owner_kind not in _OWNER_KINDS:
        raise HTTPException(status_code=400, detail="Invalid owner kind")

    sb = get_supabase()
    checksum = hashlib.sha256(content).hexdigest()
    size = len(content)

    # Find an existing *active* document of this type for this owner.
    q = (
        sb.table("documents")
        .select("*")
        .eq("document_type_code", document_type_code)
        .eq("status", "active")
    )
    q = q.eq(_OWNER_COLUMN[owner_kind], owner_id)
    existing = (q.execute().data) or []

    if existing:
        doc = existing[0]
        new_version = (doc.get("current_version") or 1) + 1
        path = _storage_path(owner_kind, owner_id, document_type_code, new_version, file_name)
        _upload_bytes(sb, path, content, mime_type)

        sb.table("document_versions").insert({
            "document_id": doc["id"],
            "version_number": new_version,
            "file_name": file_name,
            "storage_bucket": BUCKET,
            "storage_path": path,
            "mime_type": mime_type,
            "file_size_bytes": size,
            "checksum_sha256": checksum,
            "created_by": user["id"],
        }).execute()

        updated = (
            sb.table("documents")
            .update({
                "storage_path": path,
                "current_version": new_version,
                "file_name": file_name,
                "mime_type": mime_type,
                "file_size_bytes": size,
                "checksum_sha256": checksum,
                "title": title if title is not None else doc.get("title"),
            })
            .eq("id", doc["id"])
            .execute()
        ).data[0]

        await log_event(
            **_audit_owner(sb, owner_kind, owner_id),
            user_id=user["id"],
            user_display_name=user["display_name"],
            action_type="DOCUMENT_VERSION_ADDED",
            event_code=audit_events.GF_DOC_VERSION,   # no Viewpoint equivalent
            entity_type="document",
            entity_id=str(doc["id"]),
            old_value=f"{document_type_code} v{new_version - 1}",
            new_value=f"{document_type_code} v{new_version} ({file_name})",
            metadata={"owner_kind": owner_kind, "owner_id": owner_id,
                      "document_type_code": document_type_code, "version": new_version},
        )
        return updated

    # First upload of this type for this owner â†’ version 1.
    path = _storage_path(owner_kind, owner_id, document_type_code, 1, file_name)
    _upload_bytes(sb, path, content, mime_type)

    row = {
        **_owner_columns(owner_kind, owner_id),
        "document_type_code": document_type_code,
        "title": title,
        "file_name": file_name,
        "storage_bucket": BUCKET,
        "storage_path": path,
        "mime_type": mime_type,
        "file_size_bytes": size,
        "checksum_sha256": checksum,
        "current_version": 1,
        "status": "active",
        "is_generated": False,
        "uploaded_by": user["id"],
    }
    created = sb.table("documents").insert(row).execute().data[0]

    sb.table("document_versions").insert({
        "document_id": created["id"],
        "version_number": 1,
        "file_name": file_name,
        "storage_bucket": BUCKET,
        "storage_path": path,
        "mime_type": mime_type,
        "file_size_bytes": size,
        "checksum_sha256": checksum,
        "created_by": user["id"],
    }).execute()

    await log_event(
        **_audit_owner(sb, owner_kind, owner_id),
        user_id=user["id"],
        user_display_name=user["display_name"],
        action_type="DOCUMENT_UPLOADED",
        event_code=audit_events.GF_DOC_UPLOADED,   # no Viewpoint equivalent
        entity_type="document",
        entity_id=str(created["id"]),
        new_value=f"{document_type_code} v1 ({file_name})",
        metadata={"owner_kind": owner_kind, "owner_id": owner_id,
                  "document_type_code": document_type_code, "version": 1},
    )
    return created


def list_documents(*, owner_kind: str, owner_id: str) -> list[dict]:
    """Active + superseded documents for an owner, with version history.

    Embeds document_types so the UI can say WHAT the document is ("Certificate of
    Incorporation") and not just the uploaded file name.
    """
    sb = get_supabase()
    q = (
        sb.table("documents")
        .select("*, document_versions(*), document_types(code, label, category)")
        .neq("status", "deleted")
    )
    q = q.eq(_OWNER_COLUMN[owner_kind], owner_id)
    return (q.order("document_type_code").execute().data) or []


def create_signed_url(document_id: str) -> dict:
    """Signed URL that DOWNLOADS the file rather than rendering it in the tab.

    Supabase serves objects inline by default, so a PDF just opens in the
    browser. Passing `download` makes Storage return
    Content-Disposition: attachment, which is what a "Download" button should do.
    """
    sb = get_supabase()
    doc = (
        sb.table("documents").select("*").eq("id", document_id).single().execute()
    ).data
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.get("status") == "deleted":
        raise HTTPException(status_code=404, detail="Document deleted")

    file_name = doc.get("file_name") or "document"
    try:
        signed = sb.storage.from_(doc.get("storage_bucket") or BUCKET).create_signed_url(
            doc["storage_path"], _SIGNED_URL_TTL, options={"download": file_name}
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Signed URL failed: {exc}")
    url = signed.get("signedURL") or signed.get("signedUrl") or signed.get("signed_url")
    return {"url": url, "file_name": file_name, "expires_in": _SIGNED_URL_TTL}


async def soft_delete_document(*, document_id: str, user: dict) -> dict:
    sb = get_supabase()
    doc = (
        sb.table("documents").select("*").eq("id", document_id).single().execute()
    ).data
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    updated = (
        sb.table("documents").update({"status": "deleted"}).eq("id", document_id).execute()
    ).data[0]

    # Read back off the row, so a case-owned receipt (migration 029) is named
    # and filed under its company like every other document rather than
    # logging a null owner.
    owner_kind = _owner_kind_of(doc)
    owner_id = doc.get(_OWNER_COLUMN[owner_kind])
    await log_event(
        **_audit_owner(sb, owner_kind, owner_id),
        user_id=user["id"],
        user_display_name=user["display_name"],
        action_type="DOCUMENT_DELETED",
        event_code=audit_events.GF_DOC_DELETED,   # no Viewpoint equivalent
        entity_type="document",
        entity_id=str(document_id),
        old_value=f"{doc.get('document_type_code')} ({doc.get('file_name')})",
        new_value="deleted",
        before_state={"status": doc.get("status")},
        after_state={"status": "deleted"},
    )
    return updated

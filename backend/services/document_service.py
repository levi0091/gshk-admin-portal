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
from services import audit_events

BUCKET = "gflowdesk-documents"
_SIGNED_URL_TTL = 3600  # seconds

_OWNER_KINDS = {"entity", "person"}


def _storage_path(owner_kind: str, owner_id: str, document_type_code: str,
                  version: int, file_name: str) -> str:
    """Path convention (OQ-5): /{entity|person}/{id}/{document_type}/{version}/{file}."""
    safe_name = (file_name or "file").replace("/", "_")
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


def _owner_name(sb, owner_kind: str, owner_id: Optional[str]) -> Optional[str]:
    """The company or person the document belongs to — recorded on the audit row
    so the trail names the subject without a join."""
    if not owner_id:
        return None
    try:
        if owner_kind == "entity":
            row = (sb.table("entities").select("company_name")
                   .eq("id", owner_id).single().execute()).data
            return (row or {}).get("company_name")
        row = (sb.table("persons").select("full_name")
               .eq("id", owner_id).single().execute()).data
        return (row or {}).get("full_name")
    except Exception:
        return None


def _owner_columns(owner_kind: str, owner_id: str) -> dict:
    return {"entity_id": owner_id} if owner_kind == "entity" else {"person_id": owner_id}


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
    if owner_kind == "entity":
        q = q.eq("entity_id", owner_id)
    else:
        q = q.eq("person_id", owner_id)
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
            case_id=owner_id if owner_kind == "entity" else None,
            user_id=user["id"],
            user_display_name=user["display_name"],
            action_type="DOCUMENT_VERSION_ADDED",
            event_code=audit_events.GF_DOC_VERSION,   # no Viewpoint equivalent
            company_name=_owner_name(sb, owner_kind, owner_id),
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
        case_id=owner_id if owner_kind == "entity" else None,
        user_id=user["id"],
        user_display_name=user["display_name"],
        action_type="DOCUMENT_UPLOADED",
        event_code=audit_events.GF_DOC_UPLOADED,   # no Viewpoint equivalent
        company_name=_owner_name(sb, owner_kind, owner_id),
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
    if owner_kind == "entity":
        q = q.eq("entity_id", owner_id)
    else:
        q = q.eq("person_id", owner_id)
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

    owner_kind = "entity" if doc.get("entity_id") else "person"
    owner_id = doc.get("entity_id") or doc.get("person_id")
    await log_event(
        case_id=doc.get("entity_id"),
        user_id=user["id"],
        user_display_name=user["display_name"],
        action_type="DOCUMENT_DELETED",
        event_code=audit_events.GF_DOC_DELETED,   # no Viewpoint equivalent
        company_name=_owner_name(sb, owner_kind, owner_id),
        entity_type="document",
        entity_id=str(document_id),
        old_value=f"{doc.get('document_type_code')} ({doc.get('file_name')})",
        new_value="deleted",
        before_state={"status": doc.get("status")},
        after_state={"status": "deleted"},
    )
    return updated

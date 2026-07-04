"""Documents domain — Pydantic schemas + dict-row CRUD (PBI-38, greenfield).

Data access uses the Supabase client with dict rows (no ORM), mirroring
services/audit_service.py. Storage object I/O (upload / signed URL / delete) and
the upload-then-commit orchestration live in services/storage_service.py
(Block 3). This module is the DB layer only: the document_types lookup,
`documents`, and `document_versions`.

Documents are greenfield (client-confirmed 2026-07-04): nothing is migrated from
Viewpoint. Binaries live in Supabase Storage; these rows hold metadata + the
storage locator (bucket + object path) only.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from db.supabase import get_supabase

DEFAULT_BUCKET = "gflowdesk-documents"
DOCUMENT_STATUSES = ("active", "superseded", "deleted")


# --- Pydantic schemas --------------------------------------------------------

class DocumentType(BaseModel):
    """Row of the document_types lookup (seeded by the 003 migration)."""
    code: str
    label: str
    category: Optional[str] = None
    is_generated: bool = False
    template_ref: Optional[str] = None
    sort_order: int = 100
    is_active: bool = True


class DocumentCreate(BaseModel):
    """Fields required to register a document AFTER its object is in Storage."""
    document_type_code: str = "other"
    storage_path: str                      # object key within the bucket
    entity_id: Optional[str] = None        # NULL for person-scoped docs (e.g. ID scans)
    title: Optional[str] = None
    file_name: Optional[str] = None
    storage_bucket: str = DEFAULT_BUCKET
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    checksum_sha256: Optional[str] = None
    is_generated: bool = False
    generated_by: Optional[str] = None     # user id (generated docs)
    uploaded_by: Optional[str] = None      # user id (uploaded docs)


class Document(DocumentCreate):
    """Full documents row as returned by the DB."""
    id: str
    current_version: int = 1
    status: str = "active"
    generated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DocumentVersionCreate(BaseModel):
    document_id: str
    version_number: int
    storage_path: str
    storage_bucket: str = DEFAULT_BUCKET
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    checksum_sha256: Optional[str] = None
    generated_at: Optional[datetime] = None
    created_by: Optional[str] = None       # user id
    note: Optional[str] = None             # reason for the revision


class DocumentVersion(DocumentVersionCreate):
    id: str
    created_at: Optional[datetime] = None


def _payload(data: BaseModel | dict) -> dict:
    """Insert payload — model fields (or dict) with None values stripped so
    DB defaults (id, timestamps, current_version, status) apply."""
    if isinstance(data, BaseModel):
        return data.model_dump(exclude_none=True)
    return {k: v for k, v in data.items() if v is not None}


# --- document_types ----------------------------------------------------------

def list_document_types(active_only: bool = True) -> list[dict]:
    sb = get_supabase()
    q = sb.table("document_types").select("*")
    if active_only:
        q = q.eq("is_active", True)
    return q.order("sort_order").execute().data or []


# --- documents ---------------------------------------------------------------

def insert_document(data: DocumentCreate | dict) -> dict:
    """Insert a documents row. The caller MUST have uploaded the object first —
    see storage_service.store_document for the upload-then-commit helper."""
    sb = get_supabase()
    result = sb.table("documents").insert(_payload(data)).execute()
    if not result.data:
        raise RuntimeError("documents insert returned no row")
    return result.data[0]


def get_document(document_id: str) -> Optional[dict]:
    sb = get_supabase()
    rows = (
        sb.table("documents").select("*").eq("id", document_id).limit(1).execute().data
        or []
    )
    return rows[0] if rows else None


def list_documents(entity_id: Optional[str] = None) -> list[dict]:
    sb = get_supabase()
    q = sb.table("documents").select("*").neq("status", "deleted")
    if entity_id is not None:
        q = q.eq("entity_id", entity_id)
    return q.order("created_at", desc=True).execute().data or []


def set_document_status(document_id: str, status: str) -> dict:
    if status not in DOCUMENT_STATUSES:
        raise ValueError(f"invalid status {status!r}; expected one of {DOCUMENT_STATUSES}")
    sb = get_supabase()
    result = (
        sb.table("documents").update({"status": status}).eq("id", document_id).execute()
    )
    if not result.data:
        raise RuntimeError(f"document {document_id} not found")
    return result.data[0]


def delete_document_row(document_id: str) -> None:
    """Hard-delete the DB row. Storage object cleanup is the caller's job
    (storage_service). Prefer set_document_status(..., 'deleted') for soft delete."""
    sb = get_supabase()
    sb.table("documents").delete().eq("id", document_id).execute()


# --- document_versions -------------------------------------------------------

def add_version(data: DocumentVersionCreate | dict) -> dict:
    """Insert a version row and advance documents.current_version to it."""
    payload = _payload(data)
    sb = get_supabase()
    result = sb.table("document_versions").insert(payload).execute()
    if not result.data:
        raise RuntimeError("document_versions insert returned no row")
    version = result.data[0]
    (
        sb.table("documents")
        .update({"current_version": payload["version_number"]})
        .eq("id", payload["document_id"])
        .execute()
    )
    return version


def list_versions(document_id: str) -> list[dict]:
    sb = get_supabase()
    return (
        sb.table("document_versions")
        .select("*")
        .eq("document_id", document_id)
        .order("version_number")
        .execute()
        .data
        or []
    )

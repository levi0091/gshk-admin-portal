"""Supabase Storage service (PBI-38, greenfield documents).

Binaries live in a PRIVATE Supabase Storage bucket (`gflowdesk-documents`);
Postgres holds metadata + the storage locator only (services/documents_service).
Objects are reached exclusively through short-lived SIGNED URLs — no public
objects. Credentials come from the environment (gshk/secrets/supabase.env via the
Supabase client); nothing is hardcoded, printed, or logged here.

Consistency pattern (documents <-> Storage): the object is uploaded FIRST, then
the DB row that references it is committed; a failed commit deletes the orphaned
object, and a periodic sweep removes objects with no owning row. This recovers
most of the atomicity of in-DB blobs without bloating Postgres.
"""
from __future__ import annotations

import hashlib
import sys
from typing import Optional
from uuid import uuid4

from db.supabase import get_supabase
from services.documents_service import DEFAULT_BUCKET, DocumentCreate, insert_document

BUCKET = DEFAULT_BUCKET
DEFAULT_SIGNED_URL_TTL = 300  # seconds (5 min) — KYC/PII objects are short-lived


# --- bucket / object primitives ----------------------------------------------

def ensure_bucket() -> None:
    """Create the private bucket if it does not already exist. Idempotent."""
    sb = get_supabase()
    try:
        existing = sb.storage.list_buckets() or []
        ids = set()
        for b in existing:
            ids.add(getattr(b, "id", None) or (b.get("id") if isinstance(b, dict) else None))
        if BUCKET in ids:
            return
    except Exception:
        pass  # fall through to create; create is the source of truth
    sb.storage.create_bucket(BUCKET, options={"public": False})


def upload(object_path: str, content: bytes, mime_type: Optional[str] = None):
    """Upload an object. Does NOT upsert — a colliding path is an error."""
    sb = get_supabase()
    file_options = {"upsert": "false"}
    if mime_type:
        file_options["content-type"] = mime_type
    return sb.storage.from_(BUCKET).upload(object_path, content, file_options)


def signed_url(object_path: str, ttl: int = DEFAULT_SIGNED_URL_TTL) -> Optional[str]:
    """Return a short-lived signed URL for the object (None if unavailable)."""
    sb = get_supabase()
    resp = sb.storage.from_(BUCKET).create_signed_url(object_path, ttl)
    if isinstance(resp, dict):
        return resp.get("signedURL") or resp.get("signedUrl") or resp.get("signed_url")
    return resp


def delete(object_path: str):
    """Remove an object from the bucket."""
    sb = get_supabase()
    return sb.storage.from_(BUCKET).remove([object_path])


def build_object_path(
    entity_id: Optional[str], document_type_code: str, file_name: Optional[str]
) -> str:
    """entities/{entity_id}/{type}/{uuid}.ext — 'unassigned' scope when no entity
    (e.g. person-scoped ID scans). Random uuid avoids collisions/enumeration."""
    ext = ""
    if file_name and "." in file_name:
        ext = "." + file_name.rsplit(".", 1)[1].lower()
    scope = f"entities/{entity_id}" if entity_id else "unassigned"
    return f"{scope}/{document_type_code}/{uuid4().hex}{ext}"


# --- upload-then-commit write helper -----------------------------------------

def store_document(
    *,
    content: bytes,
    document_type_code: str = "other",
    entity_id: Optional[str] = None,
    file_name: Optional[str] = None,
    mime_type: Optional[str] = None,
    title: Optional[str] = None,
    is_generated: bool = False,
    generated_by: Optional[str] = None,
    uploaded_by: Optional[str] = None,
) -> dict:
    """Upload the object, THEN commit the documents row. If the DB insert fails,
    delete the orphaned object and re-raise. Returns the inserted documents row."""
    object_path = build_object_path(entity_id, document_type_code, file_name)
    checksum = hashlib.sha256(content).hexdigest()

    upload(object_path, content, mime_type)  # object first

    try:
        return insert_document(
            DocumentCreate(
                document_type_code=document_type_code,
                storage_path=object_path,
                storage_bucket=BUCKET,
                entity_id=entity_id,
                title=title,
                file_name=file_name,
                mime_type=mime_type,
                file_size_bytes=len(content),
                checksum_sha256=checksum,
                is_generated=is_generated,
                generated_by=generated_by,
                uploaded_by=uploaded_by,
            )
        )
    except Exception:
        # commit failed — roll back the orphaned object so Storage stays clean
        try:
            delete(object_path)
        except Exception as cleanup_exc:
            print(
                f"[storage_service] orphan cleanup FAILED for {object_path}: {cleanup_exc}",
                file=sys.stderr,
            )
        raise


# --- orphan sweep ------------------------------------------------------------

def _known_storage_paths(candidate_paths: list[str]) -> set[str]:
    """Paths (from the candidate list) that are referenced by a documents or
    document_versions row — i.e. NOT orphans."""
    sb = get_supabase()
    known: set[str] = set()
    for table in ("documents", "document_versions"):
        rows = (
            sb.table(table)
            .select("storage_path")
            .in_("storage_path", candidate_paths)
            .execute()
            .data
            or []
        )
        known.update(r["storage_path"] for r in rows if r.get("storage_path"))
    return known


def sweep_orphans(prefix: str = "", *, dry_run: bool = False) -> list[str]:
    """Delete objects under `prefix` with no owning DB row. Returns the orphan
    paths (removed, or that WOULD be removed when dry_run). NOTE: Storage.list is
    non-recursive — pass a leaf prefix (e.g. 'entities/<id>/<type>') per sweep."""
    sb = get_supabase()
    objects = sb.storage.from_(BUCKET).list(prefix) or []
    names = [
        (f"{prefix}/{o['name']}".lstrip("/") if prefix else o["name"])
        for o in objects
        if o.get("name")
    ]
    if not names:
        return []
    known = _known_storage_paths(names)
    orphans = [n for n in names if n not in known]
    if not dry_run:
        for path in orphans:
            sb.storage.from_(BUCKET).remove([path])
    return orphans

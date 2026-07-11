"""Document download (signed URL) + soft-delete (PBI-39 Block 1).

Upload / list live under the owner routes (companies.py / persons.py). These
two are keyed by document id directly.
"""
from fastapi import APIRouter, Depends

from middleware.auth import require_permission
from db.supabase import get_supabase
from services import document_service

router = APIRouter()


@router.get("/types")
async def list_document_types(
    user=Depends(require_permission("documents", "read")),
):
    """Seeded `document_types` lookup — drives the upload type picker.

    Declared before /{document_id}/... so "types" isn't matched as a document id.
    """
    sb = get_supabase()
    return (
        sb.table("document_types").select("*")
        .eq("is_active", True).order("sort_order").execute().data
    ) or []


@router.get("/{document_id}/download")
async def download_document(
    document_id: str,
    user=Depends(require_permission("documents", "read")),
):
    """Returns a short-lived signed URL for the current version (private bucket)."""
    return document_service.create_signed_url(document_id)


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    user=Depends(require_permission("documents", "delete")),
):
    """Soft-delete (status='deleted'); the object is retained (OQ-2)."""
    return await document_service.soft_delete_document(document_id=document_id, user=user)

"""Document download (signed URL) + soft-delete (PBI-39 Block 1).

Upload / list live under the owner routes (companies.py / persons.py). These
two are keyed by document id directly.
"""
from fastapi import APIRouter, Depends, HTTPException

from middleware.auth import require_permission
from db.supabase import get_supabase
from services import document_service

router = APIRouter()


@router.get("/types")
async def list_document_types(
    owner_type: str | None = None,
    user=Depends(require_permission("documents", "read")),
):
    """Seeded `document_types` lookup — drives the upload type picker.

    `owner_type` ("company" | "person") narrows the list to what that owner can
    actually hold: a Certificate of Incorporation is not a person's document, and
    offering it on a person profile only invites a miscategorised upload.

    Declared before /{document_id}/... so "types" isn't matched as a document id.
    """
    if owner_type not in (None, "company", "person"):
        raise HTTPException(400, "owner_type must be 'company' or 'person'")

    sb = get_supabase()
    query = sb.table("document_types").select("*").eq("is_active", True)
    if owner_type:
        query = query.in_("applies_to", [owner_type, "both"])
    return query.order("sort_order").execute().data or []


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

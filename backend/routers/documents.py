"""Document download (signed URL) + soft-delete (PBI-39 Block 1).

Upload / list live under the owner routes (companies.py / persons.py). These
two are keyed by document id directly.
"""
from fastapi import APIRouter, Depends, HTTPException

from middleware.auth import require_permission
from db.supabase import get_supabase
from services import document_service, document_sections

router = APIRouter()


@router.get("/types")
async def list_document_types(
    owner_type: str | None = None,
    category: str | None = None,
    user=Depends(require_permission("documents", "read")),
):
    """Seeded `document_types` lookup — drives the upload type picker.

    `owner_type` ("company" | "person") narrows the list to what that owner can
    actually hold: a Certificate of Incorporation is not a person's document, and
    offering it on a person profile only invites a miscategorised upload.

    `category` narrows it further, to one SECTION's types (migration 036). The
    upload button now lives inside a section, so the picker it opens must offer
    that section's types and no others — a passport is not an answer to "which
    proof of address is this?".

    Declared before /{document_id}/... so "types" isn't matched as a document id.
    """
    if owner_type not in (None, "company", "person"):
        raise HTTPException(400, "owner_type must be 'company' or 'person'")

    sb = get_supabase()
    query = sb.table("document_types").select("*").eq("is_active", True)
    if owner_type:
        query = query.in_("applies_to", [owner_type, "both"])
    if category:
        query = query.eq("category", category)
    return query.order("sort_order").execute().data or []


@router.get("/sections")
async def list_document_sections(
    owner_type: str = "person",
    user=Depends(require_permission("documents", "read")),
):
    """The sections a profile renders, and what each type inside them carries.

    Served rather than hardcoded in the screen for the reason the CR form
    contract is served (CLAUDE.md §3): the rule that a passport needs an issuing
    country is enforced by the API, so the screen must read it from the same
    place or the two drift, and the way that surfaces is a rejected filing.

    Sections come back whether or not anything has been uploaded into them — an
    empty section with its own button is how the first document gets added.
    """
    if owner_type not in ("company", "person"):
        raise HTTPException(400, "owner_type must be 'company' or 'person'")

    sb = get_supabase()
    types = (
        sb.table("document_types").select("*").eq("is_active", True)
        .in_("applies_to", [owner_type, "both"])
        .order("sort_order").execute().data
    ) or []

    by_section: dict[str, list[dict]] = {}
    for t in types:
        by_section.setdefault(
            document_sections.section_of(t.get("category")), []).append({
                "code": t["code"],
                "label": t["label"],
                "id_type": document_sections.id_type_for_code(t["code"]),
            })

    return {
        "sections": [
            {
                "key": s["key"],
                "label": s["label"],
                "description": s["description"],
                "file_required": s["file_required"],
                "is_identity": s["key"] == document_sections.IDENTITY_CATEGORY,
                "types": by_section[s["key"]],
            }
            for s in document_sections.sections_for(owner_type)
            # A section holding no active TYPE is not empty, it is inert: its
            # upload button would open a picker with nothing in it. An empty
            # section still renders — that is how the first document gets added
            # — but only where there is something to add.
            if by_section.get(s["key"])
        ],
        "identity_fields": document_sections.IDENTITY_FIELDS,
    }


@router.get("/{document_id}/download")
async def download_document(
    document_id: str,
    user=Depends(require_permission("documents", "read")),
):
    """Returns a short-lived signed URL for the current version (private bucket)."""
    return document_service.create_signed_url(document_id)


@router.get("/{document_id}/versions/{version_number}/download")
async def download_document_version(
    document_id: str,
    version_number: int,
    user=Depends(require_permission("documents", "read")),
):
    """The same, for a SUPERSEDED version.

    The document history lists every version with a Download button, and every
    one of them used to sign the current version's path — so v1 and v2 both
    handed back v3. Each row in `document_versions` carries its own
    `storage_path`; this reads it.
    """
    return document_service.create_signed_url(document_id, version_number)


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    user=Depends(require_permission("documents", "delete")),
):
    """Soft-delete (status='deleted'); the object is retained (OQ-2)."""
    return await document_service.soft_delete_document(document_id=document_id, user=user)

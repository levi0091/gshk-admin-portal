from fastapi import APIRouter, Depends, Query
from middleware.auth import require_permission
from db.supabase import get_supabase

router = APIRouter()


@router.get("/")
async def get_global_audit(
    limit: int = Query(default=200, le=500),
    user=Depends(require_permission("audit_trail", "read")),
):
    """Global audit log — all entries newest first, max 500. Requires audit_trail:read."""
    sb = get_supabase()
    result = (
        sb.table("audit_log")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []

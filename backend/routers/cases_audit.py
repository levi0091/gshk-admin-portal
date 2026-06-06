from fastapi import APIRouter, Depends
from middleware.auth import require_permission
from db.supabase import get_supabase

router = APIRouter()


@router.get("/{case_id}/audit")
async def get_case_audit(
    case_id: str,
    user=Depends(require_permission("nar1_data", "read")),
):
    """Returns audit log entries for a case, newest first. PRD: GET /cases/{case_id}/audit"""
    sb = get_supabase()
    result = (
        sb.table("audit_log")
        .select("*")
        .eq("case_id", case_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []

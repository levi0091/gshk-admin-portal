from fastapi import APIRouter, Depends
from middleware.auth import require_permission
from db.supabase import get_supabase

router = APIRouter()


@router.get("/me")
async def get_me(user=Depends(require_permission("nar1_data", "read"))):
    sb = get_supabase()
    perms_res = (
        sb.table("role_permissions")
        .select("module, permission")
        .eq("role_id", user["role_id"])
        .execute()
    )
    permissions = [
        f"{p['module']}:{p['permission']}"
        for p in (perms_res.data or [])
    ]
    return {
        "id": user["id"],
        "display_name": user["display_name"],
        "role_name": user["role_name"],
        "role_id": user["role_id"],
        "permissions": permissions,
    }

from fastapi import APIRouter, Depends
from middleware.auth import require_user
from db.supabase import get_supabase
from services.app_env import is_production

router = APIRouter()


@router.get("/me")
async def get_me(user=Depends(require_user)):
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
        # Drives the header TEST pill and the "nothing is really sent" note on
        # Client Verification. Served from the API rather than baked into the
        # bundle at build time, so it describes the backend the browser is
        # actually talking to — a dev build pointed at the prod API would
        # otherwise wear a TEST badge while filing real returns.
        "is_test_env": not is_production(),
    }

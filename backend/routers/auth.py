from fastapi import APIRouter, Depends
from middleware.auth import require_permission

router = APIRouter()


@router.get("/me")
async def get_me(user=Depends(require_permission("nar1_data", "read"))):
    return {
        "id": user["id"],
        "display_name": user["display_name"],
        "role_name": user["role_name"],
        "role_id": user["role_id"],
    }

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from middleware.auth import require_super_admin
from db.supabase import get_supabase

router = APIRouter()


class CreateUserRequest(BaseModel):
    display_name: str
    email: str
    role_id: str
    password: str


class UpdateUserRequest(BaseModel):
    role_id: Optional[str] = None
    display_name: Optional[str] = None


@router.get("/")
async def list_users(user=Depends(require_super_admin())):
    sb = get_supabase()
    result = (
        sb.table("users")
        .select("id, display_name, email, is_active, role_id, roles(name)")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


@router.post("/", status_code=201)
async def create_user(
    body: CreateUserRequest,
    user=Depends(require_super_admin()),
):
    sb = get_supabase()
    try:
        auth_resp = sb.auth.admin.create_user(
            {"email": body.email, "password": body.password, "email_confirm": True}
        )
        new_user_id = auth_resp.user.id
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Auth creation failed: {e}")

    result = (
        sb.table("users")
        .insert(
            {
                "id": new_user_id,
                "display_name": body.display_name,
                "email": body.email,
                "role_id": body.role_id,
            }
        )
        .execute()
    )
    return result.data[0]


@router.patch("/{user_id}")
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    current_user=Depends(require_super_admin()),
):
    sb = get_supabase()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = sb.table("users").update(updates).eq("id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="User not found")
    return result.data[0]


@router.patch("/{user_id}/deactivate")
async def deactivate_user(
    user_id: str,
    current_user=Depends(require_super_admin()),
):
    sb = get_supabase()
    result = sb.table("users").update({"is_active": False}).eq("id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        sb.auth.admin.update_user_by_id(user_id, {"ban_duration": "876600h"})
    except Exception:
        pass  # Auth disable is best-effort

    return {"message": "User deactivated", "user_id": user_id}

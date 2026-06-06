from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from middleware.auth import require_super_admin
from db.supabase import get_supabase

router = APIRouter()


class PermissionEntry(BaseModel):
    module: str
    permission: str


class CreateRoleRequest(BaseModel):
    name: str
    permissions: List[PermissionEntry] = []


class UpdateRoleRequest(BaseModel):
    name: Optional[str] = None
    permissions: Optional[List[PermissionEntry]] = None


@router.get("/")
async def list_roles(user=Depends(require_super_admin())):
    sb = get_supabase()
    result = (
        sb.table("roles")
        .select("id, name, created_at, role_permissions(module, permission)")
        .order("name")
        .execute()
    )
    return result.data or []


@router.post("/", status_code=201)
async def create_role(
    body: CreateRoleRequest,
    user=Depends(require_super_admin()),
):
    sb = get_supabase()
    role_result = sb.table("roles").insert({"name": body.name}).execute()
    if not role_result.data:
        raise HTTPException(status_code=400, detail="Role creation failed")

    new_role = role_result.data[0]
    if body.permissions:
        perm_rows = [
            {"role_id": new_role["id"], "module": p.module, "permission": p.permission}
            for p in body.permissions
        ]
        sb.table("role_permissions").insert(perm_rows).execute()

    return new_role


@router.patch("/{role_id}")
async def update_role(
    role_id: str,
    body: UpdateRoleRequest,
    user=Depends(require_super_admin()),
):
    if body.name is None and body.permissions is None:
        raise HTTPException(status_code=400, detail="No fields to update")

    sb = get_supabase()

    if body.name is not None:
        result = sb.table("roles").update({"name": body.name}).eq("id", role_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Role not found")

    if body.permissions is not None:
        # Replace all permissions for this role atomically
        sb.table("role_permissions").delete().eq("role_id", role_id).execute()
        if body.permissions:
            perm_rows = [
                {"role_id": role_id, "module": p.module, "permission": p.permission}
                for p in body.permissions
            ]
            sb.table("role_permissions").insert(perm_rows).execute()

    return {"message": "Role updated", "role_id": role_id}

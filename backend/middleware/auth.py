from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from db.supabase import get_supabase

security = HTTPBearer()


def _resolve_user(token: str) -> dict:
    """Validate JWT and return user profile dict. Raises HTTPException on failure."""
    sb = get_supabase()
    try:
        resp = sb.auth.get_user(token)
        auth_user = resp.user
        if auth_user is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = (
        sb.table("users")
        .select("display_name, is_active, role_id, roles(name, id)")
        .eq("id", auth_user.id)
        .single()
        .execute()
    )

    profile = result.data
    if not profile or not profile.get("is_active"):
        raise HTTPException(status_code=403, detail="Account inactive or not found")

    return {
        "id": auth_user.id,
        "display_name": profile["display_name"],
        "role_name": profile["roles"]["name"] if profile.get("roles") else None,
        "role_id": profile.get("role_id"),
    }


def require_permission(module: str, permission: str):
    """FastAPI dependency factory. Returns a dependency that checks module permission."""

    async def check(
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ) -> dict:
        user = _resolve_user(credentials.credentials)

        if user["role_name"] == "super_admin":
            return user

        sb = get_supabase()
        perms = (
            sb.table("role_permissions")
            .select("permission")
            .eq("role_id", user["role_id"])
            .eq("module", module)
            .execute()
        )

        allowed = {row["permission"] for row in (perms.data or [])}
        if permission not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        return user

    return check


def require_super_admin():
    """Dependency for Super Admin-only endpoints."""

    async def check(
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ) -> dict:
        user = _resolve_user(credentials.credentials)
        if user["role_name"] != "super_admin":
            raise HTTPException(status_code=403, detail="Super Admin only")
        return user

    return check

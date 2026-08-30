import time

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from db.supabase import get_supabase

security = HTTPBearer()

# Resolving the caller cost ~450ms on EVERY request (an Auth HTTP call plus a
# users query), which is most of the latency users feel on submits and dropdowns.
# Cache it briefly, keyed by the bearer token.
#
# TTL is deliberately short: a deactivated user or a role change keeps working
# for at most this long. 30s is the trade — a revoked account cannot linger, but
# a burst of requests from one screen resolves the caller once, not ten times.
_USER_TTL = 30.0
_PERM_TTL = 30.0
_user_cache: dict[str, tuple[float, dict]] = {}
_perm_cache: dict[tuple[str, str], tuple[float, set[str]]] = {}


def _cache_get(cache: dict, key):
    hit = cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    if hit:
        cache.pop(key, None)
    return None


def clear_auth_cache() -> None:
    """Drop cached identities — call after deactivating a user or changing a role
    so the change takes effect immediately instead of after the TTL."""
    _user_cache.clear()
    _perm_cache.clear()


def _resolve_user(token: str) -> dict:
    """Validate JWT and return user profile dict. Raises HTTPException on failure."""
    cached = _cache_get(_user_cache, token)
    if cached is not None:
        return cached

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

    user = {
        "id": auth_user.id,
        # The address they signed in with, taken from Supabase Auth rather than
        # the `users` row: Auth owns it, and it is the mailbox that actually
        # reaches this person. Read by the verification send, which copies the
        # case worker on the client's email and points the client's reply at
        # them (routers/cases.send_verification).
        "email": getattr(auth_user, "email", None),
        "display_name": profile["display_name"],
        "role_name": profile["roles"]["name"] if profile.get("roles") else None,
        "role_id": profile.get("role_id"),
    }
    _user_cache[token] = (time.monotonic() + _USER_TTL, user)
    return user


def _permissions_for(user: dict, module: str) -> set[str]:
    """The permissions this user's role holds on one module."""
    key = (user["role_id"], module)
    allowed = _cache_get(_perm_cache, key)
    if allowed is None:
        sb = get_supabase()
        perms = (
            sb.table("role_permissions")
            .select("permission")
            .eq("role_id", user["role_id"])
            .eq("module", module)
            .execute()
        )
        allowed = {row["permission"] for row in (perms.data or [])}
        _perm_cache[key] = (time.monotonic() + _PERM_TTL, allowed)
    return allowed


async def require_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Just an authenticated, active user — no module permission required.

    For the identity bootstrap (`/auth/me`): the frontend calls it right after
    login to learn who it is and what it may see. Gating that on a business
    module would lock a valid user out of the whole app for lacking one specific
    permission — e.g. a persons-only role could never load the page that would
    have told it it can read persons.
    """
    return _resolve_user(credentials.credentials)


def require_permission(module: str, permission: str):
    """FastAPI dependency factory. Returns a dependency that checks module permission."""

    async def check(
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ) -> dict:
        user = _resolve_user(credentials.credentials)

        if user["role_name"] == "super_admin":
            return user

        if permission not in _permissions_for(user, module):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        return user

    return check


def require_any_permission(*modules: tuple[str, str]):
    """Guard for endpoints serving data that belongs to no single module.

    The reference vocabularies (gender, nationality, country...) are needed by
    both the company and the person forms, so gating them on one module would
    lock out a role that only holds the other. Passes if the caller holds ANY of
    the given (module, permission) pairs.
    """

    async def check(
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ) -> dict:
        user = _resolve_user(credentials.credentials)

        if user["role_name"] == "super_admin":
            return user

        if any(perm in _permissions_for(user, module) for module, perm in modules):
            return user

        raise HTTPException(status_code=403, detail="Insufficient permissions")

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

import sys
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


#: The identity columns, and the ones a migration may not have reached yet.
#:
#: SPLIT BECAUSE THIS DEPLOYMENT ORDER IS CODE-FIRST. Railway redeploys the API
#: the moment `dev` is pushed; alembic is run by hand afterwards. So between a
#: deploy and its migration the new column DOES NOT EXIST, and PostgREST answers
#: a select naming it with 42703 rather than ignoring it.
#:
#: That gap took DEV down on 2026-09-01: `must_change_password` was added to
#: this select, the API deployed, the migration had not run, and EVERY
#: authenticated request 500'd — `/auth/me` included, so the portal could not
#: even tell the user what was wrong. This function is the single point every
#: route's identity passes through, which makes it the worst possible place for
#: a hard dependency on a schema change.
_PROFILE_BASE = "display_name, is_active, role_id, roles(name, id)"
_PROFILE_OPTIONAL = ("must_change_password",)

#: Set once a select naming the optional columns has succeeded or failed, so the
#: fallback costs one round trip per process rather than one per request.
_profile_columns_ok: bool | None = None


def _profile_for(sb, user_id: str) -> dict | None:
    """The `users` row, degrading if a pending migration has not landed yet.

    Falls back to the columns that have always existed and lets the caller read
    the missing ones as absent. That is the SAFE direction and it is also the
    TRUE one: before migration 031 no account can be flagged, so reading the
    flag as unset is not a guess — it is the state of the database.

    A permanent fallback would be wrong, so this is not silent: it says so on
    stderr the first time, naming the migration to run.
    """
    global _profile_columns_ok

    def read(columns: str):
        return (sb.table("users").select(columns)
                .eq("id", user_id).single().execute()).data

    if _profile_columns_ok is not False:
        try:
            profile = read(f"{_PROFILE_BASE}, " + ", ".join(_PROFILE_OPTIONAL))
            _profile_columns_ok = True
            return profile
        except Exception as exc:  # noqa: BLE001
            # ONLY a missing column falls back. Anything else — a dropped
            # connection, a permission error, a row that is not there — must
            # surface as it always did, or this turns every database fault into
            # a silently degraded identity.
            if "42703" not in str(exc) and "does not exist" not in str(exc):
                raise
            if _profile_columns_ok is None:
                print(
                    "[auth] WARN: `users` is missing "
                    f"{', '.join(_PROFILE_OPTIONAL)} — this deployment is ahead "
                    "of its migrations. Reading the flag as unset, which is "
                    "true until `alembic upgrade head` runs. Run it.",
                    file=sys.stderr,
                )
            _profile_columns_ok = False

    return read(_PROFILE_BASE)


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

    profile = _profile_for(sb, auth_user.id)
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
        # `bool(...)`, never the raw column: a row written before migration 031
        # returns None, and `None` would be falsy by accident rather than by
        # decision. It IS false for those rows -- they chose their password
        # under the old flow -- and saying so explicitly is what stops a later
        # `is True` comparison somewhere else reading it differently.
        "must_change_password": bool(profile.get("must_change_password")),
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


#: The 409 a user still on their generated password gets from every route
#: except the two below. A distinct status, not a 403: 403 means "your role does
#: not allow this" and would send the reader to an administrator for a problem
#: they can fix themselves in ten seconds.
PASSWORD_CHANGE_REQUIRED = (
    "your password was generated by G-FlowDesk and must be replaced before you "
    "can use the portal"
)


def _refuse_until_password_changed(user: dict) -> None:
    """Spec §7. Enforced in the MIDDLEWARE, not in the frontend router.

    A first-login redirect that lives in React is a suggestion: the API is
    reachable with the same token by anything that can type a URL. This is the
    only place that makes the flag mean something.
    """
    if user.get("must_change_password"):
        raise HTTPException(status_code=409, detail=PASSWORD_CHANGE_REQUIRED)


async def require_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Just an authenticated, active user — no module permission required.

    For the identity bootstrap (`/auth/me`): the frontend calls it right after
    login to learn who it is and what it may see. Gating that on a business
    module would lock a valid user out of the whole app for lacking one specific
    permission — e.g. a persons-only role could never load the page that would
    have told it it can read persons.

    DELIBERATELY NOT gated on `must_change_password`. `/auth/me` is how the
    frontend learns that the flag is set at all; refusing it would leave a new
    user staring at a login screen that accepted their password and then showed
    them nothing. The flag travels ON the identity this returns, and every
    route that does real work goes through `require_permission` below, which
    does refuse.
    """
    return _resolve_user(credentials.credentials)


def require_permission(module: str, permission: str):
    """FastAPI dependency factory. Returns a dependency that checks module permission."""

    async def check(
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ) -> dict:
        user = _resolve_user(credentials.credentials)

        # BEFORE the super_admin bypass, on purpose (spec §7). A super admin on
        # a generated password is exactly the account worth protecting most,
        # and letting the bypass skip this check would exempt the one role that
        # can create other users.
        _refuse_until_password_changed(user)

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
        _refuse_until_password_changed(user)   # spec §7, see require_permission

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
        _refuse_until_password_changed(user)   # spec §7, see require_permission
        if user["role_name"] != "super_admin":
            raise HTTPException(status_code=403, detail="Super Admin only")
        return user

    return check

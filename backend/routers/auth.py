import sys
import time

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
        # Shown on Client Verification, which tells the operator that a copy of
        # the client's email is coming to this address. Naming it is the point:
        # "a copy goes to you" is unverifiable, "a copy goes to levi@…" is not.
        "email": user.get("email"),
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
        # Spec §7. The frontend redirects on this, but the redirect is only the
        # courtesy: `middleware/auth` refuses every other route while it is set,
        # so a user who navigates around the screen gets 409s rather than a
        # working portal. /auth/me is deliberately still reachable — it is how
        # the frontend learns the flag is set at all.
        "must_change_password": bool(user.get("must_change_password")),
    }


#: How long a resolved contact list is reused before the database is asked
#: again. Long enough that reloading the login screen cannot be turned into a
#: query generator; short enough that a role change shows up while somebody is
#: still on the phone about it.
_CONTACTS_TTL_SECONDS = 300

#: (expires_at, contacts). Process-local, like the identity cache — Railway may
#: run several workers and each keeps its own. That is fine: the list is the
#: same on all of them, and being five minutes stale on one worker is the same
#: problem as being five minutes stale on all of them.
_contacts_cache: tuple[float, list[dict]] = (0.0, [])


def clear_contacts_cache() -> None:
    """Forget the cached contact list. Used by the tests."""
    global _contacts_cache
    _contacts_cache = (0.0, [])


def _super_admin_contacts() -> list[dict]:
    """Active super admins — display name and email, nothing else.

    Two round trips rather than one PostgREST embedded filter: `roles!inner`
    would fetch this in a single call, but the caller is an UNAUTHENTICATED
    route and a query shape that quietly returns *every* user if the embed
    name ever changes is not one to be clever with. Cached, so the two calls
    happen once per five minutes rather than once per login screen.
    """
    global _contacts_cache

    now = time.monotonic()
    expires_at, cached = _contacts_cache
    if now < expires_at:
        return cached

    sb = get_supabase()
    roles = (sb.table("roles").select("id").eq("name", "super_admin")
             .execute()).data or []
    role_ids = [r["id"] for r in roles if r.get("id")]

    contacts: list[dict] = []
    if role_ids:
        rows = (sb.table("users")
                .select("display_name, email")
                .in_("role_id", role_ids)
                .eq("is_active", True)
                .order("display_name")
                .execute()).data or []
        # An address is the entire point of this list. A super admin with no
        # email on record is not a contact, they are a row.
        contacts = [
            {"display_name": (r.get("display_name") or "").strip(),
             "email": r["email"].strip()}
            for r in rows if (r.get("email") or "").strip()
        ]

    _contacts_cache = (now + _CONTACTS_TTL_SECONDS, contacts)
    return contacts


@router.get("/super-admins")
async def super_admin_contacts():
    """Who to ask for an account or a password reset — UNAUTHENTICATED.

    The login screen is the one screen in the portal with no token, and it is
    exactly where somebody needs to know who to ask. It used to name
    `levi@zenexflow.com` in two hardcoded strings — the delivery contractor,
    not GSHK's administrators — so a locked-out GSHK user wrote to the wrong
    company, and adding an administrator changed nothing on the screen.

    THE EXPOSURE IS DELIBERATE AND BOUNDED, and worth stating plainly, because
    this is the second unauthenticated route in the API (`routers/public_approval`
    explains the first):

      * It returns the display name and email of ACTIVE SUPER ADMINS ONLY —
        never the rest of the user list, never a role id, never an account id,
        never `is_active` for anybody else, never `must_change_password`. It
        cannot be used to enumerate the staff, only to find the two or three
        people who can help.
      * Those same addresses already appear in the mail this portal sends, and
        a sign-in screen that says "contact an administrator" without saying
        *which* administrator is a dead end.
      * NOTHING FROM THE REQUEST IS READ. There is no parameter and no body,
        so there is nothing to inject and nothing to vary.
      * It is a read. No request to it can change anything.

    A failure returns an EMPTY LIST, not a 500. The login form has to render
    whether or not this resolves, and the screen carries a fallback line for
    exactly that case.
    """
    try:
        return {"super_admins": _super_admin_contacts()}
    except Exception as exc:  # noqa: BLE001
        print(f"[auth] WARN: super-admin contacts unavailable: {exc}",
              file=sys.stderr)
        return {"super_admins": []}

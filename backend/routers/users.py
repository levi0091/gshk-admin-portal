import asyncio
import secrets
import string
import sys

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional
from middleware.auth import require_super_admin, require_user, clear_auth_cache
from db.supabase import get_supabase
from services import email_service

router = APIRouter()

#: The alphabet a generated password is drawn from.
#:
#: `1 l I O 0` ARE OMITTED. Somebody is going to read this off a screen and
#: type it into a login box, and every one of those characters is confusable
#: with another in some font. Removing them costs about half a bit per
#: character and removes an entire class of "the password does not work"
#: support conversation.
#:
#: The punctuation is a small, deliberately safe set: no quotes, no backslash,
#: no space. Those are the characters that get mangled by a shell, a CSV, or a
#: mail client that decides to be helpful.
_ALPHABET = (
    "".join(c for c in string.ascii_uppercase if c not in "IO")
    + "".join(c for c in string.ascii_lowercase if c not in "l")
    + "".join(c for c in string.digits if c not in "01")
    + "-_.+="
)

#: 20 characters from a 60-character alphabet is ~118 bits. Far more than a
#: human would choose, which is the point: this password protects an account
#: that can file statutory documents, and it lives in a mailbox until the user
#: replaces it.
_PASSWORD_LENGTH = 20

#: Supabase Auth's own floor. Stated here so a generated password can never be
#: refused by the very call that is supposed to create the account.
_MIN_PASSWORD_LENGTH = 8


def generate_password(length: int = _PASSWORD_LENGTH) -> str:
    """A high-entropy password nobody chose.

    `secrets`, never `random`: the latter is seeded from the clock and is
    predictable to anybody who knows roughly when the account was created.
    """
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


class CreateUserRequest(BaseModel):
    display_name: str
    email: EmailStr
    role_id: str
    # `password` IS GONE (spec §7). An administrator no longer chooses a
    # colleague's password: the portal generates one, mails it, and requires it
    # to be replaced on first sign-in. Removed rather than deprecated — a field
    # that still accepted a password would keep the old flow alive for any
    # caller that kept sending one, which is exactly the habit this removes.


class SetPasswordRequest(BaseModel):
    new_password: str


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
    """Create a portal account and mail its owner a generated password (§7).

    THE PASSWORD EXISTS IN TWO PLACES AND NO OTHERS: this message, and Supabase
    Auth's hash of it. It is not in the response, not in a log line, not in an
    audit row, and not on the screen the administrator is looking at — so an
    administrator cannot read a colleague's credential, and neither can anybody
    reading over their shoulder or reading the server's logs.
    """
    sb = get_supabase()
    password = generate_password()

    try:
        auth_resp = sb.auth.admin.create_user(
            {"email": body.email, "password": password, "email_confirm": True}
        )
        new_user_id = auth_resp.user.id
    except Exception as e:
        # The exception text is echoed because it is Supabase's own reason
        # ("email already registered"), which the administrator needs. The
        # password is not in it: it was never part of the message, and this
        # call is the only place it appears in a request body.
        raise HTTPException(status_code=400, detail=f"Auth creation failed: {e}")

    result = (
        sb.table("users")
        .insert(
            {
                "id": new_user_id,
                "display_name": body.display_name,
                "email": body.email,
                "role_id": body.role_id,
                # Migration 031. Set by the APPLICATION, not by a column
                # default: the default stays FALSE so that a row inserted by
                # some other path cannot lock a real person out, and the one
                # path that hands out a generated password is the one that
                # demands it be replaced.
                "must_change_password": True,
            }
        )
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=400, detail="User profile insert failed")

    role_name = None
    try:
        role = (sb.table("roles").select("name").eq("id", body.role_id)
                .single().execute()).data
        role_name = (role or {}).get("name")
    except Exception:  # noqa: BLE001 — a nameless role omits one line of the mail
        role_name = None

    subject, html = email_service.welcome_email(
        body.display_name, role_name, password)

    delivery = {"welcome_email_sent": False, "welcome_email_error": None}
    try:
        # Off the event loop: email_service.send is a synchronous httpx.post
        # with a 15-second timeout, so a hung Resend would stall the whole
        # worker rather than this one request.
        sent = await asyncio.to_thread(
            email_service.send, to=[str(body.email)], subject=subject, html=html)
        delivery["welcome_email_sent"] = True
        delivery["welcome_email_redirected"] = bool(sent.get("redirected"))
    except Exception as exc:  # noqa: BLE001
        # THE ACCOUNT IS ALREADY CREATED. Raising here would leave a real user
        # in Supabase Auth while telling the administrator the creation failed,
        # and the retry would then collide on the email address. So the account
        # stands and the response says the mail did not go — which the screen
        # turns into "resend the invitation", an action that can actually be
        # taken.
        #
        # The reason is reported, but the password is not: it is not in `exc`,
        # and nothing here puts it there.
        print(f"[users] WARN: welcome email failed for {body.email}: {exc}",
              file=sys.stderr)
        delivery["welcome_email_error"] = str(exc)

    # NO PASSWORD IN THE RESPONSE. Deliberately, and this is the assertion the
    # tests hold: the administrator does not need it, the screen must not show
    # it, and a response body ends up in a browser's network log.
    return {**result.data[0], **delivery}


@router.post("/me/password")
async def set_own_password(
    body: SetPasswordRequest,
    user=Depends(require_user),
):
    """Replace the generated password with one the user chose (§7).

    `require_user`, NOT `require_permission`: this is the one route a user on a
    generated password can still reach, and gating it on a business module
    would leave a new user unable to do the only thing they are allowed to do.

    Clearing the flag is the only side effect. It does not touch the role, the
    display name, or anything else — a route that could change more than it
    says would be reachable by an account that has not finished authenticating
    itself.
    """
    new_password = (body.new_password or "").strip()
    if len(new_password) < _MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"choose a password of at least {_MIN_PASSWORD_LENGTH} "
                   f"characters",
        )

    sb = get_supabase()
    try:
        sb.auth.admin.update_user_by_id(user["id"], {"password": new_password})
    except Exception as exc:  # noqa: BLE001
        # Supabase's own refusal — its length rule, or a password it considers
        # compromised. Reported as a 400 because the caller can fix it, and
        # WITHOUT echoing the password back.
        raise HTTPException(status_code=400, detail=f"Password change failed: {exc}")

    # Only after Auth accepted it. Clearing the flag first would leave an
    # account able to use the portal on a password the change did not apply.
    (sb.table("users").update({"must_change_password": False})
     .eq("id", user["id"]).execute())
    # Identities are cached for 30 seconds. Without this the user keeps being
    # refused by every route for half a minute after doing exactly what they
    # were told to do.
    clear_auth_cache()
    return {"must_change_password": False}


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    current_user=Depends(require_super_admin()),
):
    """Issue a new generated password to a user who cannot sign in.

    The same shape as creation (§7), and for the same reasons: the portal
    generates the password, mails it to its owner, and the account can do
    nothing until its owner replaces it. THE PASSWORD IS NOT IN THE RESPONSE —
    an administrator resets an account, they do not learn how to sign in as it.

    ORDER MATTERS AND IS DELIBERATE. Auth first, then the flag, then the mail:

      * Auth first because it is the irreversible half. Everything after it is
        recoverable by pressing the button again, which is why this route is
        safe to retry — unlike creation, a second reset collides with nothing.
      * The flag next, best-effort. If it fails the user can still sign in on
        the mailed password; they simply are not forced to change it. Raising
        here would abort the mail and leave a real person locked out of an
        account whose password had already changed.
      * The mail last, best-effort and REPORTED, because it is the half that
        actually fails: Railway DEV has no `RESEND_API_KEY`, and a reset whose
        mail silently vanished is indistinguishable, from the administrator's
        chair, from one that worked.

    NOT AUDITED, deliberately. `audit_log` covers NAR1/NNC1 workflow and entity
    data (CLAUDE.md, "Audit scope"); user-management events are out of scope
    and have no seeded `action_type`, and an unseeded code renders unlabelled
    in the trail rather than failing loudly.
    """
    sb = get_supabase()

    # Read the row first. This is what makes 404 mean "no such user" rather
    # than a password change against an id that only exists in Supabase Auth,
    # and it is where the email address in the response comes from — the
    # screen tells the administrator which mailbox to chase, and it must be
    # the address the mail was actually sent to.
    #
    # `.limit(1)`, NOT `.single()`: PostgREST raises when `.single()` matches no
    # rows, so the not-found path would have to be a bare `except` — and that
    # same `except` would turn a database outage into "User not found", which
    # sends the administrator hunting for a user who is sitting right there. A
    # list distinguishes the two: empty is a 404, and a real failure raises.
    rows = (sb.table("users")
            .select("id, display_name, email, is_active")
            .eq("id", user_id).limit(1).execute()).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    target = rows[0]

    if not target.get("is_active"):
        # A deactivated account is banned in Auth. Mailing it a working-looking
        # password would put a live credential in a mailbox for an account that
        # cannot sign in, and tell the administrator the opposite of the truth.
        raise HTTPException(
            status_code=409,
            detail="This account is deactivated. Reactivate it first — a "
                   "password mailed to a banned account is a live credential "
                   "for an account that cannot sign in.",
        )

    email = (target.get("email") or "").strip()
    if not email:
        # The password only leaves by one route. No route, no reset.
        raise HTTPException(
            status_code=409,
            detail="This account has no email address on record, so the new "
                   "password could not be delivered to anybody.",
        )

    password = generate_password()

    try:
        sb.auth.admin.update_user_by_id(user_id, {"password": password})
    except Exception as exc:  # noqa: BLE001
        # Supabase's own refusal. Reported WITHOUT the password — it was never
        # part of the message and nothing here puts it there.
        raise HTTPException(status_code=400,
                            detail=f"Password reset failed: {exc}")

    must_change = True
    try:
        (sb.table("users").update({"must_change_password": True})
         .eq("id", user_id).execute())
    except Exception as exc:  # noqa: BLE001
        print(f"[users] WARN: reset flag not set for {email}: {exc}",
              file=sys.stderr)
        must_change = False

    # Identities are cached for 30 seconds. Without this the user keeps their
    # old session's cached identity — and, worse, is not sent to the
    # choose-a-password screen — for half a minute after the reset.
    clear_auth_cache()

    subject, html = email_service.password_reset_email(
        target.get("display_name") or "", password)

    delivery = {"reset_email_sent": False, "reset_email_error": None,
                "reset_email_redirected": False}
    try:
        # Off the event loop: email_service.send is a synchronous httpx.post
        # with a 15-second timeout, so a hung Resend would stall the whole
        # worker rather than this one request.
        sent = await asyncio.to_thread(
            email_service.send, to=[email], subject=subject, html=html)
        delivery["reset_email_sent"] = True
        delivery["reset_email_redirected"] = bool(sent.get("redirected"))
    except Exception as exc:  # noqa: BLE001
        # THE PASSWORD HAS ALREADY CHANGED. Raising here would tell the
        # administrator the reset failed while the user's old password had in
        # fact stopped working — the worst of both. So it is reported, and the
        # screen turns it into "press it again once mail is working", which is
        # an action that can actually be taken.
        print(f"[users] WARN: reset email failed for {email}: {exc}",
              file=sys.stderr)
        delivery["reset_email_error"] = str(exc)

    # NO PASSWORD IN THE RESPONSE, exactly as on creation. A response body ends
    # up in the browser's network log, and an administrator who can read a
    # colleague's password can sign in as them.
    return {"user_id": user_id, "email": email,
            "must_change_password": must_change, **delivery}


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
    clear_auth_cache()   # a role change must take effect now, not after the TTL
    return result.data[0]


#: What `deactivate` hands Supabase Auth: a hundred years, which is the
#: closest thing GoTrue has to "indefinitely". `reactivate` sends the string
#: below to lift it — GoTrue treats `"none"` as "clear the ban", and it is the
#: ONLY way back: nothing about flipping `users.is_active` touches Auth.
_BAN_FOREVER = "876600h"
_BAN_NONE = "none"


@router.patch("/{user_id}/deactivate")
async def deactivate_user(
    user_id: str,
    current_user=Depends(require_super_admin()),
):
    sb = get_supabase()
    result = sb.table("users").update({"is_active": False}).eq("id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="User not found")
    clear_auth_cache()   # a deactivated user must lose access immediately

    try:
        sb.auth.admin.update_user_by_id(user_id, {"ban_duration": _BAN_FOREVER})
    except Exception as exc:  # noqa: BLE001
        # Best-effort, and it can afford to be: the middleware refuses the
        # account on `is_active` alone, which is already false by the time we
        # get here. It is REPORTED rather than swallowed so the pair with
        # `reactivate` stays legible — lifting a ban that never landed is a
        # no-op, not a fault.
        print(f"[users] WARN: Auth ban failed for {user_id}: {exc}",
              file=sys.stderr)

    return {"message": "User deactivated", "user_id": user_id}


@router.patch("/{user_id}/reactivate")
async def reactivate_user(
    user_id: str,
    current_user=Depends(require_super_admin()),
):
    """Give a deactivated colleague their account back.

    THIS EXISTS BECAUSE DEACTIVATION HAD NO UNDO. The confirmation dialog said
    it "can be reversed by reassigning a role", and that was simply not true:
    `PATCH /users/{id}` writes `role_id` and `display_name` and has never
    written `is_active`, and nothing anywhere lifted the Auth ban. A
    deactivated account was permanent, and the only route back was editing the
    database by hand.

    ORDER MATTERS, AND IT IS THE OPPOSITE OF THE RESET ROUTE'S. Auth first,
    then the flag — and here an Auth failure is FATAL, because nothing has
    changed yet:

      * `is_active` is what the middleware refuses on, so writing it first
        would put the account back on screen as Active while GoTrue still
        refused the sign-in. The administrator would see a working account and
        the user would see "Invalid login credentials", with nothing on either
        screen connecting the two.
      * Failing before the flag leaves the row saying Inactive, which is TRUE
        — the person still cannot sign in — and leaves the button there to
        press again. That is the safe direction, and it is what makes this
        route re-runnable.

    Reactivating an account that is already active is a NO-OP, not an error.
    Two administrators pressing the same button is not a fault worth a 409.

    NOT AUDITED, like every other user-management event (CLAUDE.md, "Audit
    scope"): adding an `action_type` without a migration seeding it would
    render unlabelled in the trail.
    """
    sb = get_supabase()

    # `.limit(1)` rather than `.single()`, for the reason spelled out on the
    # reset route: `.single()` raises on no rows, so the not-found path would
    # need a bare `except` that would also turn a database outage into
    # "User not found".
    rows = (sb.table("users")
            .select("id, display_name, email, is_active")
            .eq("id", user_id).limit(1).execute()).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    target = rows[0]

    if target.get("is_active"):
        return {"message": "User is already active", "user_id": user_id,
                "is_active": True, "already_active": True}

    try:
        sb.auth.admin.update_user_by_id(user_id, {"ban_duration": _BAN_NONE})
    except Exception as exc:  # noqa: BLE001
        # Deliberately a refusal rather than a warning. If the ban cannot be
        # lifted the account cannot sign in, and reporting success here is the
        # one outcome that would send an administrator away believing the
        # problem was solved.
        raise HTTPException(
            status_code=502,
            detail=f"The account could not be re-enabled in Supabase Auth, so "
                   f"it is still deactivated and nothing was changed: {exc}",
        )

    result = sb.table("users").update({"is_active": True}).eq("id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="User not found")

    # Identities are cached for 30 seconds, and a REFUSAL is cached with them.
    # Without this the user is still told their account is inactive for half a
    # minute after it was restored.
    clear_auth_cache()

    return {"message": "User reactivated", "user_id": user_id,
            "is_active": True, "already_active": False,
            "display_name": target.get("display_name"),
            "email": target.get("email")}

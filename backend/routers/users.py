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
        sb.auth.admin.update_user_by_id(user_id, {"ban_duration": "876600h"})
    except Exception:
        pass  # Auth disable is best-effort

    return {"message": "User deactivated", "user_id": user_id}

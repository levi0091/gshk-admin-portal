"""The presenter credential: a G-FlowDesk user's CR filing identity.

Not to be confused with `tpsi_accounts`, which is entity-scoped and holds the
CLIENT company's own e-Registry account.

Two passwords, two jobs (spec D3):
  tpsi_password      authenticates (SHA-256 in the Basic header). Never signs.
  eservice_password  signs. Optional here: we store a GSHK staff member's OWN
                     signing password, but a client director's is entered live
                     at signing and is never persisted (spec D4).
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from db.supabase import get_supabase
from services.tpsi.config import get_config
from services.tpsi.secrets import decrypt, encrypt

_TABLE = "tpsi_presenter_credentials"

# Sentinel distinguishing "caller didn't mention this field" from "caller
# passed None." set_credential/rotate_credential default eservice_user_id
# and eservice_password to this. See _payload for why the distinction
# matters: PostgREST only touches columns present in the upsert payload, so
# omitting a key entirely preserves the stored value (an untouched-column
# rotation), while an explicit None must still reach the payload as NULL (a
# deliberate clear).
_UNSET = object()


@dataclass(frozen=True)
class PresenterCredential:
    account_id: str
    tpsi_password: str
    eservice_user_id: str | None
    eservice_password: str | None


def _read(user_id: str) -> dict | None:
    rows = (
        get_supabase().table(_TABLE).select("*").eq("user_id", user_id).execute().data
    )
    return rows[0] if rows else None


def _upsert(payload: dict) -> dict:
    return (
        get_supabase()
        .table(_TABLE)
        .upsert(payload, on_conflict="user_id")
        .execute()
        .data[0]
    )


def _to_metadata(row: dict) -> dict:
    """The one, shared definition of what's safe to return: no secrets, not
    plaintext, not ciphertext. Used by the read path (get_metadata) AND both
    write paths (set_credential/rotate_credential, off the row _upsert
    already returned) so this allow-list can't drift apart between them."""
    return {
        "presentor_account_id": row["presentor_account_id"],
        "eservice_user_id": row.get("eservice_user_id"),
        "has_eservice_password": row.get("eservice_password_enc") is not None,
        "tpsi_password_expires_at": row.get("tpsi_password_expires_at"),
        "is_test": row["is_test"],
        "last_rotated_at": row.get("last_rotated_at"),
    }


def get_metadata(user_id: str) -> dict | None:
    """Everything about the credential EXCEPT the secrets.

    No endpoint may return a password, encrypted or otherwise, so the read path
    physically cannot leak one.
    """
    row = _read(user_id)
    if not row:
        return None
    return _to_metadata(row)


def load_for_use(user_id: str) -> PresenterCredential:
    """Decrypt for an actual TPSI call. Callers must not log the result."""
    row = _read(user_id)
    if not row:
        raise LookupError(
            "no TPSI presenter credential for this user — set one before filing"
        )

    expected_test = get_config().env == "test"
    if row["is_test"] != expected_test:
        raise RuntimeError(
            f"credential is_test={row['is_test']} but TPSI_ENV="
            f"{get_config().env}; refusing to use it"
        )

    eservice_enc = row.get("eservice_password_enc")
    return PresenterCredential(
        account_id=row["presentor_account_id"],
        tpsi_password=decrypt(row["tpsi_password_enc"]),
        eservice_user_id=row.get("eservice_user_id"),
        eservice_password=decrypt(eservice_enc) if eservice_enc else None,
    )


def _payload(
    user_id: str,
    presentor_account_id: str,
    tpsi_password: str,
    eservice_user_id,
    eservice_password,
    rotated: bool,
) -> dict:
    payload = {
        "user_id": user_id,
        "presentor_account_id": presentor_account_id,
        "tpsi_password_enc": encrypt(tpsi_password),
        "is_test": get_config().env == "test",
    }
    # _UNSET ("not mentioned") -> omit the key so PostgREST leaves the
    # stored value untouched — the same mechanism that already lets
    # tpsi_password_expires_at survive a rotation. None ("explicitly
    # cleared") -> include the key as NULL. A real value -> store it
    # (encrypted, for the password). Collapsing "not mentioned" into "None"
    # here is exactly the bug this shape prevents: CR forces a TPSI
    # password change every 180 days, so rotating tpsi_password alone is
    # the routine case, and it must not wipe a stored signing password.
    if eservice_user_id is not _UNSET:
        payload["eservice_user_id"] = eservice_user_id
    if eservice_password is not _UNSET:
        payload["eservice_password_enc"] = (
            encrypt(eservice_password) if eservice_password else None
        )
    if rotated:
        payload["last_rotated_at"] = datetime.now(timezone.utc).isoformat()
    return payload


def set_credential(
    *,
    user_id: str,
    presentor_account_id: str,
    tpsi_password: str,
    eservice_user_id: str | None = _UNSET,
    eservice_password: str | None = _UNSET,
) -> dict:
    row = _upsert(
        _payload(
            user_id, presentor_account_id, tpsi_password,
            eservice_user_id, eservice_password, rotated=False,
        )
    )
    return _to_metadata(row)


def rotate_credential(
    *,
    user_id: str,
    presentor_account_id: str,
    tpsi_password: str,
    eservice_user_id: str | None = _UNSET,
    eservice_password: str | None = _UNSET,
) -> dict:
    row = _upsert(
        _payload(
            user_id, presentor_account_id, tpsi_password,
            eservice_user_id, eservice_password, rotated=True,
        )
    )
    return _to_metadata(row)


def record_password_expiry(user_id: str, expires_at: str | None) -> None:
    """Persist `password_expires_in` from the auth response so the 180-day
    expiry can be surfaced before it blocks a filing."""
    if not expires_at:
        return
    get_supabase().table(_TABLE).update(
        {"tpsi_password_expires_at": expires_at}
    ).eq("user_id", user_id).execute()

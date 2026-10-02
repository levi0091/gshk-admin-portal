"""A client officer's CR e-Registry account, kept for their own consent signature.

Levi, 2026-09-30 (answers 1, 2, 8): GSHK sets up a new director's e-Registry
account and keeps its user ID and password, so the consent signature an ND2A
needs for each newly appointed director can be applied by staff from the stored
credential, with no live PIN entry. No officer's account is used for anything
except their own consent (spec §5).

The password is Fernet-encrypted under `TPSI_CRED_KEY`, as staff CR passwords
are, and leaves this module through `load_for_signing` only. Unlike a staff
member's own credential there is NO masked hint (spec B-9): that hint is
defensible because it is shown to its owner, and this one would be shown to
every holder of `persons:read`. The service never audits; the router does,
with the user ID only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from db.supabase import get_supabase
from services.tpsi.credentials import UNSET
from services.tpsi.secrets import decrypt, encrypt

_TABLE = "person_eservice_credentials"


def _read(person_id: str) -> dict | None:
    rows = (get_supabase().table(_TABLE).select("*")
            .eq("person_id", person_id).execute().data)
    return rows[0] if rows else None


def _to_metadata(row: dict | None) -> dict:
    """The one allow-list of what may be returned. Never the ciphertext."""
    if not row:
        return {"configured": False, "eservice_user_id": None,
                "eservice_person_name": None, "has_password": False,
                "updated_at": None}
    return {
        "configured": bool(row.get("eservice_user_id")),
        "eservice_user_id": row.get("eservice_user_id"),
        "eservice_person_name": row.get("eservice_person_name"),
        "has_password": row.get("eservice_password_enc") is not None,
        "updated_at": row.get("updated_at"),
    }


def metadata(person_id: str) -> dict:
    """`{configured, eservice_user_id, eservice_person_name, has_password, updated_at}`."""
    return _to_metadata(_read(person_id))


def metadata_for(person_ids: list[str]) -> dict[str, dict]:
    ids = sorted({p for p in person_ids if p})
    if not ids:
        return {}
    rows = (get_supabase().table(_TABLE).select("*")
            .in_("person_id", ids).execute().data) or []
    by_id = {r["person_id"]: r for r in rows}
    return {pid: _to_metadata(by_id.get(pid)) for pid in ids}


def save(person_id: str, *, eservice_user_id: str, eservice_person_name: str,
         password=UNSET, user_id) -> dict:
    """Store or replace. `UNSET` keeps the stored password. Returns metadata.

    `ValueError` messages name the field, never its value.
    """
    account = str(eservice_user_id or "").strip()
    if not account:
        raise ValueError("The e-Registry user ID is required")
    name = str(eservice_person_name or "").strip() or None
    existing = _read(person_id)
    payload = {"person_id": person_id, "eservice_user_id": account,
               "eservice_person_name": name, "updated_by": user_id,
               "updated_at": datetime.now(timezone.utc).isoformat()}
    if password is UNSET:
        if not existing or existing.get("eservice_password_enc") is None:
            raise ValueError("A password is required the first time an "
                             "e-Registry account is stored")
    else:
        if not isinstance(password, str) or not password:
            raise ValueError("The e-Registry password cannot be blank")
        payload["eservice_password_enc"] = encrypt(password)
    row = (get_supabase().table(_TABLE)
           .upsert(payload, on_conflict="person_id").execute().data[0])
    return _to_metadata(row)


def clear(person_id: str) -> bool:
    gone = (get_supabase().table(_TABLE).delete()
            .eq("person_id", person_id).execute().data)
    return bool(gone)


def load_for_signing(person_id: str) -> tuple[str, str, str] | None:
    """`(user_id, person_name, password)` only when all three are stored.

    CR checks `selectPersonName` against the account, so a credential without
    its name cannot sign and is reported as missing rather than tried.
    """
    row = _read(person_id)
    if not row:
        return None
    account = row.get("eservice_user_id")
    name = row.get("eservice_person_name")
    enc = row.get("eservice_password_enc")
    if not (account and name and enc):
        return None
    return account, name, decrypt(enc)

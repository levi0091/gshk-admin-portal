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
#: The identity document an e-Registry account was opened with (Jacqueline,
#: note 1 of 1 Oct 2026): e-Reg and CR's register do not sync.
REGISTERED_ID_TYPES = ("hkid", "passport")


def _read(person_id: str) -> dict | None:
    rows = (get_supabase().table(_TABLE).select("*")
            .eq("person_id", person_id).execute().data)
    return rows[0] if rows else None


def _to_metadata(row: dict | None) -> dict:
    """The one allow-list of what may be returned. Never the ciphertext."""
    if not row:
        return {"configured": False, "eservice_user_id": None,
                "eservice_person_name": None, "has_password": False,
                "updated_at": None, "registered_id_type": None,
                "registered_id_number": None}
    return {
        "configured": bool(row.get("eservice_user_id")),
        "eservice_user_id": row.get("eservice_user_id"),
        "eservice_person_name": row.get("eservice_person_name"),
        "has_password": row.get("eservice_password_enc") is not None,
        "updated_at": row.get("updated_at"),
        "registered_id_type": row.get("registered_id_type"),
        "registered_id_number": row.get("registered_id_number"),
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
         password=UNSET, user_id, registered_id_type=UNSET,
         registered_id_number=UNSET) -> dict:
    """Store or replace. `UNSET` keeps the stored password (and the stored
    registered identity document). Returns metadata.

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
    if registered_id_type is not UNSET:
        kind = str(registered_id_type or "").strip().lower() or None
        if kind is not None and kind not in REGISTERED_ID_TYPES:
            raise ValueError("registered_id_type must be hkid or passport")
        payload["registered_id_type"] = kind
    if registered_id_number is not UNSET:
        payload["registered_id_number"] = (
            "".join(c for c in str(registered_id_number or "") if c.isalnum()).upper()
            or None)
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


def _normalised(number) -> str:
    return "".join(c for c in str(number or "") if c.isalnum()).upper()


def _partial(kind: str, number: str) -> str:
    from services.tpsi.forms import nar1_mapper
    clean = _normalised(number)
    if kind == "hkid":
        return (nar1_mapper._partial_hkid(clean) or clean[:4]) + "…"
    return nar1_mapper._partial_passport(clean) + "…"


def identity_mismatch(meta: dict, docs: list[dict], *, name: str | None = None) -> str | None:
    """Why the consent signature may be refused, or None (Jacqueline, note 1).

    An e-Registry account keeps the identity document it was opened with; a
    passport later renewed on CR's register is NOT copied to e-Reg, and CR
    compares the two when the consent is signed ("signer does not match with
    officer"). So when the profile no longer holds the number the account was
    opened with, say so — partial numbers only, since this is shown on case
    screens. None when nothing was recorded or the number is still held."""
    kind = (meta or {}).get("registered_id_type")
    number = _normalised((meta or {}).get("registered_id_number"))
    if not kind or not number:
        return None
    held = [_normalised(d.get("id_number")) for d in docs or []
            if d.get("id_type") == kind and d.get("id_number")]
    if number in held:
        return None
    label = "HKID" if kind == "hkid" else "passport"
    who = name or (meta or {}).get("eservice_person_name") or "This person"
    now = (f"the profile now holds {label} {_partial(kind, held[0])}" if held
           else f"the profile holds no {label}")
    return (f"{who}'s e-Registry account was opened with {label} {_partial(kind, number)}; "
            f"{now}. CR does not update e-Registry when the register changes, and "
            "compares the two when the consent is signed. Update the e-Registry account "
            "first.")


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

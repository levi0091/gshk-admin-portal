"""The ONE GSHK CR presenter identity — shared by every user (BE-5, W-6).

Not to be confused with either neighbour:
  tpsi_presenter_credentials  per-USER e-Service SIGNING credential (W-7). A
                              signature is a personal act.
  tpsi_accounts               entity-scoped, the CLIENT company's own
                              e-Registry account.

Everything GSHK files, it files under this record. Only a Super Admin may write
it (OQ-C), because changing it changes who the Companies Registry believes is
filing — and it spends from the deposit account named on it.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from db.supabase import get_supabase
from services.tpsi.config import get_config
from services.tpsi.credentials import UNSET as _UNSET
from services.tpsi.secrets import decrypt, encrypt

_TABLE = "tpsi_shared_presenter"

#: Same sentinel discipline as credentials.py: "not mentioned" must not collapse
#: into "explicitly cleared", or a password-only rotation wipes the deposit
#: account. See _payload.
#:
#: This is credentials.UNSET, not a second, distinct object() — see
#: routers/tpsi.py::_opt, which returns credentials.UNSET for the shared-
#: credential endpoint too. Sentinels are compared by identity (`is not
#: _UNSET`); two distinct sentinel objects would mean the router's "the caller
#: omitted this field" is never recognised as this module's sentinel, so the
#: bare object() itself would be written into the PostgREST payload as if it
#: were a real value — corrupting deposit_account_no on every password-only
#: rotation, the routine case CR forces every 180 days.
UNSET = _UNSET

_HINT_REVEAL = 4


@dataclass(frozen=True)
class SharedPresenter:
    account_id: str
    tpsi_password: str
    deposit_account_no: str | None


def _read() -> dict | None:
    rows = get_supabase().table(_TABLE).select("*").execute().data
    return rows[0] if rows else None


def _upsert(payload: dict) -> dict:
    return get_supabase().table(_TABLE).upsert(payload, on_conflict="id").execute().data[0]


def _hint(enc: str | None) -> str | None:
    """Masked echo of the stored password — last four characters at most.

    The same deliberate relaxation credentials.py documents: without it nobody
    can tell WHICH password is stored, so a rotation is done blind against an
    API that locks accounts on repeated auth failure. A password of four
    characters or fewer reveals nothing.
    """
    if not enc:
        return None
    plain = decrypt(enc)
    if len(plain) <= _HINT_REVEAL:
        return "•" * len(plain)
    return "•" * (len(plain) - _HINT_REVEAL) + plain[-_HINT_REVEAL:]


def _to_metadata(row: dict) -> dict:
    """The single definition of what is safe to return — used by the read path
    and by the write path's echo, so the allow-list cannot drift apart."""
    return {
        "presentor_account_id": row["presentor_account_id"],
        "deposit_account_no": row.get("deposit_account_no"),
        "tpsi_password_hint": _hint(row.get("tpsi_password_enc")),
        "tpsi_password_expires_at": row.get("tpsi_password_expires_at"),
        "is_test": row["is_test"],
        "last_rotated_at": row.get("last_rotated_at"),
        "updated_by": row.get("updated_by"),
        "updated_at": row.get("updated_at"),
    }


def get_metadata() -> dict | None:
    row = _read()
    return _to_metadata(row) if row else None


def load_for_use() -> SharedPresenter:
    """Decrypt for an actual CR call. Callers must not log the result."""
    row = _read()
    if not row:
        raise LookupError(
            "no shared TPSI presenter credential is configured — a Super Admin "
            "must set one before anything can be filed"
        )

    expected_test = get_config().env == "test"
    if row["is_test"] != expected_test:
        raise RuntimeError(
            f"shared credential is_test={row['is_test']} but TPSI_ENV="
            f"{get_config().env}; refusing to use it"
        )

    return SharedPresenter(
        account_id=row["presentor_account_id"],
        tpsi_password=decrypt(row["tpsi_password_enc"]),
        deposit_account_no=row.get("deposit_account_no"),
    )


def _payload(presentor_account_id, tpsi_password, deposit_account_no,
             updated_by, rotated) -> dict:
    payload = {
        "id": True,
        "presentor_account_id": presentor_account_id,
        "is_test": get_config().env == "test",
        "updated_by": updated_by,
    }
    # Same _UNSET discipline as deposit_account_no below, and for a sharper
    # reason. This is GSHK's ONLY CR identity: every user of the portal files
    # through it. Forcing the password to be re-supplied to change an unrelated
    # field (the deposit account) means retyping it from memory, and a typo is
    # not caught here -- it is caught by CR, on the next filing, as a failed
    # authentication. CR locks an account after repeated failures, so one slip
    # while editing a deposit account number could lock the whole firm out of
    # filing. Omitted -> the stored password stands.
    if tpsi_password is not _UNSET:
        payload["tpsi_password_enc"] = encrypt(tpsi_password)
    # Omitted key -> PostgREST leaves the column untouched. Explicit None ->
    # the column is cleared. See credentials._payload for why the distinction
    # is load-bearing on a 180-day password rotation.
    if deposit_account_no is not _UNSET:
        payload["deposit_account_no"] = deposit_account_no
    if rotated:
        payload["last_rotated_at"] = datetime.now(timezone.utc).isoformat()
        # The stored expiry describes the password just REPLACED, so leaving it
        # makes the metadata report an expiry — usually already in the past —
        # for a credential that no longer exists. That is the one signal meant
        # to warn before an expired password blocks a filing, so a stale value
        # is worse than none. record_password_expiry() refills it from the
        # `password_expires_in` on the next authenticate.
        payload["tpsi_password_expires_at"] = None
    return payload


def set_shared(
    *,
    presentor_account_id: str,
    tpsi_password: str | None = _UNSET,
    deposit_account_no: str | None = _UNSET,
    updated_by: str,
    rotated: bool = False,
) -> dict:
    """Create or update the one shared presenter record.

    `tpsi_password` omitted keeps whatever is stored — but there has to BE
    something stored. Refused here rather than at the database, because the
    column is nullable and a row with no password would fail much later, at CR,
    as an authentication error nobody could trace back to this call.
    """
    if tpsi_password is _UNSET and not (_read() or {}).get("tpsi_password_enc"):
        raise ValueError(
            "no shared TPSI password is stored yet, so one must be supplied "
            "when the shared presenter credential is first set"
        )
    return _to_metadata(
        _upsert(_payload(presentor_account_id, tpsi_password,
                         deposit_account_no, updated_by, rotated))
    )


def record_password_expiry(expires_at: str | None) -> None:
    """Persist `password_expires_in` from the auth response so the 180-day
    expiry surfaces before it blocks a filing, not mid-submission."""
    if not expires_at:
        return
    get_supabase().table(_TABLE).update(
        {"tpsi_password_expires_at": expires_at}
    ).eq("id", True).execute()

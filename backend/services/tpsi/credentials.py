"""The presenter credential: a G-FlowDesk user's CR filing identity.

Not to be confused with `tpsi_accounts`, which is entity-scoped and holds the
CLIENT company's own e-Registry account.

Two passwords, two jobs (spec D3):
  tpsi_password      authenticates (SHA-256 in the Basic header). Never signs.
  eservice_password  signs. This row is the ONLY source of a NAR1 signature
                     since Q1 (Levi 2026-08-30) — no endpoint accepts a
                     signing credential from a request any more. A user
                     without one cannot sign, and is told to store one here.

Spec D4 described the opposite arrangement, where a client director supplied
their own password live at signing and it was never persisted. That is
withdrawn: it made the signing account a free-text field on a statutory
declaration.
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

#: Public alias. The router needs this sentinel to say "the client did not
#: mention this field" — see routers/tpsi.py::_opt. Without it the distinction
#: dies at the HTTP boundary and every optional field gets cleared on rotation.
UNSET = _UNSET


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


#: Characters of a stored password echoed back to its owner. Four is the most
#: that may ever be revealed; the rest is masked.
_HINT_REVEAL = 4


def _hint(enc: str | None) -> str | None:
    """A recognisable echo of a stored password: masked except the last four.

    This is a DELIBERATE relaxation of the rule that no endpoint returns a
    password (Levi, v8 mock-up feedback and reaffirmed 2026-08-02). The reason
    it is worth the trade: without it nobody can tell WHICH password is stored,
    so a rotation is done blind and a user who is unsure re-types a password
    they may be getting wrong — against an API that locks accounts on repeated
    auth failures.

    What keeps it defensible:
      * scoped to the owner — get_metadata() is keyed on the caller's own
        user_id, so this never exposes one user's secret to another;
      * never more than the last four characters, whatever the length;
      * a password of four characters or fewer reveals NOTHING, because
        "the last four" would be the entire secret.

    It does disclose the password's length. That is inherent to showing a
    like-for-like mask and is accepted.
    """
    if not enc:
        return None
    plain = decrypt(enc)
    if len(plain) <= _HINT_REVEAL:
        return "•" * len(plain)
    return "•" * (len(plain) - _HINT_REVEAL) + plain[-_HINT_REVEAL:]


def _to_metadata(row: dict) -> dict:
    """The one, shared definition of what's safe to return. Used by the read
    path (get_metadata) AND both write paths (set_credential/rotate_credential,
    off the row _upsert already returned) so this allow-list can't drift apart
    between them.

    Carries a masked last-four HINT for each stored password (see _hint) — never
    the password, never the ciphertext."""
    return {
        # presentor_account_id is deliberately NOT returned. Since BE-5 this row
        # is a signing credential; the CR login is the shared presenter record,
        # which is Super-Admin-only (GET /tpsi/shared-credential). On rows
        # written before BE-5 this column holds GSHK's real CR account id, so
        # echoing it here would hand the firm's filing username to every holder
        # of `tpsi:read` through a per-user endpoint. Nothing reads it: the
        # signatory fallback in load_eservice() reads the ROW, not this payload.
        "eservice_user_id": row.get("eservice_user_id"),
        "has_eservice_password": row.get("eservice_password_enc") is not None,
        "tpsi_password_hint": _hint(row.get("tpsi_password_enc")),
        "eservice_password_hint": _hint(row.get("eservice_password_enc")),
        "tpsi_password_expires_at": row.get("tpsi_password_expires_at"),
        "deposit_account_no": row.get("deposit_account_no"),
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

    if not row.get("tpsi_password_enc"):
        # Since migration 020 (BE-5), tpsi_password_enc is nullable: a row may
        # now hold only a signing credential (W-7), with no CR login of its
        # own. Calling decrypt(None) below would raise an opaque AttributeError
        # deep inside Fernet instead of naming what actually happened — this
        # user's row is signing-only, and services.tpsi.shared_credentials is
        # what authenticates filings now.
        raise LookupError(
            "this TPSI credential is signing-only — it has no stored CR login "
            "password. The shared presenter (services.tpsi.shared_credentials) "
            "authenticates filings; this row only holds a signing credential"
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
    presentor_account_id,
    tpsi_password,
    eservice_user_id,
    eservice_password,
    deposit_account_no,
    rotated: bool,
) -> dict:
    payload = {
        "user_id": user_id,
        "is_test": get_config().env == "test",
    }
    # _UNSET-guarded like every other column here. Since BE-5 the caller has no
    # reason to send this at all -- the CR login is the shared record -- but
    # legacy rows still carry a value that load_eservice() falls back on as the
    # signatory id. Writing NULL over it because the field was simply absent
    # would silently break signing for those users.
    if presentor_account_id is not _UNSET:
        payload["presentor_account_id"] = presentor_account_id
    # Same _UNSET discipline as the optional fields below. Without it there is
    # no way to change the deposit account or the e-Service ID without also
    # re-supplying the TPSI password -- which the user would have to retype from
    # memory against an API that locks accounts on repeated auth failures.
    if tpsi_password is not _UNSET:
        payload["tpsi_password_enc"] = encrypt(tpsi_password)
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
    # Same _UNSET discipline: the deposit account must survive a password-only
    # rotation untouched (D-3).
    if deposit_account_no is not _UNSET:
        payload["deposit_account_no"] = deposit_account_no
    if rotated:
        payload["last_rotated_at"] = datetime.now(timezone.utc).isoformat()
    return payload


def set_credential(
    *,
    user_id: str,
    presentor_account_id: str | None = _UNSET,
    tpsi_password: str | None = _UNSET,
    eservice_user_id: str | None = _UNSET,
    eservice_password: str | None = _UNSET,
    deposit_account_no: str | None = _UNSET,
) -> dict:
    row = _upsert(
        _payload(
            user_id, presentor_account_id, tpsi_password,
            eservice_user_id, eservice_password, deposit_account_no,
            rotated=False,
        )
    )
    return _to_metadata(row)


def rotate_credential(
    *,
    user_id: str,
    presentor_account_id: str | None = _UNSET,
    tpsi_password: str | None = _UNSET,
    eservice_user_id: str | None = _UNSET,
    eservice_password: str | None = _UNSET,
    deposit_account_no: str | None = _UNSET,
) -> dict:
    row = _upsert(
        _payload(
            user_id, presentor_account_id, tpsi_password,
            eservice_user_id, eservice_password, deposit_account_no,
            rotated=True,
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


def load_eservice(user_id: str) -> tuple[str, str] | None:
    """This user's own e-SERVICE signing credential, or None.

    Since BE-5 the CR LOGIN is the shared presenter record, and this table holds
    only the personal signing credential (W-7).

    None means this user CANNOT SIGN. Since Q1 there is no fallback to fall
    back to — the live-entered credential path is gone — so the caller's job is
    to say so and point at CR Credentials, not to look elsewhere.

    Falls back to presentor_account_id when eservice_user_id is unset because
    that was the pre-BE-5 shape — a user whose CR account id doubled as their
    e-Service id must keep signing without re-entering anything.
    """
    row = _read(user_id)
    if not row:
        return None
    enc = row.get("eservice_password_enc")
    if not enc:
        return None
    signatory = row.get("eservice_user_id") or row.get("presentor_account_id")
    if not signatory:
        return None
    return signatory, decrypt(enc)

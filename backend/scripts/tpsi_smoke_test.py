"""Manual connectivity check against CR's TPSI TEST environment.

    cd backend && uv run python scripts/tpsi_smoke_test.py

Reads TPSI_SMOKE_USER_ID / TPSI_SMOKE_PASSWORD / TPSI_SMOKE_ACCOUNT_NO. Those
exist only for this script — the application reads per-user credentials from
`tpsi_presenter_credentials`, never from the environment. This is the
before-any-credential-is-stored bootstrap check, nothing more.

ONE ATTEMPT PER CALL, NEVER RETRIED. CR locks accounts after repeated
authentication failures — one account on this project was already locked that
way — and the TEST environment is open only Mon-Fri 10:00-16:00 HKT, so a
lockout costs a working day. If this reports a rejection, fix the credential
before running it again; do not loop.

What can be checked when (measured 2026-08-01 23:10 HKT, a Saturday):
  login                 answers 24/7                              CONFIRMED
  enquireDepositAccount answers 24/7 too - NOT window-gated       CONFIRMED
  validate/sign/submit  Mon-Fri 10:00-16:00 HKT only              not yet exercised

The balance result corrects an assumption carried through the PRD and the
design spec, which treated the whole TPSI surface as window-gated. Only the
form APIs are; the read APIs answer outside the window.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

# Hong Kong is UTC+8 year-round and has observed no DST since 1979, so a fixed
# offset is correct here and avoids depending on a tz database that Windows
# does not ship.
_HKT = timezone(timedelta(hours=8))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from services.tpsi import reads  # noqa: E402
from services.tpsi.client import TpsiClient  # noqa: E402
from services.tpsi.config import get_config  # noqa: E402
from services.tpsi.errors import (  # noqa: E402
    TpsiAuthError,
    TpsiError,
    TpsiPasswordExpiredError,
    TpsiUnavailableError,
)


def _window_state() -> str:
    now = datetime.now(_HKT)
    inside = now.weekday() < 5 and 10 <= now.hour < 16
    return (
        f"{now:%Y-%m-%d %H:%M} HKT ({now:%a}) - form-API window "
        f"{'OPEN' if inside else 'CLOSED'} (Mon-Fri 10:00-16:00)"
    )


def main() -> int:
    config = get_config()
    print(f"env      : {config.env}")
    print(f"base url : {config.base_url}")
    print(f"tls      : verify={config.tls_verify}")
    print(f"window   : {_window_state()}")

    user_id = os.environ.get("TPSI_SMOKE_USER_ID")
    password = os.environ.get("TPSI_SMOKE_PASSWORD")
    if not (user_id and password):
        print("\nSKIP: set TPSI_SMOKE_USER_ID and TPSI_SMOKE_PASSWORD to run this.")
        return 1
    print(f"account  : {user_id}")

    client = TpsiClient(user_id, password)

    # ---- 1. authenticate (ONE attempt) ------------------------------------
    print("\n[1] authenticate ... ", end="", flush=True)
    try:
        result = client.authenticate()
    except TpsiPasswordExpiredError as exc:
        print(f"PASSWORD EXPIRED\n    {exc}")
        return 1
    except TpsiAuthError as exc:
        print(f"REJECTED (not retried)\n    {exc}")
        return 1
    except TpsiUnavailableError as exc:
        print(f"UNAVAILABLE\n    {exc}")
        return 1

    print("OK")
    print(f"    token      : {result.access_token[:16]}... ({len(result.access_token)} chars)")
    print(f"    expires_in : {result.expires_in}s")
    print(f"    pw expires : {result.password_expires_in}")
    client._token_cache = result.access_token  # reuse; do not log in again

    # ---- 2. deposit balance ------------------------------------------------
    account_no = os.environ.get("TPSI_SMOKE_ACCOUNT_NO")
    if account_no:
        print(f"\n[2] enquireDepositAccount({account_no}) ... ", end="", flush=True)
        try:
            balance = reads.check_balance(client, account_no)
            print(f"OK\n    balance: {balance} (type {type(balance).__name__})")
        except TpsiError as exc:
            print(f"{type(exc).__name__}\n    {exc}")
    else:
        print("\n[2] skipped - TPSI_SMOKE_ACCOUNT_NO not set")

    # ---- 3. logout ---------------------------------------------------------
    print("\n[3] logout ... ", end="", flush=True)
    client.logout()
    print("OK (token revoked, local cache cleared)")

    print("\nConnectivity to CR confirmed. Form APIs (validate/sign/submit) need "
          "the Mon-Fri 10:00-16:00 HKT window.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

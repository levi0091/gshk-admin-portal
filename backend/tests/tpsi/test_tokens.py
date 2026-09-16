from datetime import datetime, timedelta, timezone

import psycopg2
import pytest
from cryptography.fernet import Fernet

from services.tpsi import config as cfg
from services.tpsi import tokens

# make_pem is a shared fixture from tests/tpsi/conftest.py.


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path, make_pem):
    key = tmp_path / "k.pem"
    key.write_text(make_pem())
    monkeypatch.setenv("TPSI_ENV", "test")
    monkeypatch.setenv("TPSI_BASE_URL", "https://apitest.cr.gov.hk/ICRIS3EF")
    monkeypatch.setenv("TPSI_TLS_VERIFY", "false")
    monkeypatch.setenv("TPSI_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("TPSI_CR_PUBLIC_KEY_PATH", str(key))
    cfg.get_config.cache_clear()
    yield
    cfg.get_config.cache_clear()


def _auth(token="TOK", expires_in=1800):
    return lambda: tokens.AuthResult(
        access_token=token, expires_in=expires_in, password_expires_in=None
    )


def test_fresh_acquisition_calls_authenticate_and_stores(monkeypatch):
    rows = {}
    monkeypatch.setattr(tokens, "_read_row", lambda a: rows.get(a))
    monkeypatch.setattr(tokens, "_write_row", lambda a, t, e: rows.update({a: (t, e)}))
    monkeypatch.setattr(tokens, "_with_lock", lambda a, fn: fn())

    calls = []

    def auth():
        calls.append(1)
        return tokens.AuthResult("TOK", 1800, None)

    assert tokens.acquire_token("ACCT", auth) == "TOK"
    assert len(calls) == 1
    assert "ACCT" in rows


def test_valid_cached_token_is_reused_without_authenticating(monkeypatch):
    from services.tpsi.secrets import encrypt

    future = datetime.now(timezone.utc) + timedelta(minutes=20)
    monkeypatch.setattr(tokens, "_read_row", lambda a: (encrypt("CACHED"), future))
    monkeypatch.setattr(tokens, "_write_row", lambda a, t, e: None)
    monkeypatch.setattr(tokens, "_with_lock", lambda a, fn: fn())

    calls = []

    def auth():
        calls.append(1)
        return tokens.AuthResult("NEW", 1800, None)

    assert tokens.acquire_token("ACCT", auth) == "CACHED"
    assert calls == []


def test_token_expiring_within_the_margin_is_not_handed_out(monkeypatch):
    """A token with 30s left would expire mid-request. Re-acquire instead."""
    from services.tpsi.secrets import encrypt

    nearly = datetime.now(timezone.utc) + timedelta(seconds=30)
    monkeypatch.setattr(tokens, "_read_row", lambda a: (encrypt("OLD"), nearly))
    monkeypatch.setattr(tokens, "_write_row", lambda a, t, e: None)
    monkeypatch.setattr(tokens, "_with_lock", lambda a, fn: fn())

    assert tokens.acquire_token("ACCT", _auth("NEW")) == "NEW"


def test_acquisition_happens_inside_the_advisory_lock(monkeypatch):
    """One token per account: two workers must not both log in."""
    order = []
    monkeypatch.setattr(tokens, "_read_row", lambda a: None)
    monkeypatch.setattr(tokens, "_write_row", lambda a, t, e: order.append("write"))

    def fake_lock(account, fn):
        order.append("lock")
        result = fn()
        order.append("unlock")
        return result

    monkeypatch.setattr(tokens, "_with_lock", fake_lock)

    def auth():
        order.append("auth")
        return tokens.AuthResult("TOK", 1800, None)

    tokens.acquire_token("ACCT", auth)
    assert order == ["lock", "auth", "write", "unlock"]


def test_invalidate_deletes_the_row(monkeypatch):
    deleted = []
    monkeypatch.setattr(tokens, "_delete_row", lambda a: deleted.append(a))
    tokens.invalidate("ACCT")
    assert deleted == ["ACCT"]


def test_stored_token_is_encrypted_not_plaintext(monkeypatch):
    captured = {}
    monkeypatch.setattr(tokens, "_read_row", lambda a: None)
    monkeypatch.setattr(
        tokens, "_write_row", lambda a, t, e: captured.update({"enc": t})
    )
    monkeypatch.setattr(tokens, "_with_lock", lambda a, fn: fn())
    tokens.acquire_token("ACCT", _auth("SECRET-JWT"))
    assert "SECRET-JWT" not in captured["enc"]


def test_with_lock_raises_in_prod_without_database_url(monkeypatch):
    """The whole point of this file is serialising acquisition. In prod,
    losing DATABASE_URL must fail loudly, not silently reopen the
    concurrent-login race."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Simulate prod fully, not just the one variable: config now refuses a
    # crossed env/host pair, and _with_lock reads `is_prod` through a
    # try/except that treats a raising get_config() as "not prod". A
    # half-simulated prod would therefore take the warned fallback and this
    # test would assert nothing.
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("TPSI_ENV", "prod")
    monkeypatch.setenv("TPSI_BASE_URL", "https://www.e-services.cr.gov.hk/ICRIS3EF")
    cfg.get_config.cache_clear()

    with pytest.raises(RuntimeError, match="advisory lock"):
        tokens._with_lock("ACCT", lambda: pytest.fail("must not run unlocked"))


def test_with_lock_falls_back_and_warns_in_non_prod_without_database_url(
    monkeypatch, capsys
):
    """Outside prod (e.g. this test suite), the unlocked fallback still runs
    the function — but must warn on stderr so it's never mistaken for the
    locked path."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # _env fixture already set TPSI_ENV=test.

    assert tokens._with_lock("ACCT", lambda: "ran") == "ran"

    assert "DATABASE_URL" in capsys.readouterr().err


# The DSN in these tests carries a password on purpose: the refusal must name
# the host and never echo the connection string. A driver error quoted verbatim
# into an HTTP body would put the database password on the operator's screen
# and in Railway's logs.
_UNREACHABLE_DSN = (
    "postgresql://postgres:C0RRECTH0RSE@"
    "db.tztrnnthgrtkicciufig.supabase.co:5432/postgres"
)


def _refuse_to_connect(message):
    def boom(dsn, **kwargs):
        raise psycopg2.OperationalError(message)

    return boom


def test_unreachable_lock_dsn_is_refused_by_name_not_as_a_driver_error(monkeypatch):
    """PROD, 2026-09-16, first live CR filing.

    DATABASE_URL held the DIRECT Supabase host, `db.<ref>.supabase.co`, which
    publishes AAAA records only. Railway has no IPv6 route, so psycopg2 raised
    `OperationalError: Network is unreachable` here -- and `routers.tpsi._handle`
    classifies TpsiError/RuntimeError and re-raises anything else, so it escaped
    as a bare 500 with a stack trace. The operator saw "The server could not
    complete this request", which points at the return data; nothing had gone
    wrong with the return, and CR was never reached at all.

    The remedy belongs IN the message, because the person who reads it is
    looking at a filing screen, not at this file.
    """
    monkeypatch.setenv("DATABASE_URL", _UNREACHABLE_DSN)
    monkeypatch.setattr(
        tokens.psycopg2,
        "connect",
        _refuse_to_connect(
            'connection to server at "db.tztrnnthgrtkicciufig.supabase.co" '
            "(2406:da14:1d4f:7400:6193:1590:c153:8716), port 5432 failed: "
            "Network is unreachable\n"
        ),
    )

    with pytest.raises(RuntimeError) as caught:
        tokens._with_lock("ACCT", lambda: pytest.fail("must not run unlocked"))

    message = str(caught.value)
    # Names the host that could not be reached...
    assert "db.tztrnnthgrtkicciufig.supabase.co" in message
    # ...says what to do about it, in the words the fix is spelled in...
    assert "pooler" in message.lower()
    # ...and still says WHY the call stopped, so it is not read as a CR fault.
    assert "advisory lock" in message.lower()


def test_an_unreachable_lock_dsn_never_echoes_the_password(monkeypatch):
    """The refusal travels to the browser as a 502 body and to Railway's logs."""
    monkeypatch.setenv("DATABASE_URL", _UNREACHABLE_DSN)
    monkeypatch.setattr(
        tokens.psycopg2,
        "connect",
        _refuse_to_connect("Network is unreachable"),
    )

    with pytest.raises(RuntimeError) as caught:
        tokens._with_lock("ACCT", lambda: None)

    assert "C0RRECTH0RSE" not in str(caught.value)
    assert _UNREACHABLE_DSN not in str(caught.value)


def test_an_unreachable_lock_dsn_does_not_run_the_work_unlocked(monkeypatch):
    """Refusing is the whole point: one token per CR account. A fallback that
    logged in anyway would invalidate another worker's token mid-submit."""
    monkeypatch.setenv("DATABASE_URL", _UNREACHABLE_DSN)
    monkeypatch.setattr(
        tokens.psycopg2, "connect", _refuse_to_connect("Network is unreachable")
    )

    ran = []
    with pytest.raises(RuntimeError):
        tokens._with_lock("ACCT", lambda: ran.append(1))

    assert ran == []

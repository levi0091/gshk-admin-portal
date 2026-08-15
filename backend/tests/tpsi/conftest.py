import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from services.tpsi import config as _cfg
from services.tpsi import tokens as _tokens


def _clear_config_cache():
    # A test may monkeypatch services.tpsi.config.get_config with a plain
    # lambda (test_filings does). Fixture teardown runs before that
    # monkeypatch is undone — same function-scoped monkeypatch object, and
    # this fixture depends on it, so it finalises first — and a lambda has no
    # cache_clear. Tolerate it rather than turning every such test into a
    # teardown error.
    getattr(_cfg.get_config, "cache_clear", lambda: None)()


@pytest.fixture(autouse=True)
def tpsi_env(monkeypatch, tmp_path_factory):
    """Give every TPSI test a complete, fake, self-contained config.

    These tests used to read whatever the developer's backend/.env happened to
    hold. That is why CI was red while local was green: `load_dotenv()` supplies
    TPSI_* on a dev machine and CI has no .env, so `get_config()` failed at the
    FIRST missing variable instead of the one under test — e.g.
    test_missing_var_raises_without_printing_value deletes TPSI_BASE_URL, but in
    CI the resolver died earlier on the public key and the assertion never saw
    the message it was written for.

    Depending on ambient config also meant the suite was not testing what it
    claimed: a machine with prod-ish values in .env would exercise a different
    path. Overriding here (monkeypatch beats an already-loaded .env) makes local
    and CI identical, and means CI needs NO TPSI secrets to run unit tests.

    A test that cares about a variable being absent still deletes it explicitly
    with monkeypatch.delenv — now the only thing missing is the thing under test.
    """
    key_file = tmp_path_factory.mktemp("tpsi") / "cr_public.pem"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_file.write_text(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode())

    # APP_ENV is deliberately left UNSET, not set to "dev": a fixture that
    # asserts a deployment would block every test that simulates prod. Tests
    # exercising the derivation set it themselves. Cleared so an ambient value
    # cannot leak in either.
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("TPSI_ENV", "test")
    monkeypatch.setenv("TPSI_BASE_URL", "https://apitest.cr.gov.hk/ICRIS3EF")
    monkeypatch.setenv("TPSI_TLS_VERIFY", "false")
    monkeypatch.setenv("TPSI_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("TPSI_CR_PUBLIC_KEY_PATH", str(key_file))
    # Never inherit a real inline key from the environment.
    monkeypatch.delenv("TPSI_CR_PUBLIC_KEY", raising=False)

    _clear_config_cache()
    yield
    _clear_config_cache()


@pytest.fixture(autouse=True)
def tpsi_token_store(monkeypatch):
    """Keep the TPSI token store in memory. No test may reach Supabase.

    This is not just CI plumbing. `client.logout()` and the 401 retry path call
    `tokens.invalidate()`, which goes straight to `tpsi_tokens` — so on a
    developer machine, where .env supplies SUPABASE_URL and the service-role
    key, five tests in test_client.py were issuing real DELETEs against the DEV
    database and passing because of it. CLAUDE.md is explicit: tests must not
    hit the real Supabase DB. They only failed in CI because the credentials
    were absent, which made a data-integrity problem look like a config one.

    Tests that care about store behaviour (test_tokens.py) still override these
    inside the test body — monkeypatch there is applied after this fixture.
    """
    rows: dict[str, tuple[str, object]] = {}
    monkeypatch.setattr(_tokens, "_read_row", lambda a: rows.get(a))
    monkeypatch.setattr(
        _tokens, "_write_row", lambda a, t, e: rows.update({a: (t, e)})
    )
    monkeypatch.setattr(_tokens, "_delete_row", lambda a: rows.pop(a, None))
    return rows


@pytest.fixture
def make_pem():
    """Factory fixture: each call generates a fresh, real RSA-2048 public key
    PEM. Config load validates PEM shape (a truncated/garbage key must fail
    fast, not mid-signing), so tests need parseable keys, not stub blobs. A
    factory (not a single value) lets tests that need two distinct keys —
    e.g. to prove one source takes precedence over another — get keys that
    are genuinely different rather than string-distinguishable stubs.

    Shared across every tests/tpsi/*.py file — every one of them constructs
    a TpsiConfig sooner or later, and they all need this."""

    def _make() -> str:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

    return _make

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from services.tpsi import config as cfg
from services.tpsi import secrets as sec


@pytest.fixture
def make_pem():
    """Factory fixture: each call generates a fresh, real RSA-2048 public key
    PEM. Config load validates PEM shape (a truncated/garbage key must fail
    fast, not mid-signing), so tests need a parseable key, not a stub blob."""

    def _make() -> str:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

    return _make


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


def test_round_trip():
    assert sec.decrypt(sec.encrypt("hunter2")) == "hunter2"


def test_ciphertext_does_not_contain_plaintext():
    assert "hunter2" not in sec.encrypt("hunter2")


def test_same_plaintext_encrypts_differently_each_time():
    """Fernet includes a random IV. Identical ciphertexts would let anyone with
    read access to the table tell which users share a password."""
    assert sec.encrypt("hunter2") != sec.encrypt("hunter2")


def test_decrypt_with_wrong_key_raises(monkeypatch):
    token = sec.encrypt("hunter2")
    monkeypatch.setenv("TPSI_CRED_KEY", Fernet.generate_key().decode())
    cfg.get_config.cache_clear()
    with pytest.raises(Exception):
        sec.decrypt(token)


def test_sha256_hex_matches_the_spec_worked_example():
    """The spec's own Basic-auth example decodes to
    CAMILLE:5fef526bd3b7b26001f826f469250cb954299a0169a46d11ac37a263a9ab6ab5
    — a 64-char lowercase hex digest, which pins format and case."""
    digest = sec.sha256_hex("anything")
    assert len(digest) == 64
    assert digest == digest.lower()
    assert sec.sha256_hex("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


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

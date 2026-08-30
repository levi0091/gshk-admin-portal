"""Envelope encryption for credentials and tokens held at rest.

Plaintext exists only inside the function that uses it. Nothing here is ever
logged or returned by an endpoint.
"""
import hashlib

from cryptography.fernet import Fernet

from services.tpsi.config import get_config


def _cipher() -> Fernet:
    return Fernet(get_config().cred_key)


def encrypt(plaintext: str) -> str:
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _cipher().decrypt(ciphertext.encode()).decode()


def sha256_hex(value: str) -> str:
    """Lowercase hex SHA-256 — the form CR's auth header and changeTpsiPassword
    both expect."""
    return hashlib.sha256(value.encode()).hexdigest()

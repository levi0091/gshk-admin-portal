"""The TPSI PIN signature chain (API spec Appendix 7.1, v1.0.14).

    UserCredentialHash  = BASE64( AES256( username + random32 + SHA256(password) ) )
                          key = random32
    UserSignature       = BASE64( AES-GCM( SHA256( EForm + UserCredentialHash ) ) )
                          key = the AES-GCM key
    EncryptionKey       = BASE64( RSA( random32 ) )   key = CR public key
    AESGCMEncryptionKey = the crypto-generated AES-GCM key

Randomness is INJECTED, never generated inside the signing functions. Two
reasons: the output is otherwise untestable (every run differs), and callers can
freeze a regression vector. Production callers pass nothing and get fresh
randomness. Each injection point (random32, the AES-GCM key, the AES-GCM
nonce) is independent — none is ever derived from whether another was
supplied. See user_signature's docstring for why: an AES-GCM key and nonce
must never repeat together, and deriving one from the other's presence is
how that constraint quietly breaks the first time a caller injects a key
for a reason unrelated to nonce determinism (the NNC1 per-director loop).

There is deliberately no byte-for-byte test against CR's published sample: it
predates v1.0.14 (no AESGCMEncryptionKey tag) and gives no plaintext password,
so it cannot be reproduced. Correctness is proven by a live verifyPinSigning.
"""
import base64
import os
import secrets as pysecrets
import string

from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from services.tpsi.secrets import sha256_hex

_ALPHABET = string.ascii_letters + string.digits
_GCM_NONCE_LEN = 12


def random32() -> str:
    """32-character random alphanumeric key ('random32' in the spec)."""
    return "".join(pysecrets.choice(_ALPHABET) for _ in range(32))


def _aes256_key(rand: str) -> bytes:
    """random32 is 32 ASCII characters = exactly 32 bytes = AES-256."""
    key = rand.encode()
    if len(key) != 32:
        raise ValueError("random32 must be exactly 32 characters")
    return key


def _pkcs7_pad(data: bytes) -> bytes:
    pad = 16 - (len(data) % 16)
    return data + bytes([pad]) * pad


def _pkcs7_unpad(data: bytes) -> bytes:
    return data[: -data[-1]]


def user_credential_hash(user_id: str, password: str, rand: str) -> str:
    """BASE64( AES256( username + random32 + SHA256(password) ) ), key = random32.

    ECB with PKCS#7: the spec says only "AES 256 bit encrypt using random32 as
    encryption key" with no IV anywhere in the message, and CR must be able to
    decrypt using random32 alone (recovered from EncryptionKey).
    """
    plaintext = (user_id + rand + sha256_hex(password)).encode()
    encryptor = Cipher(algorithms.AES(_aes256_key(rand)), modes.ECB()).encryptor()
    ciphertext = encryptor.update(_pkcs7_pad(plaintext)) + encryptor.finalize()
    return base64.b64encode(ciphertext).decode()


def decrypt_credential_hash(credential_hash_b64: str, rand: str) -> str:
    """Inverse of user_credential_hash — used by tests to prove the chain."""
    raw = base64.b64decode(credential_hash_b64)
    decryptor = Cipher(algorithms.AES(_aes256_key(rand)), modes.ECB()).decryptor()
    return _pkcs7_unpad(decryptor.update(raw) + decryptor.finalize()).decode()


def user_signature(
    eform_xml: str,
    credential_hash_b64: str,
    gcm_key: bytes | None = None,
    nonce: bytes | None = None,
) -> tuple[str, str]:
    """BASE64( AES-GCM( SHA256( EForm + UserCredentialHash ) ) ).

    Returns (UserSignature, AESGCMEncryptionKey) — both base64. The nonce is
    prepended to the ciphertext so CR can decrypt with the key alone.

    `gcm_key` and `nonce` are two INDEPENDENT injection points — neither is
    ever derived from the other. Deriving the nonce from "was a key
    injected?" was tried and reverted: it made an injected key imply a fixed
    (all-zero) nonce, which is safe only because today's one caller
    (filings.sign) never injects a key. The NNC1 consent flow will call this
    once per director in a loop; a future caller that reused an injected
    `gcm_key` across that loop would then silently reuse the nonce too — the
    textbook AES-GCM failure (the same key+nonce pair encrypting two
    messages leaks the authentication key and lets an attacker forge
    messages, not just a confidentiality loss). So there is no such
    derivation: production passes neither and gets a fresh, unique key AND
    nonce on every call; a test that wants a frozen vector must inject both
    explicitly, which makes the reuse a visible, deliberate choice at the
    call site instead of an implicit side effect of "a key happened to be
    supplied".
    """
    key = gcm_key or AESGCM.generate_key(bit_length=256)
    digest = sha256_hex(eform_xml + credential_hash_b64).encode()
    nonce = nonce or os.urandom(_GCM_NONCE_LEN)
    ciphertext = AESGCM(key).encrypt(nonce, digest, None)
    return (
        base64.b64encode(nonce + ciphertext).decode(),
        base64.b64encode(key).decode(),
    )


def encryption_key(rand: str, cr_public_key_pem: str) -> str:
    """BASE64( RSA( random32 ) ) using CR's public key."""
    key = load_pem_public_key(cr_public_key_pem.encode())
    return base64.b64encode(key.encrypt(rand.encode(), padding.PKCS1v15())).decode()


def build_pin_sign(
    eform_xml: str,
    user_id: str,
    eservice_password: str,
    cr_public_key_pem: str,
    uri: str = "#eForm",
    sign_id: str = "1",
    rand: str | None = None,
    gcm_key: bytes | None = None,
    nonce: bytes | None = None,
) -> str:
    """One <PinSign> block.

    Overall signature (NAR1): uri="#eForm", signing the whole EForm.
    Consent signature (NNC1, later): uri="#S1", signing that director tag.

    `nonce` exists only so a test can freeze the AES-GCM output alongside an
    injected `gcm_key` (see user_signature) — production callers, including
    the future NNC1 per-director loop, must never pass it.
    """
    rand = rand or random32()
    credential_hash = user_credential_hash(user_id, eservice_password, rand)
    signature, gcm_key_b64 = user_signature(eform_xml, credential_hash, gcm_key, nonce)
    encrypted_rand = encryption_key(rand, cr_public_key_pem)

    del gcm_key_b64  # see the AESGCMEncryptionKey note below

    return (
        f'<cr:PinSign URI="{uri}">'
        f"<cr:UserCredentialHash>{credential_hash}</cr:UserCredentialHash>"
        f"<cr:UserSignature>{signature}</cr:UserSignature>"
        f"<cr:EncryptionKey>{encrypted_rand}</cr:EncryptionKey>"
        "</cr:PinSign>"
    )
    # NOTE — AESGCMEncryptionKey is deliberately NOT emitted.
    #
    # The v1.0.14 formula table lists it, but it appears in no example CR ships:
    # not in the .docx signed sample, and not in any of the 13
    # verifyPinSigning_*.xml or 13 submit_*.xml files under
    # docs/Web Form Example/. Sending a tag CR's own examples never send is the
    # more likely way to be rejected. If a live verifyPinSigning fails with a
    # signature error, this is the first thing to revisit (Task 12 Step 9).
    #
    # There is no `id` attribute on PinSign either — CR's examples carry only
    # URI. `sign_id` is retained in the signature for the future NNC1 consent
    # flow, where each director tag needs its own S1/S2 identifier.

"""The TPSI PIN signature chain.

*** THE AUTHORITY HERE IS CR'S OWN REFERENCE PROGRAM, NOT THE APPENDIX. ***
`TPSI.html`, shipped as `word/embeddings/oleObject1.bin` inside
"TPSIT User Guideline v1.0.5.docx" (its Appendix 5.2), function
`createEFormSignatureV2`. The v1.0.14 API appendix disagrees with it in three
places, and CR's server implements the program. Verified live against CR TEST
on 2026-08-21: "Pin Signature(s) Verified Successfully."

    UserCredentialHash = BASE64( BASE64( AES256-ECB( username + random32
                                         + SHA256hex(password) ) ) )
                         key = random32          <- DOUBLE base64
    UserSignature      = BASE64( '{ciphertextBase64:"..",ivBase64:"..",
                                   gcmKeyBase64:".."}' )
                         AES-GCM over SHA256hex(EForm + UserCredentialHash),
                         random 12-byte IV       <- IV and key ride INSIDE
    EncryptionKey      = BASE64( RSA( random32 ) )
                         key = the public key of the <ds:X509Certificate> in
                         THIS validate response  <- NOT TPSI_CR_PUBLIC_KEY

There is no AESGCMEncryptionKey element. The appendix lists one; CR's program
emits three tags and the server accepts exactly those three.

`EForm` is the <cr:EForm> subtree as an XMLSerializer would emit it — i.e.
carrying the xmlns:cr declaration the browser adds because the prefix is used.

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
import re
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
    # DOUBLE base64, and not by accident. CR's reference program does
    #     encyptByBase64(encyptByAES256ECB(random32, userHash))
    # where encyptByAES256ECB returns CryptoJS's `encrypted.toString()`, which
    # is ALREADY base64 of the ciphertext; encyptByBase64 is btoa() on top.
    # CR's own shipped verifyPinSigning_NAR1.xml confirms it: the tag value
    # base64-decodes to 236 printable ASCII characters, which base64-decode
    # again to 176 bytes of AES output. Emitting a single layer is rejected.
    return base64.b64encode(
        base64.b64encode(ciphertext)
    ).decode()


def decrypt_credential_hash(credential_hash_b64: str, rand: str) -> str:
    """Inverse of user_credential_hash — used by tests to prove the chain."""
    raw = base64.b64decode(base64.b64decode(credential_hash_b64))
    decryptor = Cipher(algorithms.AES(_aes256_key(rand)), modes.ECB()).decryptor()
    return _pkcs7_unpad(decryptor.update(raw) + decryptor.finalize()).decode()


def user_signature(
    eform_xml: str,
    credential_hash_b64: str,
    gcm_key: bytes | None = None,
    nonce: bytes | None = None,
) -> str:
    """The <cr:UserSignature> value.

    Returns ONE base64 string. The AES-GCM ciphertext, the IV and the key are
    packed into a JSON-ish literal first and the whole literal is base64'd —
    see the block comment below and the module docstring.

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
    # THE IV AND THE KEY TRAVEL INSIDE THE VALUE. CR's encryptAESGCM builds the
    # literal string
    #     {ciphertextBase64:"..",ivBase64:"..",gcmKeyBase64:".."}
    # and createEFormSignatureV2 then btoa()s the whole thing into
    # <cr:UserSignature>. So the nonce is NOT prepended to the ciphertext, and
    # there is NO <cr:AESGCMEncryptionKey> element -- the v1.0.14 appendix lists
    # one, but CR's own reference program emits three tags, never four.
    # Byte-exact format: no spaces, keys unquoted, values double-quoted.
    blob = (
        '{ciphertextBase64:"' + base64.b64encode(ciphertext).decode()
        + '",ivBase64:"' + base64.b64encode(nonce).decode()
        + '",gcmKeyBase64:"' + base64.b64encode(key).decode() + '"}'
    )
    return base64.b64encode(blob.encode()).decode()


def encryption_key(rand: str, cr_public_key_pem: str) -> str:
    """BASE64( RSA( random32 ) ) using CR's public key."""
    key = load_pem_public_key(cr_public_key_pem.encode())
    return base64.b64encode(key.encrypt(rand.encode(), padding.PKCS1v15())).decode()


def signing_public_key_pem(validated_xml: str) -> str:
    """The RSA public key that <cr:EncryptionKey> must be encrypted to.

    IT IS NOT `TPSI_CR_PUBLIC_KEY`. CR's reference program calls
    verifyCrSignature(), which pulls <ds:X509Certificate> out of the signature
    CR put on THIS validate response, and encrypts random32 to that
    certificate's public key. TPSI_CR_PUBLIC_KEY is the *change-password* key
    (spec section 7.4) and is a different key entirely -- using it means CR
    cannot recover random32, cannot decrypt UserCredentialHash, and answers
    "Please note that the form data has been tampered."

    Reading it per-response also means a CR certificate rotation needs no
    redeploy: the right key arrives with the document it has to match.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    match = re.search(
        r"<(?:\w+:)?X509Certificate>(.*?)</(?:\w+:)?X509Certificate>",
        validated_xml, re.S,
    )
    if not match:
        raise ValueError(
            "no <ds:X509Certificate> in the validated payload; CR did not sign "
            "this response, so there is no key to encrypt the signature to"
        )
    der = base64.b64decode(re.sub(r"\s+", "", match.group(1)))
    public_key = x509.load_der_x509_certificate(der).public_key()
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


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
    signature = user_signature(eform_xml, credential_hash, gcm_key, nonce)
    encrypted_rand = encryption_key(rand, cr_public_key_pem)

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

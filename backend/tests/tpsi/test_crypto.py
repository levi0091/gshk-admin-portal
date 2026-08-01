import base64
import re

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from services.tpsi import crypto

EFORM = '<EForm id="eForm"><formModel id="formData"><formCode>NAR1</formCode></formModel></EForm>'
RAND = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"     # 32 chars, injected for determinism
GCM_KEY = b"\x01" * 32
# The AES-GCM nonce is a SEPARATE injection point from GCM_KEY (see
# crypto.user_signature's docstring) — a frozen regression vector must
# inject both explicitly, never rely on GCM_KEY alone implying a fixed
# nonce.
NONCE = bytes(range(1, 13))


@pytest.fixture(scope="module")
def pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        key,
        key.public_key().pem
        if hasattr(key.public_key(), "pem")
        else key.public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        ).decode(),
    )


def test_random32_is_32_alphanumeric_characters():
    value = crypto.random32()
    assert len(value) == 32
    assert re.fullmatch(r"[A-Za-z0-9]{32}", value)


def test_random32_is_not_repeatable():
    assert crypto.random32() != crypto.random32()


def test_credential_hash_is_base64_and_hides_the_password():
    out = crypto.user_credential_hash("USERID", "s3cret", RAND)
    base64.b64decode(out)                       # must decode cleanly
    assert "s3cret" not in out
    assert "USERID" not in out


def test_credential_hash_decrypts_back_to_username_rand_sha256_password():
    """Inverse test — the closest thing to a golden vector we can have without
    CR publishing a worked example with a plaintext password."""
    from services.tpsi.secrets import sha256_hex

    out = crypto.user_credential_hash("USERID", "s3cret", RAND)
    recovered = crypto.decrypt_credential_hash(out, RAND)
    assert recovered == "USERID" + RAND + sha256_hex("s3cret")


def test_credential_hash_is_deterministic_for_a_fixed_rand():
    a = crypto.user_credential_hash("U", "p", RAND)
    b = crypto.user_credential_hash("U", "p", RAND)
    assert a == b


def test_credential_hash_changes_with_rand():
    other = "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4"
    assert crypto.user_credential_hash("U", "p", RAND) != \
           crypto.user_credential_hash("U", "p", other)


def test_user_signature_signs_eform_plus_credential_hash():
    ch = crypto.user_credential_hash("U", "p", RAND)
    sig, key_b64 = crypto.user_signature(EFORM, ch, GCM_KEY)
    base64.b64decode(sig)
    base64.b64decode(key_b64)
    other, _ = crypto.user_signature(EFORM + "x", ch, GCM_KEY)
    assert sig != other       # changing the form changes the signature


def test_user_signature_changes_when_the_credential_hash_changes():
    ch1 = crypto.user_credential_hash("U", "p", RAND)
    ch2 = crypto.user_credential_hash("U", "different", RAND)
    a, _ = crypto.user_signature(EFORM, ch1, GCM_KEY)
    b, _ = crypto.user_signature(EFORM, ch2, GCM_KEY)
    assert a != b


def test_encryption_key_is_rsa_of_rand_and_decrypts_back(pem):
    private, public_pem = pem
    from cryptography.hazmat.primitives.asymmetric import padding

    enc = crypto.encryption_key(RAND, public_pem)
    recovered = private.decrypt(base64.b64decode(enc), padding.PKCS1v15())
    assert recovered.decode() == RAND


def test_pin_sign_block_matches_crs_shipped_example_exactly(pem):
    """Three cr:-prefixed children, no id attribute, no AESGCMEncryptionKey —
    the shape in docs/Web Form Example/pinSigning/verifyPinSigning_NAR1.xml."""
    _, public_pem = pem
    xml = crypto.build_pin_sign(
        EFORM, "USERID", "pw", public_pem, rand=RAND, gcm_key=GCM_KEY
    )
    for tag in ("cr:UserCredentialHash", "cr:UserSignature", "cr:EncryptionKey"):
        assert f"<{tag}>" in xml, f"missing {tag}"
    assert '<cr:PinSign URI="#eForm">' in xml
    assert "id=" not in xml
    assert "AESGCMEncryptionKey" not in xml


def test_pin_sign_child_order_matches_crs_example(pem):
    _, public_pem = pem
    xml = crypto.build_pin_sign(
        EFORM, "USERID", "pw", public_pem, rand=RAND, gcm_key=GCM_KEY
    )
    assert (xml.index("UserCredentialHash") < xml.index("UserSignature")
            < xml.index("EncryptionKey"))


def test_pin_sign_is_deterministic_when_randomness_is_injected(pem):
    """Frozen regression vector: our own, not CR's. Catches accidental changes
    to the chain.

    GCM_KEY and NONCE are injected together deliberately — the AES-GCM key
    and nonce are independent injection points (see user_signature's
    docstring), so determinism requires freezing both explicitly rather than
    relying on the key alone to imply a fixed nonce.
    """
    _, public_pem = pem
    a = crypto.build_pin_sign(EFORM, "U", "p", public_pem, rand=RAND, gcm_key=GCM_KEY, nonce=NONCE)
    b = crypto.build_pin_sign(EFORM, "U", "p", public_pem, rand=RAND, gcm_key=GCM_KEY, nonce=NONCE)
    # EncryptionKey uses PKCS1v15 padding, which is randomised — compare the
    # deterministic parts only. Tags are always cr:-prefixed (build_pin_sign
    # hardcodes the prefix), so the pattern must match on that, not the bare
    # local name.
    def part(xml, tag):
        return re.search(rf"<cr:{tag}>(.*?)</cr:{tag}>", xml).group(1)
    assert part(a, "UserCredentialHash") == part(b, "UserCredentialHash")
    assert part(a, "UserSignature") == part(b, "UserSignature")


def test_user_signature_nonce_is_never_derived_from_whether_the_key_was_injected():
    """Regression guard for the AES-GCM key/nonce coupling that used to
    exist: injecting gcm_key alone (with no explicit nonce=) must NEVER
    imply a fixed nonce. Two calls with the same injected key but no nonce=
    must produce different nonces — otherwise the future NNC1 per-director
    loop, which will call this once per director, could silently reuse a
    key+nonce pair, which is the textbook AES-GCM forgery failure."""
    ch = crypto.user_credential_hash("U", "p", RAND)
    sig_a, _ = crypto.user_signature(EFORM, ch, GCM_KEY)
    sig_b, _ = crypto.user_signature(EFORM, ch, GCM_KEY)
    nonce_a = base64.b64decode(sig_a)[:12]
    nonce_b = base64.b64decode(sig_b)[:12]
    assert nonce_a != nonce_b


def test_user_signature_is_deterministic_when_key_and_nonce_are_both_injected():
    """The other half of the guard above: explicit injection of BOTH still
    works, which is what the frozen build_pin_sign vector above relies on."""
    ch = crypto.user_credential_hash("U", "p", RAND)
    a, key_a = crypto.user_signature(EFORM, ch, GCM_KEY, nonce=NONCE)
    b, key_b = crypto.user_signature(EFORM, ch, GCM_KEY, nonce=NONCE)
    assert a == b
    assert key_a == key_b


def test_pin_sign_leaks_no_plaintext(pem):
    _, public_pem = pem
    xml = crypto.build_pin_sign(
        EFORM, "USERID", "s3cret", public_pem, rand=RAND, gcm_key=GCM_KEY
    )
    assert "s3cret" not in xml
    assert RAND not in xml


def test_consent_signature_targets_a_director_tag(pem):
    """NAR1 does not use consent signatures, but the layer must support the
    NNC1 shape without a rewrite: URI points at the director tag id."""
    _, public_pem = pem
    xml = crypto.build_pin_sign(
        '<cr:indDir id="S1"><cr:name>X</cr:name></cr:indDir>', "U", "p", public_pem,
        uri="#S1", sign_id="S1", rand=RAND, gcm_key=GCM_KEY,
    )
    assert '<cr:PinSign URI="#S1">' in xml

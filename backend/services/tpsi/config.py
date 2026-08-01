"""TPSI environment configuration.

TEST -> PROD is a config swap with zero code change (spec §9). Everything that
differs between environments — base URL, CR public key, TLS behaviour — is read
here and nowhere else.
"""
import os
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

# Form code -> (chargeable, fee in HKD).
#
# Code config, not env: a statutory fee change belongs in code review, not in a
# Railway variable someone can edit unobserved. Chargeable set is from the API
# spec §3 table. A chargeable form whose fee is None raises at lookup rather
# than letting the balance gate compare against zero.
FORM_FEES: dict[str, tuple[bool, Decimal | None]] = {
    # HK$105 — confirmed against CR's own compliance page, checked 2026-08-01:
    # https://www.cr.gov.hk/en/compliance/annual-return/private-company.htm
    # ("For a private company, an annual registration fee of HK$105 is payable
    # if the annual return is delivered within 42 days after the most recent
    # anniversary of the date of incorporation..."). The publications/fees.htm
    # URL in the original brief 404s; this compliance page is the current
    # source. Late filing attracts HK$870-HK$3,480; that path is out of scope
    # (spec §13).
    "Nar1":  (True,  Decimal("105.00")),
    "Nnc1":  (True,  None),               # R3 — fee recorded when NNC1 is built
    "Nnc1g": (True,  None),
    "Nnc2":  (True,  None),
    "Nn3":   (True,  None),
    "Nd2a":  (False, Decimal("0")),
    "Nd2b":  (False, Decimal("0")),
    "Nd4":   (False, Decimal("0")),
    "Nd5":   (False, Decimal("0")),
    "Nd7":   (False, Decimal("0")),
    "Nd8":   (False, Decimal("0")),
    "Nr1":   (False, Decimal("0")),
    "Nsc1":  (False, Decimal("0")),
}


@dataclass(frozen=True)
class TpsiConfig:
    env: str
    base_url: str
    tls_verify: bool
    cr_public_key_pem: str
    cred_key: bytes


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        # Name only — never the value; this message reaches logs.
        raise RuntimeError(f"{name} must be set for TPSI integration")
    return value


@lru_cache(maxsize=1)
def get_config() -> TpsiConfig:
    env = _require("TPSI_ENV")
    if env not in ("test", "prod"):
        raise RuntimeError("TPSI_ENV must be 'test' or 'prod'")

    verify = os.environ.get("TPSI_TLS_VERIFY", "true").lower() != "false"
    if env == "prod":
        # The TEST host uses a self-signed cert; production never does. Not a
        # setting anyone may switch off by editing an env var.
        verify = True

    key_path = _require("TPSI_CR_PUBLIC_KEY_PATH")
    with open(key_path, encoding="utf8") as fh:
        pem = fh.read()

    return TpsiConfig(
        env=env,
        base_url=_require("TPSI_BASE_URL").rstrip("/"),
        tls_verify=verify,
        cr_public_key_pem=pem,
        cred_key=_require("TPSI_CRED_KEY").encode(),
    )


def _fee_lookup(table, form_code: str) -> Decimal:
    chargeable, fee = table[form_code]
    if not chargeable:
        return Decimal("0")
    if fee is None:
        raise RuntimeError(
            f"{form_code} is chargeable but no fee is recorded — refusing to "
            "run a balance check against an unknown amount"
        )
    return fee


def fee_for(form_code: str) -> Decimal:
    return _fee_lookup(FORM_FEES, form_code)


def is_chargeable(form_code: str) -> bool:
    return FORM_FEES[form_code][0]

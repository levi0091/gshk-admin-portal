"""TPSI environment configuration.

TEST -> PROD is a config swap with zero code change (spec §9). Everything that
differs between environments — base URL, CR public key, TLS behaviour — is read
here and nowhere else.

The CR public key PEM is never committed to this repo (see the breadcrumb
comment above `_resolve_cr_public_key` for where it actually comes from and
why `TPSI_CR_PUBLIC_KEY_PATH` alone isn't enough on a fresh clone or CI).
"""
import os
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.serialization import load_pem_public_key

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
    # source. Late filing attracts HK$870-HK$3,480; COMPUTING which tier applies
    # is out of scope (spec §13) -- but see MAX_FEES below, because "we do not
    # compute it" and "we may check the balance as though it were HK$105" are
    # different statements, and only the first was intended.
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

#: THE MOST a form can cost, used ONLY to decide whether the deposit account
#: can cover it. Not displayed as "the fee" and never written to a filing row.
#:
#: WHY THIS EXISTS. `FORM_FEES` holds the ON-TIME fee. A NAR1 filed late is
#: charged more, and CR -- not this portal -- decides the tier. Checking
#: `balance >= 105` therefore green-lit filings the account could not actually
#: cover, and the operator was shown HK$105 for a charge that was not HK$105.
#:
#: Measured on the CR TEST environment, 2026-08-27: a private company's annual
#: return delivered ~7 months past its anniversary was billed **HK$2,610**
#: under revenue code 16, document code **NAR1L** -- the trailing "L" is CR's
#: own marker for a late form. Our pre-flight had quoted HK$105.
#:
#: HK$3,480 is the top of the published range on CR's compliance page (the
#: >9-months tier). Being conservative here costs a filing only when the
#: account is genuinely nearly empty; being optimistic costs a wasted, failed
#: submission attempt at CR.
MAX_FEES: dict[str, Decimal] = {
    "Nar1": Decimal("3480.00"),
}


def max_fee_for(form_code: str) -> Decimal:
    """The worst case for a sufficiency check. Falls back to the flat fee for
    forms with no late-filing tariff."""
    return MAX_FEES.get(form_code, fee_for(form_code))


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


def _validate_pem(pem: str, source_name: str) -> None:
    # A truncated or garbage key must fail here, at config load, not much
    # later inside signing — the worst place to discover it, since that path
    # runs mid-filing against a chargeable API. Never include the key content
    # or the underlying parser message in the error: a parse failure message
    # can echo back fragments of the bad input.
    try:
        load_pem_public_key(pem.encode())
    except Exception:
        # `from None` — suppress the original exception chain; the parser's
        # message can echo fragments of the bad input and must not surface.
        raise RuntimeError(
            f"{source_name} does not contain a valid PEM public key"
        ) from None


def _validate_cred_key(key: bytes) -> None:
    # Same shape as _validate_pem: a malformed or truncated Fernet key must
    # fail here, at config load, not deep inside the first encrypt/decrypt
    # call — which happens mid-request, during a credential save or a token
    # write, the worst place to discover it. Never include the key value or
    # the underlying exception message in the error: a malformed key is
    # still a secret.
    try:
        Fernet(key)
    except Exception:
        # `from None` — suppress the original exception chain; its message
        # can echo fragments of the bad key and must not surface.
        raise RuntimeError("TPSI_CRED_KEY is not a valid Fernet key") from None


def _resolve_cr_public_key() -> str:
    # Spec §9: the CR public key is an environment variable like BASE_URL and
    # TLS_VERIFY, so TEST -> PROD stays a config swap with zero code change.
    #
    # BREADCRUMB (read this if you're staring at one of the RuntimeErrors
    # below): the CR public key PEM is NOT in this repo. `*.pem` and `docs/`
    # are both gitignored repo-wide, so backend/docs/tpsi/*.pem exists only
    # on machines where someone placed it by hand — a fresh clone or CI
    # checkout will not have it. TPSI_CR_PUBLIC_KEY (inline PEM) is therefore
    # the real, deployed mechanism — Railway and CI set it directly — and is
    # resolved first, below. TPSI_CR_PUBLIC_KEY_PATH (a file on disk) is a
    # local-dev-only fallback for whoever already has the file, checked
    # second.
    #
    # Either way, the key value itself comes from spec §7.4 "For TPSIT"
    # (test) / "For TPSI Production" (prod) of
    # `docs/TPSI API Interface v1.0.14.docx` — never commit it anywhere.
    # TEST and PROD are different key values: the TEST key must never be
    # set when TPSI_ENV=prod.
    inline = os.environ.get("TPSI_CR_PUBLIC_KEY")
    if inline:
        # Railway's env UI mangles multi-line values into literal "\n"
        # escapes rather than real newlines — normalise both forms so a
        # pasted-in key doesn't silently fail PEM parsing on deploy.
        pem = inline.replace("\\n", "\n")
        _validate_pem(pem, "TPSI_CR_PUBLIC_KEY")
        return pem

    path = os.environ.get("TPSI_CR_PUBLIC_KEY_PATH")
    if path:
        try:
            with open(path, encoding="utf8") as fh:
                pem = fh.read()
        except OSError:
            # A path isn't a credential, but the underlying OSError message
            # embeds it — name only the variable, not the path or the OS
            # error text. `from None` suppresses the chained OSError too.
            raise RuntimeError(
                "TPSI_CR_PUBLIC_KEY_PATH is set but the file it points to "
                "could not be read"
            ) from None
        _validate_pem(pem, "TPSI_CR_PUBLIC_KEY_PATH")
        return pem

    # Name only — never key content; this message reaches logs.
    raise RuntimeError(
        "TPSI_CR_PUBLIC_KEY or TPSI_CR_PUBLIC_KEY_PATH must be set for TPSI "
        "integration"
    )


# CR's two hosts. Used only to catch a crossed configuration — see _check_env.
_TEST_HOST = "apitest.cr.gov.hk"
_PROD_HOST = "e-services.cr.gov.hk"

# Which TPSI environment each deployment gets when TPSI_ENV is not set. One
# variable per Railway service (APP_ENV) rather than two that can disagree.
_APP_ENV_DEFAULT_TPSI = {"dev": "test", "prod": "prod"}


def _resolve_env() -> str:
    """The TPSI environment, derived from the deployment unless overridden.

    Levi 2026-08-16: the DEV service should talk to TPSI test and PROD to TPSI
    prod, without anyone having to remember a second variable. So APP_ENV picks
    it. TPSI_ENV still wins when set explicitly — GSHK will want PROD running
    against TPSI test during the pilot, before they are ready to spend real
    money — but that has to be a deliberate act, never a default.
    """
    explicit = os.environ.get("TPSI_ENV")
    app_env = os.environ.get("APP_ENV", "").strip().lower()

    if explicit:
        env = explicit.strip().lower()
    elif app_env in _APP_ENV_DEFAULT_TPSI:
        env = _APP_ENV_DEFAULT_TPSI[app_env]
    else:
        raise RuntimeError(
            "APP_ENV must be 'dev' or 'prod' (or set TPSI_ENV explicitly) "
            "for TPSI integration"
        )

    if env not in ("test", "prod"):
        raise RuntimeError("TPSI_ENV must be 'test' or 'prod'")

    # A dev deployment must never be able to file for real. This is the one
    # combination with no legitimate use: submitFormNar1 is chargeable and
    # irreversible, so a stray prod credential on the dev service would spend
    # GSHK's deposit against live CR.
    if app_env == "dev" and env == "prod":
        raise RuntimeError(
            "APP_ENV=dev cannot run TPSI_ENV=prod — a dev deployment must not "
            "file against live CR"
        )
    return env


def _check_env_matches_host(env: str, base_url: str) -> None:
    """Refuse a crossed environment/host pair.

    The dangerous direction is TPSI_ENV=test pointing at the PRODUCTION host:
    the app relaxes TLS, labels itself TEST in the UI, and files real,
    chargeable returns anyway. The reverse wastes a filing window rather than
    money, but is just as much a misconfiguration. An unrecognised host (a
    future CR endpoint, a local stub) is left alone — this catches the mistake
    that actually happens, which is copying one service's variables into the
    other.
    """
    host = base_url.lower()
    if env == "test" and _PROD_HOST in host:
        raise RuntimeError(
            "TPSI_ENV=test but TPSI_BASE_URL points at the CR PRODUCTION host — "
            "refusing to file real returns from a test configuration"
        )
    if env == "prod" and _TEST_HOST in host:
        raise RuntimeError(
            "TPSI_ENV=prod but TPSI_BASE_URL points at the CR TEST host"
        )


@lru_cache(maxsize=1)
def get_config() -> TpsiConfig:
    env = _resolve_env()

    verify = os.environ.get("TPSI_TLS_VERIFY", "true").lower() != "false"
    if env == "prod":
        # The TEST host uses a self-signed cert; production never does. Not a
        # setting anyone may switch off by editing an env var.
        verify = True

    pem = _resolve_cr_public_key()

    cred_key = _require("TPSI_CRED_KEY").encode()
    _validate_cred_key(cred_key)

    base_url = _require("TPSI_BASE_URL").rstrip("/")
    _check_env_matches_host(env, base_url)

    return TpsiConfig(
        env=env,
        base_url=base_url,
        tls_verify=verify,
        cr_public_key_pem=pem,
        cred_key=cred_key,
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

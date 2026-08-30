from decimal import Decimal

import pytest
from cryptography.fernet import Fernet

from services.tpsi import config as cfg


@pytest.fixture(autouse=True)
def _clear_cache():
    cfg.get_config.cache_clear()
    yield
    cfg.get_config.cache_clear()


def test_loads_from_env(monkeypatch, tmp_path, make_pem):
    key = tmp_path / "k.pem"
    key.write_text(make_pem())
    monkeypatch.setenv("TPSI_ENV", "test")
    monkeypatch.setenv("TPSI_BASE_URL", "https://apitest.cr.gov.hk/ICRIS3EF")
    monkeypatch.setenv("TPSI_TLS_VERIFY", "false")
    monkeypatch.setenv("TPSI_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("TPSI_CR_PUBLIC_KEY_PATH", str(key))

    c = cfg.get_config()
    assert c.env == "test"
    assert c.tls_verify is False
    assert c.base_url == "https://apitest.cr.gov.hk/ICRIS3EF"
    assert "BEGIN PUBLIC KEY" in c.cr_public_key_pem


def test_missing_var_raises_without_printing_value(monkeypatch):
    monkeypatch.delenv("TPSI_BASE_URL", raising=False)
    monkeypatch.setenv("TPSI_ENV", "test")
    with pytest.raises(RuntimeError) as exc:
        cfg.get_config()
    assert "TPSI_BASE_URL" in str(exc.value)


def test_prod_env_forces_tls_verify(monkeypatch, tmp_path, make_pem):
    """TLS verification must not be disableable in prod, whatever the env says."""
    key = tmp_path / "k.pem"
    key.write_text(make_pem())
    # APP_ENV too: a dev deployment is not allowed to run TPSI prod at all.
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("TPSI_ENV", "prod")
    monkeypatch.setenv("TPSI_BASE_URL", "https://www.e-services.cr.gov.hk/ICRIS3EF")
    monkeypatch.setenv("TPSI_TLS_VERIFY", "false")
    monkeypatch.setenv("TPSI_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("TPSI_CR_PUBLIC_KEY_PATH", str(key))
    assert cfg.get_config().tls_verify is True


def test_inline_key_takes_precedence_over_path(monkeypatch, tmp_path, make_pem):
    """TPSI_CR_PUBLIC_KEY (spec §9 env var) wins over the local-dev file path
    when both are set."""
    path_pem = make_pem()
    inline_pem = make_pem()
    key = tmp_path / "k.pem"
    key.write_text(path_pem)
    monkeypatch.setenv("TPSI_ENV", "test")
    monkeypatch.setenv("TPSI_BASE_URL", "https://apitest.cr.gov.hk/ICRIS3EF")
    monkeypatch.setenv("TPSI_TLS_VERIFY", "false")
    monkeypatch.setenv("TPSI_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("TPSI_CR_PUBLIC_KEY_PATH", str(key))
    monkeypatch.setenv("TPSI_CR_PUBLIC_KEY", inline_pem)

    c = cfg.get_config()
    assert c.cr_public_key_pem == inline_pem
    assert c.cr_public_key_pem != path_pem


def test_inline_key_normalises_literal_newline_escapes(monkeypatch, make_pem):
    """Railway's env UI mangles multi-line values into literal backslash-n
    escapes rather than real newlines — this must not break PEM parsing."""
    real_pem = make_pem()
    mangled = real_pem.replace("\n", "\\n")
    monkeypatch.setenv("TPSI_ENV", "test")
    monkeypatch.setenv("TPSI_BASE_URL", "https://apitest.cr.gov.hk/ICRIS3EF")
    monkeypatch.setenv("TPSI_TLS_VERIFY", "false")
    monkeypatch.setenv("TPSI_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("TPSI_CR_PUBLIC_KEY_PATH", raising=False)
    monkeypatch.setenv("TPSI_CR_PUBLIC_KEY", mangled)

    c = cfg.get_config()
    assert c.cr_public_key_pem == real_pem
    assert c.cr_public_key_pem.startswith("-----BEGIN PUBLIC KEY-----\n")
    assert "\\n" not in c.cr_public_key_pem


def test_malformed_inline_key_raises(monkeypatch):
    """A truncated/garbage key must fail at config load, not mid-signing."""
    monkeypatch.setenv("TPSI_ENV", "test")
    monkeypatch.setenv("TPSI_BASE_URL", "https://apitest.cr.gov.hk/ICRIS3EF")
    monkeypatch.setenv("TPSI_TLS_VERIFY", "false")
    monkeypatch.setenv("TPSI_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("TPSI_CR_PUBLIC_KEY_PATH", raising=False)
    monkeypatch.setenv(
        "TPSI_CR_PUBLIC_KEY",
        "-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n",
    )

    with pytest.raises(RuntimeError) as exc:
        cfg.get_config()
    assert "TPSI_CR_PUBLIC_KEY" in str(exc.value)


def test_malformed_cred_key_raises(monkeypatch, tmp_path, make_pem):
    """A garbage TPSI_CRED_KEY must fail at config load, not on the first
    encrypt/decrypt call deep inside a credential save or token write."""
    key = tmp_path / "k.pem"
    key.write_text(make_pem())
    monkeypatch.setenv("TPSI_ENV", "test")
    monkeypatch.setenv("TPSI_BASE_URL", "https://apitest.cr.gov.hk/ICRIS3EF")
    monkeypatch.setenv("TPSI_TLS_VERIFY", "false")
    monkeypatch.setenv("TPSI_CRED_KEY", "not-a-valid-fernet-key")
    monkeypatch.setenv("TPSI_CR_PUBLIC_KEY_PATH", str(key))

    with pytest.raises(RuntimeError) as exc:
        cfg.get_config()
    assert "TPSI_CRED_KEY" in str(exc.value)


def test_missing_both_key_vars_raises_mentioning_both_names(monkeypatch):
    monkeypatch.setenv("TPSI_ENV", "test")
    monkeypatch.setenv("TPSI_BASE_URL", "https://apitest.cr.gov.hk/ICRIS3EF")
    monkeypatch.setenv("TPSI_TLS_VERIFY", "false")
    monkeypatch.setenv("TPSI_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("TPSI_CR_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("TPSI_CR_PUBLIC_KEY_PATH", raising=False)

    with pytest.raises(RuntimeError) as exc:
        cfg.get_config()
    assert "TPSI_CR_PUBLIC_KEY" in str(exc.value)
    assert "TPSI_CR_PUBLIC_KEY_PATH" in str(exc.value)


def test_nar1_is_chargeable_with_a_recorded_fee():
    assert cfg.is_chargeable("Nar1") is True
    assert cfg.fee_for("Nar1") > Decimal("0")


def test_free_form_has_zero_fee():
    assert cfg.is_chargeable("Nr1") is False
    assert cfg.fee_for("Nr1") == Decimal("0")


def test_chargeable_without_recorded_fee_raises():
    """A chargeable form with no fee must never silently compare against zero."""
    with pytest.raises(RuntimeError):
        cfg._fee_lookup({"Xxx1": (True, None)}, "Xxx1")


def test_unknown_form_raises():
    with pytest.raises(KeyError):
        cfg.fee_for("Zzz9")


# ---- APP_ENV drives TPSI_ENV; crossed configurations are refused -------------

def test_dev_deployment_defaults_to_the_tpsi_test_environment(monkeypatch):
    monkeypatch.delenv("TPSI_ENV", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    assert cfg.get_config().env == "test"


def test_prod_deployment_defaults_to_the_tpsi_prod_environment(monkeypatch):
    monkeypatch.delenv("TPSI_ENV", raising=False)
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("TPSI_BASE_URL", "https://www.e-services.cr.gov.hk/ICRIS3EF")
    assert cfg.get_config().env == "prod"


def test_prod_deployment_may_be_pinned_to_tpsi_test_during_the_pilot(monkeypatch):
    """Explicit beats derived — GSHK runs PROD against TPSI test before go-live."""
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("TPSI_ENV", "test")
    assert cfg.get_config().env == "test"


def test_dev_deployment_cannot_be_pointed_at_tpsi_prod(monkeypatch):
    """The one combination with no legitimate use — it spends real money."""
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("TPSI_ENV", "prod")
    with pytest.raises(RuntimeError) as exc:
        cfg.get_config()
    assert "must not file against live CR" in str(exc.value)


def test_no_app_env_and_no_tpsi_env_fails_closed(monkeypatch):
    monkeypatch.delenv("TPSI_ENV", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    with pytest.raises(RuntimeError) as exc:
        cfg.get_config()
    assert "APP_ENV" in str(exc.value)


def test_test_env_pointing_at_the_production_host_is_refused(monkeypatch):
    """The dangerous crossing: relaxed TLS, TEST badges, real chargeable filings."""
    monkeypatch.setenv("TPSI_ENV", "test")
    monkeypatch.setenv("TPSI_BASE_URL", "https://www.e-services.cr.gov.hk/ICRIS3EF")
    with pytest.raises(RuntimeError) as exc:
        cfg.get_config()
    assert "PRODUCTION host" in str(exc.value)


def test_prod_env_pointing_at_the_test_host_is_refused(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("TPSI_ENV", "prod")
    monkeypatch.setenv("TPSI_BASE_URL", "https://apitest.cr.gov.hk/ICRIS3EF")
    with pytest.raises(RuntimeError) as exc:
        cfg.get_config()
    assert "CR TEST host" in str(exc.value)


def test_an_unrecognised_host_is_not_second_guessed(monkeypatch):
    """A local stub or a future CR endpoint must still be usable."""
    monkeypatch.setenv("TPSI_ENV", "test")
    monkeypatch.setenv("TPSI_BASE_URL", "http://localhost:8081/ICRIS3EF")
    assert cfg.get_config().base_url == "http://localhost:8081/ICRIS3EF"

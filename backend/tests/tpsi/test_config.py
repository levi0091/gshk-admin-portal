import os
from decimal import Decimal

import pytest

from services.tpsi import config as cfg


@pytest.fixture(autouse=True)
def _clear_cache():
    cfg.get_config.cache_clear()
    yield
    cfg.get_config.cache_clear()


def test_loads_from_env(monkeypatch, tmp_path):
    key = tmp_path / "k.pem"
    key.write_text("-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n")
    monkeypatch.setenv("TPSI_ENV", "test")
    monkeypatch.setenv("TPSI_BASE_URL", "https://apitest.cr.gov.hk/ICRIS3EF")
    monkeypatch.setenv("TPSI_TLS_VERIFY", "false")
    monkeypatch.setenv("TPSI_CRED_KEY", "x" * 44)
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


def test_prod_env_forces_tls_verify(monkeypatch, tmp_path):
    """TLS verification must not be disableable in prod, whatever the env says."""
    key = tmp_path / "k.pem"
    key.write_text("-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n")
    monkeypatch.setenv("TPSI_ENV", "prod")
    monkeypatch.setenv("TPSI_BASE_URL", "https://www.e-services.cr.gov.hk/ICRIS3EF")
    monkeypatch.setenv("TPSI_TLS_VERIFY", "false")
    monkeypatch.setenv("TPSI_CRED_KEY", "x" * 44)
    monkeypatch.setenv("TPSI_CR_PUBLIC_KEY_PATH", str(key))
    assert cfg.get_config().tls_verify is True


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

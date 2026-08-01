"""The seed script's PROD guard.

This script exists as a script rather than a migration precisely because
migrations run in every environment. The guard is the whole reason for that
choice, so it gets tested.
"""
import importlib
import os
import sys

import pytest
from cryptography.fernet import Fernet

from services.tpsi import config as cfg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path, make_pem):
    key = tmp_path / "k.pem"
    key.write_text(make_pem())
    monkeypatch.setenv("TPSI_BASE_URL", "https://apitest.cr.gov.hk/ICRIS3EF")
    monkeypatch.setenv("TPSI_TLS_VERIFY", "false")
    monkeypatch.setenv("TPSI_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("TPSI_CR_PUBLIC_KEY_PATH", str(key))
    monkeypatch.delenv("TPSI_CR_PUBLIC_KEY", raising=False)
    cfg.get_config.cache_clear()
    yield
    cfg.get_config.cache_clear()


def _seed_module():
    return importlib.import_module("scripts.seed_tpsi_test_data")


def test_refuses_to_run_against_prod_tpsi_env(monkeypatch):
    monkeypatch.setenv("TPSI_ENV", "prod")
    monkeypatch.setenv("TPSI_BASE_URL", "https://www.e-services.cr.gov.hk/ICRIS3EF")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@db.dev.supabase.co/postgres")
    cfg.get_config.cache_clear()
    with pytest.raises(SystemExit):
        _seed_module().assert_safe_environment()


def test_refuses_a_production_looking_database_url(monkeypatch):
    """TPSI_ENV and DATABASE_URL are independent: a deploy can point at the CR
    test environment while writing to the production database."""
    monkeypatch.setenv("TPSI_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@db.prod-gflowdesk.supabase.co/postgres")
    cfg.get_config.cache_clear()
    with pytest.raises(SystemExit):
        _seed_module().assert_safe_environment()


def test_allows_test_env_with_a_dev_database(monkeypatch):
    monkeypatch.setenv("TPSI_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@db.dev-gflowdesk.supabase.co/postgres")
    cfg.get_config.cache_clear()
    _seed_module().assert_safe_environment()  # must not raise


def test_date_conversion_handles_crs_dd_mm_yyyy(monkeypatch):
    monkeypatch.setenv("TPSI_ENV", "test")
    cfg.get_config.cache_clear()
    seed = _seed_module()
    assert seed._date("01/01/2022") == "2022-01-01"
    assert seed._date("5/9/2024") == "2024-09-05"
    assert seed._date("") is None
    assert seed._date("not a date") is None


def test_capacity_maps_to_the_officer_role_enum(monkeypatch):
    monkeypatch.setenv("TPSI_ENV", "test")
    cfg.get_config.cache_clear()
    role = _seed_module()._ROLE
    assert role["director"] == "director"
    assert role["company secretary"] == "company_secretary"
    assert role["reserve director"] == "reserve_director"

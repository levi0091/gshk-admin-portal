"""One definition of "is this production", shared by every caller.

Before this module there were two independent readings of APP_ENV — one in
`email_service`, one in `tpsi.config` — and a third was about to be written for
the header badge. Three copies of a rule whose failure mode is "mail a real
client from a test deployment" is two copies too many.
"""
import os
from unittest.mock import patch

import pytest

from services import app_env


@pytest.fixture(autouse=True)
def _clear():
    app_env.is_production.cache_clear()
    yield
    app_env.is_production.cache_clear()


@pytest.mark.parametrize("value", ["prod", "PROD", " prod ", "Prod"])
def test_prod_in_any_casing_or_padding_is_production(value):
    with patch.dict(os.environ, {"APP_ENV": value}):
        assert app_env.is_production() is True


@pytest.mark.parametrize("value", ["dev", "DEV", "staging", "test", "", "   "])
def test_anything_else_is_not_production(value):
    with patch.dict(os.environ, {"APP_ENV": value}):
        assert app_env.is_production() is False


def test_unset_app_env_is_not_production():
    """The load-bearing default. A missing variable must never be read as a
    licence to mail real clients or file real returns — an unconfigured
    deployment is a test deployment until it says otherwise."""
    env = {k: v for k, v in os.environ.items() if k != "APP_ENV"}
    with patch.dict(os.environ, env, clear=True):
        assert app_env.is_production() is False


def test_is_cached_so_the_value_cannot_change_under_a_request():
    with patch.dict(os.environ, {"APP_ENV": "prod"}):
        assert app_env.is_production() is True
    with patch.dict(os.environ, {"APP_ENV": "dev"}):
        # Still True: the cache is deliberate, and cache_clear() is the only
        # way to pick up a change. A deployment does not change environment
        # halfway through its life, and a value that could flip mid-process
        # would make every interlock built on it racy.
        assert app_env.is_production() is True

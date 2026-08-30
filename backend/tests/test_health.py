"""GET /health — and the environment it reports.

The environment field exists because APP_ENV is invisible from outside Railway,
and one wrong value silently disarms the non-production mail lock. That is not
hypothetical: on 2026-08-30 the DEV service was running with APP_ENV=prod, and
the only visible symptom was a TEST badge that never appeared in the header.

These tests pin the two things that make the field worth having: that it is the
SAME reading the mail lock uses, and that it never leaks the raw value or
anything else about the configuration.
"""
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services import app_env


@pytest.fixture(autouse=True)
def _clear_env_cache():
    app_env.is_production.cache_clear()
    yield
    app_env.is_production.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


def _env(value):
    """A clean environment with APP_ENV set (or removed, for None)."""
    keep = {k: v for k, v in os.environ.items() if k != "APP_ENV"}
    if value is not None:
        keep["APP_ENV"] = value
    return patch.dict(os.environ, keep, clear=True)


def test_health_still_answers_ok(client):
    with _env("dev"):
        body = client.get("/health").json()
    assert body["status"] == "ok"


def test_a_production_deployment_says_so(client):
    with _env("prod"):
        assert client.get("/health").json()["environment"] == "production"


@pytest.mark.parametrize("value", ["dev", "staging", "test", "PRODUCTION", None])
def test_everything_else_reports_non_production(client, value):
    """Same rule as the mail lock: only exactly 'prod' is production, and an
    UNSET APP_ENV is not. 'PRODUCTION' is in this list deliberately."""
    with _env(value):
        assert client.get("/health").json()["environment"] == "non-production"


def test_health_agrees_with_the_reading_the_mail_lock_uses(client):
    """The whole point. If these could disagree, the field would be a second
    opinion rather than a window onto the one that matters."""
    for value in ("prod", "dev", None):
        app_env.is_production.cache_clear()
        with _env(value):
            reported = client.get("/health").json()["environment"]
            assert (reported == "production") is app_env.is_production()


def test_health_leaks_nothing_but_the_derived_answer(client):
    """It is unauthenticated. It may say which interlock is running; it may not
    hand out the configuration."""
    with _env("prod"):
        body = client.get("/health").json()
    assert set(body) == {"status", "environment"}
    assert "APP_ENV" not in str(body)

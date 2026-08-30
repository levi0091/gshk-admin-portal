import pytest

from middleware.auth import clear_auth_cache
from services import app_env


@pytest.fixture(autouse=True)
def _reset_auth_cache():
    """require_permission caches the resolved caller for 30s, keyed by bearer
    token. Every test uses the same dummy token, so without this the identity
    from one test leaks into the next."""
    clear_auth_cache()
    yield
    clear_auth_cache()


@pytest.fixture(autouse=True)
def _reset_app_env_cache():
    """`is_production()` is cached for the life of the process, which is right
    for a deployment and wrong for a test suite: one test setting APP_ENV=prod
    would otherwise make every later test think it was production — including
    the mail interlock tests, which would then stop redirecting."""
    app_env.is_production.cache_clear()
    yield
    app_env.is_production.cache_clear()

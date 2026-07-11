import pytest

from middleware.auth import clear_auth_cache


@pytest.fixture(autouse=True)
def _reset_auth_cache():
    """require_permission caches the resolved caller for 30s, keyed by bearer
    token. Every test uses the same dummy token, so without this the identity
    from one test leaks into the next."""
    clear_auth_cache()
    yield
    clear_auth_cache()

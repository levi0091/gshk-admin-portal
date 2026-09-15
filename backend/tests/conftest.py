from unittest.mock import patch

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


@pytest.fixture(autouse=True)
def _no_dns_in_tests():
    """No test resolves a real domain name.

    `email_service.undeliverable_reason` asks DNS whether a domain can receive
    mail, which the verification send now does for every recipient. Left live
    in the suite that would be two separate faults:

      * A NETWORK CALL IN A UNIT TEST. It would be slow, it would fail on an
        offline machine, and — exactly like the five TPSI tests that were
        DELETEing from live DEV — it would pass for a reason that has nothing
        to do with the code under test.

      * WRONG ANSWERS. Nearly every fixture address in this suite is at
        example.com, which is IANA-reserved and publishes a Null MX: it is
        genuinely undeliverable, so the real probe would drop those recipients
        and dozens of unrelated assertions would fail on a correct
        implementation.

    Patched at the module attribute `routers.cases` reads through, so a test
    that WANTS a failure re-patches the same name (see
    test_cases_verification.py's undeliverable tests). Returning None means
    "nothing known against this address", which is the same answer the real
    probe gives for every uncertain case.
    """
    with patch("services.email_service.undeliverable_reason",
               return_value=None):
        yield

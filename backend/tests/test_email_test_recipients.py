"""The test-environment mail interlock (Levi 2026-08-30).

THE REQUIREMENT, in Levi's words: "make sure that client doesnt ever receive
any email from test environment.. it is programatically impossible for a client
to receive an email from a test account."

So the redirect is NOT configuration. `EMAIL_REDIRECT_TO` — which could be
unset, misspelt, or pointed at a client by an accident of deployment — is gone,
replaced by a frozen constant in the module. There is no environment variable,
request field, or caller argument that puts a client address on a non-production
send. These tests are the proof of that claim, so they probe the routes someone
would actually take to break it rather than only the happy path.

The Client Verification screen still shows, and still lets an operator pick, the
real director addresses: that fan-out is the thing under test. What changes is
where the message lands.
"""
import os
from unittest.mock import patch

import pytest

from services import app_env, email_service


CLIENT = "director@a-real-client.com.hk"
OTHER_CLIENT = "second.director@a-real-client.com.hk"


@pytest.fixture(autouse=True)
def _clear_caches():
    email_service.get_email_config.cache_clear()
    app_env.is_production.cache_clear()
    yield
    email_service.get_email_config.cache_clear()
    app_env.is_production.cache_clear()


def _env(**overrides):
    """A clean environment: every mail variable removed, then `overrides`."""
    keep = {
        k: v for k, v in os.environ.items()
        if k not in ("APP_ENV", "EMAIL_TRANSPORT", "RESEND_API_KEY",
                     "EMAIL_REDIRECT_TO", "VERIFICATION_FROM")
    }
    keep.update({k: v for k, v in overrides.items() if v is not None})
    return patch.dict(os.environ, keep, clear=True)


class _Response:
    status_code = 200

    @staticmethod
    def json():
        return {"id": "msg-1"}


def _send_capturing_payload(**env):
    """Send to two real client addresses; return (result, resend_payload)."""
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(json)
        return _Response()

    with _env(**env), patch("httpx.post", side_effect=fake_post):
        result = email_service.send(
            to=[CLIENT, OTHER_CLIENT], subject="Annual Return", html="<p>hi</p>"
        )
    return result, captured


# ---------------------------------------------------------------------------
# The guarantee
# ---------------------------------------------------------------------------

def test_the_four_addresses_are_the_hardcoded_list_levi_gave():
    assert email_service.TEST_RECIPIENTS == (
        "levi@zenexflow.com",
        "roy@zenexflow.com",
        "brian@getstarted.hk",
        "vanis@getstarted.hk",
    )


def test_a_non_production_send_goes_to_the_four_and_not_the_client():
    result, payload = _send_capturing_payload(APP_ENV="dev", RESEND_API_KEY="re_x")
    assert payload["to"] == list(email_service.TEST_RECIPIENTS)
    assert CLIENT not in payload["to"]
    assert OTHER_CLIENT not in payload["to"]
    assert result["redirected"] is True


def test_the_real_recipients_are_still_reported_so_the_audit_trail_stays_honest():
    """`intended_to` is what the router writes into the audit row. A redirect
    that forgot the real list would make the trail claim nobody was targeted."""
    result, _ = _send_capturing_payload(APP_ENV="dev", RESEND_API_KEY="re_x")
    assert result["intended_to"] == [CLIENT, OTHER_CLIENT]
    assert result["to"] == list(email_service.TEST_RECIPIENTS)


def test_an_unset_app_env_still_redirects():
    """The most likely misconfiguration there is: a service deployed with no
    APP_ENV at all. It must behave as test, not as production."""
    _, payload = _send_capturing_payload(APP_ENV=None, RESEND_API_KEY="re_x")
    assert payload["to"] == list(email_service.TEST_RECIPIENTS)


@pytest.mark.parametrize("value", ["staging", "test", "development", "PRODUCTION"])
def test_anything_that_is_not_exactly_prod_redirects(value):
    """'PRODUCTION' is in this list deliberately — it is not 'prod', so it is
    not production, and it redirects. Erring that way costs a suppressed email;
    erring the other way mails a client from a test box."""
    _, payload = _send_capturing_payload(APP_ENV=value, RESEND_API_KEY="re_x")
    assert payload["to"] == list(email_service.TEST_RECIPIENTS)


def test_email_redirect_to_can_no_longer_point_mail_anywhere():
    """The variable is gone. If someone re-adds it to a Railway service hoping
    to steer non-production mail, it must do nothing rather than silently win."""
    _, payload = _send_capturing_payload(
        APP_ENV="dev", RESEND_API_KEY="re_x", EMAIL_REDIRECT_TO=CLIENT
    )
    assert payload["to"] == list(email_service.TEST_RECIPIENTS)


def test_a_non_production_deployment_can_send_without_any_extra_configuration():
    """Before this change, non-production REFUSED to send unless
    EMAIL_REDIRECT_TO was set. With a safe destination compiled in there is
    nothing left to configure, so the refusal is gone."""
    with _env(APP_ENV="dev", RESEND_API_KEY="re_x"):
        config = email_service.get_email_config()
    assert config.is_production is False


def test_production_still_reaches_the_real_client():
    """The interlock must not leak into production — that failure mode is
    every client silently receiving nothing."""
    _, payload = _send_capturing_payload(APP_ENV="prod", RESEND_API_KEY="re_x")
    assert payload["to"] == [CLIENT, OTHER_CLIENT]


def test_the_redirected_message_names_who_it_was_really_for():
    """Four people share these mailboxes across many test cases. A message that
    does not say which directors it was standing in for is untestable noise."""
    _, payload = _send_capturing_payload(APP_ENV="dev", RESEND_API_KEY="re_x")
    assert CLIENT in payload["subject"] and OTHER_CLIENT in payload["subject"]
    assert CLIENT in payload["html"]


def test_the_console_transport_is_gone_and_asking_for_it_fails():
    """It used to be the strongest guarantee here — no HTTP call, so no address
    to get wrong. It was removed once Resend worked, and the risk of removing it
    is that a deployment still asking for silence starts mailing for real. It
    raises instead."""
    with _env(APP_ENV="dev", EMAIL_TRANSPORT="console", RESEND_API_KEY="re_x"), \
            patch("httpx.post", side_effect=AssertionError("must not be called")):
        with pytest.raises(RuntimeError, match="EMAIL_TRANSPORT"):
            email_service.send(to=[CLIENT], subject="s", html="<p>h</p>")


def test_the_guard_fires_even_if_the_redirect_is_somehow_bypassed():
    """Defence in depth. The redirect above is the mechanism; this is the
    assertion that the mechanism ran. If a future edit reorders `send()` so a
    client address survives to the payload on a non-production deployment, this
    raises instead of delivering."""
    with _env(APP_ENV="dev", RESEND_API_KEY="re_x"), \
            patch.object(email_service, "_apply_test_recipient_lock",
                         side_effect=lambda recipients, *_: (recipients, False)), \
            patch("httpx.post", side_effect=AssertionError("must not be called")):
        with pytest.raises(email_service.EmailError, match="refusing to send"):
            email_service.send(to=[CLIENT], subject="s", html="<p>h</p>")

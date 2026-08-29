"""services/email_service.py — the Resend transport (BE-3).

Resend's HTTP API over httpx rather than the `resend` package: httpx is already
a dependency, the request shape stays visible in review, and this repo already
made the same call for Supabase (the Python client rejected the new key format).

*** THE LIVE-KEY TRAP ***
`backend/.env` holds a LIVE RESEND_API_KEY and `main.py` calls `load_dotenv()`,
so importing anything that imports `main` puts the real key into `os.environ`
before a single test runs. A test that forgot to override it AND forgot to patch
the transport would post to Resend for real, from the client's account. So the
autouse fixture below does both: a dummy key, and a `post` that raises if it is
ever reached without an explicit patch.
"""
import base64
from unittest.mock import MagicMock, patch

import pytest

from services import email_service


def _refuse(*args, **kwargs):
    raise AssertionError(
        "a test reached the real httpx.post — RESEND_API_KEY in backend/.env "
        "is a live key and this would have sent mail from GSHK's account"
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    # PROD-shaped by default: that is the configuration the send path is really
    # about. The non-prod guard gets its own tests below.
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("EMAIL_REDIRECT_TO", raising=False)
    monkeypatch.delenv("VERIFICATION_FROM", raising=False)
    # A developer .env that stubs mail out would otherwise make every send test
    # in this file return before httpx is reached — green, and proving nothing.
    monkeypatch.delenv("EMAIL_TRANSPORT", raising=False)
    monkeypatch.setattr(email_service.httpx, "post", _refuse)
    email_service.get_email_config.cache_clear()
    yield
    email_service.get_email_config.cache_clear()


def _response(status=200, payload=None):
    r = MagicMock(status_code=status)
    r.json.return_value = payload if payload is not None else {"id": "msg_1"}
    r.text = str(payload or "")
    return r


def _post(response=None):
    return patch("services.email_service.httpx.post",
                 return_value=response or _response())


# ---------------------------------------------------------------------------
# The request Resend actually receives
# ---------------------------------------------------------------------------


def test_sends_from_the_gshk_controlled_domain():
    """no-reply@getstarted.hk. SPF/DKIM only align on a domain the sender
    controls, so the sender address is not a cosmetic choice — a free-mail
    address here would fail alignment and land in spam."""
    with _post() as post:
        email_service.send(to="client@example.com", subject="S", html="<p>H</p>")
    assert post.call_args.kwargs["json"]["from"] == "no-reply@getstarted.hk"


def test_the_sender_can_be_overridden_by_configuration(monkeypatch):
    monkeypatch.setenv("VERIFICATION_FROM", "returns@getstarted.hk")
    email_service.get_email_config.cache_clear()
    with _post() as post:
        email_service.send(to="client@example.com", subject="S", html="<p>H</p>")
    assert post.call_args.kwargs["json"]["from"] == "returns@getstarted.hk"


def test_authenticates_with_the_resend_key():
    with _post() as post:
        email_service.send(to="client@example.com", subject="S", html="<p>H</p>")
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer re_test_key"


def test_the_recipient_subject_and_body_travel_as_given():
    with _post() as post:
        email_service.send(to="client@example.com", subject="Confirm",
                           html="<p>Body</p>")
    payload = post.call_args.kwargs["json"]
    assert payload["to"] == ["client@example.com"]
    assert payload["subject"] == "Confirm"
    assert payload["html"] == "<p>Body</p>"


def test_the_call_is_bounded_by_a_timeout():
    """No timeout means a hung Resend hangs the request thread holding the case,
    and the admin never learns whether the client was mailed."""
    with _post() as post:
        email_service.send(to="c@example.com", subject="S", html="<p>H</p>")
    assert post.call_args.kwargs["timeout"] > 0


def test_the_api_key_never_appears_in_the_returned_payload():
    with _post():
        result = email_service.send(to="c@example.com", subject="S", html="<p>H</p>")
    assert "re_test_key" not in str(result)


def test_the_result_reports_the_message_id_and_the_delivered_address():
    with _post():
        result = email_service.send(to="c@example.com", subject="S", html="<p>H</p>")
    assert result["id"] == "msg_1"
    # Lists, always — a caller must not have to guess the shape from the count.
    assert result["to"] == ["c@example.com"]
    assert result["intended_to"] == ["c@example.com"]
    assert result["redirected"] is False


def test_no_attachments_key_is_sent_when_there_are_none():
    with _post() as post:
        email_service.send(to="c@example.com", subject="S", html="<p>H</p>")
    assert "attachments" not in post.call_args.kwargs["json"]


def test_a_pdf_attachment_is_base64_encoded():
    with _post() as post:
        email_service.send(
            to="c@example.com", subject="S", html="<p>H</p>",
            attachments=[("NAR1.pdf", b"%PDF-1.4 body")],
        )
    attachment = post.call_args.kwargs["json"]["attachments"][0]
    assert attachment["filename"] == "NAR1.pdf"
    assert base64.b64decode(attachment["content"]) == b"%PDF-1.4 body"


# ---------------------------------------------------------------------------
# Failure — nothing leaks, nothing is reported as sent
# ---------------------------------------------------------------------------


def test_a_resend_error_raises_and_does_not_leak_the_key():
    with _post(_response(422, {"message": "domain not verified"})):
        with pytest.raises(email_service.EmailError) as exc:
            email_service.send(to="c@example.com", subject="S", html="<p>H</p>")
    assert "domain not verified" in str(exc.value)
    assert "re_test_key" not in str(exc.value)


def test_an_error_body_that_is_not_json_still_raises_a_readable_error():
    broken = MagicMock(status_code=502)
    broken.json.side_effect = ValueError("no json")
    broken.text = "<html>bad gateway</html>"
    with _post(broken):
        with pytest.raises(email_service.EmailError) as exc:
            email_service.send(to="c@example.com", subject="S", html="<p>H</p>")
    assert "502" in str(exc.value)


def test_a_transport_failure_raises_without_carrying_the_request_object():
    """httpx exceptions carry the request, and the request carries the
    Authorization header. Neither the message nor the chained context may."""
    import httpx

    with patch("services.email_service.httpx.post",
               side_effect=httpx.ConnectError("boom")):
        with pytest.raises(email_service.EmailError) as exc:
            email_service.send(to="c@example.com", subject="S", html="<p>H</p>")
    assert "re_test_key" not in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None


def test_a_missing_api_key_fails_before_any_http_call(monkeypatch):
    """Name only, never the value — this message reaches logs."""
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    email_service.get_email_config.cache_clear()
    with patch("services.email_service.httpx.post") as post:
        with pytest.raises(RuntimeError, match="RESEND_API_KEY"):
            email_service.send(to="c@example.com", subject="S", html="<p>H</p>")
    post.assert_not_called()


# ---------------------------------------------------------------------------
# The non-production interlock
#
# Levi 2026-08-30 replaced the EMAIL_REDIRECT_TO variable with the hardcoded
# TEST_RECIPIENTS list, so a non-production deployment can no longer be
# configured to mail a client at all. The six tests that used to live here
# described that variable's contract and went with it; the replacement contract
# is covered in full by tests/test_email_test_recipients.py.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The verification message
# ---------------------------------------------------------------------------


def test_the_verification_email_names_the_company_and_the_case():
    subject, html = email_service.verification_email(
        {"case_no": "NAR-2026-0041"},
        {"company_name": "ACME LIMITED", "br_number": "00000001"},
    )
    assert "ACME LIMITED" in subject or "ACME LIMITED" in html
    assert "NAR-2026-0041" in html
    assert "00000001" in html


def test_the_verification_email_never_embeds_a_credential():
    _, html = email_service.verification_email(
        {"case_no": "NAR-2026-0041"}, {"company_name": "ACME LIMITED"}
    )
    for forbidden in ("password", "token", "api_key", "bearer"):
        assert forbidden not in html.lower()


def test_a_company_name_carrying_markup_is_escaped_not_injected():
    """Company names come out of the Viewpoint ETL. An unescaped one lands in
    the client's mailbox as live markup."""
    _, html = email_service.verification_email(
        {"case_no": "NAR-2026-0041"},
        {"company_name": "<script>alert(1)</script> LIMITED"},
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_a_missing_company_name_does_not_render_the_word_none():
    subject, html = email_service.verification_email({}, {})
    assert "None" not in subject
    assert "None" not in html


# ---------------------------------------------------------------------------
# Several recipients on one message
# ---------------------------------------------------------------------------


def test_a_list_of_recipients_becomes_one_message_not_several():
    """Three directors get ONE email with three addresses on it. Three separate
    sends would break the thread the client replies into, and one Resend failure
    would leave two directors informed and the third not."""
    with _post() as post:
        result = email_service.send(
            to=["a@example.com", "b@example.com", "c@example.com"],
            subject="S", html="<p>H</p>")
    assert post.call_count == 1
    assert post.call_args.kwargs["json"]["to"] == [
        "a@example.com", "b@example.com", "c@example.com"]
    assert result["to"] == ["a@example.com", "b@example.com", "c@example.com"]


def test_a_bare_string_recipient_still_works():
    """The signature this module shipped with. A caller that sends one address
    is not wrong."""
    with _post() as post:
        email_service.send(to="c@example.com", subject="S", html="<p>H</p>")
    assert post.call_args.kwargs["json"]["to"] == ["c@example.com"]


def test_an_empty_recipient_list_is_refused_before_the_http_call():
    """Resend would answer 422 — a round trip spent learning something already
    knowable here."""
    with patch("services.email_service.httpx.post") as post:
        with pytest.raises(email_service.EmailError):
            email_service.send(to=[], subject="S", html="<p>H</p>")
    post.assert_not_called()


# ---------------------------------------------------------------------------
# EMAIL_TRANSPORT=console — the stub, and the guards that keep it off PROD
# ---------------------------------------------------------------------------


def test_the_console_transport_delivers_nothing(monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("EMAIL_TRANSPORT", "console")
    email_service.get_email_config.cache_clear()
    with patch("services.email_service.httpx.post") as post:
        result = email_service.send(to=["a@example.com", "b@example.com"],
                                    subject="Confirm", html="<p>H</p>")
    post.assert_not_called()
    assert result["transport"] == "console"
    assert result["to"] == ["a@example.com", "b@example.com"]
    assert "NOT SENT" in capsys.readouterr().err


def test_the_console_transport_needs_no_api_key(monkeypatch):
    """It is the configuration this exists FOR: Resend unusable, and the
    workflow still has to be drivable."""
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("EMAIL_TRANSPORT", "console")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    email_service.get_email_config.cache_clear()
    result = email_service.send(to="a@example.com", subject="S", html="<p>H</p>")
    assert result["transport"] == "console"


def test_production_refuses_the_console_transport(monkeypatch):
    """The worst outcome this module can produce: every client silently
    receiving nothing while the portal reports each send as successful."""
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("EMAIL_TRANSPORT", "console")
    email_service.get_email_config.cache_clear()
    with patch("services.email_service.httpx.post") as post:
        with pytest.raises(RuntimeError, match="EMAIL_TRANSPORT"):
            email_service.send(to="a@example.com", subject="S", html="<p>H</p>")
    post.assert_not_called()


def test_a_real_send_is_never_labelled_as_stubbed():
    """The mutation that would make the flag meaningless."""
    with _post():
        result = email_service.send(to="a@example.com", subject="S", html="<p>H</p>")
    assert result.get("transport", "resend") != "console"


def test_an_unknown_transport_is_refused_rather_than_assumed(monkeypatch):
    """A typo'd EMAIL_TRANSPORT must not quietly fall back to sending, nor to
    not sending. Either guess is wrong in a way nobody would notice."""
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
    email_service.get_email_config.cache_clear()
    with pytest.raises(RuntimeError, match="EMAIL_TRANSPORT"):
        email_service.send(to="a@example.com", subject="S", html="<p>H</p>")



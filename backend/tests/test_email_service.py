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


# --- the redesign (Levi 2026-08-30: "make sure the email looks professional") -

CASE = {"case_no": "NAR-2026-0041", "ar_period_year": 2026}
ENTITY = {"company_name": "ACME LIMITED", "br_number": "00000001"}


def test_the_message_survives_outlook_which_has_no_flexbox_or_grid():
    """Outlook renders mail through Word. A layout built on flex or grid
    collapses into a single unstyled column there, which is most of GSHK's
    clients."""
    _, html = email_service.verification_email(CASE, ENTITY)
    assert "display:flex" not in html
    assert "display:grid" not in html
    assert "<table" in html


def test_every_style_is_inline_because_a_style_block_gets_stripped():
    _, html = email_service.verification_email(CASE, ENTITY)
    assert "<style" not in html
    assert "class=" not in html


def test_the_masthead_names_the_form_and_the_company_it_concerns():
    """How the document itself announces what it is — and the first thing a
    director needs to know is that this is about THEIR company."""
    _, html = email_service.verification_email(CASE, ENTITY)
    assert "Form NAR1" in html
    assert html.index("Form NAR1") < html.index("ACME LIMITED")


def test_the_particulars_are_labelled_rather_than_run_together():
    _, html = email_service.verification_email(CASE, ENTITY)
    for label in ("Business Registration No.", "Return period", "Our reference"):
        assert label in html


def test_a_particular_with_no_value_omits_its_row_entirely():
    """Rather than rendering an empty box the reader has to interpret."""
    _, html = email_service.verification_email({"case_no": "NAR-2026-0041"},
                                               {"company_name": "ACME LIMITED"})
    assert "Business Registration No." not in html
    assert "Our reference" in html


def test_the_message_carries_no_link_at_all():
    """Nothing here is clickable, and that is a security property as much as a
    design one: a mail about someone's company filings that contains a link is
    the exact shape of the phishing it would train them to trust."""
    _, html = email_service.verification_email(CASE, ENTITY)
    assert "<a " not in html
    assert "http://" not in html and "https://" not in html


def test_the_message_says_what_the_reader_has_to_do():
    _, html = email_service.verification_email(CASE, ENTITY)
    assert "What we need from you" in html
    assert "Reply to this email" in html


def test_the_attachment_is_named_in_the_body_when_there_is_one():
    _, html = email_service.verification_email(
        CASE, ENTITY, attachment_name="NAR1-NAR-2026-0041.pdf")
    assert "NAR1-NAR-2026-0041.pdf" in html


def test_no_attachment_line_is_rendered_when_nothing_is_attached():
    _, html = email_service.verification_email(CASE, ENTITY)
    assert "Attached" not in html


def test_an_attachment_name_carrying_markup_is_escaped():
    _, html = email_service.verification_email(
        CASE, ENTITY, attachment_name="<script>x</script>.pdf")
    assert "<script>" not in html


def test_the_company_appears_once_and_is_not_repeated_in_the_ledger():
    """One element, one job. The masthead names the company; a ledger row
    repeating it would be decoration."""
    _, html = email_service.verification_email(CASE, ENTITY)
    assert html.count("ACME LIMITED") == 1


def test_a_company_with_no_name_falls_back_to_the_ledger_for_identity():
    """Degenerate, but it must not leave the reader with nothing telling them
    which company the return concerns."""
    _, html = email_service.verification_email(
        CASE, {"br_number": "00000001"})
    assert "Annual Return" in html
    assert "00000001" in html


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


def test_the_case_worker_is_copied_openly(monkeypatch):
    """CC, not BCC. The client should be able to see who at GSHK is handling
    their return, and reply to all."""
    with _post() as post:
        email_service.send(to="client@example.com", cc="levi@zenexflow.com",
                           subject="S", html="<p>H</p>")
    assert post.call_args.kwargs["json"]["cc"] == ["levi@zenexflow.com"]


def test_no_cc_key_is_sent_when_nobody_is_copied():
    with _post() as post:
        email_service.send(to="client@example.com", subject="S", html="<p>H</p>")
    assert "cc" not in post.call_args.kwargs["json"]


def test_an_address_already_on_to_is_not_also_copied():
    """Some clients render the same message twice, and every reply-all after
    that carries a duplicate."""
    with _post() as post:
        email_service.send(to=["Levi@Zenexflow.com", "client@example.com"],
                           cc="levi@zenexflow.com", subject="S", html="<p>H</p>")
    assert "cc" not in post.call_args.kwargs["json"]


def test_the_reply_goes_to_a_mailbox_a_human_reads():
    """The body asks the client to reply, and the sender is no-reply@. Without
    reply_to the one action the message requests reaches nobody."""
    with _post() as post:
        email_service.send(to="client@example.com", reply_to="levi@zenexflow.com",
                           subject="S", html="<p>H</p>")
    assert post.call_args.kwargs["json"]["reply_to"] == ["levi@zenexflow.com"]


def test_no_reply_to_key_is_sent_when_there_is_nobody_to_reply_to():
    with _post() as post:
        email_service.send(to="client@example.com", subject="S", html="<p>H</p>")
    assert "reply_to" not in post.call_args.kwargs["json"]


def test_the_result_reports_who_was_copied():
    with _post():
        result = email_service.send(to="client@example.com",
                                    cc="levi@zenexflow.com",
                                    subject="S", html="<p>H</p>")
    assert result["cc"] == ["levi@zenexflow.com"]
    assert result["intended_cc"] == ["levi@zenexflow.com"]


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
# EMAIL_TRANSPORT — 'resend' is the only one. 'console' was REMOVED 2026-08-30.
# ---------------------------------------------------------------------------
# The stub wrote to stderr, delivered nothing and returned success. It existed
# because RESEND_API_KEY was a placeholder; a real key is now in place and
# getstarted.hk is verified, so it is gone. These tests hold the removal down:
# a deployment that still asks for it must FAIL, not silently start sending.


@pytest.mark.parametrize("value", ["console", "smtp", "CONSOLE"])
def test_every_transport_but_resend_is_refused(monkeypatch, value):
    """Both halves of the same rule. A typo must not quietly fall back to
    sending; and 'console' — a value that used to WORK — must not quietly
    start sending either, which is the dangerous half of this removal. A
    deployment asking for silence and getting real mail is the mistake."""
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("EMAIL_TRANSPORT", value)
    email_service.get_email_config.cache_clear()
    with patch("services.email_service.httpx.post") as post:
        with pytest.raises(RuntimeError, match="EMAIL_TRANSPORT"):
            email_service.send(to="a@example.com", subject="S", html="<p>H</p>")
    post.assert_not_called()


def test_the_console_refusal_says_it_was_removed_and_what_to_do(monkeypatch):
    """A bare "unknown transport" would send whoever hits this hunting for a
    typo in a value that was correct last week."""
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("EMAIL_TRANSPORT", "console")
    email_service.get_email_config.cache_clear()
    with pytest.raises(RuntimeError) as exc:
        email_service.send(to="a@example.com", subject="S", html="<p>H</p>")
    assert "removed" in str(exc.value)
    assert "unset" in str(exc.value).lower()


def test_a_real_send_is_never_labelled_as_stubbed():
    """Existing audit rows still say transport='console', meaning nothing was
    delivered. A real send must stay distinguishable from those forever."""
    with _post():
        result = email_service.send(to="a@example.com", subject="S", html="<p>H</p>")
    assert result.get("transport", "resend") != "console"


def test_an_unset_transport_sends_for_real(monkeypatch):
    """The default, and now the only working configuration."""
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("EMAIL_TRANSPORT", raising=False)
    email_service.get_email_config.cache_clear()
    with _post() as post:
        result = email_service.send(to="a@example.com", subject="S", html="<p>H</p>")
    post.assert_called_once()
    assert result.get("transport", "resend") == "resend"



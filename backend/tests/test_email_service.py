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


def test_the_reference_line_carries_the_BR_number_and_our_own_reference():
    """NOT in the sample letter, and kept to one small line at the end for that
    reason. It costs almost nothing and it prevents the failure it exists for:
    a client replying about the wrong year."""
    _, html = email_service.verification_email(CASE, ENTITY)
    assert "BR 00000001" in html
    assert "Ref NAR-2026-0041" in html


def test_a_reference_with_no_value_omits_its_part_entirely():
    """Rather than rendering "BR" with nothing after it."""
    _, html = email_service.verification_email({"case_no": "NAR-2026-0041"},
                                               {"company_name": "ACME LIMITED"})
    assert "BR " not in html
    assert "Ref NAR-2026-0041" in html


def test_the_message_carries_no_link_WHEN_NONE_IS_GIVEN():
    """THE "NO LINK AT ALL" RULE IS REVERSED (spec section 5, Levi 2026-09-01) —
    see `verification_email`'s docstring for what replaces its protection.

    What this asserts now is the FALLBACK: a deployment that cannot build an
    approval URL sends exactly the message that shipped before, asking for a
    reply. That path has to keep working, because it is what a client gets when
    PUBLIC_API_BASE_URL is unset and the request's own base URL is unusable."""
    _, html = email_service.verification_email(CASE, ENTITY)
    assert "<a " not in html
    assert "http://" not in html and "https://" not in html
    assert "please reply to this email to confirm" in html


def test_the_message_says_what_the_reader_has_to_do():
    _, html = email_service.verification_email(CASE, ENTITY)
    assert "Your draft NAR1 is now available for review" in html
    assert "please reply to this email to confirm" in html


# --- the "Auto email - NAR1 Review" wording (Levi 2026-09-08) ---------------
#
# The approved automated letter, transcribed from
# docs/Auto email - NAR1 Review_v2.pdf. It REPLACES the hand-sent
# "Confirmation NAR1 Notice" this message used to carry, and the assertions
# below are what "verbatim" means for it: a wording change here is a change to
# what a client is told about a statutory filing and a HK$1,000 charge, so it
# has to be made deliberately rather than absorbed by a loose test.

def _letter(**over):
    kwargs = {"attachment_name": "Explod Limited NAR1 2026.pdf",
              "approval_url": "https://api.example.com/public/nar1-approval/t0",
              "deadline": "2026-08-28T00:00:00+00:00"}
    kwargs.update(over)
    return email_service.verification_email(
        {"case_no": "NAR-2026-0041", "ar_period_year": 2026},
        {"company_name": "Explod Limited", "br_number": "00000001"},
        **kwargs)


def test_the_subject_is_the_samples_own_subject_line():
    subject, _ = _letter()
    assert subject == ("[Action Required] NAR1 Review & Confirmation - "
                       "Explod Limited")


def test_a_company_with_no_name_still_gets_a_usable_subject():
    """Degenerate, but the bracketed prefix is what makes this findable in a
    director's inbox and it must not decay into a trailing dash."""
    subject, _ = email_service.verification_email({}, {})
    assert subject == "[Action Required] NAR1 Review & Confirmation"


def test_the_letter_addresses_the_client_generically():
    """"Dear Client", NOT the director's own name (Levi 2026-09-08). This is
    sent unattended, one message per director, and greeting each of them by
    name would imply a human chose to write to them."""
    _, html = _letter()
    assert "Dear Client," in html


def test_the_opening_line_is_verbatim():
    _, html = _letter()
    assert "Your draft NAR1 is now available for review." in html
    assert ("Please review the attached draft carefully, with particular "
            "attention to the following:") in html


def test_the_letter_says_no_signature_is_required():
    """It is the first thing a director asks, and the sample answers it in the
    same breath as the ask rather than three paragraphs down."""
    _, html = _letter()
    assert ("If the information is correct, please click "
            "<strong>Confirm</strong> below. No signature is required.") in html


@pytest.mark.parametrize("where,what", [
    ("Page 2", "Share Capital"),
    ("Page 5", "Director&#x27;s Details"),
    ("Schedule 1", "Shareholder&#x27;s Details"),
    ("Continuation Sheet C", "Additional Director&#x27;s Details"),
])
def test_the_page_references_are_the_samples(where, what):
    """HARDCODED, and correct because CR's form is STATIC (spec section 1b): CR
    keeps a section's page whether or not it has content, so Page 5 is Page 5 on
    every NAR1 ever filed. If the renderer ever went back to dropping empty
    pages, these lines would quietly misdirect every client."""
    _, html = _letter()
    assert where in html
    assert what in html


def test_continuation_sheet_C_says_when_it_applies():
    """It is the ONE conditional entry: the sheet exists only where the board
    runs past the space Page 5 gives it. A client without one must not be sent
    hunting through their PDF for a page that was never printed."""
    _, html = _letter()
    assert "if applicable, where there is more than one director" in html


def test_the_deadline_is_stated_and_says_what_happens_after_it():
    _, html = _letter()
    assert "28 August 2026" in html
    assert ("the draft will be deemed confirmed and we will proceed with the "
            "NAR1 filing") in html


def test_no_deadline_still_says_what_silence_means():
    """A blank where a legal deadline should be is worse than no date at all —
    but what silence MEANS does not depend on the date, so that half stays."""
    _, html = _letter(deadline=None)
    assert ("the draft will be deemed confirmed and we will proceed with the "
            "NAR1 filing") in html
    assert "hear from you by" not in html


def test_the_service_fee_is_stated_and_says_WHEN_it_applies():
    """"After filing", not "later". They are different events, and the second
    reads as a charge for changing your mind before anything has been sent."""
    _, html = _letter()
    assert ("Any changes requested after filing will be subject to a "
            "HK$1,000 service fee.") in html


def test_changes_are_sent_to_the_renewal_mailbox_and_NOT_by_replying():
    """The message is sent from no-reply@ and says replies are not monitored,
    so the one mailbox it names has to be a mailbox somebody reads. A letter
    that said "reply to us" here would be an instruction to do nothing."""
    _, html = _letter()
    assert ("If changes are required, please <strong>do not click "
            "confirm</strong> and email renewal@getstarted.hk before the "
            "deadline.") in html


def test_the_letter_says_it_is_automated_and_that_replies_are_not_read():
    _, html = _letter()
    assert ("This is an automatically generated email. Replies to this email "
            "are not monitored.") in html


def test_the_automated_notice_is_WITHHELD_when_there_is_no_button():
    """The no-link fallback asks the reader to REPLY. Telling them in the next
    paragraph that replies are not read would leave them with nothing they can
    do at all."""
    _, html = _letter(approval_url=None)
    assert "Replies to this email are not monitored" not in html
    assert "please reply to this email to confirm" in html


def test_the_company_signs_it_and_no_person_does():
    """"Kind regards, Get Started HK Limited" (Levi 2026-09-08). The letter goes
    out unattended; a case worker's name on it would claim a human wrote it,
    and there is no longer a `sender_name` argument to put one there."""
    _, html = _letter()
    assert "Kind regards," in html
    assert "Get Started HK Limited" in html
    assert "Account Manager" not in html
    assert "Best regards" not in html


def test_the_footer_is_GSHKs_own_block_verbatim():
    _, html = _letter()
    assert "GET STARTED HK LIMITED" in html
    assert "+ 852 2813 7600" in html
    assert "+852 5541 1994" in html
    assert ("Suite C, Level 7, World Trust Tower, 50 Stanley Street, Central, "
            "Hong Kong") in html
    assert "Corporate Advisory | Company Formation | Accounting Services" in html


def test_the_confirm_button_is_a_table_cell_not_a_styled_anchor():
    """Outlook renders mail through Word, which drops padding on inline anchors
    and leaves a bare blue link where the call to action should be."""
    _, html = _letter()
    assert ">Confirm NAR1</a>" in html
    assert 'bgcolor="#F36C32"' in html
    assert "nar1-approval/t0" in html


def test_the_button_is_the_LAST_thing_in_the_letter():
    """The sample places it under the sign-off. A confirm button ABOVE the
    paragraph explaining the HK$1,000 charge invites a press before the charge
    has been read."""
    _, html = _letter()
    assert html.index("Kind regards,") < html.index(">Confirm NAR1</a>")
    assert html.index("service fee") < html.index(">Confirm NAR1</a>")


def test_the_message_asks_for_ONE_answer_not_two():
    """"Reply to confirm" beside a Confirm button asks for the same thing twice,
    and a reader who does both produces two answers for one return."""
    _, html = _letter()
    assert "please reply to this email to confirm" not in html
    assert ("please click <strong>Confirm</strong> below") in html


def test_an_approval_url_carrying_markup_is_escaped():
    """It is ours, not the client's — but the escaping rule in this module has
    no exceptions: the one place a rule is relaxed is where the next injection
    lands."""
    _, html = _letter(approval_url='https://x/"><script>alert(1)</script>')
    assert "<script>" not in html


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


# ---------------------------------------------------------------------------
# undeliverable_reason — can this domain receive mail at all? (Levi 2026-09-08)
#
# Resend answers 200 for any syntactically valid address and bounces it out of
# band, so a send to a made-up domain reported success and the operator learned
# nothing. This is the half of "is it deliverable" that does not need a bounce.
#
# NOTHING HERE TOUCHES THE NETWORK. Each test drives the one library call the
# probe makes; the real resolver is never used, so the suite neither slows down
# nor depends on where it is run.
# ---------------------------------------------------------------------------

#: THE REAL FUNCTION, captured at import time.
#:
#: conftest's autouse `_no_dns_in_tests` replaces
#: `email_service.undeliverable_reason` with a stub for every test in the
#: suite, so that no unit test resolves a domain name. That is right
#: everywhere except here — these are the tests OF that function, and calling
#: it through the module attribute would assert on the stub and pass no matter
#: what the real implementation did. Module import runs before any fixture, so
#: this binding is the genuine article.
_probe = email_service.undeliverable_reason


def _validator(exc):
    """Patch email_validator.validate_email to raise `exc` (or pass if None)."""
    if exc is None:
        return patch("email_validator.validate_email", return_value=MagicMock())
    return patch("email_validator.validate_email", side_effect=exc)


def test_a_domain_that_does_not_exist_is_reported_with_its_reason():
    """The wording is the library's own and NAMES THE DOMAIN, which is the part
    the operator has to fix — so it is passed through rather than replaced with
    a generic phrase."""
    from email_validator import EmailUndeliverableError
    with _validator(EmailUndeliverableError(
            "The domain name nosuch.invalid does not exist.")):
        reason = _probe("a@nosuch.invalid")
    assert reason == "The domain name nosuch.invalid does not exist."


def test_a_domain_that_does_not_accept_email_is_reported():
    """A Null MX (RFC 7505), or no MX and no A/AAAA fallback. The domain is
    real; mail to it is not."""
    from email_validator import EmailUndeliverableError
    with _validator(EmailUndeliverableError(
            "The domain name parked.example does not accept email.")):
        assert _probe("a@parked.example")


def test_a_deliverable_address_returns_None():
    with _validator(None):
        assert _probe("levi@zenexflow.com") is None


def test_a_TIMEOUT_lets_the_address_through():
    """SILENCE IS PERMISSION. A wrongly withheld verification email stalls a
    statutory filing on a director who was never written to; a bounce merely
    wastes a send. The library already returns rather than raises on a timeout,
    and this pins that we depend on it."""
    import dns.exception
    with _validator(dns.exception.Timeout()):
        assert _probe("a@slow.example") is None


def test_AN_UNEXPECTED_ERROR_lets_the_address_through():
    """No network at all, a resolver misconfiguration, a library upgrade that
    raises something new. None of those are evidence against the address."""
    with _validator(RuntimeError("resolver exploded")):
        assert _probe("a@example.org") is None


def test_a_SYNTAX_complaint_is_not_reported_here():
    """The caller applies its own syntax gate and phrases its own refusal.
    Re-reporting the same address in different words would put two entries in
    the failure list for one mistake."""
    from email_validator import EmailSyntaxError
    with _validator(EmailSyntaxError("bad syntax")):
        assert _probe("not-an-address") is None


def test_the_probe_asks_for_deliverability_and_bounds_the_wait():
    """It runs in front of an operator watching a spinner, so an unbounded DNS
    wait would be theirs to sit through."""
    with patch("email_validator.validate_email",
               return_value=MagicMock()) as validate:
        _probe("a@example.org")
    kwargs = validate.call_args.kwargs
    assert kwargs["check_deliverability"] is True
    assert kwargs["timeout"] == email_service.DNS_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# CLIENT_CC — the fixed copy on every client-facing message
# ---------------------------------------------------------------------------

def test_the_client_copy_is_the_shared_renewals_mailbox():
    """Levi 2026-09-08. Not the person who pressed Send: the client must not
    see an individual's address on a letter about their statutory return, and
    GSHK's record of it must not live in one person's mailbox."""
    assert email_service.CLIENT_CC == "renewal@getstarted.hk"


def test_client_cc_matches_the_screen():
    """THE SCREEN PROMISES THIS ADDRESS BY NAME, before the send exists, so it
    cannot read the value back off a response — it repeats the constant. This
    reads the actual JSX and fails if the two ever drift, which is the only
    thing stopping the note from telling an operator a copy went somewhere it
    did not."""
    from pathlib import Path
    jsx = (Path(__file__).resolve().parents[2] / "frontend" / "src"
           / "components" / "case" / "StageClientVerification.jsx")
    assert jsx.exists(), f"the screen moved: {jsx}"
    assert (f"export const CLIENT_CC = '{email_service.CLIENT_CC}'"
            in jsx.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# delivery_status — did Resend actually deliver it? (Levi 2026-09-08)
#
# A 200 from send() means Resend ACCEPTED the message. `GET /emails/{id}`
# reports its `last_event`, which is the same fact a bounce webhook would push
# — asked for rather than waited for, so it needs no public endpoint, no
# signing secret and no dashboard registration.
# ---------------------------------------------------------------------------

def _get(status=200, payload=None):
    return patch("services.email_service.httpx.get",
                 return_value=_response(status, payload))


def test_a_delivered_message_reports_delivered():
    with _get(payload={"last_event": "delivered"}):
        assert email_service.delivery_status("m1")["status"] == "delivered"


def test_a_bounced_message_reports_failed_with_a_reason():
    with _get(payload={"last_event": "bounced"}):
        result = email_service.delivery_status("m1")
    assert result["status"] == "failed"
    assert result["event"] == "bounced"
    assert "rejected" in result["detail"]


def test_a_SUPPRESSED_address_reports_failed():
    """The quiet one this check earns its place on. An address that hard-bounced
    for anyone on this Resend account is suppressed, and a later send to it
    returns 200 with an id and is never actually attempted — indistinguishable
    from a delivery without asking."""
    with _get(payload={"last_event": "suppressed"}):
        result = email_service.delivery_status("m1")
    assert result["status"] == "failed"
    assert "suppression list" in result["detail"]


def test_an_ACCEPTED_but_unresolved_message_is_pending_not_delivered():
    """`sent` is what send() already told us. Treating it as delivered would
    make the whole check a no-op that always says yes."""
    with _get(payload={"last_event": "sent"}):
        assert email_service.delivery_status("m1")["status"] == "pending"


def test_a_delayed_delivery_is_pending_not_failed():
    """The receiving server is retrying — a full mailbox, a transient fault. It
    may still arrive, and calling it a failure would have the operator re-send
    a statutory notice to a client who is about to get the first one."""
    with _get(payload={"last_event": "delivery_delayed"}):
        assert email_service.delivery_status("m1")["status"] == "pending"


def test_a_COMPLAINT_still_counts_as_arrived():
    """It reached the mailbox and the reader pressed 'spam'. Worth saying, but
    it is not a delivery failure and must not send anyone chasing a re-send."""
    with _get(payload={"last_event": "complained"}):
        result = email_service.delivery_status("m1")
    assert result["status"] == "delivered"
    assert "spam" in result["detail"]


@pytest.mark.parametrize("event", ["opened", "clicked"])
def test_events_that_imply_delivery_count_as_delivered(event):
    with _get(payload={"last_event": event}):
        assert email_service.delivery_status(event)["status"] == "delivered"


def test_an_UNKNOWN_event_is_pending_never_failed():
    """Resend can add events after this was written. A name we do not recognise
    is not evidence that a director was not written to."""
    with _get(payload={"last_event": "something_new"}):
        result = email_service.delivery_status("m1")
    assert result["status"] == "pending"
    assert result["event"] == "something_new"


def test_a_TRANSPORT_FAILURE_is_pending_and_never_leaks_the_key():
    """Telling an operator a return bounced when it did not would have them
    re-send to a client who already has it — and re-sending invalidates every
    approval link the rest of the board is holding."""
    import httpx
    with patch("services.email_service.httpx.get",
               side_effect=httpx.ConnectError("boom")):
        result = email_service.delivery_status("m1")
    assert result["status"] == "pending"
    assert "re_test_key" not in str(result)


def test_an_ERROR_RESPONSE_is_pending():
    with _get(status=500, payload={"message": "server error"}):
        assert email_service.delivery_status("m1")["status"] == "pending"


def test_an_UNREADABLE_BODY_is_pending():
    broken = MagicMock(status_code=200)
    broken.json.side_effect = ValueError("no json")
    with patch("services.email_service.httpx.get", return_value=broken):
        assert email_service.delivery_status("m1")["status"] == "pending"


def test_a_missing_message_id_is_pending_without_calling_resend():
    with patch("services.email_service.httpx.get") as get:
        assert email_service.delivery_status("")["status"] == "pending"
    get.assert_not_called()


def test_the_check_authenticates_and_is_bounded():
    with _get(payload={"last_event": "delivered"}) as get:
        email_service.delivery_status("abc-123")
    assert get.call_args.args[0].endswith("/emails/abc-123")
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer re_test_key"
    assert get.call_args.kwargs["timeout"] == email_service.DELIVERY_TIMEOUT_SECONDS


def test_the_client_copy_is_NOT_one_of_the_test_recipients():
    """It is a real GSHK mailbox, so the non-production lock must DROP it
    rather than treat it as already-covered. If it were ever added to
    TEST_RECIPIENTS, a test deployment could mail the renewals team about a
    case that does not exist."""
    assert email_service.CLIENT_CC not in email_service.TEST_RECIPIENTS



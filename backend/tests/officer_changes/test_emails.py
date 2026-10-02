"""The officer-change client email (spec B-14): what it says, and what it never says."""
from datetime import date

from services import email_service
from services.officer_changes import emails

CASE = {"id": "K1", "case_no": "ND2A-2026-0001", "form_code": "Nd2a"}
ENTITY = {"company_name": "Kanenas Holding Limited <b>", "br_number": "69123456"}
HOME = "Flat A, 10/F, Harbour View"


def _entries():
    return [
        {"kind": "cessation", "capacity": "director", "cessation_reason": "R",
         "effective_date": "2026-09-28", "party": {"name": "CHAN Tai Man"}},
        {"kind": "appointment", "capacity": "company_secretary",
         "effective_date": "2026-09-29", "party": {"name": "WONG Ka Yan",
                                                    "hkid": "A1234563"}},
    ]


def _nd2b_entries():
    return [{"kind": "change", "capacity": "director", "party": {"name": "LEE Siu Ming"},
             "items": [
                 {"key": "name_en", "label": "Name in English", "old_text": "LEE Siu Ming",
                  "new_text": "LI Siu Ming", "effective_date": "2026-09-20", "omitted": False},
                 {"key": "residential_address", "label": "Residential address",
                  "old_text": HOME, "new_text": "Flat B, 2/F", "effective_date": "2026-09-21",
                  "omitted": False},
                 {"key": "hkid", "label": "Hong Kong identity card number",
                  "old_text": "A1234563", "new_text": "B7654321",
                  "effective_date": "2026-09-22", "omitted": False},
                 {"key": "email", "label": "Email address", "old_text": "a@x.com",
                  "new_text": "b@x.com", "effective_date": "2026-09-23", "omitted": True},
             ]}]


def test_summary_names_each_change_with_its_date():
    lines = emails.changes_summary(_entries())
    assert lines == [
        "CHAN Tai Man ceases to act as Director on 28 September 2026.",
        "WONG Ka Yan is appointed Company Secretary on 29 September 2026.",
    ]


def test_nd2b_summary_shows_names_but_never_an_address_or_id_number():
    lines = emails.changes_summary(_nd2b_entries())
    text = " ".join(lines)
    assert "Name in English changed from LEE Siu Ming to LI Siu Ming" in text
    assert "Residential address changed" in text
    assert "Hong Kong identity card number changed" in text
    assert HOME not in text and "Flat B" not in text
    assert "A1234563" not in text and "B7654321" not in text
    assert "b@x.com" not in text  # the omitted line is not filed, so not mentioned
    assert len(lines) == 3


def test_letter_has_the_nar1_shape_and_a_confirm_button():
    subject, body = emails.officer_change_email(
        CASE, ENTITY, _entries(), approval_url="https://x.test/a?t=1&u=2",
        respond_by=date(2026, 10, 10))
    assert subject == ("[Action Required] ND2A Review & Confirmation - "
                       "Kanenas Holding Limited <b>")
    assert "Dear Client," in body
    assert "Get Started HK Limited" in body
    assert email_service.RENEWAL_MAILBOX in body
    assert "Confirm ND2A" in body
    assert "10 October 2026" in body
    assert "Replies to this email are not monitored" in body
    assert "Kanenas Holding Limited &lt;b&gt;" in body and "<b>" not in body.split("Kanenas")[1][:5]
    assert "https://x.test/a?t=1&amp;u=2" in body


def test_letter_never_claims_silence_is_consent():
    _, body = emails.officer_change_email(CASE, ENTITY, _entries(),
                                          approval_url="https://x.test/a",
                                          respond_by=date(2026, 10, 10))
    assert "deemed confirmed" not in body
    assert "HK$1,000" not in body


def test_without_a_link_it_asks_for_a_reply_and_drops_the_unmonitored_line():
    _, body = emails.officer_change_email(CASE, ENTITY, _entries(), approval_url=None,
                                          respond_by=None)
    assert "reply to this email" in body
    assert "not monitored" not in body
    assert "Confirm ND2A" not in body
    assert "as soon as possible" in body


def test_nd2b_letter_is_titled_for_nd2b_and_carries_no_identity_number():
    subject, body = emails.officer_change_email(
        {**CASE, "form_code": "Nd2b", "case_no": "ND2B-2026-0001"}, ENTITY,
        _nd2b_entries(), approval_url="https://x.test/a", respond_by="2026-10-10")
    assert subject.startswith("[Action Required] ND2B Review & Confirmation")
    assert "Confirm ND2B" in body and "Form ND2B" in body
    assert "B7654321" not in body and HOME not in body


def test_markup_is_table_based_with_no_style_block():
    _, body = emails.officer_change_email(CASE, ENTITY, _entries(),
                                          approval_url="https://x.test/a",
                                          respond_by=date(2026, 10, 10))
    assert "<style" not in body and "display:flex" not in body and "grid" not in body
    assert body.startswith("<table")

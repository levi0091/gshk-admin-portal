"""A new director's consent to act, signed in G-FlowDesk (Jacqueline A2)."""
import asyncio
from datetime import datetime, timedelta, timezone

import pymupdf
import pytest

from services.officer_change_form import page_plan, render
from services.officer_changes import econsent, form_xml, nd2a_mapper
from tests.officer_changes import cr_fixtures as fx
from tests.officer_changes.fakes import FakeSupabase

FUTURE = datetime.now(timezone.utc) + timedelta(days=5)
PAST = datetime.now(timezone.utc) - timedelta(days=1)
LEE = {"id": "N1", "case_id": "K1", "kind": "appointment", "capacity": "director",
       "person_id": "P9", "party_type": "individual"}
SEC = {"id": "N2", "case_id": "K1", "kind": "appointment", "capacity": "company_secretary",
       "person_id": "P8", "party_type": "individual"}
CORP = {"id": "N3", "case_id": "K1", "kind": "appointment", "capacity": "director",
        "corporate_entity_id": "C1", "consent_person_id": "P7", "party_type": "corporate"}


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase({"officer_change_consents": []})
    monkeypatch.setattr(econsent, "get_supabase", lambda: fake)
    return fake


def test_eligible_takes_new_natural_directors_with_an_email_and_no_account():
    meta = {"P9": {"eservice_user_id": None, "has_password": False}}
    emails = {"P9": "lee@example.com"}
    assert [e["id"] for e in econsent.eligible([LEE, SEC, CORP], meta, emails)] == ["N1"]


def test_eligible_skips_directors_with_a_stored_account():
    meta = {"P9": {"eservice_user_id": "LKH1", "eservice_person_name": "LEE",
                   "has_password": True}}
    assert econsent.eligible([LEE], meta, {"P9": "lee@example.com"}) == []


def test_eligible_skips_directors_with_no_email():
    assert econsent.eligible([LEE], {}, {}) == []


def test_issue_stores_only_the_hash_and_supersedes_previous_links(db):
    first = econsent.issue("K1", [LEE], revision=1, expires_at=FUTURE)
    second = econsent.issue("K1", [LEE], revision=2, expires_at=FUTURE)
    rows = db.rows("officer_change_consents")
    assert len(rows) == 2 and first["N1"] != second["N1"]
    assert all(first["N1"] not in str(r) for r in rows)
    assert rows[0]["superseded_at"] and not rows[1].get("superseded_at")
    assert econsent.find(second["N1"])["revision"] == 2


def test_find_refuses_junk_and_unknown_tokens(db):
    assert econsent.find("short") is None
    assert econsent.find("x" * 43) is None


def test_usable_rules(db):
    token = econsent.issue("K1", [LEE], revision=1, expires_at=FUTURE)["N1"]
    row = econsent.find(token)
    assert econsent.usable(row) is True
    assert econsent.usable({**row, "superseded_at": "2026-10-01T00:00:00Z"}) is False
    assert econsent.usable({**row, "expires_at": PAST.isoformat()}) is False


def test_names_match_ignores_case_and_spacing():
    person = {"full_name": "LEE Ka Ho", "surname": "LEE", "given_names": "Ka Ho"}
    assert econsent.names_match("lee  ka ho", person)
    assert econsent.names_match(" LEE KA HO ", person)
    assert not econsent.names_match("LEE Ka", person)
    assert not econsent.names_match("", person)


def test_claim_is_first_signature_wins(db):
    token = econsent.issue("K1", [LEE], revision=1, expires_at=FUTURE)["N1"]
    row = econsent.find(token)
    first = econsent.claim(row["id"], typed_name="LEE Ka Ho", ip="203.0.113.5",
                           user_agent="UA")
    assert first["signed_at"] and first["signed_name"] == "LEE Ka Ho"
    assert econsent.claim(row["id"], typed_name="LEE Ka Ho", ip=None, user_agent=None) is None


def test_status_reports_sent_and_signed(db):
    token = econsent.issue("K1", [LEE], revision=1, expires_at=FUTURE)["N1"]
    assert econsent.status_for("K1")["N1"]["sent"] is True
    econsent.claim(econsent.find(token)["id"], typed_name="LEE Ka Ho", ip=None, user_agent=None)
    status = econsent.status_for("K1")["N1"]
    assert status["signed_at"] and status["signed_name"] == "LEE Ka Ho"


def test_supersede_spares_a_signed_consent(db):
    token = econsent.issue("K1", [LEE], revision=1, expires_at=FUTURE)["N1"]
    econsent.claim(econsent.find(token)["id"], typed_name="LEE Ka Ho", ip=None, user_agent=None)
    assert econsent.supersede("K1") == 0
    assert econsent.status_for("K1")["N1"]["signed_at"]


@pytest.fixture(scope="module")
def overflow_pdf():
    graph, entries = fx.combined_world("ND2A", fx.ND2A_OVERFLOW, fx.ND2A_OVERFLOW_RENAMES)
    xml = form_xml.build("Nd2a", nd2a_mapper.map_case(graph, entries))
    sheets = [p["sheet"] for p in page_plan("Nd2a", xml, public_only=True)]
    return render("Nd2a", xml, public_only=True, company_name="X"), sheets


def test_stamp_places_the_name_on_that_directors_consent_page(overflow_pdf):
    pdf, sheets = overflow_pdf
    out = econsent.stamp(pdf, sheets, consent_index=3, name="LEE Ka Ho",
                         when=datetime(2026, 10, 2, 6, 3, tzinfo=timezone.utc),
                         ip="203.0.113.5", user_agent="UA", case_no="ND2A-2026-0007",
                         revision=1)
    doc = pymupdf.open(stream=out)
    assert len(doc) == 2
    first = doc[0].get_text()
    assert "LEE Ka Ho" in first and "Signed electronically via G-FlowDesk" in first
    assert "02 Oct 2026 14:03 HKT" in first
    signed = doc[0].search_for("Signed electronically")[0]
    label = doc[0].search_for("Signed")[0]
    assert abs(signed.y0 - label.y0) < 30
    record = doc[1].get_text()
    assert "Signature record" in record and "203.0.113.5" in record
    assert "ND2A-2026-0007" in record


def test_stamp_first_natural_appointment_is_page_two(overflow_pdf):
    pdf, sheets = overflow_pdf
    out = econsent.stamp(pdf, sheets, consent_index=1, name="X Y", when=None, ip=None,
                         user_agent=None, case_no="C", revision=None)
    page = pymupdf.open(stream=out)[0]
    assert "Consent to Act" in page.get_text() or "Consent" in page.get_text()


def test_sign_refuses_a_wrong_name_before_writing(db):
    token = econsent.issue("K1", [LEE], revision=1, expires_at=FUTURE)["N1"]
    row = econsent.find(token)
    with pytest.raises(econsent.NameMismatch):
        asyncio.run(econsent.sign(row, {"id": "K1"}, LEE,
                                  {"full_name": "LEE Ka Ho"}, typed_name="WONG",
                                  ip=None, user_agent=None))
    assert not db.rows("officer_change_consents")[0].get("signed_at")


def test_sign_files_the_stamped_consent(db, monkeypatch):
    token = econsent.issue("K1", [LEE], revision=1, expires_at=FUTURE)["N1"]
    row = econsent.find(token)

    async def fake_pdf(case, entry, signed):
        return b"%PDF-stamped"

    uploads = []

    async def fake_upload(case, entry, **kwargs):
        uploads.append(kwargs)
        return {"id": "DOC-1"}

    monkeypatch.setattr(econsent, "consent_pdf", fake_pdf)
    monkeypatch.setattr(econsent.documents, "upload", fake_upload)
    out = asyncio.run(econsent.sign(row, {"id": "K1"}, LEE, {"full_name": "LEE Ka Ho"},
                                    typed_name="lee ka ho", ip="203.0.113.5",
                                    user_agent="UA"))
    assert out["document_id"] == "DOC-1" and out["error"] is None
    assert uploads[0]["document_type_code"] == "consent_to_act"
    assert uploads[0]["source"] == "econsent" and uploads[0]["user"] is None
    assert uploads[0]["uploaded_by_name"] == "lee ka ho"
    assert db.rows("officer_change_consents")[0]["document_id"] == "DOC-1"


def test_a_pdf_failure_still_records_the_signature(db, monkeypatch):
    token = econsent.issue("K1", [LEE], revision=1, expires_at=FUTURE)["N1"]
    row = econsent.find(token)

    async def broken(case, entry, signed):
        raise RuntimeError("renderer down")

    monkeypatch.setattr(econsent, "consent_pdf", broken)
    out = asyncio.run(econsent.sign(row, {"id": "K1"}, LEE, {"full_name": "LEE Ka Ho"},
                                    typed_name="LEE Ka Ho", ip=None, user_agent=None))
    assert out["document_id"] is None and "renderer down" in out["error"]
    assert db.rows("officer_change_consents")[0]["signed_at"]


def test_regenerate_files_the_pdf_a_failed_render_left_out(db, monkeypatch):
    token = econsent.issue("K1", [LEE], revision=1, expires_at=FUTURE)["N1"]
    econsent.claim(econsent.find(token)["id"], typed_name="LEE Ka Ho", ip=None, user_agent=None)

    async def fake_pdf(case, entry, signed):
        return b"%PDF"

    async def fake_upload(case, entry, **kwargs):
        return {"id": "DOC-2"}

    monkeypatch.setattr(econsent, "consent_pdf", fake_pdf)
    monkeypatch.setattr(econsent.documents, "upload", fake_upload)
    assert asyncio.run(econsent.regenerate({"id": "K1"}, LEE)) == "DOC-2"
    assert db.rows("officer_change_consents")[0]["document_id"] == "DOC-2"


def test_regenerate_refuses_an_unsigned_consent(db):
    econsent.issue("K1", [LEE], revision=1, expires_at=FUTURE)
    with pytest.raises(LookupError):
        asyncio.run(econsent.regenerate({"id": "K1"}, LEE))

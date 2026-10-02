"""The public consent-to-act page (Jacqueline A2): the Confirm page's rules —
no script, GET writes nothing, one 'unavailable' answer for every miss."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from routers import public_approval, public_consent as pc
from services.officer_changes import econsent
from tests.officer_changes.fakes import FakeSupabase

client = TestClient(app)
FUTURE = datetime.now(timezone.utc) + timedelta(days=5)
CASE = {"id": "K1", "case_no": "ND2A-2026-0007", "entity_id": "E1", "form_code": "Nd2a",
        "closed_at": None, "client_approved": None,
        "verification_xml": "<x/>", "verification_revision": 1}
ENTRY = {"id": "N1", "case_id": "K1", "kind": "appointment", "capacity": "director",
         "person_id": "P9", "party_type": "individual", "effective_date": None}
PERSON = {"id": "P9", "full_name": "LEE Ka Ho", "surname": "LEE", "given_names": "Ka Ho"}


@pytest.fixture
def world(monkeypatch):
    fake = FakeSupabase({"officer_change_consents": [], "officer_change_entries": [ENTRY],
                         "persons": [PERSON]})
    monkeypatch.setattr(econsent, "get_supabase", lambda: fake)
    monkeypatch.setattr(pc, "get_supabase", lambda: fake)
    public_approval._HITS.clear()
    state = {"case": dict(CASE)}
    monkeypatch.setattr(pc.nar1_cases, "get_case", lambda cid: dict(state["case"]))
    monkeypatch.setattr(pc.nar1_cases, "entity_for",
                        lambda eid: {"company_name": "Sample Trading Limited",
                                     "br_number": "12345678"})

    async def fake_pdf(case, entry, signed):
        return b"%PDF-stamped"

    async def fake_upload(case, entry, **kwargs):
        fake.tables.setdefault("officer_change_documents", []).append(
            {"id": "DOC-1", **{k: v for k, v in kwargs.items() if k != "content"}})
        return {"id": "DOC-1"}

    monkeypatch.setattr(econsent, "consent_pdf", fake_pdf)
    monkeypatch.setattr(econsent.documents, "upload", fake_upload)
    token = econsent.issue("K1", [ENTRY], revision=1, expires_at=FUTURE)["N1"]
    with patch.object(pc, "log_event", new_callable=AsyncMock) as audit:
        yield {"db": fake, "token": token, "audit": audit, "state": state}


def _path(token):
    return f"/public/officer-consent/{token}"


def test_get_shows_the_statement_and_writes_nothing(world):
    before = str(world["db"].tables)
    resp = client.get(_path(world["token"]))
    assert resp.status_code == 200
    assert ("I consent to act as director of this company and confirm that I have "
            "attained the age of 18 years.") in resp.text
    assert "LEE Ka Ho" in resp.text and "Sample Trading Limited" in resp.text
    assert "To be confirmed" in resp.text
    assert str(world["db"].tables) == before
    world["audit"].assert_not_awaited()
    assert resp.headers["cache-control"].startswith("no-store")


def test_page_runs_no_script_and_never_carries_the_token(world):
    resp = client.get(_path(world["token"]))
    assert "<script" not in resp.text.lower() and "onclick" not in resp.text.lower()
    assert world["token"] not in resp.text


def test_unknown_token_is_the_one_unavailable_page(world):
    miss = client.get(_path("x" * 43))
    junk = client.get(_path("short"))
    assert miss.status_code == junk.status_code == 200
    assert "no longer available" in miss.text and miss.text == junk.text


def test_sign_records_and_files_the_consent(world):
    resp = client.post(_path(world["token"]), data={"full_name": "LEE Ka Ho", "agree": "on"},
                       headers={"x-forwarded-for": "203.0.113.5"})
    assert resp.status_code == 200 and "your consent is recorded" in resp.text
    row = world["db"].rows("officer_change_consents")[0]
    assert row["signed_at"] and row["signed_name"] == "LEE Ka Ho"
    assert row["document_id"] == "DOC-1"
    audit = world["audit"].await_args.kwargs
    assert audit["action_type"] == "OFFICER_ECONSENT_SIGNED"
    assert audit["user_id"] is None and audit["user_display_name"] == "LEE Ka Ho"
    assert audit["metadata"]["entry_id"] == "N1" and "ip_address" in audit["metadata"]


def test_name_check_ignores_case_and_spacing(world):
    resp = client.post(_path(world["token"]), data={"full_name": "lee  ka ho", "agree": "on"})
    assert "your consent is recorded" in resp.text


def test_wrong_name_is_refused_and_nothing_changes(world):
    resp = client.post(_path(world["token"]), data={"full_name": "WONG Mei Ling",
                                                    "agree": "on"})
    assert resp.status_code == 200 and "must match the name on the form" in resp.text
    assert not world["db"].rows("officer_change_consents")[0].get("signed_at")
    world["audit"].assert_not_awaited()


def test_the_statement_must_be_ticked(world):
    resp = client.post(_path(world["token"]), data={"full_name": "LEE Ka Ho"})
    assert "Tick the statement" in resp.text
    assert not world["db"].rows("officer_change_consents")[0].get("signed_at")


def test_consent_still_works_after_another_director_confirmed(world):
    """Review Focus 2: Confirm supersedes Confirm links only."""
    world["state"]["case"] = {**CASE, "client_approved": True}
    assert "I consent to act" in client.get(_path(world["token"])).text
    resp = client.post(_path(world["token"]), data={"full_name": "LEE Ka Ho", "agree": "on"})
    assert "your consent is recorded" in resp.text


def test_closed_case_link_is_unavailable(world):
    world["state"]["case"] = {**CASE, "closed_at": "2026-10-02T00:00:00Z"}
    assert "no longer available" in client.get(_path(world["token"])).text
    resp = client.post(_path(world["token"]), data={"full_name": "LEE Ka Ho", "agree": "on"})
    assert "no longer available" in resp.text
    assert not world["db"].rows("officer_change_consents")[0].get("signed_at")


def test_a_superseded_link_is_unavailable(world):
    econsent.supersede("K1")
    assert "no longer available" in client.get(_path(world["token"])).text


def test_signing_twice_shows_it_is_already_recorded(world):
    client.post(_path(world["token"]), data={"full_name": "LEE Ka Ho", "agree": "on"})
    again = client.get(_path(world["token"]))
    assert "already recorded" in again.text

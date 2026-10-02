"""Supporting documents held on the case, then filed to each officer's profile
(spec §6, answers 7, 11, 13; Review Focus 4)."""
import asyncio

import pytest

from services import document_service
from services.officer_changes import documents
from tests.officer_changes.fakes import FakeSupabase

USER = {"id": "U1", "display_name": "Staff"}
CASE = {"id": "K1", "case_no": "ND2A-2026-0001", "entity_id": "E1", "form_code": "Nd2a"}
LEAVER = {"id": "N1", "case_id": "K1", "kind": "cessation", "person_id": "P1",
          "corporate_entity_id": None, "party": {"name": "CHAN Tai Man"}}
JOINER = {"id": "N2", "case_id": "K1", "kind": "appointment", "person_id": None,
          "corporate_entity_id": "C9", "party": {"name": "Corp Director Limited"}}


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase({
        "officer_change_documents": [], "officer_change_entries": [LEAVER, JOINER],
        "document_types": [{"code": "resignation_letter", "label": "Resignation letter"},
                           {"code": "board_resolution", "label": "Board resolution"}],
        "persons": [{"id": "P1", "full_name": "CHAN Tai Man"}],
        "entities": [{"id": "C9", "company_name": "Corp Director Limited"}],
    })
    monkeypatch.setattr(documents, "get_supabase", lambda: fake)
    return fake


def _upload(entry=LEAVER, code="resignation_letter", case=CASE, content=b"%PDF-1"):
    return asyncio.run(documents.upload(case, entry, document_type_code=code,
                                        file_name="letter.pdf", content=content,
                                        mime_type="application/pdf", user=USER))


def test_upload_holds_the_file_under_the_case_not_the_profile(db):
    row = _upload()
    assert row["storage_path"].startswith("officer-change/K1/N1/")
    assert row["storage_path"].endswith("-letter.pdf")
    assert (document_service.BUCKET, row["storage_path"]) in db.storage.objects
    assert row["checksum_sha256"] and row["file_size_bytes"] == 6


@pytest.mark.parametrize("kwargs, message", [
    ({"code": "id_hkid"}, "supporting document"),
    ({"content": b""}, "empty"),
    ({"case": {**CASE, "changes_applied_at": "2026-10-01T00:00:00Z"}}, "filed"),
    ({"entry": {**LEAVER, "case_id": "OTHER"}}, "not on this case"),
])
def test_upload_refusals(db, kwargs, message):
    with pytest.raises(ValueError, match=message):
        _upload(**kwargs)


def test_list_names_each_file_and_where_it_will_go(db):
    _upload()
    _upload(entry=JOINER, code="board_resolution")
    rows = documents.list_for_case("K1")
    assert [r["type_label"] for r in rows] == ["Resignation letter", "Board resolution"]
    assert rows[0]["destination"] == {"owner_kind": "person", "owner_id": "P1",
                                      "name": "CHAN Tai Man"}
    assert rows[1]["destination"]["owner_kind"] == "entity"
    assert rows[0]["filed"] is False


def test_remove_before_filing_deletes_the_row_and_the_object(db):
    row = _upload()
    documents.remove(CASE, row["id"])
    assert documents.list_for_case("K1") == []
    assert db.storage.objects == {}


def test_a_filed_document_cannot_be_removed_from_the_case(db):
    row = _upload()
    db.tables["officer_change_documents"][0]["filed_at"] = "2026-10-01T00:00:00Z"
    with pytest.raises(ValueError, match="profile"):
        documents.remove(CASE, row["id"])


def test_signed_url_downloads_the_held_file(db):
    row = _upload()
    assert documents.signed_url(row).endswith(row["storage_path"])


def test_filing_puts_each_file_on_its_officers_profile_once(db, monkeypatch):
    calls = []

    async def fake_upload(**kwargs):
        calls.append(kwargs)
        return {"id": f"DOC-{len(calls)}", "current_version": 1}

    monkeypatch.setattr(documents.document_service, "upload_document", fake_upload)
    _upload()
    _upload(entry=JOINER, code="board_resolution")
    out = asyncio.run(documents.file_to_profiles(CASE, [LEAVER, JOINER], user=USER))
    assert [c["owner_kind"] for c in calls] == ["person", "entity"]
    assert calls[0]["owner_id"] == "P1" and calls[0]["content"] == b"%PDF-1"
    assert calls[0]["title"] == "ND2A-2026-0001 — Resignation letter"
    assert all(r["error"] is None and r["filed"] for r in out)
    assert out[0]["filed_document_id"] == "DOC-1"
    # A second run files nothing twice.
    asyncio.run(documents.file_to_profiles(CASE, [LEAVER, JOINER], user=USER))
    assert len(calls) == 2


def test_one_failure_is_reported_and_the_rest_still_file(db, monkeypatch):
    async def fake_upload(**kwargs):
        if kwargs["owner_kind"] == "person":
            raise RuntimeError("storage down")
        return {"id": "DOC-9", "current_version": 2}

    monkeypatch.setattr(documents.document_service, "upload_document", fake_upload)
    _upload()
    _upload(entry=JOINER, code="board_resolution")
    out = asyncio.run(documents.file_to_profiles(CASE, [LEAVER, JOINER], user=USER))
    assert "storage down" in out[0]["error"] and out[0]["filed"] is False
    assert out[1]["error"] is None and out[1]["filed_document_version"] == 2


def test_filing_never_raises_even_when_the_table_cannot_be_read(monkeypatch):
    def boom():
        raise RuntimeError("database down")
    monkeypatch.setattr(documents, "get_supabase", boom)
    out = asyncio.run(documents.file_to_profiles(CASE, [], user=USER))
    assert out and "database down" in out[0]["error"]

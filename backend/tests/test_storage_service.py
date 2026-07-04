import hashlib
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from services.storage_service import (
    BUCKET,
    build_object_path,
    ensure_bucket,
    signed_url,
    store_document,
    sweep_orphans,
)


def test_build_object_path_scopes_and_ext():
    p = build_object_path("e1", "nar1", "Annual.PDF")
    assert p.startswith("entities/e1/nar1/")
    assert p.endswith(".pdf")
    assert build_object_path(None, "id_scan", None).startswith("unassigned/id_scan/")


def test_store_document_uploads_then_commits():
    content = b"hello world"
    with patch("services.storage_service.get_supabase") as msb, patch(
        "services.storage_service.insert_document"
    ) as mins:
        sb = MagicMock()
        msb.return_value = sb
        mins.return_value = {"id": "doc-1"}

        row = store_document(
            content=content,
            document_type_code="nar1",
            entity_id="e1",
            file_name="a.pdf",
            mime_type="application/pdf",
            uploaded_by="u1",
        )

        assert row["id"] == "doc-1"
        # object uploaded to the private bucket
        sb.storage.from_.assert_called_with(BUCKET)
        assert sb.storage.from_.return_value.upload.called
        # DB row committed AFTER upload, carrying checksum + size
        created = mins.call_args[0][0]
        assert created.file_size_bytes == len(content)
        assert created.checksum_sha256 == hashlib.sha256(content).hexdigest()
        assert created.storage_bucket == BUCKET


def test_store_document_deletes_orphan_on_commit_failure():
    with patch("services.storage_service.get_supabase") as msb, patch(
        "services.storage_service.insert_document"
    ) as mins:
        sb = MagicMock()
        msb.return_value = sb
        mins.side_effect = RuntimeError("db down")

        with pytest.raises(RuntimeError):
            store_document(content=b"x", document_type_code="other", file_name="x.bin")

        # the uploaded object must be removed to avoid an orphan
        assert sb.storage.from_.return_value.remove.called


def test_signed_url_normalizes_key():
    with patch("services.storage_service.get_supabase") as msb:
        sb = MagicMock()
        msb.return_value = sb
        sb.storage.from_.return_value.create_signed_url.return_value = {"signedURL": "https://x/y"}
        assert signed_url("path/obj.pdf") == "https://x/y"


def test_ensure_bucket_creates_when_absent():
    with patch("services.storage_service.get_supabase") as msb:
        sb = MagicMock()
        msb.return_value = sb
        sb.storage.list_buckets.return_value = []
        ensure_bucket()
        sb.storage.create_bucket.assert_called_once()


def test_ensure_bucket_noop_when_present():
    with patch("services.storage_service.get_supabase") as msb:
        sb = MagicMock()
        msb.return_value = sb
        sb.storage.list_buckets.return_value = [SimpleNamespace(id=BUCKET)]
        ensure_bucket()
        sb.storage.create_bucket.assert_not_called()


def test_sweep_orphans_removes_unreferenced_objects():
    with patch("services.storage_service.get_supabase") as msb:
        sb = MagicMock()
        msb.return_value = sb
        sb.storage.from_.return_value.list.return_value = [{"name": "a"}, {"name": "b"}]
        # _known_storage_paths: only "a" is referenced by a DB row
        sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
            {"storage_path": "a"}
        ]

        orphans = sweep_orphans(prefix="")

        assert orphans == ["b"]
        sb.storage.from_.return_value.remove.assert_called_with(["b"])

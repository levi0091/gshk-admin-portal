"""PBI-39 documents — upload/versioning/download/soft-delete via the real routes.

Exercises companies.py + persons.py upload routes and documents.py download/delete,
all delegating to services.document_service. Supabase Storage + audit are mocked.
"""
from unittest.mock import patch, MagicMock, AsyncMock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

SUPER_ADMIN = {"id": "admin-1", "display_name": "Levi Z.", "role_name": "super_admin", "role_id": "role-sa"}
REGULAR = {"id": "u-2", "display_name": "Staff", "role_name": "staff", "role_id": "role-x"}
H = {"Authorization": "Bearer tok"}
FILE = {"file": ("proof.pdf", b"%PDF-bytes", "application/pdf")}


def _no_existing(sb):
    """documents select (existing-of-type) chain resolves to no rows."""
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = []


def test_upload_company_document_new_creates_version_1_and_audits():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("services.document_service.get_supabase") as msb, \
         patch("services.document_service.log_event", new=AsyncMock()) as audit:
        sb = msb.return_value
        _no_existing(sb)
        sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "doc-1", "entity_id": "e1", "current_version": 1}]
        resp = client.post("/companies/e1/documents", files=FILE,
                           data={"document_type_code": "coi"}, headers=H)
        assert resp.status_code == 201
        assert audit.await_args.kwargs["action_type"] == "DOCUMENT_UPLOADED"
        # polymorphic owner: documents insert carries entity_id, not person_id
        first_insert = sb.table.return_value.insert.call_args_list[0][0][0]
        assert first_insert["entity_id"] == "e1" and "person_id" not in first_insert
        # storage received the object
        sb.storage.from_.return_value.upload.assert_called_once()


def test_reupload_existing_type_creates_new_version():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("services.document_service.get_supabase") as msb, \
         patch("services.document_service.log_event", new=AsyncMock()) as audit:
        sb = msb.return_value
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "doc-1", "entity_id": "e1", "current_version": 1, "title": "t"}]
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "doc-1", "current_version": 2}]
        resp = client.post("/companies/e1/documents", files=FILE,
                           data={"document_type_code": "coi"}, headers=H)
        assert resp.status_code == 201
        assert resp.json()["current_version"] == 2
        assert audit.await_args.kwargs["action_type"] == "DOCUMENT_VERSION_ADDED"
        assert audit.await_args.kwargs["metadata"]["version"] == 2


def test_person_upload_anchors_to_person():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("services.document_service.get_supabase") as msb, \
         patch("services.document_service.log_event", new=AsyncMock()):
        sb = msb.return_value
        _no_existing(sb)
        sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "doc-2", "person_id": "p1"}]
        resp = client.post("/persons/p1/documents", files={"file": ("id.jpg", b"img", "image/jpeg")},
                           data={"document_type_code": "id_scan"}, headers=H)
        assert resp.status_code == 201
        first_insert = sb.table.return_value.insert.call_args_list[0][0][0]
        assert first_insert["person_id"] == "p1" and "entity_id" not in first_insert


def test_list_company_documents():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("services.document_service.get_supabase") as msb:
        msb.return_value.table.return_value.select.return_value.neq.return_value.eq.return_value.order.return_value.execute.return_value.data = [
            {"id": "doc-1", "document_type_code": "coi", "document_versions": []}]
        resp = client.get("/companies/e1/documents", headers=H)
        assert resp.status_code == 200 and len(resp.json()) == 1


def test_download_returns_signed_url():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("services.document_service.get_supabase") as msb:
        sb = msb.return_value
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "id": "doc-1", "storage_bucket": "gflowdesk-documents",
            "storage_path": "entity/e1/coi/1/x.pdf", "status": "active", "file_name": "x.pdf"}
        sb.storage.from_.return_value.create_signed_url.return_value = {"signedURL": "https://signed/x"}
        resp = client.get("/documents/doc-1/download", headers=H)
        assert resp.status_code == 200 and resp.json()["url"] == "https://signed/x"


def test_download_deleted_document_404():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("services.document_service.get_supabase") as msb:
        msb.return_value.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "id": "doc-1", "status": "deleted", "storage_path": "x"}
        assert client.get("/documents/doc-1/download", headers=H).status_code == 404


def test_delete_soft_deletes_and_audits():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("services.document_service.get_supabase") as msb, \
         patch("services.document_service.log_event", new=AsyncMock()) as audit:
        sb = msb.return_value
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "id": "doc-1", "entity_id": "e1", "status": "active"}
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "doc-1", "status": "deleted"}]
        resp = client.delete("/documents/doc-1", headers=H)
        assert resp.status_code == 200
        assert audit.await_args.kwargs["action_type"] == "DOCUMENT_DELETED"


def test_delete_requires_delete_permission():
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb:
        # role has documents read+write but NOT delete
        msb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"permission": "read"}, {"permission": "write"}]
        assert client.delete("/documents/doc-1", headers=H).status_code == 403


def test_list_document_types():
    """Drives the upload type picker; must not be matched as a document id."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.documents.get_supabase") as msb:
        msb.return_value.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
            {"code": "coi", "label": "Certificate of Incorporation"}]
        resp = client.get("/documents/types", headers=H)
        assert resp.status_code == 200
        assert resp.json()[0]["code"] == "coi"


def test_upload_requires_write_permission():
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb:
        msb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        resp = client.post("/companies/e1/documents", files=FILE,
                           data={"document_type_code": "coi"}, headers=H)
        assert resp.status_code == 403

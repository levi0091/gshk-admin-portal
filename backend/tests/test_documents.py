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


# --------------------------------------------------------------------------- #
#  A document is GATED BY ITS OWNER'S MODULE (Levi 2026-09-07, migration 040).
#
#  There is no `documents` permission module. The right to read a record is the
#  right to read the papers filed against it, and the right to change the record
#  is the right to add and remove them — see services/document_permissions.py.
#
#  `documents:delete` has no successor level: neither `companies` nor `persons`
#  has one, so removing a document is a WRITE on the owning record.
# --------------------------------------------------------------------------- #


def _as(grants, owner=None):
    """Sign in as a plain role holding `grants` ({module: [levels]}), over a
    document owned by `owner`.

    THE PERMISSION MOCK IS MODULE-AWARE, and that is the whole point of this
    block. A mock that answered the same rows for every module would make
    "documents are gated by their owner" untestable: the role would hold
    `read` on persons and companies alike, and a route that asked for the wrong
    module would pass. So the second `.eq("module", ...)` decides what comes
    back, and the real `_permissions_for` still does the asking.

    TWO SEPARATE DATABASE READERS, patched separately and on purpose: the owner
    lookup is `services.document_permissions.get_supabase` and the permission
    lookup is `middleware.auth.get_supabase`. One module-wide patch would make
    every predicate built on it true.
    """
    perms = MagicMock()

    def by_module(_column, module):
        step = MagicMock()
        step.execute.return_value.data = [
            {"permission": p} for p in grants.get(module, ())]
        return step

    perms.table.return_value.select.return_value.eq.return_value.eq.side_effect = (
        by_module)

    docs = MagicMock()
    (docs.table.return_value.select.return_value.eq.return_value.limit.return_value
     .execute.return_value.data) = [owner] if owner else []

    return (patch("middleware.auth._resolve_user", return_value=REGULAR),
            patch("middleware.auth.get_supabase", return_value=perms),
            patch("services.document_permissions.get_supabase", return_value=docs))


class _Stack:
    def __init__(self, *cms):
        self.cms = cms

    def __enter__(self):
        for cm in self.cms:
            cm.__enter__()

    def __exit__(self, *exc):
        for cm in reversed(self.cms):
            cm.__exit__(*exc)


COMPANY_DOC = {"entity_id": "e1", "person_id": None, "nar1_case_id": None}
PERSON_DOC = {"entity_id": None, "person_id": "p1", "nar1_case_id": None}


def test_deleting_a_company_document_needs_companies_write():
    """`companies:read` opens the company and its papers. It does not remove
    them — that is a change to what the record holds."""
    with _Stack(*_as({"companies": ["read"]}, COMPANY_DOC)):
        # The permission cache is keyed by (role_id, module); a role_id reused
        # across tests would answer from a previous test's grants.
        from middleware.auth import _perm_cache
        _perm_cache.clear()
        assert client.delete("/documents/doc-1", headers=H).status_code == 403


def test_companies_write_can_remove_a_company_document():
    """The other half, and the bug this replaced: a role granted Companies
    (edit) could not touch the papers on a company it was trusted to edit."""
    with _Stack(*_as({"companies": ["read", "write"]}, COMPANY_DOC)), \
         patch("services.document_service.get_supabase") as msb, \
         patch("services.document_service.log_event", new=AsyncMock()):
        from middleware.auth import _perm_cache
        _perm_cache.clear()
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value.single
         .return_value.execute.return_value.data) = {
            "id": "doc-1", "entity_id": "e1", "status": "active"}
        (sb.table.return_value.update.return_value.eq.return_value
         .execute.return_value.data) = [{"id": "doc-1", "status": "deleted"}]
        assert client.delete("/documents/doc-1", headers=H).status_code == 200


def test_a_persons_paper_is_refused_to_a_role_holding_only_companies():
    """The module is read off the DOCUMENT, not off the caller's best grant. A
    role that may read companies has no business downloading a director's
    identity scan."""
    with _Stack(*_as({"companies": ["read"]}, PERSON_DOC)):
        from middleware.auth import _perm_cache
        _perm_cache.clear()
        # The role's one grant is on `companies`; the document is a person's,
        # so `persons:read` is what is asked for and the role does not hold it.
        assert client.get("/documents/doc-1/download",
                          headers=H).status_code == 403


def test_a_document_owned_by_nothing_is_refused_rather_than_waved_through():
    """FAILS CLOSED. These routes sign URLs for identity scans; a row that
    cannot be attributed to a record has no permissions that could allow it."""
    with _Stack(*_as({"companies": ["read", "write"], "persons": ["read", "write"]},
                     {"entity_id": None, "person_id": None,
                      "nar1_case_id": None})):
        from middleware.auth import _perm_cache
        _perm_cache.clear()
        assert client.get("/documents/doc-1/download",
                          headers=H).status_code == 403


def test_an_unknown_document_is_404_not_403():
    """403 here would confirm to an unauthorised caller that the id exists —
    and it is what the route would have answered anyway on reading it."""
    with _Stack(*_as({"companies": ["read", "write"]}, None)):
        from middleware.auth import _perm_cache
        _perm_cache.clear()
        assert client.get("/documents/doc-1/download",
                          headers=H).status_code == 404


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


# --------------------------------------------------------------------------- #
#  A document is filed under its OWNER's module (Levi 2026-09-04).
#
#  There is no `documents` module. The screen showed why: an id scan uploaded
#  against Brian YIU sat under "Documents" directly above an edit to Brian YIU
#  under "Natural Person" — the same person, the same afternoon, two filter
#  values. Nothing below asserts a NEW module; every assertion is that a
#  document row lands on the SAME module that record's own edits already do.
# --------------------------------------------------------------------------- #
def _audit_owner(owner_kind, owner_id):
    """`document_service._audit_owner` against a mocked Supabase.

    The chained MagicMock resolves every `.data` to a MagicMock, so the names
    come out meaningless — irrelevant here, because `module` and `subject_kind`
    are literals chosen by the branch, and the branch is what is under test.
    """
    from services import document_service
    with patch("services.document_service.get_supabase") as msb:
        return document_service._audit_owner(msb.return_value, owner_kind, owner_id)


def test_a_person_owned_document_is_a_natural_person_row():
    out = _audit_owner("person", "p-1")
    assert out["module"] == "natural_person"
    assert out["subject_kind"] == "person"


def test_a_company_owned_document_is_a_body_corporate_row():
    out = _audit_owner("entity", "e-1")
    assert out["module"] == "body_corporate"
    assert out["subject_kind"] == "company"


def test_a_case_owned_receipt_is_a_post_incorporation_row():
    """A CR receipt is an artefact of one filing, so it files under the
    workflow — not under the company, and not under a module of its own."""
    out = _audit_owner("receipt", "c-1")
    assert out["module"] == "post_incorporation"
    assert out["subject_kind"] == "case"


def test_an_upload_through_the_real_route_writes_the_owners_module():
    """The row the operator actually complained about, end to end."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("services.document_service.get_supabase") as msb, \
         patch("services.document_service.log_event", new=AsyncMock()) as audit:
        sb = msb.return_value
        _no_existing(sb)
        sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "doc-1", "person_id": "p-1", "current_version": 1}]
        resp = client.post("/persons/p-1/documents", files=FILE,
                           data={"document_type_code": "id_scan"}, headers=H)
        assert resp.status_code == 201
        assert audit.await_args.kwargs["module"] == "natural_person"

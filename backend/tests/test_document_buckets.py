"""Document buckets (GSHK 2026-11-21, migration 065).

Drop many files into a bucket with no type to choose; tag, describe and move
them afterwards in bulk. Supabase, Storage and the audit writer are mocked.
"""
import importlib.util
import pathlib
import re
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from services import audit_events, document_sections, document_service

client = TestClient(app)

SUPER_ADMIN = {"id": "admin-1", "display_name": "Levi Z.",
               "role_name": "super_admin", "role_id": "role-sa"}
READ_ONLY = {"id": "u-3", "display_name": "Reader", "role_name": "reader",
             "role_id": "role-r"}
H = {"Authorization": "Bearer tok"}


@pytest.fixture(autouse=True)
def _owners_are_live():
    live = MagicMock()
    (live.table.return_value.select.return_value.eq.return_value
     .execute.return_value.data) = [{"id": "owner", "deleted_at": None}]
    with patch("routers.companies.get_supabase", return_value=live), \
         patch("routers.persons.get_supabase", return_value=live):
        yield


# ── the vocabulary ──────────────────────────────────────────────────────────

def test_the_migration_checks_exactly_the_buckets_the_code_knows():
    path = pathlib.Path(__file__).parent.parent / "alembic/versions/065_document_buckets.py"
    spec = importlib.util.spec_from_file_location("m065", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # 065 also allows `other`, the fallback bucket retired the same day it
    # shipped (Levi 2026-11-21). It is never written again: no route accepts it.
    assert set(mod.BUCKET_KEYS) == set(document_sections.BUCKET_KEYS) \
        | document_sections.RETIRED_BUCKETS
    assert not set(document_sections.BUCKET_KEYS) & document_sections.RETIRED_BUCKETS
    assert mod.AUDIT_CODE[0] == audit_events.GF_DOC_UPDATED
    assert (mod.revision, mod.down_revision) == ("065", "064")

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    ini = pathlib.Path(__file__).parent.parent / "alembic.ini"
    assert ScriptDirectory.from_config(Config(str(ini))).get_heads() == ["066"]


def test_the_migration_seeds_its_audit_code_as_g_flowdesk():
    """An unseeded code renders with a blank Action (migrations 022, 034), and
    the column default would file it as Viewpoint history."""
    path = pathlib.Path(__file__).parent.parent / "alembic/versions/065_document_buckets.py"
    sql = []
    spec = importlib.util.spec_from_file_location("m065b", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with patch.object(mod, "op") as op:
        mod.upgrade()
        sql = " ".join(c[0][0] for c in op.execute.call_args_list)
    assert "GF_DOC_UPDATED" in sql and "'g_flowdesk'" in sql and "'document'" in sql
    assert "tags text[] NOT NULL DEFAULT '{}'" in sql
    assert "CHECK (bucket IS NULL OR bucket IN (" in sql


def test_a_company_has_gshks_six_buckets_in_their_order():
    keys = [b["key"] for b in document_sections.buckets_for("company")
            if not b.get("fallback")]
    assert keys == ["annual_return", "corporate_identity", "br_renewal",
                    "maintenance", "payments", "incorporation"]


@pytest.mark.parametrize("code, category, bucket", [
    ("nar1", "government_form", "annual_return"),
    ("approval_receipt", "government_form", "annual_return"),
    ("nnc1", "government_form", "incorporation"),
    ("coi", "certificate", "incorporation"),
    ("aoa", "statutory", "incorporation"),
    ("nd2a", "government_form", "maintenance"),
    ("resignation_letter", "officer_change", "maintenance"),
    ("addr_utility_bill", "address_proof", "corporate_identity"),
    # Nothing is left outside GSHK's buckets (Levi 2026-11-21).
    ("other", "internal", "corporate_identity"),
    ("never_seen", None, "corporate_identity"),
])
def test_a_typed_company_document_is_placed_by_its_type(code, category, bucket):
    doc = {"document_type_code": code, "document_types": {"category": category}}
    assert document_sections.bucket_of("company", doc) == bucket


@pytest.mark.parametrize("title, file_name, bucket", [
    ("ND2A-2026-0001 — CR receipt", "Primevector Limited - ND2A 2026.pdf", "maintenance"),
    (None, "Skyline NAR1 2026 receipt.pdf", "annual_return"),
    ("NNC1 receipt", None, "incorporation"),
    (None, None, "maintenance"),
])
def test_a_company_cr_receipt_goes_where_its_filing_went(title, file_name, bucket):
    doc = {"document_type_code": "cr_receipt", "document_types": {"category": "filing"},
           "title": title, "file_name": file_name}
    assert document_sections.bucket_of("company", doc) == bucket


@pytest.mark.parametrize("code, category", [
    ("cr_receipt", "filing"), ("resignation_letter", "officer_change"),
    ("consent_to_act", "officer_change"), ("other", "internal"), ("nd2a", "government_form"),
    ("addr_utility_bill", "address_proof"), ("never_seen", None),
])
def test_everything_on_a_person_but_identity_is_in_the_one_bucket(code, category):
    doc = {"document_type_code": code, "document_types": {"category": category}}
    assert document_sections.bucket_of("person", doc) == "kyc"


def test_a_row_stored_under_the_retired_fallback_is_placed_by_its_type():
    doc = {"bucket": "other", "document_type_code": "nd2b",
           "document_types": {"category": "government_form"}}
    assert document_sections.bucket_of("company", doc) == "maintenance"


def test_no_owner_has_a_fallback_bucket():
    for owner in ("company", "person"):
        assert not any(b.get("fallback") for b in document_sections.buckets_for(owner))


def test_a_chosen_bucket_beats_the_type():
    doc = {"bucket": "payments", "document_type_code": "nar1",
           "document_types": {"category": "government_form"}}
    assert document_sections.bucket_of("company", doc) == "payments"


def test_a_bucket_from_the_other_owner_type_is_not_honoured():
    doc = {"bucket": "payments", "document_type_code": "addr_utility_bill",
           "document_types": {"category": "address_proof"}}
    assert document_sections.bucket_of("person", doc) == "kyc"


def test_a_persons_identity_scan_is_in_no_bucket():
    """It renders on its identity record, not in KYC & AML."""
    for code in ("id_passport", "id_scan"):
        doc = {"document_type_code": code, "document_types": {"category": "identity"}}
        assert document_sections.bucket_of("person", doc) is None


@pytest.mark.parametrize("name, size, refused", [
    ("minutes.docx", 10, None),
    ("ledger.xlsx", 10, None),
    ("deck.pptx", 10, None),
    ("notes.txt", 10, None),
    ("export.csv", 10, None),
    ("scan.HEIC", 10, None),
    ("email.msg", 10, None),
    ("page.html", 10, None),
    ("no-extension", 10, None),
    ("payload.EXE", 10, ".exe files can run code"),
    ("macro.js", 10, ".js files can run code"),
    ("empty.pdf", 0, "The file is empty"),
    ("huge.pdf", document_sections.MAX_FILE_BYTES + 1, "larger than 50 MB"),
])
def test_uploads_are_refused_only_for_what_runs_or_cannot_be_stored(name, size, refused):
    reason = document_sections.upload_refusal(name, size)
    if refused is None:
        assert reason is None
    else:
        assert refused in reason


def test_tags_are_trimmed_and_deduplicated_ignoring_case():
    assert document_sections.normalise_tags(
        ["  Filed  ND2A ", "filed nd2a", "", None, "Payment Slip"]) == [
        "Filed ND2A", "Payment Slip"]


# ── upload into a bucket ────────────────────────────────────────────────────

def _bucket_upload(path, data, *, user=SUPER_ADMIN, name="slip.pdf", body=b"%PDF"):
    with patch("middleware.auth._resolve_user", return_value=user), \
         patch("services.document_service.get_supabase") as msb, \
         patch("services.document_service.log_event", new=AsyncMock()) as audit:
        sb = msb.return_value
        sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "doc-9", "created_at": "2026-11-21T04:00:00+00:00"}]
        resp = client.post(path, files={"file": (name, body, "application/pdf")},
                           data=data, headers=H)
        return resp, sb, audit


def test_a_bucket_upload_is_always_a_new_document():
    resp, sb, audit = _bucket_upload("/companies/e1/documents", {"bucket": "payments"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["bucket"] == "payments"
    row = sb.table.return_value.insert.call_args_list[0][0][0]
    assert row["bucket"] == "payments"
    assert row["document_type_code"] == "other"
    assert row["entity_id"] == "e1"
    # Never looked for an existing document of the type to version over: the
    # only select is the audit row's lookup of the company's name.
    assert all(c[0] == ("id, company_name, br_number",)
               for c in sb.table.return_value.select.call_args_list)
    assert audit.await_args.kwargs["event_code"] == audit_events.GF_DOC_UPLOADED
    assert "Payments" in audit.await_args.kwargs["new_value"]


def test_two_files_of_one_name_get_two_storage_paths():
    _r1, sb1, _ = _bucket_upload("/companies/e1/documents", {"bucket": "payments"})
    _r2, sb2, _ = _bucket_upload("/companies/e1/documents", {"bucket": "payments"})
    p1 = sb1.storage.from_.return_value.upload.call_args[0][0]
    p2 = sb2.storage.from_.return_value.upload.call_args[0][0]
    assert p1 != p2 and p1.endswith("/slip.pdf") and "/bucket/payments/" in p1


# ── storage keys: Storage refuses most of what a file name holds ────────────

#: Supabase Storage's own key rule (storage-api `isValidKey`); `\w` is ASCII.
#: Measured on DEV 2026-11-21: "—", "–", "é", Chinese, # % [ ] { } ^ ~ | < >
#: each answer 400 InvalidKey.
_STORAGE_KEY_OK = re.compile(r"^(\w|/|!|-|\.|\*|'|\(|\)| |&|\$|@|=|;|:|\+|,|\?)*$", re.ASCII)

CR_FORM_NAME = "ND2A Notification — Form ND2A _ XXXXXX LIMITED.pdf"


@pytest.mark.parametrize("name, key", [
    (CR_FORM_NAME, "ND2A Notification - Form ND2A _ XXXXXX LIMITED.pdf"),
    ("ND2B Notification – Form ND2B.pdf", "ND2B Notification - Form ND2B.pdf"),
    ("Café résumé.PDF", "Cafe resume.pdf"),
    ("中文文件.pdf", "file.pdf"),
    ("公司 NAR1 2026.pdf", "NAR1 2026.pdf"),
    ("a#b%c[d]{e}^f~g|h<i>.xlsx", "a_b_c_d_e_f_g_h_i.xlsx"),
    ("../../etc/passwd", "etc_passwd"),
    ("no extension", "no extension"),
    ("", "file"),
    (None, "file"),
    ("x" * 300 + ".pdf", "x" * 100 + ".pdf"),
])
def test_a_storage_key_is_what_storage_accepts(name, key):
    got = document_service.storage_name(name)
    assert got == key
    assert _STORAGE_KEY_OK.match(got) and "/" not in got


def test_a_cr_form_pdf_uploads_and_keeps_its_own_name():
    """The 2026-11-21 failure: CR names its form PDFs with an em dash."""
    resp, sb, _ = _bucket_upload("/companies/e1/documents", {"bucket": "maintenance"},
                                 name=CR_FORM_NAME)
    assert resp.status_code == 201, resp.text
    key = sb.storage.from_.return_value.upload.call_args[0][0]
    assert _STORAGE_KEY_OK.match(key), key
    row = sb.table.return_value.insert.call_args_list[0][0][0]
    assert row["file_name"] == CR_FORM_NAME          # the name nobody sees changed
    assert row["storage_path"] == key


def test_a_storage_refusal_is_a_503_never_a_502():
    """Cloudflare and the Railway edge replace an origin 502 with their own page,
    which has no CORS headers: the browser said only "Failed to fetch"."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("services.document_service.get_supabase") as msb, \
         patch("services.document_service.log_event", new=AsyncMock()):
        msb.return_value.storage.from_.return_value.upload.side_effect = \
            RuntimeError("InvalidKey")
        resp = client.post("/companies/e1/documents", data={"bucket": "payments"},
                           files={"file": ("a.pdf", b"%PDF", "application/pdf")}, headers=H)
    assert resp.status_code == 503
    assert "InvalidKey" in resp.json()["detail"]
    msb.return_value.table.return_value.insert.assert_not_called()


def test_a_dropped_connection_to_storage_is_retried():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("services.document_service.get_supabase") as msb, \
         patch("services.document_service.time.sleep"), \
         patch("services.document_service.log_event", new=AsyncMock()):
        sb = msb.return_value
        sb.storage.from_.return_value.upload.side_effect = [
            httpx.RemoteProtocolError("Server disconnected"), None]
        sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "doc-9", "created_at": "2026-11-21T04:00:00+00:00"}]
        resp = client.post("/companies/e1/documents", data={"bucket": "payments"},
                           files={"file": ("a.pdf", b"%PDF", "application/pdf")}, headers=H)
    assert resp.status_code == 201, resp.text
    assert sb.storage.from_.return_value.upload.call_count == 2


class _DuplicateKey(Exception):
    code = "23505"


def test_an_insert_that_landed_before_the_connection_dropped_is_not_made_twice():
    sb = MagicMock()
    row = {"id": "fixed-id", "file_name": "a.pdf"}
    sb.table.return_value.insert.return_value.execute.side_effect = [
        httpx.ReadError("dropped"), _DuplicateKey("duplicate key value 23505")]
    sb.table.return_value.select.return_value.eq.return_value.single.return_value \
        .execute.return_value.data = {"id": "fixed-id", "file_name": "a.pdf"}
    with patch("services.document_service.time.sleep"):
        got = document_service._insert_once(sb, "documents", row)
    assert got["id"] == "fixed-id"
    assert sb.table.return_value.insert.call_count == 2
    assert all(c[0][0]["id"] == "fixed-id" for c in sb.table.return_value.insert.call_args_list)


def test_a_duplicate_key_on_the_first_attempt_is_a_real_error():
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.side_effect = _DuplicateKey("23505")
    with pytest.raises(_DuplicateKey):
        document_service._insert_once(sb, "documents", {"id": "x"})


def test_an_insert_that_keeps_dropping_is_a_503():
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.side_effect = httpx.ReadError("dropped")
    with patch("services.document_service.time.sleep"), pytest.raises(HTTPException) as exc:
        document_service._insert_once(sb, "documents", {"id": "x"})
    assert exc.value.status_code == 503
    assert sb.table.return_value.insert.call_count == 3


def test_every_bucket_upload_row_carries_its_id_before_the_first_attempt():
    _resp, sb, _ = _bucket_upload("/companies/e1/documents", {"bucket": "payments"})
    doc, ver = (c[0][0] for c in sb.table.return_value.insert.call_args_list[:2])
    assert doc["id"] and ver["id"] and doc["id"] in doc["storage_path"]


# ── upload_id: a browser retry never files the same drop twice ──────────────

UPLOAD_ID = "6f1c2b3a-0d4e-4f5a-9b8c-7d6e5f4a3b2c"


def _upload_with_id(landed, *, insert_error=None, upload_id=UPLOAD_ID):
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("services.document_service.get_supabase") as msb, \
         patch("services.document_service.log_event", new=AsyncMock()) as audit:
        sb = msb.return_value
        lookups = list(landed)
        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = \
            lambda: MagicMock(data=lookups.pop(0) if lookups else [])
        ins = sb.table.return_value.insert.return_value.execute
        if insert_error:
            ins.side_effect = insert_error
        else:
            ins.return_value.data = [{"id": UPLOAD_ID, "created_at": "2026-11-21T04:00:00+00:00"}]
        resp = client.post("/companies/e1/documents",
                           data={"bucket": "maintenance", "upload_id": upload_id},
                           files={"file": (CR_FORM_NAME, b"%PDF", "application/pdf")}, headers=H)
        return resp, sb, audit


def test_the_upload_id_becomes_the_document_id():
    resp, sb, _ = _upload_with_id([[]])
    assert resp.status_code == 201, resp.text
    row = sb.table.return_value.insert.call_args_list[0][0][0]
    assert row["id"] == UPLOAD_ID and f"/{UPLOAD_ID}/" in row["storage_path"]


def test_a_retry_whose_first_attempt_landed_returns_that_document():
    first = {"id": UPLOAD_ID, "entity_id": "e1", "bucket": "maintenance",
             "file_name": CR_FORM_NAME, "created_at": "2026-11-21T04:00:00+00:00"}
    resp, sb, audit = _upload_with_id([[first]])
    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == UPLOAD_ID and resp.json()["replayed"] is True
    sb.storage.from_.return_value.upload.assert_not_called()
    sb.table.return_value.insert.assert_not_called()
    audit.assert_not_awaited()                 # one upload, one audit row


def test_a_retry_that_overtook_its_first_attempt_returns_the_first_attempts_row():
    first = {"id": UPLOAD_ID, "entity_id": "e1", "bucket": "maintenance",
             "created_at": "2026-11-21T04:00:00+00:00"}
    resp, sb, _ = _upload_with_id([[], [first]], insert_error=_DuplicateKey("23505"))
    assert resp.status_code == 201, resp.text
    assert resp.json()["replayed"] is True
    assert sb.table.return_value.insert.call_count == 1   # never a version row of its own


def test_an_upload_id_of_another_owner_is_refused():
    other = {"id": UPLOAD_ID, "entity_id": "someone-else", "bucket": "payments"}
    resp, sb, _ = _upload_with_id([[other]])
    assert resp.status_code == 409
    sb.storage.from_.return_value.upload.assert_not_called()


def test_an_upload_id_must_be_a_uuid():
    resp, sb, _ = _upload_with_id([[]], upload_id="not-a-uuid")
    assert resp.status_code == 422
    sb.storage.from_.return_value.upload.assert_not_called()


def test_a_person_uploads_into_kyc():
    resp, sb, _ = _bucket_upload("/persons/p1/documents", {"bucket": "kyc"})
    assert resp.status_code == 201
    assert sb.table.return_value.insert.call_args_list[0][0][0]["person_id"] == "p1"


@pytest.mark.parametrize("path, bucket", [
    ("/persons/p1/documents", "payments"),     # a company's bucket
    ("/companies/e1/documents", "kyc"),        # a person's bucket
    ("/companies/e1/documents", "other"),      # the fallback is not a target
    ("/companies/e1/documents", "nonsense"),
])
def test_a_bucket_the_owner_does_not_have_is_refused(path, bucket):
    resp, sb, _ = _bucket_upload(path, {"bucket": bucket})
    assert resp.status_code == 422
    sb.storage.from_.return_value.upload.assert_not_called()


def test_an_executable_is_refused_before_storage():
    resp, sb, _ = _bucket_upload("/companies/e1/documents", {"bucket": "payments"},
                                 name="invoice.exe")
    assert resp.status_code == 422
    assert "invoice.exe" in resp.json()["detail"]
    sb.storage.from_.return_value.upload.assert_not_called()


def test_neither_a_bucket_nor_a_type_is_refused():
    resp, _sb, _ = _bucket_upload("/companies/e1/documents", {})
    assert resp.status_code == 422


def test_a_reader_cannot_upload_into_a_bucket():
    with patch("middleware.auth._resolve_user", return_value=READ_ONLY), \
         patch("middleware.auth.get_supabase") as auth_sb:
        (auth_sb.return_value.table.return_value.select.return_value.eq.return_value
         .eq.return_value.execute.return_value.data) = []
        resp = client.post("/companies/e1/documents",
                           files={"file": ("a.pdf", b"x", "application/pdf")},
                           data={"bucket": "payments"}, headers=H)
    assert resp.status_code == 403


# ── bulk edit ───────────────────────────────────────────────────────────────

def _docs():
    return [
        {"id": "d1", "entity_id": "e1", "file_name": "a.pdf", "bucket": None,
         "document_type_code": "other", "document_types": {"category": "internal"},
         "title": None, "tags": [], "status": "active"},
        {"id": "d2", "entity_id": "e1", "file_name": "b.pdf", "bucket": "payments",
         "document_type_code": "other", "document_types": {"category": "internal"},
         "title": "Old", "tags": ["Payment Slip"], "status": "active"},
    ]


def _bulk(path, body, rows=None, user=SUPER_ADMIN):
    with patch("middleware.auth._resolve_user", return_value=user), \
         patch("services.document_service.get_supabase") as msb, \
         patch("services.document_service._audit_owner", return_value={}), \
         patch("services.document_service.log_event", new=AsyncMock()) as audit:
        sb = msb.return_value
        (sb.table.return_value.select.return_value.in_.return_value.eq.return_value
         .neq.return_value.execute.return_value.data) = _docs() if rows is None else rows
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = []
        resp = client.patch(path, json=body, headers=H)
        return resp, sb, audit


def test_bulk_move_tag_and_describe_in_one_request():
    resp, sb, audit = _bulk("/companies/e1/documents", {
        "ids": ["d1", "d2"], "bucket": "maintenance",
        "title": "Q3 filings", "add_tags": ["Filed ND2A"]})
    assert resp.status_code == 200, resp.text
    body = {d["id"]: d for d in resp.json()}
    assert body["d1"]["bucket"] == body["d2"]["bucket"] == "maintenance"
    assert body["d1"]["title"] == "Q3 filings"
    assert body["d2"]["tags"] == ["Payment Slip", "Filed ND2A"]
    updates = [c[0][0] for c in sb.table.return_value.update.call_args_list]
    assert {"bucket": "maintenance", "title": "Q3 filings", "tags": ["Filed ND2A"]} in updates
    # One audit row per changed field per document: 3 + 3.
    assert audit.await_count == 6
    assert {c.kwargs["event_code"] for c in audit.await_args_list} == {"GF_DOC_UPDATED"}


def test_a_tag_only_edit_leaves_every_description_alone():
    """`title` absent = not mentioned. A bulk "add tag" must not wipe twenty
    descriptions."""
    resp, sb, _ = _bulk("/companies/e1/documents", {"ids": ["d2"], "add_tags": ["X"]},
                        rows=[_docs()[1]])
    assert resp.status_code == 200
    update = sb.table.return_value.update.call_args[0][0]
    assert "title" not in update


def test_an_empty_description_clears_it():
    resp, sb, _ = _bulk("/companies/e1/documents", {"ids": ["d2"], "title": "  "},
                        rows=[_docs()[1]])
    assert resp.status_code == 200
    assert sb.table.return_value.update.call_args[0][0] == {"title": None}


def test_removing_a_tag_ignores_its_case():
    resp, sb, _ = _bulk("/companies/e1/documents",
                        {"ids": ["d2"], "remove_tags": ["payment slip"]}, rows=[_docs()[1]])
    assert resp.status_code == 200
    assert sb.table.return_value.update.call_args[0][0] == {"tags": []}


def test_an_unchanged_edit_writes_and_audits_nothing():
    resp, sb, audit = _bulk("/companies/e1/documents",
                            {"ids": ["d2"], "bucket": "payments"}, rows=[_docs()[1]])
    assert resp.status_code == 200
    sb.table.return_value.update.assert_not_called()
    audit.assert_not_awaited()


def test_a_document_of_another_owner_refuses_the_whole_edit():
    resp, sb, _ = _bulk("/companies/e1/documents",
                        {"ids": ["d1", "elsewhere"], "add_tags": ["X"]}, rows=[_docs()[0]])
    assert resp.status_code == 404
    sb.table.return_value.update.assert_not_called()


def test_moving_into_the_fallback_or_a_foreign_bucket_is_refused():
    for bucket in ("other", "kyc"):
        resp, _sb, _ = _bulk("/companies/e1/documents", {"ids": ["d1"], "bucket": bucket})
        assert resp.status_code == 422, bucket


def test_too_many_tags_is_refused():
    resp, _sb, _ = _bulk("/companies/e1/documents", {
        "ids": ["d1"], "add_tags": [f"t{i}" for i in range(13)]})
    assert resp.status_code == 422


def test_an_unknown_field_is_refused():
    resp, _sb, _ = _bulk("/companies/e1/documents", {"ids": ["d1"], "document_type_code": "x"})
    assert resp.status_code == 422


def test_a_person_bulk_edit_is_scoped_to_the_person():
    rows = [{**_docs()[0], "entity_id": None, "person_id": "p1"}]
    resp, sb, _ = _bulk("/persons/p1/documents", {"ids": ["d1"], "bucket": "kyc"}, rows=rows)
    assert resp.status_code == 200, resp.text
    eq = sb.table.return_value.select.return_value.in_.return_value.eq
    assert eq.call_args[0] == ("person_id", "p1")


def test_a_reader_cannot_bulk_edit():
    with patch("middleware.auth._resolve_user", return_value=READ_ONLY), \
         patch("middleware.auth.get_supabase") as auth_sb:
        (auth_sb.return_value.table.return_value.select.return_value.eq.return_value
         .eq.return_value.execute.return_value.data) = []
        resp = client.patch("/companies/e1/documents",
                            json={"ids": ["d1"], "add_tags": ["X"]}, headers=H)
    assert resp.status_code == 403


# ── listing ─────────────────────────────────────────────────────────────────

def test_listing_places_each_document_and_sorts_by_upload_newest_first():
    rows = [
        {"id": "old", "entity_id": "e1", "document_type_code": "nar1", "current_version": 2,
         "created_at": "2025-01-01T00:00:00Z",
         "document_types": {"category": "government_form"},
         "document_versions": [
             {"version_number": 1, "created_at": "2025-01-01T00:00:00Z"},
             {"version_number": 2, "created_at": "2026-11-20T00:00:00Z"}]},
        {"id": "new", "entity_id": "e1", "document_type_code": "other", "bucket": "payments",
         "current_version": 1, "created_at": "2026-06-01T00:00:00Z",
         "document_types": {"category": "internal"}, "document_versions": []},
    ]
    with patch("services.document_service.get_supabase") as msb:
        (msb.return_value.table.return_value.select.return_value.neq.return_value
         .eq.return_value.order.return_value.execute.return_value.data) = rows
        out = document_service.list_documents(owner_kind="entity", owner_id="e1")
    # The NAR1's v2 arrived after the payment slip, so it sorts first.
    assert [d["id"] for d in out] == ["old", "new"]
    assert out[0]["bucket"] == "annual_return"
    assert out[0]["uploaded_at"] == "2026-11-20T00:00:00Z"
    assert out[1]["tags"] == []

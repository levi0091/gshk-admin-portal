"""Identity documents: creating one, replacing one, and the scan beside it.

THE TWO DEFECTS THESE COVER (Levi 2026-09-04):

  1. "the personal information has no field to enter the ID number" — a person
     could be created with names, a nationality and a date of birth, and no way
     to record the number CR files them by. The profile could only EDIT identity
     documents, so a person created through the portal had none.

  2. "when i upload a passport it does not overwrite the existing passport
     record ... it only simply adds a record into the document history" — the
     upload wrote a `documents` row and never touched
     `person_identity_documents`, and every identity scan shared one document
     type (`id_scan`), so a passport uploaded after an HKID became version 2 of
     the HKID.

The rule the fix rests on: the NUMBER is overwritten, the SCAN is versioned.
"""
from unittest.mock import patch, MagicMock, AsyncMock

from fastapi.testclient import TestClient

from main import app
from services import document_sections

client = TestClient(app)

SUPER_ADMIN = {"id": "admin-1", "display_name": "Levi Z.",
               "role_name": "super_admin", "role_id": "role-sa"}
H = {"Authorization": "Bearer tok"}

#: A real, internally consistent HKID. A made-up one would make the check-digit
#: assertions meaningless.
GOOD_HKID = "A123456(3)"


class _Tables:
    """`sb.table(name)` returning a per-table mock, so a test can say which
    table it is stubbing rather than counting `.eq()`s in a shared chain."""

    def __init__(self, **by_name):
        self._by_name = by_name

    def __call__(self, name):
        return self._by_name.setdefault(name, MagicMock())

    def __getitem__(self, name):
        return self._by_name[name]


def _persons_table(person):
    t = MagicMock()
    (t.select.return_value.eq.return_value.single.return_value
     .execute.return_value.data) = person
    t.insert.return_value.execute.return_value.data = [person]
    return t


def _identity_table(held, saved):
    t = MagicMock()
    t.select.return_value.eq.return_value.execute.return_value.data = held
    t.update.return_value.eq.return_value.execute.return_value.data = [saved]
    t.insert.return_value.execute.return_value.data = [saved]
    return t


# ── the vocabulary ────────────────────────────────────────────────────────────

def test_every_id_type_has_a_document_type_and_back():
    """The upload turns a document type code into an `id_document_type`. A code
    without a partner silently stops identity uploads recording a number."""
    assert set(document_sections.CODE_BY_ID_TYPE) == {
        "hkid", "passport", "china_id", "other"}
    for id_type, code in document_sections.CODE_BY_ID_TYPE.items():
        assert document_sections.id_type_for_code(code) == id_type


def test_the_retired_catch_all_maps_to_no_id_type():
    """`id_scan` could not say WHICH document it was — which is why it was
    retired. It must not be mistaken for one now."""
    assert document_sections.id_type_for_code(
        document_sections.LEGACY_IDENTITY_CODE) is None
    assert not document_sections.is_identity_code("address_proof")


def test_an_hkid_takes_a_number_and_nothing_else():
    """CR has no country box beside <hkid>, and a Hong Kong identity card does
    not expire. Offering three more fields invites three answers CR cannot use."""
    assert document_sections.identity_fields("hkid") == ["id_number"]


def test_a_passport_cannot_be_filed_without_its_issuing_country():
    """`nar1_mapper._individual_id` refuses a passport number whose issuing
    country has no CR code, so an empty one is a filing blocked later."""
    assert "issuing_country" in document_sections.required_identity_fields("passport")


# ── GET /documents/sections ───────────────────────────────────────────────────

def _sections(types, owner_type="person"):
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.documents.get_supabase") as msb:
        (msb.return_value.table.return_value.select.return_value.eq.return_value
         .in_.return_value.order.return_value.execute.return_value.data) = types
        return client.get(
            f"/documents/sections?owner_type={owner_type}", headers=H)


def test_sections_group_their_types_under_the_right_heading():
    resp = _sections([
        {"code": "id_passport", "label": "Passport", "category": "identity"},
        {"code": "addr_utility_bill", "label": "Utility Bill", "category": "address_proof"},
    ])
    assert resp.status_code == 200
    body = resp.json()
    by_key = {s["key"]: s for s in body["sections"]}

    identity = by_key["identity"]
    assert identity["is_identity"] is True
    assert identity["file_required"] is False   # the number is the filing
    assert identity["types"] == [
        {"code": "id_passport", "label": "Passport", "id_type": "passport"}]
    assert by_key["address_proof"]["is_identity"] is False
    assert body["identity_fields"]["hkid"]["fields"] == ["id_number"]


def test_a_section_with_types_but_no_uploads_still_comes_back():
    """An empty section with its own button is how the first document gets
    added — the whole point of point 2. Nothing has been uploaded here at all."""
    resp = _sections([
        {"code": "addr_utility_bill", "label": "Utility Bill", "category": "address_proof"},
    ])
    assert [s["key"] for s in resp.json()["sections"]] == ["address_proof"]


def test_a_section_with_no_types_at_all_is_not_offered():
    """Not empty — INERT. Its upload button would open a picker with nothing in
    it, which is a worse answer than no section."""
    resp = _sections([
        {"code": "id_passport", "label": "Passport", "category": "identity"},
    ])
    keys = [s["key"] for s in resp.json()["sections"]]
    assert keys == ["identity"]
    assert "kyc" not in keys


def test_sections_refuse_an_owner_type_that_is_neither():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN):
        assert client.get(
            "/documents/sections?owner_type=case", headers=H).status_code == 400


def test_the_type_picker_can_be_scoped_to_one_section():
    """The upload button lives inside a section now, so the picker it opens must
    offer that section's types — a passport is not an answer to "which proof of
    address is this?"."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.documents.get_supabase") as msb:
        q = msb.return_value.table.return_value.select.return_value.eq.return_value
        q.in_.return_value.eq.return_value.order.return_value.execute.return_value.data = []
        resp = client.get(
            "/documents/types?owner_type=person&category=identity", headers=H)

    assert resp.status_code == 200
    q.in_.return_value.eq.assert_called_once_with("category", "identity")


# ── creating a person WITH their identity number ──────────────────────────────

def test_a_person_can_be_created_with_their_identity_number():
    tables = _Tables(
        persons=_persons_table({"id": "p-new", "full_name": "Jane"}),
        person_identity_documents=MagicMock(),
    )
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb, \
         patch("routers.persons.log_event", new=AsyncMock()) as audit:
        msb.return_value.table.side_effect = tables
        resp = client.post("/persons", headers=H, json={
            "full_name": "Jane",
            "identity_document": {"id_type": "hkid", "id_number": GOOD_HKID},
        })

    assert resp.status_code == 201
    inserted = tables["person_identity_documents"].insert.call_args.args[0]
    assert inserted["person_id"] == "p-new"
    assert inserted["id_type"] == "hkid"
    assert inserted["id_number"] == GOOD_HKID
    # The audit row can finally quote the number, because one now exists at
    # creation. Before this it could not — there was no field to type it into.
    assert GOOD_HKID in str(audit.await_args.kwargs)


def test_a_bad_hkid_refuses_the_whole_creation():
    """Validated BEFORE the person is inserted. A 422 after the insert would
    leave a person behind with no identity document and an error the operator
    has already navigated away from."""
    tables = _Tables(persons=_persons_table({"id": "p-new", "full_name": "Jane"}))
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb, \
         patch("routers.persons.log_event", new=AsyncMock()):
        msb.return_value.table.side_effect = tables
        resp = client.post("/persons", headers=H, json={
            "full_name": "Jane",
            "identity_document": {"id_type": "hkid", "id_number": "Z351007(9)"},
        })

    assert resp.status_code == 422
    assert "check digit" in resp.text.lower()
    tables["persons"].insert.assert_not_called()


def test_a_passport_without_an_issuing_country_is_refused_in_crs_words():
    tables = _Tables(persons=_persons_table({"id": "p-new", "full_name": "Jane"}))
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb, \
         patch("routers.persons.log_event", new=AsyncMock()):
        msb.return_value.table.side_effect = tables
        resp = client.post("/persons", headers=H, json={
            "full_name": "Jane",
            "identity_document": {"id_type": "passport", "id_number": "987654321"},
        })

    assert resp.status_code == 422
    assert "issuing country" in resp.text.lower()
    tables["persons"].insert.assert_not_called()


def test_an_hkid_does_not_store_fields_cr_has_no_box_for():
    tables = _Tables(
        persons=_persons_table({"id": "p-new", "full_name": "Jane"}),
        person_identity_documents=MagicMock(),
    )
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb, \
         patch("routers.persons.log_event", new=AsyncMock()):
        msb.return_value.table.side_effect = tables
        resp = client.post("/persons", headers=H, json={
            "full_name": "Jane",
            "identity_document": {
                "id_type": "hkid", "id_number": GOOD_HKID,
                "issuing_country": "GB", "expiry_date": "2031-01-27",
            },
        })

    assert resp.status_code == 201
    inserted = tables["person_identity_documents"].insert.call_args.args[0]
    assert "issuing_country" not in inserted
    assert "expiry_date" not in inserted


def test_an_unknown_identity_type_is_refused_by_name():
    tables = _Tables(persons=_persons_table({"id": "p-new", "full_name": "Jane"}))
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb:
        msb.return_value.table.side_effect = tables
        resp = client.post("/persons", headers=H, json={
            "full_name": "Jane",
            "identity_document": {"id_type": "drivers_licence", "id_number": "X"},
        })

    assert resp.status_code == 422
    assert "passport" in resp.text     # names what it WOULD have accepted


def test_nationality_origin_can_be_set_at_creation():
    """It was editable on the profile and absent from creation, so it could only
    ever be filled in on a second visit to a record made from the same data."""
    tables = _Tables(persons=_persons_table({"id": "p-new", "full_name": "Jane"}))
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb, \
         patch("routers.persons.log_event", new=AsyncMock()):
        msb.return_value.table.side_effect = tables
        resp = client.post("/persons", headers=H,
                           json={"full_name": "Jane", "nationality_origin": "British"})

    assert resp.status_code == 201
    assert tables["persons"].insert.call_args.args[0]["nationality_origin"] == "British"


# ── replacing an identity document, and the scan beside it ────────────────────

def _save_identity(held, *, data, files=None, saved=None):
    tables = _Tables(
        persons=_persons_table({"id": "p1", "full_name": "Jane"}),
        person_identity_documents=_identity_table(
            held, saved or {"id": "i1", "id_type": data["id_type"]}),
    )
    upload = AsyncMock(return_value={"id": "doc-9", "current_version": 2})
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb, \
         patch("routers.persons.document_service.upload_document", new=upload), \
         patch("routers.persons.log_events", new=AsyncMock()) as audit:
        msb.return_value.table.side_effect = tables
        resp = client.post("/persons/p1/identity-documents", headers=H,
                           data=data, files=files)
    return resp, tables, upload, audit


PASSPORT = {"id_type": "passport", "id_number": "987654321",
            "issuing_country": "GB"}


def test_re_uploading_a_passport_replaces_the_passport_record():
    """The defect verbatim: it used to add a file to history and leave the
    passport record untouched. One passport row per person, replaced in place."""
    held = [{"id": "i1", "id_type": "passport", "id_number": "OLD-111",
             "issuing_country": "GB", "is_primary": True}]
    resp, tables, _upload, _audit = _save_identity(
        held, data=PASSPORT, files={"file": ("p.pdf", b"%PDF", "application/pdf")})

    assert resp.status_code == 201
    idt = tables["person_identity_documents"]
    idt.insert.assert_not_called()                       # replaced, not added
    # call_args_list[0]: a promotion writes a SECOND update that clears
    # is_primary on the other rows, and that one is not the row under test.
    written = idt.update.call_args_list[0].args[0]
    assert written["id_number"] == "987654321"
    assert written["scan_document_id"] == "doc-9"        # the number knows its scan


def test_the_scan_is_filed_under_the_passports_own_type_not_a_shared_one():
    """`upload_document` versions on (owner, document_type_code). While every
    identity scan shared `id_scan`, a passport uploaded after an HKID became
    version 2 of the HKID."""
    _resp, _tables, upload, _audit = _save_identity(
        [], data=PASSPORT, files={"file": ("p.pdf", b"%PDF", "application/pdf")})

    assert upload.await_args.kwargs["document_type_code"] == "id_passport"
    assert upload.await_args.kwargs["owner_kind"] == "person"


def test_a_passport_replaces_the_passport_and_leaves_the_hkid_alone():
    held = [
        {"id": "i-hkid", "id_type": "hkid", "id_number": GOOD_HKID, "is_primary": True},
        {"id": "i-pass", "id_type": "passport", "id_number": "OLD-111",
         "issuing_country": "GB"},
    ]
    resp, tables, _upload, _audit = _save_identity(held, data=PASSPORT)

    assert resp.status_code == 201
    # the row it updated is the passport's, not the HKID's
    eq_call = tables["person_identity_documents"].update.return_value.eq
    assert eq_call.call_args_list[0].args == ("id", "i-pass")


def test_an_identity_document_can_be_recorded_without_a_scan():
    """GSHK holds passport numbers whose scan nobody can find, and CR never asks
    to see one. Refusing the number until a file turns up would block a return
    over evidence the Registry does not want."""
    resp, tables, upload, _audit = _save_identity([], data=PASSPORT)

    assert resp.status_code == 201
    upload.assert_not_awaited()
    inserted = tables["person_identity_documents"].insert.call_args.args[0]
    assert inserted["id_number"] == "987654321"
    assert "scan_document_id" not in inserted


def test_the_first_identity_document_a_person_holds_is_primary():
    """The header and `audit_subject.primary_id_number` both quote the primary,
    so a person whose only document is not primary reads as having none."""
    resp, tables, _upload, _audit = _save_identity(
        [], data={**PASSPORT, "is_primary": "false"})

    assert resp.status_code == 201
    assert tables["person_identity_documents"].insert.call_args.args[0]["is_primary"] is True


def test_an_empty_attachment_is_refused_rather_than_ignored():
    """No file is fine; an EMPTY one is not. Ignoring it would report a
    successful save of a scan that does not exist."""
    resp, tables, upload, _audit = _save_identity(
        [], data=PASSPORT, files={"file": ("p.pdf", b"", "application/pdf")})

    assert resp.status_code == 422
    assert "empty" in resp.text.lower()
    upload.assert_not_awaited()
    tables["person_identity_documents"].insert.assert_not_called()


def test_a_bad_hkid_is_refused_before_anything_is_stored():
    resp, tables, upload, _audit = _save_identity(
        [], data={"id_type": "hkid", "id_number": "Z351007(9)"},
        files={"file": ("p.pdf", b"%PDF", "application/pdf")})

    assert resp.status_code == 422
    upload.assert_not_awaited()
    tables["person_identity_documents"].insert.assert_not_called()


def test_an_issuing_country_cr_cannot_resolve_is_refused_on_create():
    """The same defect as the address country: 'HK-CH' passed every check and
    killed a real NAR1 at Data Verification."""
    resp, _tables, _upload, _audit = _save_identity(
        [], data={**PASSPORT, "issuing_country": "HK-CH"})

    assert resp.status_code == 422
    assert "HK-CH" in resp.text


def test_replacing_the_primary_document_does_not_demote_it():
    """`is_primary` promotes and never demotes. Re-recording the passport a
    person is quoted by must not quietly stop them being quoted by it."""
    held = [{"id": "i1", "id_type": "passport", "id_number": "OLD-111",
             "issuing_country": "GB", "is_primary": True},
            {"id": "i2", "id_type": "hkid", "id_number": GOOD_HKID,
             "is_primary": False}]
    resp, tables, _upload, _audit = _save_identity(
        held, data={**PASSPORT, "is_primary": "false"})

    assert resp.status_code == 201
    assert tables["person_identity_documents"].update.call_args_list[0].args[0]["is_primary"] is True


def test_saving_an_identity_document_audits_each_changed_field():
    held = [{"id": "i1", "id_type": "passport", "id_number": "OLD-111",
             "issuing_country": "GB", "is_primary": True}]
    _resp, _tables, _upload, audit = _save_identity(held, data=PASSPORT)

    events = audit.await_args.args[0]
    changed = {e["after_state"]["field"] for e in events}
    assert changed == {"passport.id_number"}     # the country did not change
    assert events[0]["event_code"] == "CPC"      # Viewpoint: Change Compliance
    assert events[0]["old_value"] == "OLD-111"


def test_saving_an_identity_document_404s_for_an_unknown_person():
    tables = _Tables(persons=_persons_table(None))
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb:
        msb.return_value.table.side_effect = tables
        resp = client.post("/persons/nope/identity-documents", headers=H,
                           data=PASSPORT)

    assert resp.status_code == 404


def test_saving_an_identity_document_needs_write_permission():
    regular = {"id": "u-2", "display_name": "Staff", "role_name": "staff",
               "role_id": "role-x"}
    with patch("middleware.auth._resolve_user", return_value=regular), \
         patch("middleware.auth.get_supabase") as msb:
        (msb.return_value.table.return_value.select.return_value.eq.return_value
         .eq.return_value.execute.return_value.data) = []
        resp = client.post("/persons/p1/identity-documents", headers=H,
                           data=PASSPORT)

    assert resp.status_code == 403


# ── the field nobody asked for ────────────────────────────────────────────────

def test_the_renewal_reminder_is_no_longer_writable():
    """Levi 2026-09-04: "remove the renewal reminder, it is not required, i
    didnt ask for this". The COLUMN survives, as `place_of_issue` did; nothing
    writes it."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase"):
        resp = client.patch("/persons/p1/identity-documents/d1", headers=H,
                            json={"reminder_date": "2030-01-01"})

    assert resp.status_code == 422

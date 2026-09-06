"""Block 4 — the CR form fields over the API.

Covers the columns migration 028 added, the business-nature auto-fill, the
identity-document endpoint that gives the HKID check digit somewhere to apply,
and `GET /form-contract`.
"""
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

SUPER_ADMIN = {"id": "admin-1", "display_name": "Levi Z.",
               "role_name": "super_admin", "role_id": "role-sa"}
H = {"Authorization": "Bearer tok"}


# --- the new profile columns --------------------------------------------

def test_person_accepts_the_alias_and_chinese_previous_name():
    """Brian's B12. `extra = "forbid"` means an unknown field is a 422, so
    this fails until the model carries them."""
    current = {"id": "p1", "alias_en": None, "alias_zh": None,
               "former_name_zh": None}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb, \
         patch("routers.persons.log_events", new=AsyncMock()):
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .single.return_value.execute.return_value.data) = current
        (sb.table.return_value.update.return_value.eq.return_value
         .execute.return_value.data) = [{"id": "p1"}]

        resp = client.patch("/persons/p1", headers=H, json={
            "alias_en": "JD", "alias_zh": "別名", "former_name_zh": "前名"})

    assert resp.status_code == 200


def test_company_accepts_business_nature_and_mortgages():
    """Brian's B5 and B6."""
    current = {"id": "c1", "business_nature_code": None, "mortgages_total": None}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_events", new=AsyncMock()):
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .single.return_value.execute.return_value.data) = current
        (sb.table.return_value.update.return_value.eq.return_value
         .execute.return_value.data) = [{"id": "c1"}]

        resp = client.patch("/companies/c1", headers=H, json={
            "business_nature_code": "070", "mortgages_total": "Nil"})

    assert resp.status_code == 200


def test_business_nature_description_is_filled_in_from_the_code():
    """CR derives natureDesc from nature after web-form validation, so the
    description is never typed. Sending a code must store both."""
    current = {"id": "c1", "business_nature_code": None,
               "business_nature_desc": None}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_events", new=AsyncMock()):
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .single.return_value.execute.return_value.data) = current
        (sb.table.return_value.update.return_value.eq.return_value
         .execute.return_value.data) = [{"id": "c1"}]

        client.patch("/companies/c1", headers=H,
                     json={"business_nature_code": "070"})

        written = sb.table.return_value.update.call_args.args[0]

    assert written["business_nature_code"] == "070"
    assert written["business_nature_desc"].startswith("Activities of head offices")


def test_an_unknown_business_nature_code_is_refused():
    """CR's list is closed. A code it has never heard of fails the filing, so
    it must not reach the database."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        (msb.return_value.table.return_value.select.return_value.eq.return_value
         .single.return_value.execute.return_value.data) = {"id": "c1"}

        resp = client.patch("/companies/c1", headers=H,
                            json={"business_nature_code": "999"})

    assert resp.status_code == 422


def test_company_type_accepts_crs_own_codes():
    """PRD §7.4 — P Private, N Public, G Guarantee, and nothing else."""
    current = {"id": "c1", "company_type": "P"}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN),          patch("routers.companies.get_supabase") as msb,          patch("routers.companies.log_events", new=AsyncMock()):
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .single.return_value.execute.return_value.data) = current
        (sb.table.return_value.update.return_value.eq.return_value
         .execute.return_value.data) = [{"id": "c1"}]

        resp = client.patch("/companies/c1", headers=H, json={"company_type": "G"})

    assert resp.status_code == 200


def test_a_company_cannot_be_CREATED_with_a_type_cr_refuses():
    """The edit path grandfathers legacy values because they already exist. A
    company being created now has no legacy to protect, so CR's three are the
    whole list -- otherwise the portal keeps minting rows it will later have
    to grandfather."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase"):
        resp = client.post("/companies", headers=H, json={
            "company_name": "NewCo", "status": "live",
            "company_type": "Private company limited by shares"})

    assert resp.status_code == 422
    assert "company type" in resp.text.lower()


def test_a_company_can_be_created_with_crs_code():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_event", new=AsyncMock()):
        (msb.return_value.table.return_value.insert.return_value
         .execute.return_value.data) = [{"id": "c9", "company_name": "NewCo"}]

        resp = client.post("/companies", headers=H, json={
            "company_name": "NewCo", "status": "live", "company_type": "P"})

    assert resp.status_code == 201


def test_an_invented_company_type_is_refused():
    current = {"id": "c1", "company_type": "P"}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN),          patch("routers.companies.get_supabase") as msb:
        (msb.return_value.table.return_value.select.return_value.eq.return_value
         .single.return_value.execute.return_value.data) = current

        resp = client.patch("/companies/c1", headers=H,
                            json={"company_type": "Sole Trader"})

    assert resp.status_code == 422


def test_a_legacy_company_type_can_be_saved_back_unchanged():
    """Grandfathering, as for HKID (D4). `entities.company_type` held
    Viewpoint's free text before CR's codes existed here; re-saving a profile
    that still carries one must not be refused, or the record freezes."""
    legacy = "Private company limited by shares"
    current = {"id": "c1", "company_type": legacy, "case_notes": None}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN),          patch("routers.companies.get_supabase") as msb,          patch("routers.companies.log_events", new=AsyncMock()):
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .single.return_value.execute.return_value.data) = current
        (sb.table.return_value.update.return_value.eq.return_value
         .execute.return_value.data) = [{"id": "c1"}]

        resp = client.patch("/companies/c1", headers=H,
                            json={"company_type": legacy, "case_notes": "hi"})

    assert resp.status_code == 200


# --- identity documents: where the HKID check digit applies ---------------

def test_identity_document_rejects_a_bad_hkid_check_digit():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb:
        (msb.return_value.table.return_value.select.return_value.eq.return_value
         .eq.return_value.single.return_value.execute.return_value.data) = {
             "id": "d1", "person_id": "p1", "id_type": "hkid",
             "id_number": "A123456(3)"}

        resp = client.patch("/persons/p1/identity-documents/d1", headers=H,
                            json={"id_number": "Z351007(9)"})

    assert resp.status_code == 422
    assert "check digit" in resp.text.lower()


def test_identity_document_accepts_a_correct_hkid():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb, \
         patch("routers.persons.log_events", new=AsyncMock()):
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .eq.return_value.single.return_value.execute.return_value.data) = {
             "id": "d1", "person_id": "p1", "id_type": "hkid",
             "id_number": "A123456(3)"}
        (sb.table.return_value.update.return_value.eq.return_value
         .execute.return_value.data) = [{"id": "d1"}]

        resp = client.patch("/persons/p1/identity-documents/d1", headers=H,
                            json={"id_number": "AB987654(3)"})

    assert resp.status_code == 200


def test_a_bad_stored_hkid_does_not_block_editing_a_different_field():
    """Grandfathering (PRD D4). 31 real rows in DEV would fail the check, 29
    of them Mainland China IDs mis-typed as HKID. Validation runs only when
    id_number is itself being written, so none of those records is frozen."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb, \
         patch("routers.persons.log_events", new=AsyncMock()):
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .eq.return_value.single.return_value.execute.return_value.data) = {
             "id": "d1", "person_id": "p1", "id_type": "hkid",
             "id_number": "440782198611028063"}     # a real stored value
        (sb.table.return_value.update.return_value.eq.return_value
         .execute.return_value.data) = [{"id": "d1"}]

        resp = client.patch("/persons/p1/identity-documents/d1", headers=H,
                            json={"issuing_country": "CHN"})

    assert resp.status_code == 200


def test_an_issuing_country_cr_cannot_resolve_is_refused():
    """`indvPptIssCtry` is a CR-validated field, so it takes CR's codes. This
    is the same defect as the address country: the dropdown used to offer
    Viewpoint's list, 20 of whose codes CR has never heard of."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb:
        (msb.return_value.table.return_value.select.return_value.eq.return_value
         .eq.return_value.single.return_value.execute.return_value.data) = {
             "id": "d1", "person_id": "p1", "id_type": "passport",
             "id_number": "123456789", "issuing_country": "GB"}

        resp = client.patch("/persons/p1/identity-documents/d1", headers=H,
                            json={"issuing_country": "HK-CH"})

    assert resp.status_code == 422
    assert "HK-CH" in resp.text


def test_an_issuing_country_cr_does_resolve_is_accepted():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb, \
         patch("routers.persons.log_events", new=AsyncMock()):
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .eq.return_value.single.return_value.execute.return_value.data) = {
             "id": "d1", "person_id": "p1", "id_type": "passport",
             "id_number": "123456789", "issuing_country": "GB"}
        (sb.table.return_value.update.return_value.eq.return_value
         .execute.return_value.data) = [{"id": "d1"}]

        resp = client.patch("/persons/p1/identity-documents/d1", headers=H,
                            json={"issuing_country": "HK"})

    assert resp.status_code == 200


def test_a_passport_number_is_not_check_digit_validated():
    """There is no passport check digit to compute. Only format and length."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb, \
         patch("routers.persons.log_events", new=AsyncMock()):
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .eq.return_value.single.return_value.execute.return_value.data) = {
             "id": "d1", "person_id": "p1", "id_type": "passport",
             "id_number": "123456789"}
        (sb.table.return_value.update.return_value.eq.return_value
         .execute.return_value.data) = [{"id": "d1"}]

        resp = client.patch("/persons/p1/identity-documents/d1", headers=H,
                            json={"id_number": "Z351007"})

    assert resp.status_code == 200


# --- the contract over the wire ------------------------------------------

def test_form_contract_serves_the_mapped_fields_with_their_cr_limits():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN):
        resp = client.get("/form-contract", headers=H)

    assert resp.status_code == 200
    body = resp.json()
    surname = body["persons"]["surname"]
    assert surname["max_length"] == 50
    assert body["addresses"]["line1"]["max_length"] == 60


def test_form_contract_marks_the_fields_cr_requires():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN):
        body = client.get("/form-contract", headers=H).json()

    # ctryRegion is Mandatory=Y on every address block CR defines.
    assert body["addresses"]["country"]["mandatory"] is True
    # An alias is not required by anyone.
    assert body["persons"]["alias_en"]["mandatory"] is False

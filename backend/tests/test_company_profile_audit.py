"""The 2026-09-04 body-corporate profile pass (Levi's 13 items).

Grouped in one file because the changes are one review of one screen and each
test's reason for existing is the same review — splitting them across
test_companies_router / test_documents / test_lookups would scatter that.

Supabase and audit are mocked throughout; no DB is touched. `super_admin` via
`_resolve_user` bypasses `require_permission`, so the happy paths only mock the
router's `get_supabase`.
"""
from unittest.mock import patch, MagicMock, AsyncMock

from fastapi.testclient import TestClient

from main import app
from routers import lookups as lookups_router

client = TestClient(app)

#: For the two tests that exercise the catch-all handler. TestClient re-raises
#: server exceptions by default, which is the opposite of what is being tested:
#: the question is what the BROWSER receives, and the browser gets a response.
error_client = TestClient(app, raise_server_exceptions=False)

SUPER_ADMIN = {"id": "admin-1", "display_name": "Levi Z.",
               "role_name": "super_admin", "role_id": "role-sa"}
H = {"Authorization": "Bearer tok"}


# --------------------------------------------------------------------------- #
#  Item 8 — "Could not reach the server" when adding a shareholder
# --------------------------------------------------------------------------- #

def test_share_class_from_another_company_is_refused_by_name():
    """A free-text Share Class box sent "1" at a `uuid NOT NULL REFERENCES`
    column. PostgREST raised 22P02, nothing caught it, and the 500 came back
    from OUTSIDE the CORS middleware -- so the browser reported the API as
    unreachable for a request the API had understood perfectly.

    The refusal has to name the classes the company actually has, because the
    operator's next move is to pick one.
    """
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        (msb.return_value.table.return_value.select.return_value
         .eq.return_value.execute.return_value.data) = [
            {"id": "sc-1", "class_name": "Ordinary"},
            {"id": "sc-2", "class_name": "Preference"},
        ]
        resp = client.post("/companies/e1/shareholders",
                           json={"person_id": "p1", "share_class_id": "1"},
                           headers=H)

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "not a class of shares this company has" in detail
    assert "Ordinary" in detail and "Preference" in detail


def test_share_class_refusal_says_to_add_one_when_there_are_none():
    """219 client companies hold no share capital at all. "Its classes are: "
    followed by nothing is not an instruction."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        (msb.return_value.table.return_value.select.return_value
         .eq.return_value.execute.return_value.data) = []
        resp = client.post("/companies/e1/shareholders",
                           json={"person_id": "p1", "share_class_id": "sc-x"},
                           headers=H)

    assert resp.status_code == 422
    assert "no share capital recorded yet" in resp.json()["detail"]


def test_a_valid_share_class_still_links():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_event", new=AsyncMock()):
        sb = msb.return_value
        (sb.table.return_value.select.return_value
         .eq.return_value.execute.return_value.data) = [
            {"id": "sc-1", "class_name": "Ordinary"}]
        sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "sh-1"}]
        resp = client.post("/companies/e1/shareholders",
                           json={"person_id": "p1", "share_class_id": "sc-1",
                                 "shares_held": 100},
                           headers=H)
    assert resp.status_code == 201


def test_unhandled_error_answers_through_the_cors_middleware():
    """WHY THIS TEST EXISTS AT ALL. Without a handler for `Exception`, an
    unhandled error is answered by Starlette OUTSIDE `CORSMiddleware`, the
    browser blocks the reply, `fetch` rejects, and every screen prints "Could
    not reach the server" for a server that answered in 40ms.

    Asserting the CORS header is the whole point -- a 500 with a nice JSON body
    and no `Access-Control-Allow-Origin` is exactly as unreadable as before.
    """
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase", side_effect=RuntimeError("boom")):
        resp = error_client.get("/companies/e1",
                          headers={**H, "Origin": "http://localhost:5173"})

    assert resp.status_code == 500
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
    # Not a stack trace: nothing on it is actionable, and it can quote a row
    # the operator should not see.
    assert "Nothing was saved" in resp.json()["detail"]
    assert "boom" not in resp.text


def test_a_database_constraint_is_a_422_that_quotes_the_constraint():
    """A SQLSTATE in the data-fault set is a fact about the SUBMITTED VALUE, so
    re-sending the identical request cannot succeed -- 422, not 500, and the
    operator is told which value."""
    from postgrest.exceptions import APIError

    fault = APIError({"code": "22P02",
                      "message": 'invalid input syntax for type uuid: "1"',
                      "details": None, "hint": None})
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase", side_effect=fault):
        resp = error_client.get("/companies/e1",
                          headers={**H, "Origin": "http://localhost:5173"})

    assert resp.status_code == 422
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
    body = resp.json()["detail"]
    assert body["message"] == "A value is not of the type the column requires."
    assert any("uuid" in p for p in body["problems"])


# --------------------------------------------------------------------------- #
#  Items 11 & 12 — beneficial-owner vocabularies
# --------------------------------------------------------------------------- #

def test_owner_type_outside_the_list_is_refused():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase"):
        resp = client.post("/companies/e1/beneficial-owners",
                           json={"person_id": "p1", "owner_type": "vibes"},
                           headers=H)
    assert resp.status_code == 422
    assert "significant_controller" in resp.json()["detail"]


def test_nature_of_control_takes_the_two_ordinance_conditions():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_event", new=AsyncMock()):
        msb.return_value.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "bo-1"}]
        resp = client.post(
            "/companies/e1/beneficial-owners",
            json={"person_id": "p1", "owner_type": "ubo",
                  "nature_of_control": "significant_influence"},
            headers=H)
    assert resp.status_code == 201

    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase"):
        bad = client.post("/companies/e1/beneficial-owners",
                          json={"person_id": "p1", "nature_of_control": "lots"},
                          headers=H)
    assert bad.status_code == 422


def test_a_legacy_owner_type_can_be_edited_without_first_being_corrected():
    """GRANDFATHERING, as everywhere else in this repo. `owner_type` has carried
    Viewpoint free text since the ETL. Refusing the stored value would mean an
    unrelated edit to the same row could not be saved."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_events", new=AsyncMock()):
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .eq.return_value.single.return_value.execute.return_value.data) = {
            "id": "bo-1", "entity_id": "e1", "owner_type": "Trustee (legacy)"}
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "bo-1"}]
        resp = client.patch("/companies/e1/beneficial-owners/bo-1",
                            json={"owner_type": "Trustee (legacy)"}, headers=H)
    assert resp.status_code == 200


def test_viewpoint_spellings_are_normalised_onto_one_code():
    """"Ultimate Beneficial Owner" and "ubo" are the SAME fact, so they must not
    become two codes in one dropdown."""
    captured = {}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_event", new=AsyncMock()):
        def insert(row):
            captured.update(row)
            m = MagicMock()
            m.execute.return_value.data = [{"id": "bo-1", **row}]
            return m
        msb.return_value.table.return_value.insert.side_effect = insert
        resp = client.post(
            "/companies/e1/beneficial-owners",
            json={"person_id": "p1", "owner_type": "Ultimate Beneficial Owner"},
            headers=H)
    assert resp.status_code == 201
    assert captured["owner_type"] == "ubo"


# --------------------------------------------------------------------------- #
#  Item 9 — recording a share transfer
# --------------------------------------------------------------------------- #

def test_a_holding_can_be_marked_former_rather_than_deleted():
    """`nar1_mapper._schedule_1` skips a holding with `is_current` false, so
    this drops the outgoing member from the return exactly as a DELETE would --
    while keeping the row, which is what makes the transfer legible in the audit
    trail and keeps the register showing who held the shares before.
    """
    captured = {}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_events", new=AsyncMock()):
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .eq.return_value.single.return_value.execute.return_value.data) = {
            "id": "sh-1", "entity_id": "e1", "is_current": True}

        def update(values):
            captured.update(values)
            m = MagicMock()
            m.eq.return_value.execute.return_value.data = [{"id": "sh-1", **values}]
            return m

        sb.table.return_value.update.side_effect = update
        resp = client.patch("/companies/e1/shareholders/sh-1",
                            json={"is_current": False}, headers=H)

    assert resp.status_code == 200
    # A real boolean, not the string "false" -- which Python reads as true, and
    # the register would then show a transferred-out member as still holding.
    assert captured["is_current"] is False


# --------------------------------------------------------------------------- #
#  Item 1 — Add Company parity with the edit form
# --------------------------------------------------------------------------- #

def test_create_accepts_business_nature_and_derives_its_description():
    """CR derives `natureDesc` from `nature`, so the operator picks a code and
    the description follows. Accepting a typed description would let the two
    disagree."""
    captured = {}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_event", new=AsyncMock()):
        def insert(row):
            captured.update(row)
            m = MagicMock()
            m.execute.return_value.data = [{"id": "e9", **row}]
            return m
        msb.return_value.table.return_value.insert.side_effect = insert
        resp = client.post("/companies", headers=H, json={
            "company_name": "New Co", "status": "live", "company_type": "P",
            "business_nature_code": "070", "mortgages_total": "Nil",
            "cr_number": "3300012",
        })

    assert resp.status_code == 201
    assert captured["business_nature_code"] == "070"
    assert captured["business_nature_desc"]          # derived, not sent
    assert captured["mortgages_total"] == "Nil"


def test_create_refuses_a_business_nature_code_the_edit_form_would_refuse():
    """A code accepted at creation and refused on edit would let a company be
    born unable to save itself."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase"):
        resp = client.post("/companies", headers=H, json={
            "company_name": "New Co", "status": "live",
            "business_nature_code": "ZZZZ"})
    assert resp.status_code == 422
    assert "business nature code" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
#  Clearing a field, and the company phone
# --------------------------------------------------------------------------- #

def test_an_emptied_field_is_stored_as_null_not_ignored():
    """Deleting a value and pressing Save used to do nothing at all, and looked
    exactly like a save that worked -- the old value came back on reload. A
    blank is a real answer, so "" on the wire clears the column."""
    captured = {}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_events", new=AsyncMock()):
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .single.return_value.execute.return_value.data) = {
            "id": "e1", "company_name": "Skyline", "company_name_zh": "天際"}

        def update(values):
            captured.update(values)
            m = MagicMock()
            m.eq.return_value.execute.return_value.data = [{"id": "e1", **values}]
            return m

        sb.table.return_value.update.side_effect = update
        resp = client.patch("/companies/e1", json={"company_name_zh": ""}, headers=H)

    assert resp.status_code == 200
    assert captured["company_name_zh"] is None


def test_clearing_business_nature_clears_the_description_with_it():
    """The description is derived from the code, so it cannot outlive it -- and
    "" must not be validated as a CR code, which is what would happen if the
    normalisation ran after the lookup."""
    captured = {}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_events", new=AsyncMock()):
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .single.return_value.execute.return_value.data) = {
            "id": "e1", "business_nature_code": "070"}

        def update(values):
            captured.update(values)
            m = MagicMock()
            m.eq.return_value.execute.return_value.data = [{"id": "e1", **values}]
            return m

        sb.table.return_value.update.side_effect = update
        resp = client.patch("/companies/e1",
                            json={"business_nature_code": ""}, headers=H)

    assert resp.status_code == 200
    assert captured["business_nature_code"] is None
    assert captured["business_nature_desc"] is None


def test_company_phone_can_be_corrected_after_creation():
    """THE GAP. `company_phone` was accepted by POST /companies, written to
    `contacts`, printed on the profile -- and then unreachable. CR's NAR1 maps
    `telNo` straight off it, so a number mistyped at creation went onto a
    statutory filing with no way to correct it short of SQL."""
    captured = {}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_event", new=AsyncMock()) as audit:
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .single.return_value.execute.return_value.data) = {
            "id": "e1", "company_name": "Skyline", "br_number": "2100031"}
        (sb.table.return_value.select.return_value.eq.return_value.eq.return_value
         .order.return_value.limit.return_value.execute.return_value.data) = [
            {"id": "ct-1", "contact_value": "+852 0000 0000"}]

        def update(values):
            captured.update(values)
            m = MagicMock()
            m.eq.return_value.execute.return_value.data = [{"id": "ct-1", **values}]
            return m

        sb.table.return_value.update.side_effect = update
        resp = client.put("/companies/e1/company-phone",
                          json={"company_phone": "+852 3500 1234"}, headers=H)

    assert resp.status_code == 200
    assert captured["contact_value"] == "+852 3500 1234"
    kwargs = audit.await_args.kwargs
    assert kwargs["action_type"] == "CASE_FIELD_UPDATED"
    assert kwargs["old_value"] == "+852 0000 0000"
    assert kwargs["new_value"] == "+852 3500 1234"


def test_clearing_the_phone_when_none_was_stored_writes_nothing():
    """Inserting a row whose value is NULL would claim a phone record exists."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_event", new=AsyncMock()) as audit:
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .single.return_value.execute.return_value.data) = {
            "id": "e1", "company_name": "Skyline"}
        (sb.table.return_value.select.return_value.eq.return_value.eq.return_value
         .order.return_value.limit.return_value.execute.return_value.data) = []
        resp = client.put("/companies/e1/company-phone",
                          json={"company_phone": ""}, headers=H)

    assert resp.status_code == 200
    sb.table.return_value.insert.assert_not_called()
    audit.assert_not_awaited()


# --------------------------------------------------------------------------- #
#  Items 2, 3 & 11/12 — the vocabularies the dropdowns are drawn from
# --------------------------------------------------------------------------- #

def _serve_lookups(msb):
    (msb.return_value.table.return_value.select.return_value
     .eq.return_value.order.return_value.order.return_value
     .limit.return_value.execute.return_value.data) = []


def test_currency_offers_the_three_gshk_actually_files_in_first():
    """Alphabetical order buried HKD at position 22 of 54, behind AED, AFA, ALL
    and eighteen others nobody here has ever filed."""
    lookups_router.clear_cache()
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.lookups.get_supabase") as msb:
        _serve_lookups(msb)
        codes = [v["code"] for v in client.get("/lookups/cr_currency", headers=H).json()]

    assert codes[:3] == ["EUR", "HKD", "USD"]
    # The list is still complete, and still CR's rather than ISO's.
    assert "RMB" in codes and "CNY" not in codes
    assert len(codes) == len(set(codes))     # pinned, not duplicated


def test_share_class_names_are_offered_but_not_closed():
    lookups_router.clear_cache()
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.lookups.get_supabase") as msb:
        _serve_lookups(msb)
        names = [v["code"] for v in
                 client.get("/lookups/share_class_name", headers=H).json()]
    assert names == ["Ordinary", "Ordinary A", "Ordinary B", "Preference"]


def test_beneficial_owner_vocabularies_are_served_and_are_not_crs():
    lookups_router.clear_cache()
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.lookups.get_supabase") as msb:
        _serve_lookups(msb)
        body = client.get("/lookups", headers=H).json()

    assert [v["code"] for v in body["bo_owner_type"]] == [
        "ubo", "significant_controller"]
    assert [v["label"] for v in body["bo_nature_of_control"]] == [
        "Holds more than 25% of the issued shares of the company",
        "Has the right to exercise, or actually exercises, significant "
        "influence or control over the company",
    ]
    # No `cr_` prefix on purpose: neither NAR1 nor NNC1 carries a single
    # `beneficial_owners.*` field. These are the Companies Ordinance's, not
    # CR's, and mislabelling them would invite someone to map one onto a form.
    assert not any(k.startswith("cr_bo") for k in body)


# --------------------------------------------------------------------------- #
#  Item 10 — a natural person's TCSP licence
# --------------------------------------------------------------------------- #

def test_a_persons_tcsp_licence_can_be_recorded():
    """The Company Secretary tile printed "TCSP Licence No." off the corporate
    party alone, so a secretary who is a licensed individual rendered an em dash
    and no screen in the portal could fill it in."""
    captured = {}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb, \
         patch("routers.persons.log_events", new=AsyncMock()), \
         patch("services.audit_subject.primary_id_number", return_value=None):
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .single.return_value.execute.return_value.data) = {
            "id": "p1", "full_name": "Abo Ahmad"}

        def update(values):
            captured.update(values)
            m = MagicMock()
            m.eq.return_value.execute.return_value.data = [{"id": "p1", **values}]
            return m

        sb.table.return_value.update.side_effect = update
        resp = client.patch("/persons/p1",
                            json={"tcsp_licence_no": "TC000807"}, headers=H)

    assert resp.status_code == 200
    assert captured["tcsp_licence_no"] == "TC000807"


# --------------------------------------------------------------------------- #
#  Item 13 — downloading a superseded version
# --------------------------------------------------------------------------- #

def test_a_superseded_version_downloads_its_own_bytes():
    """The history listed v1, v2 and v3 with a Download button each, and every
    one of them signed the CURRENT version's path -- three buttons, one file,
    three names. Each `document_versions` row has always had its own
    `storage_path`; nothing was reading it."""
    signed = {}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("services.document_service.get_supabase") as msb:
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .single.return_value.execute.return_value.data) = {
            "id": "d1", "current_version": 3, "status": "active",
            "storage_path": "e/d1/v3.pdf", "file_name": "coi-v3.pdf"}
        (sb.table.return_value.select.return_value.eq.return_value.eq.return_value
         .limit.return_value.execute.return_value.data) = [
            {"version_number": 1, "storage_path": "e/d1/v1.pdf",
             "file_name": "coi-v1.pdf"}]

        def create_signed_url(path, ttl, options=None):
            signed["path"] = path
            signed["download"] = (options or {}).get("download")
            return {"signedURL": "https://x/signed"}

        sb.storage.from_.return_value.create_signed_url.side_effect = create_signed_url
        resp = client.get("/documents/d1/versions/1/download", headers=H)

    assert resp.status_code == 200
    assert signed["path"] == "e/d1/v1.pdf"
    assert signed["download"] == "coi-v1.pdf"
    assert resp.json()["file_name"] == "coi-v1.pdf"


def test_a_version_that_does_not_exist_is_a_404_not_the_current_file():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("services.document_service.get_supabase") as msb:
        sb = msb.return_value
        (sb.table.return_value.select.return_value.eq.return_value
         .single.return_value.execute.return_value.data) = {
            "id": "d1", "current_version": 3, "status": "active",
            "storage_path": "e/d1/v3.pdf", "file_name": "coi-v3.pdf"}
        (sb.table.return_value.select.return_value.eq.return_value.eq.return_value
         .limit.return_value.execute.return_value.data) = []
        resp = client.get("/documents/d1/versions/9/download", headers=H)

    assert resp.status_code == 404
    assert "does not exist" in resp.json()["detail"]

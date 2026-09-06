"""PUT /companies/{id}/registered-address and /persons/{id}/residential-address.

Supabase and audit are mocked; no DB is touched. The branch that matters is
copy-vs-update: a shared address row must survive a save unchanged.
"""
from unittest.mock import patch, MagicMock, AsyncMock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

SUPER_ADMIN = {"id": "admin-1", "display_name": "Levi Z.",
               "role_name": "super_admin", "role_id": "role-sa"}
REGULAR = {"id": "u-2", "display_name": "Staff", "role_name": "staff", "role_id": "role-x"}
H = {"Authorization": "Bearer tok"}

GOOD = {
    "line1": "Suite C, Level 7", "line2": "World Trust Tower",
    "line3": "50 Stanley Street", "city": "CENTRAL",
    "state_region": None, "postal_code": None, "country": "HK",
}
OLD_ADDRESS = {
    "id": "addr-old", "line1": "Old flat", "line2": None, "line3": None,
    "city": None, "state_region": None, "postal_code": None, "country": "HK",
}


def _sb_for(*, owner_table, owner_row, reference_count, written_id="addr-new"):
    """A supabase mock wired for one address save.

    `reference_count` is split across entities/persons the way
    address_service.count_references adds them up.
    """
    sb = MagicMock()
    tables = {}

    def table(name):
        return tables.setdefault(name, MagicMock())

    sb.table.side_effect = table

    # owner lookup + the current address lookup both go through .single()
    table(owner_table).select.return_value.eq.return_value.single.return_value \
        .execute.return_value.data = owner_row
    table("addresses").select.return_value.eq.return_value.single.return_value \
        .execute.return_value.data = OLD_ADDRESS

    # count_references: entities + persons, count="exact"
    table("entities").select.return_value.eq.return_value.limit.return_value \
        .execute.return_value.count = reference_count
    table("persons").select.return_value.eq.return_value.limit.return_value \
        .execute.return_value.count = 0

    written = {**GOOD, "id": written_id}
    table("addresses").insert.return_value.execute.return_value.data = [written]
    table("addresses").update.return_value.eq.return_value.execute.return_value.data = [
        {**GOOD, "id": OLD_ADDRESS["id"]}
    ]
    return sb, tables


# ---- access control ---------------------------------------------------------

def test_company_address_requires_a_token():
    assert client.put("/companies/c-1/registered-address", json=GOOD).status_code == 403


def test_company_address_requires_companies_write():
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb:
        msb.return_value.table.return_value.select.return_value.eq.return_value \
            .eq.return_value.execute.return_value.data = []
        resp = client.put("/companies/c-1/registered-address", json=GOOD, headers=H)
    assert resp.status_code == 403


def test_person_address_requires_persons_write():
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb:
        msb.return_value.table.return_value.select.return_value.eq.return_value \
            .eq.return_value.execute.return_value.data = []
        resp = client.put("/persons/p-1/residential-address", json=GOOD, headers=H)
    assert resp.status_code == 403


# ---- copy-on-write ----------------------------------------------------------

def test_a_shared_address_is_copied_and_the_original_is_left_alone():
    """The whole point. GSHK's registered office is on 4,446 companies; saving
    one company's address must not UPDATE that row."""
    sb, tables = _sb_for(
        owner_table="entities",
        owner_row={"id": "c-1", "company_name": "TRiVANTA", "registered_address_id": "addr-old"},
        reference_count=4446,
    )
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase", return_value=sb), \
         patch("routers.companies.log_events", new=AsyncMock()):
        resp = client.put("/companies/c-1/registered-address", json=GOOD, headers=H)

    assert resp.status_code == 200
    tables["addresses"].insert.assert_called_once()
    tables["addresses"].update.assert_not_called()
    # and the company now points at the new row
    tables["entities"].update.assert_called_once()
    assert tables["entities"].update.call_args[0][0] == {"registered_address_id": "addr-new"}


def test_an_unshared_address_is_edited_in_place():
    """No copy when this company is the only referent — otherwise every edit
    would litter the table with a new row."""
    sb, tables = _sb_for(
        owner_table="entities",
        owner_row={"id": "c-1", "company_name": "TRiVANTA", "registered_address_id": "addr-old"},
        reference_count=1,
    )
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase", return_value=sb), \
         patch("routers.companies.log_events", new=AsyncMock()):
        resp = client.put("/companies/c-1/registered-address", json=GOOD, headers=H)

    assert resp.status_code == 200
    tables["addresses"].update.assert_called_once()
    tables["addresses"].insert.assert_not_called()


def test_a_company_with_no_address_yet_gets_a_new_row():
    sb, tables = _sb_for(
        owner_table="entities",
        owner_row={"id": "c-1", "company_name": "TRiVANTA", "registered_address_id": None},
        reference_count=0,
    )
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase", return_value=sb), \
         patch("routers.companies.log_events", new=AsyncMock()):
        resp = client.put("/companies/c-1/registered-address", json=GOOD, headers=H)

    assert resp.status_code == 200
    tables["addresses"].insert.assert_called_once()


# ---- validation -------------------------------------------------------------

def test_a_line_over_sixty_is_refused_with_422_and_nothing_is_written():
    """The API must not accept what the NAR1 mapper will later reject — that
    is exactly how the 874 bad rows arose."""
    sb, tables = _sb_for(
        owner_table="entities",
        owner_row={"id": "c-1", "company_name": "TRiVANTA", "registered_address_id": "addr-old"},
        reference_count=1,
    )
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase", return_value=sb), \
         patch("routers.companies.log_events", new=AsyncMock()):
        resp = client.put(
            "/companies/c-1/registered-address",
            json={**GOOD, "line3": "x" * 61}, headers=H,
        )

    assert resp.status_code == 422
    assert "line3" in resp.json()["detail"]
    tables["addresses"].update.assert_not_called()
    tables["addresses"].insert.assert_not_called()


def test_an_unknown_hong_kong_district_is_refused():
    sb, _ = _sb_for(
        owner_table="entities",
        owner_row={"id": "c-1", "company_name": "TRiVANTA", "registered_address_id": "addr-old"},
        reference_count=1,
    )
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase", return_value=sb), \
         patch("routers.companies.log_events", new=AsyncMock()):
        resp = client.put(
            "/companies/c-1/registered-address",
            json={**GOOD, "city": "Atlantis"}, headers=H,
        )
    assert resp.status_code == 422
    assert "Atlantis" in resp.json()["detail"]


def test_an_unknown_field_is_refused_rather_than_silently_dropped():
    """A typo'd key that is ignored looks exactly like a save that worked."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN):
        resp = client.put(
            "/companies/c-1/registered-address",
            json={**GOOD, "line4": "nope"}, headers=H,
        )
    assert resp.status_code == 422


# ---- audit ------------------------------------------------------------------

def test_a_copy_records_what_it_was_copied_from():
    """Otherwise the trail shows an address changing with no account of why
    the other 4,445 companies did not change too."""
    sb, _ = _sb_for(
        owner_table="entities",
        owner_row={"id": "c-1", "company_name": "TRiVANTA", "registered_address_id": "addr-old"},
        reference_count=4446,
    )
    logged = AsyncMock()
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase", return_value=sb), \
         patch("routers.companies.log_events", new=logged):
        client.put("/companies/c-1/registered-address", json=GOOD, headers=H)

    entries = logged.await_args[0][0]
    assert entries, "a changed address must audit"
    assert all(e["action_type"] == "CASE_FIELD_UPDATED" for e in entries)
    assert all(e["event_code"] == "LRO" for e in entries)
    assert all(e["metadata"]["copied_from"] == "addr-old" for e in entries)


def test_a_person_address_audits_under_the_master_details_code():
    sb, _ = _sb_for(
        owner_table="persons",
        owner_row={"id": "p-1", "full_name": "CHAN, Tai Man", "residential_address_id": "addr-old"},
        reference_count=1,
    )
    logged = AsyncMock()
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase", return_value=sb), \
         patch("routers.persons.log_events", new=logged):
        resp = client.put("/persons/p-1/residential-address", json=GOOD, headers=H)

    assert resp.status_code == 200
    entries = logged.await_args[0][0]
    assert all(e["event_code"] == "ADC" for e in entries)


def test_an_unchanged_field_is_not_audited():
    """One entry per CHANGED line — re-saving an identical address is not
    twelve field updates."""
    sb, _ = _sb_for(
        owner_table="entities",
        owner_row={"id": "c-1", "company_name": "TRiVANTA", "registered_address_id": "addr-old"},
        reference_count=1,
    )
    logged = AsyncMock()
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase", return_value=sb), \
         patch("routers.companies.log_events", new=logged):
        client.put("/companies/c-1/registered-address", json=GOOD, headers=H)

    fields = {e["before_state"]["field"] for e in logged.await_args[0][0]}
    assert "country" not in fields  # HK before and after

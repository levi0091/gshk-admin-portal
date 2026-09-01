"""Block 5 — what the Body Corporate Registry screen needs from the API.

Brian's B4 (shareholders need an address), B9 (business name on the profile)
and OQ-3 (statutory record locations, fully editable) all describe data that
already existed in Postgres and that nothing ever sent to the screen. This
covers the reading of it, and the one new write.

Addresses are the reason this is one batched lookup rather than several: a
profile with eight directors, four shareholders and thirteen registers would
otherwise be twenty-five sequential ~200ms round trips to Supabase.
"""
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

SUPER_ADMIN = {"id": "admin-1", "display_name": "Levi Z.",
               "role_name": "super_admin", "role_id": "role-sa"}
H = {"Authorization": "Bearer tok"}


class _Table:
    """One table's answers, matched on the filters the router applies."""

    def __init__(self, rows, single=None):
        self._rows = rows
        self._single = single
        self.updates = []
        self.upserts = []

    # -- query building: every filter is a no-op that returns self ----------
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def neq(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def range(self, *a, **k): return self

    def single(self):
        return _Single(self._single)

    def update(self, values):
        self.updates.append(values)
        return _Returning([{**(self._single or {}), **values}])

    def upsert(self, values, **kwargs):
        self.upserts.append((values, kwargs))
        return _Returning([values])

    def execute(self):
        return SimpleNamespace(data=self._rows, count=len(self._rows))


class _Single:
    def __init__(self, row): self._row = row
    def execute(self): return SimpleNamespace(data=self._row)


class _Returning:
    def __init__(self, rows): self._rows = rows
    def eq(self, *a, **k): return self
    def execute(self): return SimpleNamespace(data=self._rows)


class _Supabase:
    def __init__(self, tables): self.tables = tables
    def table(self, name):
        return self.tables.setdefault(name, _Table([]))


ENTITY = {
    "id": "e1", "company_name": "Skyline Capital", "is_client": True,
    "registered_address_id": None, "business_nature_code": "070",
}

# A director whose correspondence address differs from where they live — the
# 22 real officers in DEV for whom D2 is not a redundant column.
OFFICER = {
    "id": "o1", "role": "director", "entity_id": "e1",
    "correspondence_address_id": "addr-corr",
    "persons": {"id": "p1", "full_name": "John Smith",
                "email": "js@x.com", "residential_address_id": "addr-home"},
}
SHAREHOLDER = {
    "id": "s1", "entity_id": "e1", "shares_held": 100,
    "corporate_entity_id": "e9",
    "persons": None,
    "share_classes": {"class_name": "Ordinary", "currency": "HKD"},
}
ADDRESSES = [
    {"id": "addr-corr", "line1": "Care of GSHK", "country": "HK"},
    {"id": "addr-home", "line1": "Flat 3B", "country": "HK"},
    {"id": "addr-reg", "line1": "Suite 900", "country": "HK"},
    {"id": "addr-recs", "line1": "Records Room", "country": "HK"},
]


def _tables(**overrides):
    tables = {
        "entities": _Table([{"id": "e9", "company_name": "Asia BC Ltd",
                             "registered_address_id": "addr-reg"}],
                           single=ENTITY),
        "entity_officers": _Table([OFFICER]),
        "shareholdings": _Table([SHAREHOLDER]),
        "beneficial_owners": _Table([]),
        "contacts": _Table([]),
        "share_classes": _Table([]),
        "business_names": _Table([
            {"id": "bn1", "business_name": "Skyline Advisory",
             "business_name_zh": "天際顧問", "status": "active"}]),
        "entity_record_locations": _Table([
            {"id": "rl1", "record_type": "SM", "address_id": "addr-recs"}]),
        "addresses": _Table(ADDRESSES),
        "nar1_case_registry": _Table([]),
        "nnc1_cases": _Table([]),
    }
    tables.update(overrides)
    return tables


def _get_company(tables=None):
    tables = tables if tables is not None else _tables()
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase",
               return_value=_Supabase(tables)), \
         patch("routers.companies.document_service.list_documents",
               return_value=[]), \
         patch("routers.companies.address_service.count_references",
               return_value=1):
        return client.get("/companies/e1", headers=H)


# --- reading -------------------------------------------------------------

def test_the_profile_carries_the_business_name():
    """B9. `business_names` holds 5,026 named rows and no screen showed one."""
    body = _get_company().json()

    assert [b["business_name"] for b in body["business_names"]] == ["Skyline Advisory"]


def test_a_director_carries_the_correspondence_address_not_just_its_id():
    """D2. The id was already on the row; without the address itself the
    screen can only render a UUID."""
    officer = _get_company().json()["officers"][0]

    assert officer["correspondence_address"]["line1"] == "Care of GSHK"


def test_a_director_carries_their_residential_address_too():
    """CR wants both, and they differ for the 22 officers D2 exists for."""
    officer = _get_company().json()["officers"][0]

    assert officer["persons"]["residential_address"]["line1"] == "Flat 3B"


def test_a_corporate_shareholder_carries_its_registered_office():
    """B4 — 'shareholders need an address' covers bodies corporate, whose
    address is their registered office rather than a residence."""
    shareholder = _get_company().json()["shareholders"][0]

    assert shareholder["corporate_entity"]["registered_address"]["line1"] == "Suite 900"


def test_record_locations_carry_their_address_and_a_label():
    """OQ-3. `SM` is CR's Register of Members; the code alone is unreadable."""
    locations = _get_company().json()["record_locations"]
    members = next(r for r in locations if r["record_type"] == "SM")

    assert members["address"]["line1"] == "Records Room"
    assert members["label"] == "Register of Members"


def test_every_register_cr_asks_about_is_listed_even_with_no_address():
    """A register with nowhere recorded is the answer NAR1 s16 needs to show,
    not a row to omit — 13 registers, one seeded."""
    locations = _get_company().json()["record_locations"]

    assert len(locations) == 13
    assert all("label" in r for r in locations)
    assert sum(1 for r in locations if r["address"]) == 1


def test_addresses_are_fetched_in_one_batch():
    """Twenty-five sequential lookups is most of a profile's load time."""
    tables = _tables()
    calls = []
    original = tables["addresses"].in_

    def counting_in(*a, **k):
        calls.append(a)
        return original(*a, **k)

    tables["addresses"].in_ = counting_in
    _get_company(tables)

    assert len(calls) == 1


# --- writing (OQ-3: fully editable) --------------------------------------

def _put_record_location(record_type, body, tables=None):
    tables = tables if tables is not None else _tables()
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase",
               return_value=_Supabase(tables)), \
         patch("routers.companies.log_events", new=AsyncMock()):
        return client.put(f"/companies/e1/record-locations/{record_type}",
                          headers=H, json=body)


def test_a_register_location_can_be_repointed():
    tables = _tables()
    resp = _put_record_location("SM", {"address_id": "addr-reg"}, tables)

    assert resp.status_code == 200
    written, _ = tables["entity_record_locations"].upserts[0]
    assert written["address_id"] == "addr-reg"
    assert written["record_type"] == "SM"


def test_a_register_location_can_be_cleared():
    """'We do not keep this register here' is an answer, not a missing one."""
    tables = _tables()
    resp = _put_record_location("SM", {"address_id": None}, tables)

    assert resp.status_code == 200
    written, _ = tables["entity_record_locations"].upserts[0]
    assert written["address_id"] is None


def test_a_record_type_cr_does_not_ask_about_is_refused():
    """`SS` is a company seal — a physical object, deliberately excluded."""
    resp = _put_record_location("SS", {"address_id": "addr-reg"})

    assert resp.status_code == 422
    assert "SS" in resp.text


def test_repointing_a_register_is_audited():
    """No new action_type (PRD §12b) — a field edit on the company."""
    logged = AsyncMock()
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase",
               return_value=_Supabase(_tables())), \
         patch("routers.companies.log_events", new=logged):
        client.put("/companies/e1/record-locations/SM", headers=H,
                   json={"address_id": "addr-reg"})

    entries = logged.await_args.args[0]
    assert entries[0]["action_type"] == "CASE_FIELD_UPDATED"
    assert entries[0]["new_value"] == "addr-reg"


def test_repointing_a_register_to_where_it_already_is_writes_no_audit_row():
    """The trail records changes. A no-op save is not one."""
    logged = AsyncMock()
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase",
               return_value=_Supabase(_tables())), \
         patch("routers.companies.log_events", new=logged):
        client.put("/companies/e1/record-locations/SM", headers=H,
                   json={"address_id": "addr-recs"})

    assert logged.await_args.args[0] == []


def test_setting_a_register_location_needs_companies_write():
    """Mocked at `middleware.auth.get_supabase`, never the live client — a
    permission test that reaches DEV passes locally and fails in CI."""
    reader = {**SUPER_ADMIN, "role_name": "case_manager", "role_id": "role-cm"}
    with patch("middleware.auth._resolve_user", return_value=reader), \
         patch("middleware.auth.get_supabase") as msb:
        # No matching row in role_permissions -> insufficient.
        (msb.return_value.table.return_value.select.return_value.eq.return_value
         .eq.return_value.execute.return_value.data) = []
        resp = client.put("/companies/e1/record-locations/SM", headers=H,
                          json={"address_id": "addr-reg"})

    assert resp.status_code == 403

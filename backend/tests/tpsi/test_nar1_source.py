"""services/tpsi/forms/nar1_source.py — the one module in BE-1 that touches
Supabase, so the one that has to be proved against a mocked client.

Mocked at the get_supabase() boundary, the same boundary tests/test_nar1_cases.py
mocks. NOTHING here reaches the DEV database: a test that silently reached DEV
would still pass, and that is exactly how five TPSI tests came to be issuing
live DELETEs.

The double is a real (tiny) query engine rather than a MagicMock returning one
fixed payload, because the loader queries `entities` TWICE with different
filters -- once by id for the filing company, once by `in_` for the corporate
parties -- and a fixed return_value cannot tell those apart.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.tpsi.forms import nar1_source


class _Query:
    def __init__(self, rows: list[dict], log: list):
        self._rows = list(rows)
        self._filters: list[tuple] = []
        self._log = log

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self._filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self._filters.append(("in", column, list(values)))
        return self

    def execute(self):
        rows = self._rows
        for kind, column, value in self._filters:
            if kind == "eq":
                rows = [r for r in rows if r.get(column) == value]
            else:
                rows = [r for r in rows if r.get(column) in value]
        self._log.append((self._filters, len(rows)))
        return SimpleNamespace(data=rows)


class _Supabase:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables
        self.queried: list[str] = []
        self.log: dict[str, list] = {}

    def table(self, name):
        self.queried.append(name)
        return _Query(self._tables.get(name, []), self.log.setdefault(name, []))


ENTITY = {
    "id": "e1", "company_name": "TEST COMPANY LIMITED",
    "company_name_zh": "測試有限公司", "br_number": "00000001",
    "registered_address_id": "a1",
}
FILER_ADDR = {"id": "a1", "line1": "Flat A", "country": "Hong Kong"}
RES_ADDR = {"id": "a2", "line1": "Flat B", "country": "Hong Kong"}
CORP_ADDR = {"id": "a3", "line1": "Suite 1", "country": "Hong Kong"}
PERSON = {"id": "p1", "full_name": "CHAN TAI MAN", "surname": "CHAN",
          "given_names": "TAI MAN", "residential_address_id": "a2"}
HOLDCO = {"id": "c1", "company_name": "HOLDCO LIMITED",
          "company_name_zh": "控股有限公司", "br_number": "00000002",
          "registered_address_id": "a3"}


# ---- the failure path ------------------------------------------------------

async def test_an_unknown_entity_raises_lookup_error():
    sb = _Supabase({"entities": []})
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        with pytest.raises(LookupError):
            await nar1_source.load_entity_graph("nope")


# ---- the happy path --------------------------------------------------------

async def test_loads_an_individual_officer_with_person_address_and_id_docs():
    sb = _Supabase({
        "entities": [ENTITY],
        "entity_officers": [{"id": "o1", "entity_id": "e1", "person_id": "p1",
                             "party_type": "individual", "role": "director",
                             "is_current": True}],
        "company_secretaries": [{"id": "s1", "entity_id": "e1", "is_gshk": True,
                                 "secretary_name": "Get Started HK Limited",
                                 "is_current": True}],
        "share_classes": [{"id": "sc1", "entity_id": "e1",
                           "class_name": "Ordinary"}],
        "shareholdings": [{"id": "sh1", "entity_id": "e1", "share_class_id": "sc1",
                           "person_id": "p1", "party_type": "individual",
                           "is_current": True}],
        "persons": [PERSON],
        "person_identity_documents": [{"id": "d1", "person_id": "p1",
                                       "id_type": "hkid",
                                       "id_number": "A123456(7)"}],
        "addresses": [FILER_ADDR, RES_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    assert graph["entity"]["id"] == "e1"
    assert graph["registered_address"] == FILER_ADDR
    assert graph["persons"]["p1"]["surname"] == "CHAN"
    assert graph["addresses"]["a2"] == RES_ADDR
    assert [d["id_type"] for d in graph["identity_documents"]["p1"]] == ["hkid"]
    assert len(graph["officers"]) == 1
    assert len(graph["secretaries"]) == 1
    assert len(graph["share_classes"]) == 1
    assert len(graph["shareholdings"]) == 1


async def test_a_company_with_no_secretary_and_no_shareholder_still_loads():
    """Empty is empty, not None -- the mapper indexes these keys directly."""
    sb = _Supabase({"entities": [ENTITY], "addresses": [FILER_ADDR]})
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    assert graph["secretaries"] == []
    assert graph["shareholdings"] == []
    assert graph["officers"] == []
    assert graph["share_classes"] == []
    assert graph["persons"] == {}
    assert graph["identity_documents"] == {}


# ---- the .in_() guards -----------------------------------------------------

async def test_no_person_ids_means_the_person_tables_are_never_queried():
    """PostgREST turns .in_("id", []) into a filter that matches nothing but
    still costs a round trip -- and on some builds errors outright."""
    sb = _Supabase({"entities": [ENTITY], "addresses": [FILER_ADDR]})
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        await nar1_source.load_entity_graph("e1")

    assert "persons" not in sb.queried
    assert "person_identity_documents" not in sb.queried


async def test_no_address_ids_means_the_addresses_table_is_never_queried():
    sb = _Supabase({"entities": [{**ENTITY, "registered_address_id": None}]})
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    assert "addresses" not in sb.queried
    assert graph["addresses"] == {}
    assert graph["registered_address"] is None


# ---- corporate parties (migration 007 corporate_entity_id) -----------------

async def test_a_corporate_officer_carries_its_own_address_not_the_filers():
    """entity_officers.corporate_entity_id -> entities -> that entity's own
    registered office. Substituting the filing company's address puts a wrong
    address on a statutory return, and CR accepts it."""
    sb = _Supabase({
        "entities": [ENTITY, HOLDCO],
        "entity_officers": [{"id": "o1", "entity_id": "e1", "role": "director",
                             "party_type": "corporate",
                             "corporate_entity_id": "c1", "is_current": True}],
        "addresses": [FILER_ADDR, CORP_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    officer = graph["officers"][0]
    assert officer["corporate_address"] == CORP_ADDR
    assert officer["corporate_address"] != graph["registered_address"]
    assert officer["corporate_name"] == "HOLDCO LIMITED"
    assert officer["corporate_br_no"] == "00000002"
    assert officer["corporate_name_zh"] == "控股有限公司"


async def test_a_corporate_shareholder_carries_its_own_address():
    sb = _Supabase({
        "entities": [ENTITY, HOLDCO],
        "shareholdings": [{"id": "sh1", "entity_id": "e1", "share_class_id": "sc1",
                           "party_type": "corporate", "corporate_entity_id": "c1",
                           "is_current": True}],
        "addresses": [FILER_ADDR, CORP_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    assert graph["shareholdings"][0]["corporate_address"] == CORP_ADDR


async def test_a_corporate_party_with_no_address_row_gets_none_not_the_filers():
    """The loader does not invent one. `None` here is what makes the mapper
    raise MappingError instead of filing the filer's address."""
    sb = _Supabase({
        "entities": [ENTITY, {**HOLDCO, "registered_address_id": None}],
        "entity_officers": [{"id": "o1", "entity_id": "e1", "role": "director",
                             "party_type": "corporate",
                             "corporate_entity_id": "c1", "is_current": True}],
        "addresses": [FILER_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    assert graph["officers"][0]["corporate_address"] is None


async def test_no_corporate_parties_means_no_second_entities_query():
    sb = _Supabase({
        "entities": [ENTITY],
        "entity_officers": [{"id": "o1", "entity_id": "e1", "person_id": "p1",
                             "party_type": "individual", "role": "director",
                             "is_current": True}],
        "persons": [PERSON],
        "addresses": [FILER_ADDR, RES_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        await nar1_source.load_entity_graph("e1")

    assert sb.queried.count("entities") == 1

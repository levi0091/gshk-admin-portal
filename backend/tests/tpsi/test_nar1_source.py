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


# ---- the corporate company secretary's own entity --------------------------

#: GSHK, as a body corporate in its own right. `company_secretaries` names it
#: and holds nothing else about it, so everything below has to be reached
#: through the entities table.
GSHK = {"id": "g1", "company_name": "Get Started HK Limited",
        "company_name_zh": "", "br_number": "67169839",
        "registered_address_id": "a4"}
GSHK_ADDR = {"id": "a4", "line1": "Suite C, Level 7", "country": "Hong Kong"}


def _secretary(**over):
    row = {"id": "s1", "entity_id": "e1", "is_gshk": True,
           "secretary_name": "Get Started HK Limited",
           "tcsp_number": "TC000807", "is_current": True}
    row.update(over)
    return row


async def test_a_corporate_secretary_carries_its_own_address_and_br_number():
    """The register has no FK to the party, so the secretary's address, BR
    number and Chinese name are reached by resolving its NAME to an entity.
    Before this the mapper filed the FILING COMPANY's registered office --
    wrong for 1,043 of 5,604 companies on DEV."""
    sb = _Supabase({
        "entities": [ENTITY, GSHK],
        "company_secretaries": [_secretary()],
        "addresses": [FILER_ADDR, GSHK_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    sec = graph["secretaries"][0]
    assert sec["corporate_entity_resolution"] == "ok"
    assert sec["corporate_entity_id"] == "g1"
    assert sec["corporate_address"] == GSHK_ADDR
    assert sec["corporate_address"] != graph["registered_address"]
    assert sec["corporate_br_no"] == "67169839"


async def test_a_secretary_already_loaded_as_an_officer_costs_no_extra_query():
    """The GSHK secretary is usually ALSO an entity_officers row, so its entity
    is already in hand. Resolving by name must not issue a third `entities`
    query for a company already loaded -- each Supabase round trip is ~200ms in
    front of every filing."""
    sb = _Supabase({
        "entities": [ENTITY, GSHK],
        "entity_officers": [{"id": "o1", "entity_id": "e1",
                             "role": "company_secretary",
                             "party_type": "corporate",
                             "corporate_name": "GETSTA",
                             "corporate_entity_id": "g1", "is_current": True}],
        "company_secretaries": [_secretary()],
        "addresses": [FILER_ADDR, GSHK_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    assert graph["secretaries"][0]["corporate_entity_id"] == "g1"
    assert sb.queried.count("entities") == 2      # the filer, then the parties


async def test_a_secretary_the_officer_register_does_not_cover_is_looked_up():
    """The 796 companies whose officer register names a DIFFERENT firm from
    their secretary register. The officer's entity cannot answer for the
    secretary, so the name is resolved against `entities` directly."""
    other = {"id": "c9", "company_name": "Cheap Incorporation Limited",
             "registered_address_id": "a3"}
    sb = _Supabase({
        "entities": [ENTITY, GSHK, other],
        "entity_officers": [{"id": "o1", "entity_id": "e1",
                             "role": "company_secretary",
                             "party_type": "corporate",
                             "corporate_entity_id": "c9", "is_current": True}],
        "company_secretaries": [_secretary()],
        "addresses": [FILER_ADDR, CORP_ADDR, GSHK_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    sec = graph["secretaries"][0]
    assert sec["corporate_entity_id"] == "g1"
    assert sec["corporate_address"] == GSHK_ADDR
    assert sb.queried.count("entities") == 3      # filer, parties, by name


async def test_a_secretary_naming_no_company_on_record_resolves_to_not_found():
    sb = _Supabase({
        "entities": [ENTITY],
        "company_secretaries": [_secretary(secretary_name="Nobody Limited")],
        "addresses": [FILER_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    sec = graph["secretaries"][0]
    assert sec["corporate_entity_resolution"] == "not_found"
    assert sec["corporate_address"] is None


async def test_two_companies_of_the_same_name_resolve_to_ambiguous():
    """They have different addresses and different BR numbers. Picking the
    first would put a plausible, unverifiable, possibly wrong company on a
    statutory return."""
    twin = {"id": "g2", "company_name": "Get Started HK Limited",
            "br_number": "99999999", "registered_address_id": "a3"}
    sb = _Supabase({
        "entities": [ENTITY, GSHK, twin],
        "company_secretaries": [_secretary()],
        "addresses": [FILER_ADDR, GSHK_ADDR, CORP_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    sec = graph["secretaries"][0]
    assert sec["corporate_entity_resolution"] == "ambiguous"
    assert "corporate_entity_id" not in sec
    assert sec["corporate_address"] is None


async def test_an_individual_secretary_is_not_resolved_as_a_body_corporate():
    """A register row with a person_id is a natural-person secretary; it has no
    entity to resolve and must not acquire one."""
    sb = _Supabase({
        "entities": [ENTITY, GSHK],
        "company_secretaries": [_secretary(person_id="p1", secretary_name=None)],
        "persons": [PERSON],
        "addresses": [FILER_ADDR, RES_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    assert "corporate_entity_resolution" not in graph["secretaries"][0]


async def test_the_linked_entitys_name_beats_the_stored_viewpoint_code():
    """`corporate_name` holds Viewpoint's entity CODE, not a company name --
    "GETSTA", "57THST", "BLACKANDWH" -- on 5,604 of 5,606 current corporate
    officers and all 213 corporate shareholdings on DEV. Preferring it over the
    linked entity is what named a reserve director "GETSTA" on a rendered
    return and a Schedule 1 member "57THST"."""
    sb = _Supabase({
        "entities": [ENTITY, HOLDCO],
        "entity_officers": [{"id": "o1", "entity_id": "e1", "role": "director",
                             "party_type": "corporate",
                             "corporate_name": "HOLDCO",
                             "corporate_entity_id": "c1", "is_current": True}],
        "shareholdings": [{"id": "sh1", "entity_id": "e1", "share_class_id": "sc1",
                           "party_type": "corporate",
                           "corporate_name": "57THST",
                           "corporate_entity_id": "c1", "is_current": True}],
        "addresses": [FILER_ADDR, CORP_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    assert graph["officers"][0]["corporate_name"] == "HOLDCO LIMITED"
    assert graph["shareholdings"][0]["corporate_name"] == "HOLDCO LIMITED"


async def test_the_corporate_parties_are_returned_for_the_return_data_card():
    """nar1_return_data._party_name has always looked for graph["entities"] to
    name a body corporate and never found it -- the key was not returned -- so
    the Data Verification card showed "GETSTA" as the company secretary."""
    sb = _Supabase({
        "entities": [ENTITY, HOLDCO],
        "entity_officers": [{"id": "o1", "entity_id": "e1", "role": "director",
                             "party_type": "corporate",
                             "corporate_entity_id": "c1", "is_current": True}],
        "addresses": [FILER_ADDR, CORP_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    assert graph["entities"]["c1"]["company_name"] == "HOLDCO LIMITED"


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


# ---- entities.email, attached as `corporate_email` (migration 045) ----------

async def test_a_corporate_secretary_carries_its_own_email():
    """CR holds one for each body corporate and diffs the filed return against
    it — an empty element is what produced the discrepancy notice against
    GET STARTED HK LIMITED."""
    sb = _Supabase({
        "entities": [ENTITY, {**GSHK, "email": "dataresources@getstarted.hk"}],
        "company_secretaries": [_secretary()],
        "addresses": [FILER_ADDR, GSHK_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    assert graph["secretaries"][0]["corporate_email"] == "dataresources@getstarted.hk"


async def test_a_corporate_officer_carries_its_own_email():
    sb = _Supabase({
        "entities": [ENTITY, {**HOLDCO, "email": "board@holdco.example"}],
        "entity_officers": [{"id": "o1", "entity_id": "e1", "role": "director",
                             "party_type": "corporate",
                             "corporate_entity_id": "c1", "is_current": True}],
        "addresses": [FILER_ADDR, CORP_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    assert graph["officers"][0]["corporate_email"] == "board@holdco.example"


async def test_a_party_row_without_the_column_does_not_blow_up_the_load():
    """A deployment whose 045 has not run yet returns entity rows with no
    `email` key. CR marks the field optional, so a filing must not 500 over it
    — this is the deploy-before-migrate window, which is the normal order here
    because Railway deploys on push and alembic is run by hand."""
    sb = _Supabase({
        "entities": [ENTITY, GSHK],          # no `email` key on either row
        "company_secretaries": [_secretary()],
        "addresses": [FILER_ADDR, GSHK_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    assert graph["secretaries"][0]["corporate_email"] is None


# ---- entities.tcsp_licence_no, attached as `corporate_tcsp_licence_no` ------

async def test_a_corporate_secretary_officer_row_carries_its_entitys_tcsp_licence():
    """PROD 2026-09-19, Payward Limited: a company profile created IN THE
    PORTAL has its secretary in `entity_officers` only. `company_secretaries`
    is the Viewpoint ETL's register and the portal never writes it, so that
    profile had no row there, and the register row was the only place the
    mapper looked for a licence. The NAR1 printed an empty Licence No. box
    under a profile screen showing TC000807, which it reads off the
    secretary's own entity. That entity is where this has to come from too."""
    sb = _Supabase({
        "entities": [ENTITY, {**GSHK, "tcsp_licence_no": "TC000807"}],
        "entity_officers": [{"id": "o1", "entity_id": "e1",
                             "role": "company_secretary",
                             "party_type": "corporate",
                             "corporate_entity_id": "g1", "is_current": True}],
        "addresses": [FILER_ADDR, GSHK_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    assert graph["officers"][0]["corporate_tcsp_licence_no"] == "TC000807"


async def test_a_register_secretary_carries_its_entitys_tcsp_licence():
    sb = _Supabase({
        "entities": [ENTITY, {**GSHK, "tcsp_licence_no": "TC000807"}],
        "company_secretaries": [_secretary(tcsp_number="")],
        "addresses": [FILER_ADDR, GSHK_ADDR],
    })
    with patch("services.tpsi.forms.nar1_source.get_supabase", return_value=sb):
        graph = await nar1_source.load_entity_graph("e1")

    assert graph["secretaries"][0]["corporate_tcsp_licence_no"] == "TC000807"

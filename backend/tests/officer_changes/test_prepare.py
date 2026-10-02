"""The router's one door to CR's XML: build, problems, and the consent plan."""
import asyncio

import pytest

from services.officer_changes import prepare
from tests.officer_changes import cr_fixtures as fx
from tests.officer_changes.fakes import FakeSupabase

CASE = {"id": "K1", "entity_id": "E1", "form_code": "Nd2a"}


def _director_world():
    path = next(p for p in fx.files("ND2A") if "Appoint Individual Director" in p.name)
    return fx.build_world(path)


@pytest.fixture
def world(monkeypatch):
    graph, entries = _director_world()

    async def load(entity_id, entries_):
        return graph

    monkeypatch.setattr(prepare.source, "load_graph", load)
    return graph, entries


def test_build_uses_the_individual_default_capacity(world):
    graph, entries = world
    xml = asyncio.run(prepare.build_form_xml(CASE, entries))
    assert "<cr:selectCapacityDesc>Director</cr:selectCapacityDesc>" in xml
    assert '<cr:appOfNpBean id="S1">' in xml


def test_the_cases_stored_capacity_wins(world):
    graph, entries = world
    xml = asyncio.run(prepare.build_form_xml({**CASE, "signatory_capacity": "Secretary"},
                                             entries))
    assert "<cr:selectCapacityDesc>Secretary</cr:selectCapacityDesc>" in xml


def test_problems_are_returned_never_raised(world, monkeypatch):
    graph, entries = world
    graph["entity"]["br_number"] = ""
    assert any("BR number" in p for p in asyncio.run(prepare.mapping_problems(CASE, entries)))

    async def broken(entity_id, entries_):
        raise RuntimeError("database down")
    monkeypatch.setattr(prepare.source, "load_graph", broken)
    out = asyncio.run(prepare.mapping_problems(CASE, entries))
    assert out and "database down" in out[0]


def test_an_overlong_value_is_a_mapping_problem(world):
    graph, entries = world
    pid = entries[0]["person_id"]
    graph["persons"][pid]["email"] = "x" * 70 + "@example.com"
    problems = asyncio.run(prepare.mapping_problems(CASE, entries))
    assert any("indvEmailAddr" in p or "Email" in p for p in problems)


def test_consent_plan_names_who_is_missing_a_credential(monkeypatch):
    fake = FakeSupabase({"persons": [{"id": "P1", "full_name": "HO New"},
                                     {"id": "P2", "full_name": "LAM Ready"}],
                         # A Hong Kong company: e-Reg takes its consent (Brian, A10).
                         "entities": [{"id": "C9", "company_name": "Corp Director Limited",
                                       "incorporation_place": "HK"}],
                         "person_eservice_credentials": [
                             {"person_id": "P2", "eservice_user_id": "ER2",
                              "eservice_person_name": "LAM, READY",
                              "eservice_password_enc": "enc"}]})
    monkeypatch.setattr(prepare, "get_supabase", lambda: fake)
    monkeypatch.setattr(prepare.eservice, "get_supabase", lambda: fake)
    entries = [
        {"id": "N1", "kind": "appointment", "capacity": "director", "person_id": "P1"},
        {"id": "N2", "kind": "appointment", "capacity": "company_secretary", "person_id": "P1"},
        {"id": "N3", "kind": "appointment", "capacity": "director",
         "corporate_entity_id": "C9", "consent_person_id": "P2",
         "consent_signed_at": "2026-10-01T00:00:00Z"},
        {"id": "N4", "kind": "cessation", "capacity": "director", "person_id": "P2"},
    ]
    plan = asyncio.run(prepare.consent_plan(CASE, entries))
    assert [(p["entry_id"], p["bean_id"], p["ready"]) for p in plan] == [
        ("N1", "S1", False), ("N3", "S2", True)]
    assert plan[0]["reason"] == "HO New has no e-Registry account stored on their profile"
    assert plan[1]["eservice_user_id"] == "ER2" and plan[1]["signed_at"]
    assert "enc" not in str(plan)


def test_an_nd2b_needs_no_consent():
    entries = [{"id": "N1", "kind": "change", "capacity": "director", "person_id": "P1"}]
    assert asyncio.run(prepare.consent_plan({**CASE, "form_code": "Nd2b"}, entries)) == []



# -- e-Reg and corporate directors (Jacqueline A10, Brian) --------------------------

def test_hk_company_by_place():
    assert prepare.is_hong_kong_company({"incorporation_place": "HK"})
    assert prepare.is_hong_kong_company({"incorporation_place": "Hong Kong"})


def test_hk_company_by_cr_number_when_no_place():
    assert prepare.is_hong_kong_company({"cr_number": "1234567"})


def test_overseas_or_unknown_company_is_not():
    assert not prepare.is_hong_kong_company({"incorporation_place": "VG", "cr_number": "1"})
    assert not prepare.is_hong_kong_company({})


def _corp_world(monkeypatch, corp):
    fake = FakeSupabase({"persons": [{"id": "P2", "full_name": "HO Siu Fong"}],
                         "entities": [corp],
                         "person_eservice_credentials": [
                             {"person_id": "P2", "eservice_user_id": "HSF88213",
                              "eservice_person_name": "HO, SIU FONG",
                              "eservice_password_enc": "enc"}]})
    monkeypatch.setattr(prepare, "get_supabase", lambda: fake)
    monkeypatch.setattr(prepare.eservice, "get_supabase", lambda: fake)
    return [{"id": "N1", "kind": "appointment", "capacity": "director",
             "corporate_entity_id": corp["id"], "consent_person_id": "P2"}]


def test_consent_plan_refuses_an_overseas_corporate_director(monkeypatch):
    entries = _corp_world(monkeypatch, {"id": "C1", "company_name": "Island Holdings Ltd",
                                        "incorporation_place": "VG"})
    plan = asyncio.run(prepare.consent_plan(CASE, entries))
    assert plan[0]["ready"] is False
    assert "only for a Hong Kong company" in plan[0]["reason"]
    assert "Island Holdings Ltd" in plan[0]["reason"]
    assert "Virgin Islands" in plan[0]["reason"]


def test_consent_plan_says_when_the_country_is_unknown(monkeypatch):
    entries = _corp_world(monkeypatch, {"id": "C1", "company_name": "Mystery Ltd"})
    plan = asyncio.run(prepare.consent_plan(CASE, entries))
    assert plan[0]["ready"] is False and "no country of incorporation" in plan[0]["reason"]


def test_consent_plan_accepts_a_hk_corporate_director(monkeypatch):
    entries = _corp_world(monkeypatch, {"id": "C1", "company_name": "Evergreen Limited",
                                        "incorporation_place": "HK"})
    assert asyncio.run(prepare.consent_plan(CASE, entries))[0]["ready"] is True


def test_consent_plan_carries_the_eregistry_identity_mismatch(monkeypatch):
    fake = FakeSupabase({"persons": [{"id": "P1", "full_name": "LEE Ka Ho"}],
                         "person_identity_documents": [
                             {"person_id": "P1", "id_type": "passport",
                              "id_number": "Y7654321"}],
                         "person_eservice_credentials": [
                             {"person_id": "P1", "eservice_user_id": "LKH20455",
                              "eservice_person_name": "LEE, KA HO",
                              "eservice_password_enc": "enc",
                              "registered_id_type": "passport",
                              "registered_id_number": "X1234567"}]})
    monkeypatch.setattr(prepare, "get_supabase", lambda: fake)
    monkeypatch.setattr(prepare.eservice, "get_supabase", lambda: fake)
    entries = [{"id": "N1", "kind": "appointment", "capacity": "director", "person_id": "P1"}]
    row = asyncio.run(prepare.consent_plan(CASE, entries))[0]
    assert row["ready"] is True  # a warning, not a refusal: CR decides
    assert "X123" in row["id_mismatch"] and "Y765" in row["id_mismatch"]
    assert "X1234567" not in row["id_mismatch"]

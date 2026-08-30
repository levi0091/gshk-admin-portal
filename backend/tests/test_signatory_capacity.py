"""The operator chooses the signing capacity; the portal stops refusing.

BACKGROUND. GSHK is the company secretary of the companies it files for, and
GSHK is a body corporate. A body corporate does not sign — a natural person
signs on its behalf, and CR's `selectCapacityDesc` says which one, from a
controlled vocabulary of 15 values. Nothing in the company profile can answer
that; it depends on who at GSHK actually signs.

`nar1_mapper` therefore REFUSED to map any such company, and the Data
Verification screen rendered that refusal as "This company cannot be filed as a
NAR1 yet". Since every real GSHK client is in exactly that position, the
practical effect was that no real company could be prepared at all.

Levi 2026-08-30: the operator knows their own filing arrangement. Offer the
choice, do not block on it. These tests cover the choice being made, stored,
validated, and reaching the form.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services import nar1_return_data
from services.tpsi.forms import nar1_mapper
from services.tpsi.forms.cr_vocabularies import (
    CAPACITY_BODY_CORPORATE, CAPACITY_INDIVIDUAL,
)
from tests.tpsi.test_nar1_mapper import graph as _mapper_graph, person as _person

client = TestClient(app)

#: A real value from CR's Body Corporate sheet.
CORPORATE_CAPACITY = "Director of the Company Secretary (Body Corporate)"


# ---------------------------------------------------------------------------
# The mapper
# ---------------------------------------------------------------------------

def _graph_with_corporate_secretary():
    """The shape every real GSHK client has: a body-corporate secretary.

    Built from tests/tpsi/test_nar1_mapper.py's own fixture rather than a
    hand-rolled dict. A thin graph makes `map_entity` raise KeyError, which
    `summarise` catches and reports as "could not check this company" -- so
    these tests would pass against a crash rather than against the verdict.
    """
    return _mapper_graph()


def test_a_body_corporate_signatory_has_no_derived_capacity():
    """The premise. If this ever starts returning a capacity, the mapper has
    begun guessing a value CR accepts and the filing would misstate."""
    resolved = nar1_mapper._derive_signatory(_graph_with_corporate_secretary())
    assert resolved["is_corporate"] is True
    assert not resolved["capacity"]


def test_without_a_capacity_the_mapper_still_refuses():
    """Unchanged, and deliberately so: the refusal now has a remedy on screen,
    but an unanswered question must not become a silent guess."""
    problems = []
    nar1_mapper._signatory_block(
        _graph_with_corporate_secretary(), None, problems
    )
    assert any("Capacity (Body Corporate)" in p for p in problems)


def test_the_chosen_capacity_reaches_the_form_and_clears_the_refusal():
    problems = []
    block = nar1_mapper._signatory_block(
        _graph_with_corporate_secretary(), None, problems, CORPORATE_CAPACITY
    )
    assert block["selectCapacityDesc"] == CORPORATE_CAPACITY
    assert block["selectPersonName"] == "Get Started HK Limited"
    assert problems == []


def test_a_capacity_outside_CRs_vocabulary_is_still_a_problem():
    """CR's field is String(500): it takes any string at the schema gate and
    rejects it server-side, after the fee has been taken."""
    problems = []
    nar1_mapper._signatory_block(
        _graph_with_corporate_secretary(), None, problems, "Chief Signing Officer"
    )
    assert any("not in CR's" in p for p in problems)


def test_an_individual_value_is_refused_for_a_body_corporate():
    """The two vocabularies do not overlap. 'Company Secretary' is an
    Individual value, and it is the one someone would reach for first."""
    problems = []
    nar1_mapper._signatory_block(
        _graph_with_corporate_secretary(), None, problems, "Company Secretary"
    )
    assert any("Capacity (Body Corporate)" in p for p in problems)


def test_the_override_changes_the_capacity_and_nothing_else():
    """It is a separate argument from `signatory` precisely so it cannot
    disturb the resolved signer's identity."""
    graph = _graph_with_corporate_secretary()
    plain = nar1_mapper._signatory_block(graph, None, [])
    with_cap = nar1_mapper._signatory_block(graph, None, [], CORPORATE_CAPACITY)
    assert with_cap["selectPersonName"] == plain["selectPersonName"]
    assert with_cap["signatoryDate"] == plain["signatoryDate"]
    assert "selectPersonId" not in with_cap  # empty is correct for a corporate


def test_an_explicit_signatory_still_replaces_the_whole_signer():
    """The documented contract of `signatory` is that an ABSENT key means
    something — no `is_corporate` means a natural person, and a natural person
    with no `person_id` is a MappingError. A capacity override must not quietly
    turn that full replacement into a partial merge."""
    problems = []
    nar1_mapper._signatory_block(
        _graph_with_corporate_secretary(),
        {"name": "Wong Mei Ling", "capacity": "Director"},
        problems,
    )
    assert any("no e-Service" in p for p in problems)


# ---------------------------------------------------------------------------
# The card
# ---------------------------------------------------------------------------

def test_the_card_offers_the_body_corporate_vocabulary_for_a_corporate_signer():
    summary = nar1_return_data.summarise(
        _graph_with_corporate_secretary(), year=2026
    )
    assert summary["signatory"]["is_corporate"] is True
    assert set(summary["signatory_capacity_options"]) == set(CAPACITY_BODY_CORPORATE)
    assert summary["signatory_capacity"] is None


def test_choosing_a_capacity_clears_the_cards_verdict():
    """The card runs the mapper for its verdict. Without the stored choice fed
    in, every GSHK company reports the capacity problem forever — including the
    ones where the operator already answered it."""
    graph = _graph_with_corporate_secretary()
    assert any("Capacity (Body Corporate)" in p
               for p in nar1_return_data.summarise(graph, year=2026)["problems"])
    after = nar1_return_data.summarise(
        graph, year=2026, signatory_capacity=CORPORATE_CAPACITY
    )
    assert not any("Capacity (Body Corporate)" in p for p in after["problems"])
    assert after["signatory"]["capacity"] == CORPORATE_CAPACITY


def test_the_card_offers_the_individual_vocabulary_for_a_natural_person():
    graph = _mapper_graph(
        secretaries=[{"is_gshk": False, "person_id": "p1", "is_current": True}],
        persons={"p1": _person("p1")},
    )
    summary = nar1_return_data.summarise(graph, year=2026)
    assert summary["signatory"]["is_corporate"] is False
    assert set(summary["signatory_capacity_options"]) == set(CAPACITY_INDIVIDUAL)


# ---------------------------------------------------------------------------
# PATCH /cases/{id}
# ---------------------------------------------------------------------------

def _patch_case(payload, before=None, role="super_admin"):
    with patch("middleware.auth._resolve_user") as resolve, \
            patch("routers.cases.nar1_cases") as cases, \
            patch("routers.cases.log_event"):
        resolve.return_value = {"id": "u1", "display_name": "Levi Z.",
                                "role_name": role, "role_id": "r1"}
        cases.get_case.return_value = {"id": "c1", "entity_id": "e1",
                                       **(before or {})}
        cases.update_case.return_value = {"id": "c1"}
        response = client.patch("/cases/c1", json=payload,
                                headers={"Authorization": "Bearer tok"})
        return response, cases


def test_a_valid_capacity_is_stored_on_the_case():
    response, cases = _patch_case({"signatory_capacity": CORPORATE_CAPACITY})
    assert response.status_code == 200
    cases.update_case.assert_called_once()
    assert cases.update_case.call_args[0][1]["signatory_capacity"] == CORPORATE_CAPACITY


def test_a_capacity_outside_CRs_vocabulary_is_rejected_before_it_is_stored():
    response, cases = _patch_case({"signatory_capacity": "Chief Signing Officer"})
    assert response.status_code == 400
    assert "capacity vocabulary" in response.json()["detail"]
    cases.update_case.assert_not_called()


def test_an_individual_value_is_accepted_here_and_judged_by_the_mapper():
    """This endpoint does not know whether the signatory is a person or a
    company, and the mapper checks against the right list anyway. Rejecting a
    valid Individual value here would block a natural-person signer."""
    response, _ = _patch_case({"signatory_capacity": "Company Secretary"})
    assert response.status_code == 200


def test_an_empty_string_clears_the_choice():
    """The picker's blank option has to be expressible. None means 'not in this
    PATCH'; empty string means 'unset it'."""
    response, cases = _patch_case(
        {"signatory_capacity": ""}, before={"signatory_capacity": "Director"}
    )
    assert response.status_code == 200
    assert cases.update_case.call_args[0][1]["signatory_capacity"] is None


def test_an_unchanged_capacity_writes_nothing():
    response, cases = _patch_case(
        {"signatory_capacity": "Director"}, before={"signatory_capacity": "Director"}
    )
    assert response.status_code == 200
    cases.update_case.assert_not_called()


def test_the_choice_is_audited_as_a_case_field_change():
    with patch("middleware.auth._resolve_user") as resolve, \
            patch("routers.cases.nar1_cases") as cases, \
            patch("routers.cases.log_event") as log:
        resolve.return_value = {"id": "u1", "display_name": "Levi Z.",
                                "role_name": "super_admin", "role_id": "r1"}
        cases.get_case.return_value = {"id": "c1", "entity_id": "e1"}
        cases.update_case.return_value = {"id": "c1"}
        client.patch("/cases/c1", json={"signatory_capacity": CORPORATE_CAPACITY},
                     headers={"Authorization": "Bearer tok"})

    # PATCH /cases/{id} carries the field name in `metadata`, with the values
    # in old_value/new_value -- see the loop at the end of patch_case.
    fields = [c.kwargs.get("metadata", {}).get("field") for c in log.call_args_list]
    assert "signatory_capacity" in fields
    entry = next(c for c in log.call_args_list
                 if c.kwargs.get("metadata", {}).get("field") == "signatory_capacity")
    assert entry.kwargs["new_value"] == CORPORATE_CAPACITY


@pytest.mark.parametrize("role", ["viewer"])
def test_a_role_without_nar1_write_cannot_choose_the_capacity(role):
    with patch("middleware.auth._resolve_user") as resolve, \
            patch("middleware.auth.get_supabase") as sb:
        resolve.return_value = {"id": "u2", "display_name": "Read Only",
                                "role_name": role, "role_id": "r2"}
        supabase = MagicMock()
        sb.return_value = supabase
        supabase.table.return_value.select.return_value.eq.return_value \
            .eq.return_value.eq.return_value.execute.return_value.data = []
        response = client.patch("/cases/c1",
                                json={"signatory_capacity": CORPORATE_CAPACITY},
                                headers={"Authorization": "Bearer tok"})
    assert response.status_code == 403

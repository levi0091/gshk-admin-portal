"""`persons.hide_email_on_forms` on the NAR1 (PRD nd2-change-requests §1, test 1).

Levi 2026-10-29: a person who ticks the box has their email left off every form
we file or print. The NAR1's only emission of an individual's address is
`nar1_mapper._individual` (`indvEmailAddr`), used for individual secretaries,
directors and reserve directors; the rendered PDF reads this XML, so a missing
element is blank on the page too. CR marks the element Mandatory = N.

Built on the mapper's own fixtures (`tests/tpsi/test_nar1_mapper.py`) so the
graph is the real shape rather than a hand-rolled one that would make
`map_entity` raise KeyError.
"""
import pytest

from tests.tpsi.test_nar1_mapper import ADDR, graph, mapped, person

ROLES = [
    ("director", "indDirList"),
    ("reserve_director", "resDirList"),
    ("company_secretary", "indSecList"),
]


def _graph_with(role: str, **person_fields):
    return graph(
        officers=[{"person_id": "p1", "party_type": "individual",
                   "role": role, "is_current": True}],
        persons={"p1": person(**person_fields)},
        addresses={"a1": ADDR, "a2": ADDR},
    )


@pytest.mark.parametrize("role, key", ROLES)
def test_a_hidden_email_is_not_filed(role, key):
    data = mapped(_graph_with(role, hide_email_on_forms=True))
    assert "indvEmailAddr" not in data[key][0]


@pytest.mark.parametrize("role, key", ROLES)
def test_an_unhidden_email_is_filed_as_before(role, key):
    for flag in ({"hide_email_on_forms": False}, {}):
        data = mapped(_graph_with(role, **flag))
        assert data[key][0]["indvEmailAddr"] == "test@cr.gov.hk"


def test_the_flag_hides_only_that_persons_email():
    g = graph(
        officers=[{"person_id": "p1", "party_type": "individual",
                   "role": "director", "is_current": True},
                  {"person_id": "p2", "party_type": "individual",
                   "role": "director", "is_current": True}],
        persons={"p1": person("p1", hide_email_on_forms=True),
                 "p2": person("p2", email="other@example.com")},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    first, second = mapped(g)["indDirList"]
    assert "indvEmailAddr" not in first
    assert second["indvEmailAddr"] == "other@example.com"


def test_a_secretary_on_the_register_is_covered_too():
    """The register is walked before entity_officers and has its own call site."""
    g = graph(
        secretaries=[{"person_id": "p1", "secretary_name": "CHAN TAI MAN",
                      "is_current": True, "tcsp_number": "TC000001"}],
        persons={"p1": person(hide_email_on_forms=True)},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    data = mapped(g)
    assert data["indSecList"] and "indvEmailAddr" not in data["indSecList"][0]

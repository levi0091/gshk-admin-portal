"""services/nar1_return_data.py — the Data Verification card's payload.

Mocked at the graph, not at the mapper: `summarise` exists to say what CR is
about to be shown, so a test that stubbed `map_entity` would assert only that
one function calls another.
"""
from unittest.mock import MagicMock, patch

from services import nar1_return_data
from services.tpsi.forms import nar1_mapper


def _graph(**over) -> dict:
    graph = {
        "entity": {
            "id": "e1", "company_name": "Harbour Tech Ltd.",
            "company_name_zh": "海港科技有限公司", "br_number": "2100028",
            "cr_number": "3456789", "incorporation_date": "2022-01-01",
        },
        "registered_address": {
            "line1": "Unit 12A", "district": "Central", "country": "HKG",
        },
        "officers": [
            {"role": "director", "person_id": "p1", "is_current": True},
            {"role": "company_secretary", "person_id": "p2", "is_current": True},
            {"role": "director", "corporate_entity_id": "e9",
             "corporate_name": "Nominee Holdings Ltd.", "is_current": True},
        ],
        "secretaries": [{"person_id": "p2", "is_current": True}],
        "share_classes": [{"class_name": "Ordinary", "total_issued": 100,
                           "currency": "HKD"}],
        "shareholdings": [{"id": "h1", "holder_person_id": "p1"},
                          {"id": "h2", "holder_person_id": "p2"}],
        "persons": {
            "p1": {"id": "p1", "full_name": "Chan Tai Man",
                   "eservice_user_id": "T2607D"},
            "p2": {"id": "p2", "full_name": "Wong Mei Ling",
                   "eservice_user_id": "T2607S"},
        },
        "addresses": {},
        "identity_documents": {},
    }
    graph.update(over)
    return graph


def test_reports_the_rows_the_card_renders():
    out = nar1_return_data.summarise(_graph(), year=2026)

    assert out["company_name"] == "Harbour Tech Ltd."
    assert out["br_number"] == "2100028"
    assert out["year"] == 2026
    assert out["registered_office"] == "Unit 12A, Central, HKG"
    assert out["share_classes"] == [
        {"name": "Ordinary", "total_issued": 100, "currency": "HKD"}
    ]


def test_names_corporate_officers_as_well_as_people():
    # An officer row is a person OR a body corporate. Reading only person_id
    # would silently drop a corporate director from a card whose whole job is
    # to show who is on the return.
    out = nar1_return_data.summarise(_graph(), year=2026)
    assert out["directors"] == ["Chan Tai Man", "Nominee Holdings Ltd."]
    assert out["secretaries"] == ["Wong Mei Ling"]


def test_counts_distinct_members_not_holdings():
    graph = _graph(shareholdings=[
        {"id": "h1", "holder_person_id": "p1"},
        {"id": "h2", "holder_person_id": "p1"},   # same member, second class
        {"id": "h3", "holder_person_id": "p2"},
    ])
    assert nar1_return_data.summarise(graph, year=2026)["member_count"] == 2


def test_reports_the_signatory_the_mapper_would_derive():
    out = nar1_return_data.summarise(_graph(), year=2026)
    assert out["signatory"]["name"] == "Wong Mei Ling"
    # The e-Service User ID, never an identity document number — CR verifies
    # this account is real and authorised for the company.
    assert out["signatory"]["person_id"] == "T2607S"


def test_surfaces_mapper_problems_without_raising():
    # The card must stay READABLE for a company that cannot be filed — that is
    # the case it is most needed in. map_entity raises; summarise must not.
    graph = _graph(entity={"id": "e1", "company_name": "Broken Ltd."})
    out = nar1_return_data.summarise(graph, year=2026)

    assert out["company_name"] == "Broken Ltd."
    assert out["problems"], "a company with no BR number must report a problem"
    assert all(isinstance(p, str) for p in out["problems"])


def test_a_clean_company_reports_no_problems():
    with patch.object(nar1_mapper, "map_entity", return_value={}):
        assert nar1_return_data.summarise(_graph(), year=2026)["problems"] == []


def test_a_mapper_crash_is_reported_not_disguised_as_company_data():
    with patch.object(nar1_mapper, "map_entity", side_effect=RuntimeError("boom")):
        out = nar1_return_data.summarise(_graph(), year=2026)
    assert out["problems"] == ["could not check this company: boom"]
    # and the card still has its data
    assert out["company_name"] == "Harbour Tech Ltd."


def test_missing_registered_address_reads_as_absent_not_empty_string():
    out = nar1_return_data.summarise(_graph(registered_address=None), year=2026)
    assert out["registered_office"] is None


def test_year_defaults_to_hong_kongs_year_not_utcs():
    # 31 December 16:05 UTC is already 1 January in Hong Kong, and the year on
    # a statutory form is not a rounding question.
    import datetime as _dt

    class _FixedDatetime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return _dt.datetime(2026, 12, 31, 16, 5, tzinfo=_dt.timezone.utc)

    with patch.object(nar1_return_data, "datetime", _FixedDatetime):
        assert nar1_return_data._hk_year() == 2027


# ---- the endpoint's permission -------------------------------------------

def test_summarise_never_touches_the_database():
    """It decorates a graph the caller already loaded. A query in here would
    make the card a second, divergent definition of the return."""
    with patch("services.nar1_return_data.nar1_mapper.map_entity", return_value={}):
        with patch("db.supabase.get_supabase", MagicMock(side_effect=AssertionError(
                "summarise must not query"))):
            nar1_return_data.summarise(_graph(), year=2026)

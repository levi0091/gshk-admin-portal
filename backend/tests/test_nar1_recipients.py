"""services/nar1_cases.default_recipients — who a verification email goes to.

Mocked at the get_supabase() boundary, not by mocking the function under test:
the whole behaviour here IS which tables are read and how their rows are
combined, so a double that stands in for the function would assert nothing.

The failure this module exists to prevent is a SILENT one — a three-director
board mailed to whichever director sorted first, with nothing on screen saying
the other two were never asked. So the tests below care as much about the
directors that come back WITHOUT an address as the ones that come back with one.
"""
from unittest.mock import MagicMock, patch

from services import nar1_cases


def _sb(officers=(), persons=(), contacts=()):
    """A Supabase double that answers per table, and per SELECT within a table.

    `persons` is read twice with different column lists — once for names, once
    for addresses — so dispatching on the table name alone would hand the name
    query the email rows.
    """
    # Memoised: a fresh mock per call would throw away the very call arguments
    # the "only directors / only current" tests read back.
    made = {}

    def table(name):
        if name in made:
            return made[name]
        t = made.setdefault(name, MagicMock())
        if name == "entity_officers":
            (t.select.return_value.eq.return_value.eq.return_value
             .in_.return_value.execute.return_value.data) = list(officers)
        elif name == "persons":
            def select(cols):
                s = MagicMock()
                rows = [{"id": p["id"], "full_name": p.get("full_name")}
                        if "full_name" in cols
                        else {"id": p["id"], "email": p.get("email")}
                        for p in persons]
                s.in_.return_value.execute.return_value.data = rows
                return s
            t.select.side_effect = select
        elif name == "contacts":
            (t.select.return_value.in_.return_value
             .execute.return_value.data) = list(contacts)
        else:
            raise AssertionError(f"unexpected table {name!r}")
        return t

    sb = MagicMock()
    sb.table.side_effect = table
    return sb


def _officer(person_id=None, role="director", party_type="individual",
             corporate_name=None):
    return {"person_id": person_id, "role": role, "party_type": party_type,
            "corporate_name": corporate_name, "appointed_date": "2020-01-01",
            "created_at": "2020-01-01T00:00:00Z"}


BOARD = [
    _officer("p1"), _officer("p2"), _officer("p3"),
]
PEOPLE = [
    {"id": "p1", "full_name": "AH CHAN", "email": "chan@example.com"},
    {"id": "p2", "full_name": "BO LEE", "email": "lee@example.com"},
    {"id": "p3", "full_name": "CHRIS WONG", "email": "wong@example.com"},
]


def _run(sb):
    with patch("services.nar1_cases.get_supabase", return_value=sb):
        return nar1_cases.default_recipients("e1")


def test_every_director_on_the_board_comes_back():
    """The headline behaviour: three directors, three recipients."""
    got = _run(_sb(officers=BOARD, persons=PEOPLE))
    assert [r["email"] for r in got] == [
        "chan@example.com", "lee@example.com", "wong@example.com"]


def test_a_director_with_no_address_is_returned_with_the_reason():
    """NOT dropped. A three-director board rendering two chips looks exactly
    like a two-director board, and nothing on screen would say otherwise."""
    people = [PEOPLE[0], PEOPLE[1], {"id": "p3", "full_name": "CHRIS WONG"}]
    got = _run(_sb(officers=BOARD, persons=people))
    assert len(got) == 3
    silent = [r for r in got if r["email"] is None]
    assert [r["name"] for r in silent] == ["CHRIS WONG"]
    assert "no email" in silent[0]["reason"]


def test_a_corporate_director_is_listed_but_never_given_an_address():
    """A body corporate has no mailbox in this schema. Inventing one from its
    own officer list would mail a client's statutory return to a third
    company's staff."""
    officers = [_officer("p1"),
                _officer(None, party_type="corporate",
                         corporate_name="HOLDCO LIMITED")]
    got = _run(_sb(officers=officers, persons=[PEOPLE[0]]))
    holdco = [r for r in got if r["name"] == "HOLDCO LIMITED"][0]
    assert holdco["email"] is None
    assert holdco["party_type"] == "corporate"
    assert "corporate" in holdco["reason"]


def test_only_directors_are_asked():
    """The secretary prepares the return and a reserve director has no
    appointment to confirm. Either can still be added by hand on the send
    screen — that is what "add a recipient" is for."""
    sb = _sb(officers=BOARD, persons=PEOPLE)
    _run(sb)
    officers_table = sb.table("entity_officers")
    roles = officers_table.select.return_value.eq.return_value.eq.return_value \
        .in_.call_args.args
    assert roles[0] == "role"
    assert list(roles[1]) == ["director"]


def test_only_current_officers_are_asked():
    """A resigned director must not be sent this year's return."""
    sb = _sb(officers=BOARD, persons=PEOPLE)
    _run(sb)
    second_eq = sb.table("entity_officers").select.return_value.eq.return_value.eq
    assert second_eq.call_args.args == ("is_current", True)


def test_a_contact_row_beats_the_etld_persons_column():
    """`contacts` is where the portal writes a CORRECTED address. If the ETL'd
    column won, fixing a bounced address in the UI would change nothing about
    where the mail goes."""
    contacts = [{"person_id": "p1", "contact_type": "EB",
                 "contact_value": "corrected@example.com",
                 "is_preferred": True, "created_at": "2026-01-01T00:00:00Z"}]
    got = _run(_sb(officers=[_officer("p1")], persons=[PEOPLE[0]],
                   contacts=contacts))
    assert got[0]["email"] == "corrected@example.com"


def test_a_non_address_in_the_contacts_column_is_not_treated_as_one():
    """`contacts` is Viewpoint-shaped: (contact_type, contact_value), where the
    value may be a phone number and the type may be NULL."""
    contacts = [{"person_id": "p1", "contact_type": None,
                 "contact_value": "+852 9123 4567",
                 "is_preferred": True, "created_at": "2026-01-01T00:00:00Z"}]
    got = _run(_sb(officers=[_officer("p1")], persons=[PEOPLE[0]],
                   contacts=contacts))
    assert got[0]["email"] == "chan@example.com"


def test_a_company_with_no_directors_returns_nothing_rather_than_guessing():
    """None is a legitimate answer and the caller treats it as one — it is what
    makes the router fall back to the company contact instead of mailing
    whoever happened to be first in the table."""
    assert _run(_sb(officers=[])) == []


def test_no_person_query_is_made_for_an_all_corporate_board():
    """`in_("id", [])` is a query that can only return nothing — a round trip
    spent learning something already known."""
    officers = [_officer(None, party_type="corporate", corporate_name="A LTD")]
    sb = _sb(officers=officers)
    got = _run(sb)
    assert [r["name"] for r in got] == ["A LTD"]
    assert [c.args[0] for c in sb.table.call_args_list] == ["entity_officers"]


def test_the_order_is_stable_across_calls():
    """These render as removable chips. An unstable order moves the chip under
    the operator's cursor between one load and the next."""
    forwards = _run(_sb(officers=BOARD, persons=PEOPLE))
    backwards = _run(_sb(officers=list(reversed(BOARD)),
                         persons=list(reversed(PEOPLE))))
    assert [r["name"] for r in forwards] == [r["name"] for r in backwards]

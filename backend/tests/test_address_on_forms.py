"""`persons.address_on_forms` (migration 067, Levi 2026-11-28).

"there should be an option in Natural Person profile for user to select whether
to use correspondence address or residential address. By default this flag
should be set to correspondence address. if user choose to change it to
residential address then only the NAR1, ND2A and ND2B will include the
residential address. Also if the profile has correspondence address selected
but there is actually no correspondence address then the NAR1, ND2B, ND2A will
use residential address instead".

And NAR1's Schedule 1 (the public register of members) prints the same address
the officer boxes do, rather than always the residential one.
"""
from services import appointment_links as links
from services.officer_changes import particulars
from tests.tpsi.test_nar1_mapper import ADDR, graph, mapped, person

CORR = {**ADDR, "line1": "Suite C, Level 7", "line2": "Corr Plaza 77",
        "line3": "50 Stanley Street"}
HOME = {**ADDR, "line1": "Flat B", "line2": "Res Tower"}


def _collect(node, key, out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                out.append(v)
            _collect(v, key, out)
    elif isinstance(node, list):
        for v in node:
            _collect(v, key, out)
    return out


def _bldg(blocks):
    return [b.get("bldg") for b in blocks]


def _nar1(*, flag=None, director=True, link: str | None = "c1"):
    p = person(**({"address_on_forms": flag} if flag else {}))
    officers = []
    if director:
        officers.append({"person_id": "p1", "party_type": "individual", "role": "director",
                         "is_current": True,
                         **({"correspondence_address_id": link} if link else {})})
    else:
        # The return still needs a director; p2 is one with no links.
        officers.append({"person_id": "p2", "party_type": "individual", "role": "director",
                         "is_current": True})
    g = graph(officers=officers,
              persons={"p1": p, "p2": person("p2", residential_address_id="a9")},
              addresses={"a2": HOME, "a9": {**ADDR, "line2": "Other Tower"}, "c1": CORR},
              share_classes=[{"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
                              "total_issued": 1000, "total_paid": 1000}],
              shareholdings=[{"share_class_id": "sc1", "person_id": "p1",
                              "party_type": "individual", "shares_held": 1000,
                              "is_current": True}])
    links.apply_to_graph(g["persons"], g["identity_documents"], g["officers"])
    data = mapped(g)
    return (_bldg(_collect(data.get("schedule1"), "allotteeAddr")),
            _bldg(_collect({k: v for k, v in data.items() if k != "schedule1"}, "stdAddress")))


# -- the rule ------------------------------------------------------------------------

def test_correspondence_is_the_default_and_anything_unknown_reads_as_it():
    assert not links.files_residential({})
    assert not links.files_residential({"address_on_forms": "correspondence"})
    assert not links.files_residential({"address_on_forms": "something else"})
    assert links.files_residential({"address_on_forms": "residential"})


def test_filed_address_follows_the_flag_and_falls_back_to_residential():
    addresses = {"A": HOME, "C": CORR}
    linked = {"residential_address_id": "A", links.CORRESPONDENCE: "C"}
    assert links.filed_address(linked, addresses) is CORR
    assert links.filed_address({**linked, "address_on_forms": "residential"}, addresses) is HOME
    assert links.filed_address({"residential_address_id": "A"}, addresses) is HOME
    assert links.filed_address({**linked, links.CORRESPONDENCE: "GONE"}, addresses) is HOME


# -- NAR1 ----------------------------------------------------------------------------

def test_schedule_1_defaults_to_the_correspondence_address():
    schedule, officers = _nar1()
    assert schedule == ["Corr Plaza 77"]
    assert "Corr Plaza 77" in officers and "Res Tower" not in officers


def test_residential_on_forms_files_the_residential_address_in_both():
    schedule, officers = _nar1(flag="residential")
    assert schedule == ["Res Tower"]
    assert "Res Tower" in officers and "Corr Plaza 77" not in officers


def test_with_no_correspondence_address_schedule_1_files_the_residential_one():
    schedule, _ = _nar1(link=None)
    assert schedule == ["Res Tower"]


def test_a_shareholder_who_holds_no_appointment_files_the_residential_address():
    schedule, officers = _nar1(director=False)
    assert schedule == ["Res Tower"]
    assert "Other Tower" in officers and "Res Tower" not in officers


# -- ND2A ----------------------------------------------------------------------------

def _nd2a_printed(monkeypatch, *, flag=None, choices=(), entry_extra=None, secretary=False):
    """What `indvCorrAddr` is built from, and the problems the mapper raised."""
    from services.officer_changes import nd2a_mapper

    seen, problems = {}, []

    def fake(addr, problems_, where, **kw):
        if "correspondence" in where:
            seen["corr"] = addr
            seen["hkg_only"] = kw.get("hkg_only")
        return {}

    monkeypatch.setattr(nd2a_mapper, "cr_address", fake)
    monkeypatch.setattr(nd2a_mapper, "full_ids", lambda *a, **k: {})
    entry = {"kind": "appointment", "person_id": "p1", "effective_date": "2026-11-01",
             **(entry_extra or {}),
             "capacity": "company_secretary" if secretary else "director"}
    p = {"id": "p1", "surname": "CHAN", "given_names": "TAI MAN",
         "residential_address_id": "a2", **({"address_on_forms": flag} if flag else {})}
    g = {"persons": {"p1": p}, "addresses": {"a2": HOME}, "identity_documents": {},
         "profile_correspondence": {"p1": list(choices)}}
    try:
        nd2a_mapper._natural_appointment(g, entry, "S1", problems, False)
    except (KeyError, TypeError):
        pass  # later blocks may want more of the graph; the address is set first
    return seen, problems


def _choice(address_id, address, used_by=("E1",)):
    from services.officer_changes import profile_correspondence as pc
    return {"address_id": address_id, "address": pc.normalised(address),
            "address_ids": [address_id], "used_by": list(used_by)}


def test_nd2a_files_the_profiles_correspondence_address_by_default(monkeypatch):
    from services.officer_changes import profile_correspondence as pc
    for flag in (None, "correspondence"):
        seen, problems = _nd2a_printed(monkeypatch, flag=flag,
                                       choices=[_choice("c1", CORR)])
        assert seen["corr"] == pc.normalised(CORR), flag
        assert not problems


def test_nd2a_files_the_residential_address_when_the_profile_says_so(monkeypatch):
    seen, _ = _nd2a_printed(monkeypatch, flag="residential",
                            choices=[_choice("c1", CORR)])
    assert seen["corr"] == HOME or seen["corr"]["line1"] == HOME["line1"]


def test_nd2a_files_the_residential_address_when_the_profile_has_no_correspondence(monkeypatch):
    seen, problems = _nd2a_printed(monkeypatch, choices=[])
    assert seen["corr"]["line1"] == HOME["line1"] and not problems


def test_nd2a_is_a_problem_when_the_profile_holds_several_and_none_is_chosen(monkeypatch):
    other = {**CORR, "line1": "Elsewhere"}
    seen, problems = _nd2a_printed(
        monkeypatch, choices=[_choice("c1", CORR), _choice("c2", other, ("E2",))])
    assert seen["corr"] is None
    assert any("the profile holds several correspondence addresses" in m for m in problems)


def test_nd2a_the_entry_chooses_among_several(monkeypatch):
    other = {**CORR, "line1": "Elsewhere"}
    seen, problems = _nd2a_printed(
        monkeypatch, choices=[_choice("c1", CORR), _choice("c2", other, ("E2",))],
        entry_extra={"correspondence_address_id": "c2"})
    assert seen["corr"]["line1"] == "Elsewhere" and not problems


def test_nd2a_ambiguity_is_no_problem_for_a_residential_person(monkeypatch):
    other = {**CORR, "line1": "Elsewhere"}
    seen, problems = _nd2a_printed(
        monkeypatch, flag="residential",
        choices=[_choice("c1", CORR), _choice("c2", other, ("E2",))])
    assert seen["corr"]["line1"] == HOME["line1"] and not problems


def test_nd2a_ignores_the_old_typed_address_fields(monkeypatch):
    typed = {**CORR, "line1": "Typed by hand"}
    seen, _ = _nd2a_printed(
        monkeypatch, choices=[_choice("c1", CORR)],
        entry_extra={"correspondence_same_as_residential": False,
                     "correspondence_address": typed})
    assert seen["corr"]["line1"] == CORR["line1"]


def test_nd2a_a_secretary_keeps_the_hong_kong_only_rule(monkeypatch):
    seen, _ = _nd2a_printed(monkeypatch, secretary=True, choices=[_choice("c1", CORR)])
    assert seen["hkg_only"] is True


# -- ND2B ----------------------------------------------------------------------------

def test_switching_to_residential_reports_a_correspondence_change():
    base = {"party_type": "individual", "residential_address": HOME,
            "correspondence_address": CORR}
    current = particulars._current_for(
        {"party_type": "individual", "residential_address": HOME,
         "residential_on_forms": True},
        "e1", {"e1": {"correspondence": CORR}})
    assert current["correspondence_address"] is None
    items = particulars.diff(base, current, capacity="director")
    assert [i["key"] for i in items] == ["correspondence_address"]


def test_correspondence_on_forms_keeps_the_linked_address():
    current = particulars._current_for(
        {"party_type": "individual", "residential_address": HOME,
         "residential_on_forms": False},
        "e1", {"e1": {"correspondence": CORR}})
    assert current["correspondence_address"] is CORR


def test_the_flag_is_a_tracked_particular():
    assert "address_on_forms" in particulars.TRACKED_PERSON_FIELDS

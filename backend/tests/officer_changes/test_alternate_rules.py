"""Alternate directors and the company rules (PBI-70 revived, 2026-11-04).

An alternate is on the board, and listed, but is never a director for a minimum:
a private company whose only natural-person director ceases is still short of
one, however many alternates it has.
"""
from services.officer_changes import rules
from tests.officer_changes.test_rules import (
    BOARD, appoint, cease, check, officer, run,
)


def alternate(oid, person, to, to_name):
    return {**officer(oid, "alternate_director", person=person),
            "alternate_to_officer_id": to, "alternate_to_name": to_name}


WITH_ALTERNATE = [*BOARD, alternate("OA", "PA", "O1", "Director One")]


def cease_party(entry, name):
    return {**entry, "party": {"name": name}}


def test_an_alternate_is_not_counted_as_a_director():
    result = run([], officers=WITH_ALTERNATE)
    assert result["summary"].startswith("After these changes the company will have "
                                        "2 directors (2 natural persons) and 1 secretary")
    assert [d["name"] for d in result["board"]["directors"]] == ["O1", "O2"]
    assert [a["name"] for a in result["board"]["alternates"]] == ["OA"]


def test_a_company_whose_only_director_leaves_is_not_saved_by_its_alternate():
    officers = [officer("O1", "director", person="P1"),
                alternate("OA", "PA", "O1", "O1"), BOARD[2]]
    result = run([cease("O1", person="P1"), cease("OA", person="PA",
                                                  capacity="alternate_director")],
                 officers=officers)
    assert check(result, "natural_director")["ok"] is False
    assert result["blocking"] is True


def test_a_new_alternate_does_not_satisfy_the_natural_person_director_rule():
    officers = [officer("O1", "director", person="P1"), BOARD[2]]
    entry = appoint(person="P9", capacity="alternate_director", name="Alt Nine")
    entry["alternate_to_officer_id"] = "O1"
    result = run([cease("O1", person="P1"), entry], officers=officers)
    assert check(result, "natural_director")["ok"] is False


def test_the_summary_lists_alternates_separately_when_any_remain():
    result = run([], officers=WITH_ALTERNATE)
    assert "Alternate directors: OA (alternate to Director One)." in result["lines"]
    # And not at all when there are none.
    assert not any(line.startswith("Alternate directors") for line in run([])["lines"])


def test_a_new_alternate_is_listed_with_the_director_it_acts_for():
    entry = appoint(person="P9", capacity="alternate_director", name="Alt Nine")
    entry["alternate_to_officer_id"] = "O2"
    entry["alternate_to_name"] = "Director Two"
    result = run([entry])
    assert "Alternate directors: Alt Nine (alternate to Director Two)." in result["lines"]


def test_ceasing_a_director_while_their_alternate_stays_is_a_rule_failure():
    result = run([cease_party(cease("O1", person="P1"), "Director One")],
                 officers=WITH_ALTERNATE)
    orphan = check(result, "alternate_orphaned")
    assert orphan["ok"] is False and orphan["level"] == "rule"
    assert orphan["text"] == ("OA is alternate to Director One, who ceases on this form; "
                              "cease the alternate too.")
    assert result["blocking"] is True


def test_ceasing_the_alternate_too_clears_the_orphan_rule():
    result = run([cease_party(cease("O1", person="P1"), "Director One"),
                  cease("OA", person="PA", capacity="alternate_director")],
                 officers=WITH_ALTERNATE)
    # Nobody is left to orphan, so the check is not shown at all.
    assert not any(c["code"] == "alternate_orphaned" for c in result["checks"])
    assert result["blocking"] is False


def test_ceasing_only_the_alternate_is_fine():
    result = run([cease("OA", person="PA", capacity="alternate_director")],
                 officers=WITH_ALTERNATE)
    assert not any(c["code"] == "alternate_orphaned" for c in result["checks"])
    assert result["blocking"] is False


def test_a_new_alternate_to_a_director_who_ceases_is_orphaned_too():
    entry = appoint(person="P9", capacity="alternate_director", name="Alt Nine")
    entry["alternate_to_officer_id"] = "O1"
    result = run([cease_party(cease("O1", person="P1"), "Director One"), entry])
    assert check(result, "alternate_orphaned")["ok"] is False


def test_there_is_no_orphan_check_on_a_company_without_alternates():
    result = run([cease("O1", person="P1")])
    assert not any(c["code"] == "alternate_orphaned" for c in result["checks"])


def test_an_underage_alternate_is_refused_like_an_underage_director():
    entry = appoint(person="P9", capacity="alternate_director", name="Alt Nine",
                    date_of_birth="2015-01-01")
    entry["alternate_to_officer_id"] = "O1"
    result = run([entry])
    age = check(result, "director_age")
    assert age["ok"] is False and "Alt Nine" in age["text"]


def test_board_after_keeps_the_alternate_link():
    board = rules.board_after(WITH_ALTERNATE, [])
    alt = next(b for b in board if b["role"] == "alternate_director")
    assert alt["alternate_to_officer_id"] == "O1"

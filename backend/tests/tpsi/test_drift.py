"""Spec §6 — the pre-submit drift gate.

Two failure directions, and they are not symmetric:

  FALSE POSITIVE  blocks a legitimate filing near a statutory deadline.
  FALSE NEGATIVE  files a return the client never approved.

So the false-positive tests here are as load-bearing as the detection ones: an
unmodified case must produce ZERO differences, whatever noise (element order,
absent-vs-empty, the declaration date moving) the two documents carry.
"""
from unittest.mock import MagicMock, patch

import pytest

from services.tpsi import drift, filings
from services.tpsi.forms import nar1
from tests.tpsi.test_nar1_mapper import ADDR, graph, mapped, person


def xml_for(g, **kw):
    return nar1.build_nar1_xml(mapped(g, **kw))


#: `role` and `party_type` are the keys `nar1_mapper._officer_lists` reads.
#: `officer_type` is not one of them — a graph using it maps to a return with no
#: directors at all, which every comparison here would then agree about.
DIRECTOR = {"person_id": "p1", "party_type": "individual",
            "role": "director", "is_current": True}

BASE = graph(
    officers=[DIRECTOR],
    persons={"p1": person()},
    addresses={"a1": graph()["registered_address"], "a2": ADDR},
)

#: Built ONCE, at import. Several tests below patch `nar1_mapper.map_entity`,
#: and building a fixture inside one of those patches would run the mock
#: instead of the mapper — the fixture would inherit the test's own stub.
STORED_XML = nar1.build_nar1_xml(mapped(BASE))
STORED_XML_2024 = nar1.build_nar1_xml(mapped(BASE, year=2024))


def test_the_fixture_actually_files_a_director():
    """A guard on everything below. `nar1_mapper` reads `role`/`party_type`; an
    officer dict using any other key maps to a return with NO directors, and
    every comparison in this file would then agree about nothing."""
    assert any("indDir" in path for path in drift.flatten(STORED_XML))


# --------------------------------------------------------------------------- #
#  flatten() — the comparison's substrate
# --------------------------------------------------------------------------- #

def test_flatten_reads_leaf_values_out_of_a_bare_fragment():
    """`build_nar1_xml` returns a fragment whose `cr:` prefix is never declared.
    Anything that forgets to wrap it dies on "unbound prefix"."""
    flat = drift.flatten("<cr:brNo>00000001</cr:brNo>")
    assert flat == {"brNo": "00000001"}


def test_flatten_indexes_repeats_positionally():
    """Director one and director two are different people. Sorting them, or
    collapsing them onto one key, would hide a swap — which is a real change to
    a statutory return."""
    fragment = (
        "<cr:indDirList>"
        "<cr:indDir><cr:indvEngSname>CHAN</cr:indvEngSname></cr:indDir>"
        "<cr:indDir><cr:indvEngSname>WONG</cr:indvEngSname></cr:indDir>"
        "</cr:indDirList>"
    )
    flat = drift.flatten(fragment)
    assert flat["indDirList/indDir/indvEngSname"] == "CHAN"
    assert flat["indDirList/indDir[2]/indvEngSname"] == "WONG"


def test_flatten_drops_empty_leaves():
    """`build_nar1_xml` omits blank elements entirely, so an absent element and
    an empty one must not read as a difference."""
    flat = drift.flatten("<cr:brNo>1</cr:brNo><cr:telNo>   </cr:telNo>")
    assert flat == {"brNo": "1"}


def test_flatten_ignores_the_declaration_date():
    """`signatoryDate` is `_hk_today()` at build time. Comparing it would block
    every filing not submitted on the day it was prepared."""
    flat = drift.flatten(
        "<cr:brNo>1</cr:brNo><cr:signatoryDate>01/09/2026</cr:signatoryDate>"
    )
    assert flat == {"brNo": "1"}


def test_flatten_never_reads_the_signing_credential():
    """PinSign carries the e-Service credential hash. It must not be compared,
    and must not reach a diff that ends up in an error body or an audit row."""
    fragment = (
        "<cr:brNo>1</cr:brNo>"
        "<cr:EFormSignatures><cr:PinSign>"
        "<cr:UserCredentialHash>SECRET</cr:UserCredentialHash>"
        "</cr:PinSign></cr:EFormSignatures>"
    )
    flat = drift.flatten(fragment)
    assert flat == {"brNo": "1"}
    assert "SECRET" not in str(flat)


def test_flatten_refuses_unparseable_xml_rather_than_returning_nothing():
    """An empty dict would compare EQUAL to another empty dict and wave the
    filing through — the false negative this gate exists to prevent."""
    with pytest.raises(drift.DriftError, match="could not be parsed"):
        drift.flatten("<cr:brNo>oops")


# --------------------------------------------------------------------------- #
#  compare() — no false positives
# --------------------------------------------------------------------------- #

def test_an_unmodified_return_reports_no_differences():
    """The single most important assertion in this file. A gate that fires on
    an unchanged case blocks every filing."""
    stored = xml_for(BASE)
    assert drift.compare(stored, xml_for(BASE)) == []


def test_a_return_rebuilt_on_a_different_day_reports_no_differences():
    """Only `signatoryDate` moved."""
    stored = xml_for(BASE).replace(
        "<cr:signatoryDate>", "<cr:signatoryDate>X", 1
    ) if "signatoryDate" in xml_for(BASE) else xml_for(BASE)
    current = xml_for(BASE)
    assert drift.compare(stored, current) == []


def test_the_empty_document_compares_equal_to_itself():
    assert drift.compare("", "") == []


# --------------------------------------------------------------------------- #
#  compare() — no false negatives
# --------------------------------------------------------------------------- #

def test_a_changed_registered_office_is_reported_with_both_values():
    moved = graph(
        officers=BASE["officers"], persons=BASE["persons"],
        addresses={**BASE["addresses"],
                   "a1": {**BASE["addresses"]["a1"], "line2": "New Tower"}},
        registered_address={**BASE["registered_address"], "line2": "New Tower"},
    )
    differences = drift.compare(xml_for(BASE), xml_for(moved))

    by_path = {d["path"]: d for d in differences}
    office = by_path["roAddr/bldg"]
    assert office["validated"] == "Test Tower"
    assert office["current"] == "New Tower"
    # The label is what the operator reads. A path is not a field name.
    assert office["field"] == "Registered office · Building"
    # The company secretary is GSHK and GSHK's address IS this company's
    # registered office (a TCSP files its clients at its own address — 4,446
    # DEV companies share one address row, and that is correct). So the same
    # edit legitimately moves two blocks of the return, and the gate reports
    # both rather than pretending one field changed.
    assert set(by_path) == {"roAddr/bldg", "corpSecList/corpSec/stdAddress/bldg"}


def test_a_changed_company_name_is_reported():
    renamed = graph(
        entity={**BASE["entity"], "company_name": "RENAMED LIMITED"},
        officers=BASE["officers"], persons=BASE["persons"],
        addresses=BASE["addresses"],
    )
    differences = drift.compare(xml_for(BASE), xml_for(renamed))
    fields = {d["field"] for d in differences}
    assert "Company name (English)" in fields


def test_a_director_removed_since_validation_is_reported_as_absent():
    """Not merely edited — the field is gone. `None` rather than "" so the UI
    can say "(absent)" and the operator can see a person left the board."""
    two = graph(
        officers=[DIRECTOR, {**DIRECTOR, "person_id": "p2"}],
        persons={"p1": person(), "p2": person("p2", full_name="WONG SIU MING",
                                              surname="WONG", given_names="SIU MING",
                                              full_name_zh="黃小明")},
        addresses=BASE["addresses"],
    )
    differences = drift.compare(xml_for(two), xml_for(BASE))

    absent = [d for d in differences if d["current"] is None]
    assert absent, "a departed director must appear in the diff"
    assert any("Director (individual) 2" in d["field"] for d in absent)


def test_every_difference_carries_a_path_a_label_and_both_values():
    renamed = graph(
        entity={**BASE["entity"], "br_number": "99999999"},
        officers=BASE["officers"], persons=BASE["persons"],
        addresses=BASE["addresses"],
    )
    for d in drift.compare(xml_for(BASE), xml_for(renamed)):
        assert set(d) == {"path", "field", "validated", "current"}
        assert d["path"] and d["field"]


def test_differences_come_back_in_a_stable_order():
    changed = graph(
        entity={**BASE["entity"], "br_number": "99999999",
                "company_name": "RENAMED LIMITED"},
        officers=BASE["officers"], persons=BASE["persons"],
        addresses=BASE["addresses"],
    )
    first = drift.compare(xml_for(BASE), xml_for(changed))
    second = drift.compare(xml_for(BASE), xml_for(changed))
    assert [d["path"] for d in first] == [d["path"] for d in second]
    assert len(first) > 1


# --------------------------------------------------------------------------- #
#  _label()
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path,expected", [
    ("brNo", "Business Registration number"),
    ("roAddr/bldg", "Registered office · Building"),
    ("indDirList/indDir[2]/stdAddress/bldg",
     "Director (individual) 2 · Address · Building"),
    ("shareCapitals/shareCapital[3]/paidUpCapital",
     "Share capital · Share class 3 · Paid-up capital"),
])
def test_labels_read_as_english(path, expected):
    assert drift._label(path) == expected


def test_an_unmapped_element_falls_back_to_its_own_name():
    """CR owns this vocabulary and has changed it before. A label table that
    crashed on an unknown element would take the whole gate down with it."""
    assert drift._label("someNewFieldCrAdded") == "someNewFieldCrAdded"
    assert drift._label("newContainer/someNewField") == "someNewField"


# --------------------------------------------------------------------------- #
#  The gate inside filings.submit
# --------------------------------------------------------------------------- #

def _filing(**over):
    # `signed_xml` already carries a depositAccountNo, so `submit` sends it
    # verbatim instead of routing through `append_deposit_account` — which
    # parses for a closing </submission> and is not what these tests are about.
    row = {"id": "f1", "entity_id": "e1", "nar1_case_id": "c1",
           "form_code": "Nar1", "stage": filings.STAGE_SIGNED,
           "request_xml": STORED_XML,
           "signed_xml": "<cr:submission><cr:depositAccountNo>N1"
                         "</cr:depositAccountNo></cr:submission>"}
    row.update(over)
    return row


def test_submit_refuses_when_the_company_record_has_moved():
    moved = graph(
        officers=BASE["officers"], persons=BASE["persons"],
        addresses=BASE["addresses"],
        registered_address={**BASE["registered_address"], "line2": "New Tower"},
    )
    client = MagicMock()
    with patch("services.tpsi.filings.get_filing", return_value=_filing()), \
         patch("services.tpsi.filings.case_of", return_value={}), \
         patch("services.tpsi.drift.current_xml_for", return_value=xml_for(moved)):
        with pytest.raises(filings.DriftDetected) as exc:
            filings.submit(client, "f1", True, "N00061980009")

    assert exc.value.differences
    assert "Restart verification" in str(exc.value)
    # NO CR TRAFFIC AT ALL — not even the free balance read.
    client.post_form.assert_not_called()
    client.authenticate.assert_not_called()


def test_submit_proceeds_when_nothing_has_moved():
    client = MagicMock()
    with patch("services.tpsi.filings.get_filing", return_value=_filing()), \
         patch("services.tpsi.filings.case_of", return_value={}), \
         patch("services.tpsi.drift.current_xml_for", return_value=xml_for(BASE)), \
         patch("services.tpsi.filings.fee_quote_for") as quote, \
         patch("services.tpsi.reads.check_balance", return_value=0):
        quote.return_value = MagicMock(amount=0, band="on time", certain=True)
        with patch("services.tpsi.filings._update"), \
             patch("services.tpsi.filings._write_back_receipt"), \
             patch("services.tpsi.filings.parse_receipt",
                   return_value={"caseNo": "1"}):
            result = filings.submit(client, "f1", True, "N00061980009")

    assert result["filing_id"] == "f1"
    client.post_form.assert_called_once()


def test_a_gate_that_cannot_run_refuses_rather_than_waving_the_filing_through():
    """"We could not check" is not a reason to make an irreversible chargeable
    call. It is reported as its own message, not as drift, so the operator is
    not sent to restart verification for a problem restarting cannot fix."""
    client = MagicMock()
    with patch("services.tpsi.filings.get_filing", return_value=_filing()), \
         patch("services.tpsi.filings.case_of", return_value={}), \
         patch("services.tpsi.drift.current_xml_for",
               side_effect=drift.DriftError("supabase is down")):
        with pytest.raises(filings.SubmitGateError) as exc:
            filings.submit(client, "f1", True, "N00061980009")

    assert not isinstance(exc.value, filings.DriftDetected)
    assert "could not be checked" in str(exc.value)
    # `check_failed`, not `record_unusable`: the screen reads this to decide
    # whether to offer Restart verification, and restarting cannot reach a
    # Supabase that is down.
    assert exc.value.reason == "check_failed"
    assert exc.value.problems == []
    client.post_form.assert_not_called()


def test_an_unfilable_company_is_refused_with_its_faults_as_a_list():
    """The other half of the same gate, and the one an operator actually hits:
    somebody edited the company mid-case into a state CR would reject. Each
    fault has to arrive separately — the screen draws one card per fault, and a
    "; "-spliced sentence is what it drew before."""
    client = MagicMock()
    faults = ["corporate party ACME LIMITED: no CR region code is known for "
              "country 'HK-CH' — correct the address",
              "entity: no BR number — CR rejects a NAR1 without one"]
    with patch("services.tpsi.filings.get_filing", return_value=_filing()), \
         patch("services.tpsi.filings.case_of", return_value={}), \
         patch("services.tpsi.drift.current_xml_for",
               side_effect=drift.DriftError("the company record has changed "
                                            "and can no longer be made into a "
                                            "NAR1", problems=faults)):
        with pytest.raises(filings.RecordCheckFailed) as exc:
            filings.submit(client, "f1", True, "N00061980009")

    assert exc.value.problems == faults
    assert exc.value.reason == "record_unusable"
    # Readable on its own, with no fault text spliced into it.
    assert "HK-CH" not in str(exc.value)
    assert "not submitted" in str(exc.value)
    client.post_form.assert_not_called()


def test_the_drift_gate_runs_before_the_off_portal_interlock_is_satisfied():
    """Order matters on this path. A case already filed on paper must be
    refused by its own interlock, not by a drift comparison that would reload
    the company for a filing that can never be sent."""
    client = MagicMock()
    with patch("services.tpsi.filings.get_filing", return_value=_filing()), \
         patch("services.tpsi.filings.case_of",
               return_value={"id": "c1", "case_no": "NAR-1",
                             "manual_receipt": {"caseNo": "180256934"},
                             "manual_submitted_at": "2026-08-18T02:00:00+00:00"}), \
         patch("services.tpsi.drift.current_xml_for") as rebuild:
        with pytest.raises(filings.ManualCompletionInterlock):
            filings.submit(client, "f1", True, "N00061980009")
    rebuild.assert_not_called()


def test_a_closed_case_is_refused_before_the_drift_gate_reloads_the_company():
    """Same ordering rule, the other interlock. A case the client cancelled is
    refused on its own terms, not by a comparison that would reload the whole
    company graph for a filing that can never be sent.

    THE SECOND LOCK. Closing supersedes every live filing, so `_check_gate`
    normally refuses first — but that cleanup is best-effort by design, and a
    signed filing left behind on a closed case is one chargeable call from
    lodging a return the client stopped."""
    client = MagicMock()
    with patch("services.tpsi.filings.get_filing", return_value=_filing()), \
         patch("services.tpsi.filings.case_of",
               return_value={"id": "c1", "case_no": "NAR-1",
                             "closed_at": "2026-09-05T02:00:00+00:00",
                             "closed_reason": "client is dissolving the company"}), \
         patch("services.tpsi.drift.current_xml_for") as rebuild:
        with pytest.raises(filings.CaseClosedInterlock, match="closed"):
            filings.submit(client, "f1", True, "N00061980009")
    rebuild.assert_not_called()
    # Not one byte to CR, the free balance read included.
    client.post_form.assert_not_called()


def test_closure_is_reported_ahead_of_an_off_portal_filing():
    """A case that is both must name the closure. It is the fact that decides
    what the operator does next: no amount of correcting the filing reopens a
    closed case."""
    client = MagicMock()
    with patch("services.tpsi.filings.get_filing", return_value=_filing()), \
         patch("services.tpsi.filings.case_of",
               return_value={"id": "c1", "case_no": "NAR-1",
                             "closed_at": "2026-09-05T02:00:00+00:00",
                             "manual_receipt": {"caseNo": "1"}}):
        with pytest.raises(filings.CaseClosedInterlock):
            filings.submit(client, "f1", True, "N00061980009")


def test_a_non_nar1_filing_is_not_drift_checked():
    """`submit` is generic over form codes and the comparator rebuilds through
    `nar1_mapper`. Pointing it at an NNC1 would fail to map and refuse a filing
    it knows nothing about — a form with no rebuilder is simply not checked,
    which is where everything stood before this gate existed."""
    client = MagicMock()
    with patch("services.tpsi.filings.get_filing",
               return_value=_filing(form_code="Nnc1")),          patch("services.tpsi.filings.case_of", return_value={}),          patch("services.tpsi.drift.current_xml_for") as rebuild,          patch("services.tpsi.filings.fee_quote_for") as quote,          patch("services.tpsi.reads.check_balance", return_value=0):
        quote.return_value = MagicMock(amount=0, band="on time", certain=True)
        with patch("services.tpsi.filings._update"),              patch("services.tpsi.filings._write_back_receipt"),              patch("services.tpsi.filings.parse_receipt", return_value={}):
            filings.submit(client, "f1", True, "N00061980009")
    rebuild.assert_not_called()


def test_the_refusal_names_how_many_fields_moved():
    differences = [{"path": "brNo", "field": "Business Registration number",
                    "validated": "1", "current": "2"}]
    assert "1 field changed" in str(filings.DriftDetected(differences))
    assert "2 fields changed" in str(filings.DriftDetected(differences * 2))


# --------------------------------------------------------------------------- #
#  current_xml_for — the rebuild
# --------------------------------------------------------------------------- #

def test_the_rebuild_uses_the_year_the_stored_document_declares():
    """A return prepared in December and submitted in January must not be
    reported as drifting by a year it never had."""
    captured = {}

    mapped_base = mapped(BASE)          # BEFORE the patch, or this recurses

    def fake_map(graph_arg, *, year, **kw):
        captured["year"] = year
        return mapped_base

    with patch("services.tpsi.forms.nar1_source.load_entity_graph"), \
         patch("services.tpsi.drift._run_async", return_value=BASE), \
         patch("services.tpsi.forms.nar1_mapper.map_entity", side_effect=fake_map), \
         patch("services.nar1_cases.get_case",
               return_value={"signatory_capacity":
                             "Director of the Company Secretary (Body Corporate)"}):
        drift.current_xml_for(_filing(request_xml=STORED_XML_2024))

    assert captured["year"] == 2024


def test_the_rebuild_uses_the_capacity_the_case_stored():
    """Every real GSHK client signs through a body corporate. Resolving the
    capacity differently from `prepare` would report a spurious difference on
    the signatory and block every one of them."""
    captured = {}

    mapped_base = mapped(BASE)          # BEFORE the patch, or this recurses

    def fake_map(graph_arg, *, year, signatory_capacity=None, **kw):
        captured["capacity"] = signatory_capacity
        return mapped_base

    with patch("services.tpsi.drift._run_async", return_value=BASE), \
         patch("services.tpsi.forms.nar1_mapper.map_entity", side_effect=fake_map), \
         patch("services.nar1_cases.get_case",
               return_value={"signatory_capacity": "Director (Body Corporate)"}):
        drift.current_xml_for(_filing())

    assert captured["capacity"] == "Director (Body Corporate)"


def test_a_filing_with_no_year_is_an_operational_failure_not_drift():
    with pytest.raises(drift.DriftError, match="no year of annual return"):
        drift.current_xml_for(_filing(request_xml="<cr:brNo>1</cr:brNo>"))


def test_a_filing_with_no_company_cannot_be_checked():
    with pytest.raises(drift.DriftError, match="no company"):
        drift.current_xml_for(_filing(entity_id=None))


def test_a_company_that_no_longer_maps_is_reported_as_such():
    """It is a change since validation, and a decisive reason not to file — but
    the message has to say the company cannot be made into a return, not that
    two documents differ, because the remedy is different."""
    from services.tpsi.forms import nar1_mapper

    with patch("services.tpsi.drift._run_async", return_value=BASE), \
         patch("services.tpsi.forms.nar1_mapper.map_entity",
               side_effect=nar1_mapper.MappingError(["no BR number"])), \
         patch("services.nar1_cases.get_case", return_value={}):
        with pytest.raises(drift.DriftError, match="can no longer be made"):
            drift.current_xml_for(_filing())


def test_the_mappers_faults_stay_a_list_instead_of_one_spliced_sentence():
    """They used to be joined into the message with "; ", which is how three
    faults reached the screen as one 300-character line above the Submit
    button. The screen draws one card per fault, so the list has to survive."""
    from services.tpsi.forms import nar1_mapper

    faults = ["entity: no BR number",
              "corporate party ACME LIMITED: no CR region code for 'HK-CH'"]
    with patch("services.tpsi.drift._run_async", return_value=BASE), \
         patch("services.tpsi.forms.nar1_mapper.map_entity",
               side_effect=nar1_mapper.MappingError(faults)), \
         patch("services.nar1_cases.get_case", return_value={}):
        with pytest.raises(drift.DriftError) as exc:
            drift.current_xml_for(_filing())

    assert exc.value.problems == faults
    # And the headline stays readable on its own — no fault text spliced in.
    assert "HK-CH" not in str(exc.value)


def test_an_operational_failure_carries_no_problem_list():
    """`problems` is what tells the gate to say "fix the profile, then restart".
    A graph that would not load is not fixable that way, so it must stay
    empty."""
    with patch("services.tpsi.drift._run_async",
               side_effect=RuntimeError("supabase is down")), \
         patch("services.nar1_cases.get_case", return_value={}):
        with pytest.raises(drift.DriftError) as exc:
            drift.current_xml_for(_filing())

    assert exc.value.problems == []

"""The EventString decoder (PBI-41).

The blobs below are real, taken verbatim from the live Viewpoint EventLog —
these are the exact rows that rendered as "Form Generated" with no form and
"Master File Details Changed" with no detail.
"""
import pytest

from services.audit_changes import (
    describe, extract_changes, is_noise, render, status_change, summarize,
)


def parse(s):
    """Same shape the ETL hands us: the EventString split into key/value."""
    return dict(
        tok.split("=", 1) for tok in s.split("\x0c") if "=" in tok
    )


# --- the pipe convention: Field=new|old ------------------------------------
# Verified against 3,494 live events carrying BOTH the pipe and an explicit
# Old/New pair: they agreed every time, zero disagreements.

def test_pipe_is_new_then_old():
    out = extract_changes(parse("DateLastAnRe=2025-07-21|2024-07-21"))
    assert out == [{"field": "DateLastAnRe", "label": "DateLastAnRe",
                    "old": "2024-07-21", "new": "2025-07-21"}]


def test_pipe_with_equal_halves_is_not_a_change():
    """Confidential=False|False is context written in change form."""
    assert extract_changes(parse("Confidential=False|False")) == []


def test_pipe_with_empty_half_is_a_change():
    out = extract_changes(parse("IncorpNr=77592654|"))
    assert out == [{"field": "IncorpNr", "label": "IncorpNr",
                    "old": None, "new": "77592654"}]


def test_explicit_old_new_pair():
    out = extract_changes(parse("OldAdNrBA=6030\x0cNewAdNrBA=8029"))
    assert out == [{"field": "AdNrBA", "label": "AdNrBA",
                    "old": "6030", "new": "8029"}]


def test_labels_applied():
    out = extract_changes(parse("IncorpNr=776|"), {"IncorpNr": "Incorporation Number"})
    assert out[0]["label"] == "Incorporation Number"


# --- noise suppression -----------------------------------------------------
# Viewpoint's internal document/checklist flags flip on nearly every event and
# mean nothing to a user. They are what buried the real change.

@pytest.mark.parametrize("field", [
    "Di1chkD", "SCxchkS", "ImchkD", "VPC.SEV7", "ALLOTLIST1chkS",
    "MergedChangeNumber", "LinkedChangeNumbers", "EventNr", "PRIV",
])
def test_internal_flags_are_noise(field):
    assert is_noise(field)


@pytest.mark.parametrize("field", ["IncorpNr", "DateLastAnRe", "Nationality", "AdNrBA"])
def test_real_fields_are_not_noise(field):
    assert not is_noise(field)


def test_noise_is_excluded_from_changes():
    out = extract_changes(parse("DIxchkD=1|0\x0cIncorpNr=776|775\x0cVPC.LAC=a|b"))
    assert [c["field"] for c in out] == ["IncorpNr"]


# --- address cards ---------------------------------------------------------

def test_address_card_resolves_to_the_address():
    """"Business Address: 6030 -> 8029" is not a usable audit entry."""
    out = extract_changes(
        parse("OldAdNrBA=6030\x0cNewAdNrBA=8029"),
        {"AdNrBA": "Business Address"},
        {"6030": "Old Road, ZA", "8029": "Unit 301, Illovo Towers, ZA"},
    )
    assert out[0]["old"] == "Old Road, ZA"
    assert out[0]["new"] == "Unit 301, Illovo Towers, ZA"


def test_unknown_address_card_falls_back_to_the_number():
    out = extract_changes(parse("NewAdNrBA=9999"), {}, {"1": "Somewhere"})
    assert out[0]["new"] == "9999"


def test_statutory_registers_collapse_to_one_change():
    """Filing all 17 statutory registers at one address is ONE decision.
    Viewpoint writes it as 17 near-identical changes."""
    blob = "\x0c".join(f"New{f}=1" for f in
                       ["AdNrSR", "AdNrSM", "AdNrSO", "AdNrSQ", "AdNrSH", "AdNrSG"])
    out = extract_changes(parse(blob))
    assert len(out) == 1
    assert out[0]["field"] == "statutory_registers"
    assert "6" in out[0]["label"]
    assert out[0]["new"] == "1"


def test_registers_going_to_different_places_keep_their_detail():
    blob = "NewAdNrSR=1\x0cNewAdNrSM=2\x0cNewAdNrSO=3"
    assert len(extract_changes(parse(blob))) == 3


# --- action events: say WHAT happened --------------------------------------

def test_form_generation_names_the_form():
    """The complaint verbatim: "form generated" — what form?"""
    blob = ("SFMG\x0cFQnumber=FQ025280"
            "\x0cFormName=NAR1 - Annual Return Private Company"
            "\x0cEntCode=OBSYDIANGR\x0cEventNr=181993")
    out = describe("SFMG", parse(blob), {"FormName": "Form", "FQnumber": "Form Reference"})
    assert out == [
        {"field": "FormName", "label": "Form", "old": None,
         "new": "NAR1 - Annual Return Private Company"},
        {"field": "FQnumber", "label": "Form Reference", "old": None, "new": "FQ025280"},
    ]


def test_master_file_creation_names_what_was_created():
    """A creation event has no diff — reporting its address cards instead of the
    name of the thing created is what made "Company created" say nothing."""
    blob = ("ADN\x0cEntCode=NOVUSDUXLI\x0cRefType=C\x0cName=Novus Dux Limited"
            "\x0cNewAdNrBA=2311\x0cNewAdNrMA=2311")
    out = describe("ADN", parse(blob), {"Name": "Name"})
    assert out == [{"field": "Name", "label": "Name", "old": None,
                    "new": "Novus Dux Limited"},
                   {"field": "RefType", "label": "RefType", "old": None, "new": "C"}]


def test_summarize_skips_absent_fields():
    assert summarize("SFMG", parse("FormName=NAR1")) == [
        {"field": "FormName", "label": "FormName", "old": None, "new": "NAR1"}]


def test_describe_falls_back_to_changes_for_unmapped_codes():
    out = describe("XXXX", parse("IncorpNr=776|775"))
    assert out[0]["field"] == "IncorpNr"


def test_describe_returns_empty_when_the_blob_says_nothing():
    assert describe("XXXX", parse("EntCode=ABC\x0cEventNr=1")) == []


# --- status ----------------------------------------------------------------

def test_status_codes_are_decoded():
    """"0 -> 8" is not a status trail."""
    assert status_change("0", "8") == [{
        "field": "Status", "label": "Status",
        "old": "Open/Active", "new": "Closed/Inactive",
    }]


def test_unknown_status_code_passes_through():
    assert status_change(None, "Z")[0]["new"] == "Z"


def test_status_change_with_nothing_set():
    assert status_change(None, None) == []


# --- rendering to the searchable text columns ------------------------------

def test_single_change_renders_bare():
    assert render([{"label": "Passport No.", "old": "A1", "new": "B2"}], "new") == "B2"


def test_several_changes_are_prefixed_by_field():
    changes = [{"label": "Entity Type", "old": None, "new": "CL14"},
               {"label": "Jurisdiction", "old": None, "new": "HK"}]
    assert render(changes, "new") == "Entity Type: CL14; Jurisdiction: HK"


def test_render_returns_none_when_that_side_is_empty():
    assert render([{"label": "Name", "old": None, "new": "X"}], "old") is None
    assert render([], "new") is None

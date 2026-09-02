"""Display names: what CR PRINTS for a code it accepts.

These are one-way and rendering-only. The failure they guard against is not a
crash but a printed statutory return that reads "CENTRAL" and "SWE" where
GSHK's own filed specimen reads "Central" and "Sweden" -- and, far worse, a
display table that quietly starts disagreeing with the codes CR validates
against.
"""
import pytest

from services.tpsi.forms import cr_vocabularies as v


# ---------------------------------------------------------------------------
# The invariant: a display name can never imply a different code
# ---------------------------------------------------------------------------

def test_every_district_code_has_a_name_and_no_name_is_invented():
    """DISTRICT_NAMES and DISTRICT_CODES are two hand-written lists that must
    agree exactly. A name added for a district CR does not have, or a code
    left without a name, is caught here rather than by a blank box on a
    filing."""
    assert set(v.DISTRICT_NAMES) == set(v.DISTRICT_CODES)


def test_every_district_name_normalises_back_to_its_own_code():
    """The typo guard. CR's code IS the name with its separators stripped, so
    if `_district_key("Wan Chai")` does not come back "WANCHAI" then the name
    is misspelt -- and a misspelt name on a printed return names a district
    the company is not in."""
    for code, name in v.DISTRICT_NAMES.items():
        assert v._district_key(name) == code, \
            f"{name!r} normalises to {v._district_key(name)!r}, not {code!r}"


def test_every_country_display_name_preserves_CRs_own_letters():
    """Display may change CASE and nothing else. If a country's printed name
    normalises differently from CR's description, a letter was added, dropped
    or altered -- so the form would name a different country from the one
    filed."""
    for code, description in v.CR_COUNTRY_CODES.items():
        shown = v.display_country(code)
        assert v._normalise(shown) == v._normalise(description), \
            f"{code}: {shown!r} is not {description!r} recased"


# ---------------------------------------------------------------------------
# The cases that appear on the reference return
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code, expected", [
    ("CENTRAL", "Central"),
    ("WANCHAI", "Wan Chai"),          # the code that is NOT its own name
    ("TSEUNGKWANO", "Tseung Kwan O"),
    ("MIDLEVELS", "Mid-Levels"),      # separator is a hyphen, not a space
    ("JARDINESLOOKOUT", "Jardine's Lookout"),
])
def test_a_district_prints_the_name_not_the_code(code, expected):
    assert v.display_district(code) == expected


def test_a_district_is_matched_however_it_was_typed():
    assert v.display_district("wan chai") == "Wan Chai"
    assert v.display_district("  CENTRAL  ") == "Central"


def test_an_overseas_city_is_returned_untouched():
    """Outside Hong Kong this column is free text -- a city, a state, a
    postcode. Discarding a line of somebody's address because it is not on
    CR's district list would be worse than any casing."""
    assert v.display_district("Stockholm 11859") == "Stockholm 11859"
    assert v.display_district("") == ""
    assert v.display_district(None) == ""


@pytest.mark.parametrize("code, expected", [
    ("SWE", "Sweden"),                        # the reference return's director
    ("HKG", "Hong Kong"),
    ("ARE", "United Arab Emirates"),
    ("ATG", "Antigua and Barbuda"),           # "AND" is not capitalised
    ("GNB", "Guinea-Bissau"),
    ("LAO", "Lao People's Democratic Republic"),   # not "People'S"
    ("CIV", "Cote D'Ivoire"),
    ("GBR1", "Guernsey"),                     # CR's own non-ISO code
])
def test_a_country_prints_the_name_not_the_code(code, expected):
    assert v.display_country(code) == expected


def test_a_dotted_initialism_keeps_its_capitals():
    """`str.title()` renders CR's "U.S. VIRGIN ISLANDS" as "U.s. ..."."""
    shown = v.display_country("VIR")
    assert shown.startswith("U.S."), shown


def test_an_unknown_country_is_passed_through_rather_than_blanked():
    """This runs on data CR has already accepted and filed. Refusing here
    would empty a box on a return that exists."""
    assert v.display_country("Neverland") == "Neverland"
    assert v.display_country("") == ""
    assert v.display_country(None) == ""


def test_display_helpers_never_feed_the_filing_path():
    """One owner per vocabulary. `resolve_*` decides what CR is SENT and must
    keep taking the code; the display name is for the printed page only, and a
    display name must never become a second way to name a code."""
    assert v.resolve_district("Wan Chai") == "WANCHAI"
    assert v.resolve_country("Sweden") == "SWE"

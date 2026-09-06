"""`canonical_country` — the value a country column should be STORED as.

WHAT THIS PROTECTS. An operator picked Viewpoint's Chinese-labelled Hong Kong
out of the old country dropdown, it stored 'HK-CH', every check on the profile
passed, and the NAR1 died weeks later at Data Verification with "no CR region
code is known for country 'HK-CH'". Migration 032 rewrites the twenty codes CR
has no entry for; these tests are why that rewrite can be trusted.

THE LINE THAT MATTERS: `resolve_country` must stay STRICT. This table is for
correcting stored data, never for making the write guard accept a value CR
would refuse — that guard is the thing standing between an operator and a fee
taken for a filing that is then rejected.
"""
import pytest

from services.tpsi.forms.cr_vocabularies import (
    ALPHA2_TO_CR_CODE,
    VIEWPOINT_SUBDIVISIONS,
    canonical_country,
    resolve_country,
    to_alpha2,
)


# --------------------------------------------------------------------------- #
#  The refusal must NOT be relaxed
# --------------------------------------------------------------------------- #

def test_the_unfilable_codes_still_do_not_resolve():
    """`address_service.validate` and `readiness.filing_problems` both refuse a
    country `resolve_country` cannot answer for. Teaching the resolver these
    codes would silently re-open the hole migration 032 exists to close, and
    the next one would be found by CR after the fee."""
    for source in VIEWPOINT_SUBDIVISIONS:
        assert resolve_country(source) is None, (
            f"{source!r} now resolves — the write guard would accept it again"
        )


# --------------------------------------------------------------------------- #
#  Every target is a place CR actually carries
# --------------------------------------------------------------------------- #

def test_every_target_is_on_crs_own_sheet():
    for source, alpha2 in VIEWPOINT_SUBDIVISIONS.items():
        assert alpha2 in ALPHA2_TO_CR_CODE, (
            f"{source!r} maps to {alpha2!r}, which CR has no row for"
        )


def test_the_chinese_twins_map_to_the_english_ones():
    """香港 / 澳門 / 台灣. Viewpoint's own labels name the same three places as
    its 'HK', 'MO' and 'TW' rows — this is a duplicate code, not a different
    country."""
    assert canonical_country("HK-CH") == "HK"
    assert canonical_country("MO-CH") == "MO"
    assert canonical_country("TW-CH") == "TW"
    assert [resolve_country(canonical_country(c))
            for c in ("HK-CH", "MO-CH", "TW-CH")] == ["HKG", "MAC", "TWN"]


def test_the_channel_islands_go_to_guernsey_and_never_to_gbr():
    """Alderney and Sark are in the Bailiwick of Guernsey, which CR carries as
    its OWN code. GBR1, GBR2 and GBR3 exist precisely because CR does not treat
    them as the United Kingdom, and filing GBR for a Guernsey address is the
    mistake the whole alpha-2 table was built to stop."""
    for source in ("GB-ALD", "GB-SAR"):
        assert canonical_country(source) == "GG"
        assert resolve_country(canonical_country(source)) == "GBR1"


def test_the_uk_constituent_countries_go_to_the_united_kingdom():
    for source in ("GB-ENG", "GB-SCT", "GB-WLS", "GB-NIR", "GB-EAW"):
        assert canonical_country(source) == "GB"
        assert resolve_country(canonical_country(source)) == "GBR"


def test_zaire_becomes_the_democratic_republic_and_not_congo():
    """Renamed in 1997. 'CONGO' (COG) is a different country with a shared
    border, and picking it would file a director as resident in the wrong
    state."""
    assert canonical_country("ZR") == "CD"
    assert resolve_country("CD") == "COD"
    assert resolve_country("CG") == "COG"


def test_us_states_and_labuan_go_to_their_countries():
    for source in ("US-CA", "US-DE", "US-NY", "US-WY"):
        assert canonical_country(source) == "US"
    assert canonical_country("MY-15") == "MY"


def test_no_subdivision_shadows_a_code_cr_actually_carries():
    """A key that is itself a CR code or alpha-2 would rewrite good data."""
    for source in VIEWPOINT_SUBDIVISIONS:
        assert resolve_country(source) is None
        assert source.upper() not in ALPHA2_TO_CR_CODE


# --------------------------------------------------------------------------- #
#  "Leave it alone" has to mean leave it alone
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("value", ["HK", "GB", "US", "CD", "GG"])
def test_a_value_already_canonical_is_left_alone(value):
    """None means "no change". Returning the same string would make every
    backfill count thousands of no-op writes as corrections."""
    assert canonical_country(value) is None


def test_a_filable_spelling_is_still_normalised_for_the_dropdown():
    """"Hong Kong" and "HKG" both FILE. Neither can be SELECTED in a dropdown
    keyed by alpha-2, which is why 251 companies rendered as
    "Hong Kong (not in list)"."""
    assert canonical_country("Hong Kong") == "HK"
    assert canonical_country("HKG") == "HK"


def test_a_country_with_no_justified_parent_is_left_for_a_human():
    """The original caution, kept: anything not in the table is untouched, and
    `registry_reconciliation` still names it."""
    assert canonical_country("Atlantis") is None
    assert canonical_country("ZZ-NOWHERE") is None


@pytest.mark.parametrize("value", [None, "", "   "])
def test_blank_input_is_not_a_country(value):
    assert canonical_country(value) is None


def test_case_and_padding_do_not_hide_a_bad_code():
    assert canonical_country(" hk-ch ") == "HK"
    assert canonical_country("Hk-Ch") == "HK"


def test_it_agrees_with_to_alpha2_wherever_cr_can_resolve_at_all():
    """The two must not disagree: `to_alpha2` answers for values CR already
    accepts, and `canonical_country` has to give the same answer there or a
    backfill would flip rows back and forth on alternate runs."""
    for value in ("Hong Kong", "HKG", "hk", "UNITED KINGDOM", "GBR1", "VN"):
        expected = to_alpha2(value)
        result = canonical_country(value)
        assert result in (None, expected)
        if result is None:
            assert expected == value.strip()

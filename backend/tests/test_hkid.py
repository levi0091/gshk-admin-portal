"""The HKID check digit.

Brian asked for this. It is a real, computable checksum -- CR's own NNC1 XML
carries `hkid` and `hkidChkDtg` as separate elements -- so a mistyped identity
card number can be caught at entry rather than at filing.

Measured against DEV before this shipped: 483 HKIDs, 452 passing, 1 genuinely
wrong, and 30 unparseable -- of which 29 are 18-digit Mainland China ID numbers
filed under id_type='hkid'. So the validator is right about almost everything
it rejects; those rows are mis-typed, not mis-validated. They stay editable
because the check only runs when id_number is itself being written.

Passport has NO equivalent. The only checksums in a passport live in the
machine-readable zone and are computed over the whole MRZ line, not the number,
so passports get format and length only.
"""
import pytest

from services.hkid import check_digit, is_valid_hkid, split_hkid


@pytest.mark.parametrize("number", [
    "A123456(3)",     # the canonical single-letter example
    "AB987654(3)",    # two-letter prefix
    "a123456(3)",     # lower case
    "A123456 (3)",    # stray space
    "A1234563",       # no parentheses
])
def test_accepts_a_correct_hkid_however_it_is_typed(number):
    assert is_valid_hkid(number)


def test_rejects_the_one_real_hkid_in_dev_that_fails_its_check_digit():
    """Z351007(9) is a real stored value. Its correct check digit is 8."""
    assert not is_valid_hkid("Z351007(9)")
    assert check_digit("Z351007") == "8"


@pytest.mark.parametrize("number", [
    "440782198611028063",   # a Mainland China resident ID, mis-typed as HKID
    "xxxxxxx",              # a literal placeholder, also real
    "",
    None,
    "A12345(3)",            # too few digits
    "ABC123456(3)",         # three letters
])
def test_rejects_what_is_not_an_hkid_at_all(number):
    assert not is_valid_hkid(number)


def test_check_digit_a_stands_for_ten():
    """11 - remainder == 10 is written 'A', not '10'. Without this the whole
    band of identity cards ending in A is rejected as malformed."""
    assert check_digit("G123456") == "A"
    assert is_valid_hkid("G123456(A)")


def test_split_returns_the_number_and_the_check_digit_separately():
    """CR takes them as two XML elements (hkid, hkidChkDtg), so the stored
    single value has to come apart cleanly."""
    assert split_hkid("A123456(3)") == ("A123456", "3")


def test_split_returns_none_for_something_that_is_not_an_hkid():
    assert split_hkid("440782198611028063") is None

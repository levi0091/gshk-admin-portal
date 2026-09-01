"""The Hong Kong Identity Card check digit.

WHY THIS IS WORTH HAVING. An HKID carries its own checksum, so a transposed
digit is detectable at the moment someone types it rather than when CR refuses
the filing weeks later. CR treats the two halves as separate XML elements --
NNC1 sends `hkid` and `hkidChkDtg` -- which is why `split_hkid` exists: we
store what the operator typed ("A123456(3)") and take it apart on the way out.

THE ALGORITHM. Right-justify the letter prefix to two characters, padding with
a space. Value a letter as A=10 .. Z=35 and the pad as 36. Weight the eight
characters 9, 8, 7 ... 2, add the check digit (where "A" means 10), and the
total is divisible by 11.

    " A123456" -> 36*9 + 10*8 + 1*7 + 2*6 + 3*5 + 4*4 + 5*3 + 6*2 = 481
    481 + 3 = 484 = 44 * 11, so A123456(3) is valid.

WHAT THIS IS NOT. There is no passport equivalent. A passport's only checksums
are in the machine-readable zone and are computed over the whole MRZ line, not
over the number, so a passport number alone cannot be verified -- it gets
format and length checks and nothing more. Saying otherwise would be a
validator that validates nothing.
"""
import re
from typing import Optional

#: One or two letters, six digits, then the check digit -- optionally in
#: parentheses, optionally spaced. Anything else is not an HKID, including the
#: 18-digit Mainland China resident ID numbers that 29 rows in DEV carry under
#: id_type='hkid'.
_HKID = re.compile(r"^([A-Z]{1,2})(\d{6})\s*\(?([0-9A])\)?$")

_PAD_VALUE = 36     # the space used to right-justify a single-letter prefix
_LETTER_OFFSET = 55  # ord("A") - 10


def _value(char: str) -> int:
    if char == " ":
        return _PAD_VALUE
    if char.isalpha():
        return ord(char) - _LETTER_OFFSET
    return int(char)


def _normalise(number: Optional[str]) -> str:
    return (number or "").strip().upper().replace(" ", "")


def check_digit(prefix_and_digits: str) -> Optional[str]:
    """The check digit for an HKID body such as "A123456", or None.

    Returns a single character: "0"-"9", or "A" for ten.
    """
    body = _normalise(prefix_and_digits)
    match = re.fullmatch(r"([A-Z]{1,2})(\d{6})", body)
    if not match:
        return None

    total = sum(
        _value(char) * weight
        for char, weight in zip(match.group(1).rjust(2), range(9, 7, -1))
    ) + sum(
        int(digit) * weight
        for digit, weight in zip(match.group(2), range(7, 1, -1))
    )
    remainder = (11 - total % 11) % 11
    return "A" if remainder == 10 else str(remainder)


def split_hkid(number: Optional[str]) -> Optional[tuple[str, str]]:
    """("A123456", "3") from "A123456(3)", or None if it is not an HKID.

    Does NOT verify the check digit -- `is_valid_hkid` does that. Splitting a
    stored value and judging it are different questions: a legacy row must
    still be readable even when its check digit is wrong.
    """
    match = _HKID.match(_normalise(number))
    if not match:
        return None
    return f"{match.group(1)}{match.group(2)}", match.group(3)


def is_valid_hkid(number: Optional[str]) -> bool:
    """True when `number` is a well-formed HKID whose check digit agrees."""
    parts = split_hkid(number)
    if parts is None:
        return False
    body, given = parts
    return check_digit(body) == given

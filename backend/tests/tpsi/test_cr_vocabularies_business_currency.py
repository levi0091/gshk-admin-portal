"""Business Nature and Currency, transcribed from CR's workbook.

These join the country / district / capacity tables already in
`cr_vocabularies` and are verified the same way: re-read CR's sheet and compare
row for row, so a transcription slip is a red test rather than a rejected
filing.

Currency matters more than it looks. `lookup_values` already offers 162
currency codes lifted from Viewpoint, but CR accepts only 54 — and four of
CR's are NOT ISO 4217: RMB (ISO says CNY), NTD (TWD), WON (KRW), NIS (ILS).
Offering the ISO code for the renminbi to someone filing a Chinese-currency
share class produces a form CR refuses.
"""
from pathlib import Path

import pytest

from services.tpsi.forms import cr_vocabularies

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cr-examples"
WORKSHEET = _FIXTURES / "Worksheet in TPSI API Interface v1.0.14.xlsx"


def _sheet_rows(sheet_name):
    """(code, english) from a CR vocabulary sheet, header row dropped.

    A hard failure, never a skip: the workbook is committed, so its absence is
    a broken checkout — and a silently skipped transcription check is exactly
    what let the country table drift unnoticed before.
    """
    assert WORKSHEET.exists(), f"committed CR workbook missing: {WORKSHEET}"
    import openpyxl

    workbook = openpyxl.load_workbook(WORKSHEET, read_only=True, data_only=True)
    try:
        rows = []
        for row in workbook[sheet_name].iter_rows(min_row=2, values_only=True):
            if row and row[0] not in (None, ""):
                rows.append((str(row[0]).strip(), str(row[1] or "").strip()))
        return rows
    finally:
        workbook.close()


def test_business_nature_matches_crs_sheet_row_for_row():
    expected = dict(_sheet_rows("Business Nature"))

    assert cr_vocabularies.BUSINESS_NATURE == expected


def test_business_nature_resolves_the_code_brian_cited():
    """070 is the code on the specimen Brian attached to his comment. If the
    dropdown cannot turn it into a description, the auto-fill is broken.

    Note the tail: CR's *printed* form shows this description truncated at
    "...consultancy activities", but the sheet carries "such as company
    secretary services" too. The sheet is the authority — the description CR
    fills in after validation is the long one.
    """
    assert cr_vocabularies.BUSINESS_NATURE["070"] == (
        "Activities of head offices; management and management consultancy "
        "activities, such as company secretary services"
    )


def test_currency_matches_crs_sheet_row_for_row():
    expected = dict(_sheet_rows("Currency"))

    assert cr_vocabularies.CURRENCY == expected


@pytest.mark.parametrize("cr_code, iso_code", [
    ("RMB", "CNY"),
    ("NTD", "TWD"),
    ("WON", "KRW"),
    ("NIS", "ILS"),
])
def test_currency_uses_crs_non_iso_codes_and_not_the_iso_ones(cr_code, iso_code):
    """The trap this table exists to close. A share class stored as CNY is
    filed as a currency CR has never heard of."""
    assert cr_code in cr_vocabularies.CURRENCY
    assert iso_code not in cr_vocabularies.CURRENCY

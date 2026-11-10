"""CR's ND2B (Specification No. 1/2023): which widget holds which value.

Read off the template by overlaying every widget's name on the rendered page
and looking (2026-10-02), as for ND2A.

Pages, 1-based as in the template:
  1  section 1 (company), section 2 part A (the first natural person as CR
     holds them) and the presenter's block
  2  section 2 part B: that person's changed items, each with its own date
  3  section 3 (the first body corporate, parts A and B), the sheet counts and
     the signature
  4  Continuation Sheet A: one more natural person, parts A and B together
  5  Continuation Sheet B: one more body corporate
  6  PI-ND2B: one natural person's new full identity number and/or new
     residential address
  7-14 the notes — never output

Item (d), the residential address, has only a DATE on the public pages: the
address itself goes on the PI sheet. Item (g) on the public pages is the
PARTIAL new HKID; the PI sheet carries the full one.
"""
from __future__ import annotations

PAGE_MAIN_1, PAGE_MAIN_2, PAGE_MAIN_3 = 1, 2, 3
PAGE_SHEET_A, PAGE_SHEET_B, PAGE_PI = 4, 5, 6


def _dates(prefix: str, first: int) -> dict:
    return {f"{prefix}_dd": first, f"{prefix}_mm": first + 1, f"{prefix}_yyyy": first + 2}


def _named(page: int, numbers: dict, checkboxes: dict) -> dict:
    out = {k: f"fill_{n}_P.{page}" for k, n in numbers.items()}
    out.update({k: f"cb_{n}_P.{page}" for k, n in checkboxes.items()})
    return out


#: Part B of a natural person, as numbered on page 2 (offset 0) and on
#: Continuation Sheet A (where every number is 5 higher: the sheet carries
#: part A above it).
def _natural_changes(offset: int) -> dict:
    n = {
        "new_name_zh": 2, **_dates("name_zh_date", 3),
        "new_surname_en": 6, "new_other_names_en": 7, **_dates("name_en_date", 8),
        "new_alias_zh": 11, "new_alias_en": 12, **_dates("alias_date", 13),
        **_dates("res_date", 16),
        "corr_flat": 19, "corr_building": 20, "corr_street": 21, "corr_district": 22,
        "corr_country": 23, **_dates("corr_date", 24),
        "new_email": 27, **_dates("email_date", 28),
        "new_hkid_partial": 31, **_dates("hkid_date", 32),
        "new_passport_country": 35, "new_passport_partial": 36, **_dates("passport_date", 37),
        "new_tcsp_licence": 40, "new_tcsp_reason": 41, **_dates("tcsp_date", 42),
    }
    return {k: v + offset for k, v in n.items()}


MAIN_1 = _named(PAGE_MAIN_1, {
    "br_number": 1, "company_name": 2, "name_zh": 3, "surname_en": 4,
    "other_names_en": 5, "hkid_partial": 6, "passport_partial": 7,
    "presenter_name": 8, "presenter_address": 9, "presenter_tel": 10,
    "presenter_fax": 11, "presenter_email": 12, "presenter_reference": 13,
}, {"cap_secretary": 1, "cap_director": 2, "cap_alternate": 3})

MAIN_2 = _named(PAGE_MAIN_2, {"br_number": 1, **_natural_changes(0)},
                {"new_tcsp_not_required": 1})

SHEET_A = _named(PAGE_SHEET_A, {
    "br_number": 1, "name_zh": 2, "surname_en": 3, "other_names_en": 4,
    "hkid_partial": 5, "passport_partial": 6, **_natural_changes(5),
}, {"cap_secretary": 1, "cap_director": 2, "cap_alternate": 3,
    "new_tcsp_not_required": 4})


def _corporate(page: int) -> dict:
    return _named(page, {
        "br_number": 1, "name_zh": 2, "name_en": 3, "own_br_number": 4,
        "new_name_zh": 5, "new_name_en": 6, **_dates("name_date", 7),
        "addr_flat": 10, "addr_building": 11, "addr_street": 12, "addr_district": 13,
        "addr_country": 14, **_dates("addr_date", 15),
        "new_email": 18, **_dates("email_date", 19),
        "new_tcsp_licence": 22, "new_tcsp_reason": 23, **_dates("tcsp_date", 24),
    }, {"cap_secretary": 1, "cap_director": 2, "cap_alternate": 3,
        "new_tcsp_not_required": 4})


MAIN_3 = {
    **_corporate(PAGE_MAIN_3),
    "count_sheet_a": "fill_27_P.3", "count_sheet_b": "fill_28_P.3",
    "count_pi": "fill_29_P.3", "signed_name": "fill_30_P.3",
    "signed_date": "fill_31_P.3",
    "signature_strike_director": "Dropdown_1_P.3",
    "signature_strike_secretary": "Dropdown_2_P.3",
}
SHEET_B = _corporate(PAGE_SHEET_B)

PI = _named(PAGE_PI, {
    "br_number": 1, "name_zh": 2, "surname_en": 3, "other_names_en": 4,
    "hkid_full": 5, "hkid_check_digit": 6, "passport_country": 7, "passport_full": 8,
    "res_flat": 9, "res_building": 10, "res_street": 11, "res_district": 12,
    "res_country": 13,
}, {"cap_secretary": 1, "cap_director": 2, "cap_alternate": 3})

BR_NUMBER_FIELDS = frozenset(b["br_number"] for b in
                             (MAIN_1, MAIN_2, MAIN_3, SHEET_A, SHEET_B, PI))

_DATE_KEYS = [k for k in MAIN_2 if k.endswith(("_dd", "_mm", "_yyyy"))]
_CORP_DATE_KEYS = [k for k in MAIN_3 if k.endswith(("_dd", "_mm", "_yyyy"))]

CENTRED_FIELDS = frozenset(
    set(BR_NUMBER_FIELDS) | {MAIN_1["company_name"]}
    | {b[k] for b in (MAIN_1, SHEET_A) for k in ("hkid_partial",)}
    | {b[k] for b in (MAIN_2, SHEET_A) for k in _DATE_KEYS + ["new_hkid_partial"]}
    | {b[k] for b in (MAIN_3, SHEET_B) for k in _CORP_DATE_KEYS + ["own_br_number"]}
    | {MAIN_3[k] for k in ("count_sheet_a", "count_sheet_b", "count_pi",
                           "signed_name", "signed_date")}
    | {PI["hkid_full"], PI["hkid_check_digit"]}
)

REGULAR_WEIGHT_FIELDS = frozenset(MAIN_1[k] for k in (
    "presenter_name", "presenter_address", "presenter_tel", "presenter_fax",
    "presenter_email", "presenter_reference"))

FIELD_SIZES = {**{name: 14.0 for name in BR_NUMBER_FIELDS},
               MAIN_1["company_name"]: 12.0}

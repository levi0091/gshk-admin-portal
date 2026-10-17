"""CR's ND2A (Specification No. 1/2023): which widget holds which value.

Read off the template by filling every widget with its own name and LOOKING at
the rendered page (scratchpad overlays of 2026-10-01), not inferred from names.
The widget names CR used are positional (`fill_7_P.1`), so every one is mapped
here to what it means; nothing else in the renderer spells a widget name.

Pages, 1-based as in the template:
  1  sections 1-2 (company, first cessation) and the presenter's block
  2  section 3: first natural-person appointment, consent to act
  3  section 4: first body-corporate appointment, consent, the sheet counts,
     section 5 and the signature
  4  Continuation Sheet A: one more cessation
  5  Continuation Sheet B: one more natural-person appointment
  6  Continuation Sheet C: one more body-corporate appointment
  7  PI-ND2A: one natural person's full identity number and residential address
  8-17 the notes — never output

SECTION 5 HAS NO WIDGET. It is a printed statement ("Each natural person
appointed as company secretary ... ordinarily resides in Hong Kong") made by
signing the form, so there is nothing to tick; `section5_confirmed` is enforced
before the client is asked (rules.secretary_hong_kong) rather than printed.

The `Dropdown_*` widgets are CR's deletion marks: choosing the option strikes
a word through. Each dropdown is one FIELD with two widgets (the Chinese word
and the English word), so one value strikes both.
"""
from __future__ import annotations

PAGE_MAIN_1, PAGE_MAIN_2, PAGE_MAIN_3 = 1, 2, 3
PAGE_SHEET_A, PAGE_SHEET_B, PAGE_SHEET_C, PAGE_PI = 4, 5, 6, 7


def _cessation(page: int) -> dict:
    p = f"P.{page}"
    return {
        "br_number": f"fill_1_{p}",
        "cap_secretary": f"cb_1_{p}", "cap_director": f"cb_2_{p}",
        "cap_alternate": f"cb_3_{p}", "alternate_to": f"fill_2_{p}",
        "name_zh": f"fill_3_{p}", "surname_en": f"fill_4_{p}",
        "other_names_en": f"fill_5_{p}", "hkid_partial": f"fill_6_{p}",
        "passport_partial": f"fill_7_{p}", "corp_name_zh": f"fill_8_{p}",
        "corp_name_en": f"fill_9_{p}", "reason_resign": f"cb_4_{p}",
        "reason_deceased": f"cb_5_{p}", "date_dd": f"fill_10_{p}",
        "date_mm": f"fill_11_{p}", "date_yyyy": f"fill_12_{p}",
        "still_yes": f"cb_6_{p}", "still_no": f"cb_7_{p}",
    }


#: Page 1 carries the same cessation block one field later (f2 is the company
#: name), plus the presenter's block.
MAIN_1 = {
    "br_number": "fill_1_P.1", "company_name": "fill_2_P.1",
    "cap_secretary": "cb_1_P.1", "cap_director": "cb_2_P.1",
    "cap_alternate": "cb_3_P.1", "alternate_to": "fill_3_P.1",
    "name_zh": "fill_4_P.1", "surname_en": "fill_5_P.1",
    "other_names_en": "fill_6_P.1", "hkid_partial": "fill_7_P.1",
    "passport_partial": "fill_8_P.1", "corp_name_zh": "fill_9_P.1",
    "corp_name_en": "fill_10_P.1", "reason_resign": "cb_4_P.1",
    "reason_deceased": "cb_5_P.1", "date_dd": "fill_11_P.1",
    "date_mm": "fill_12_P.1", "date_yyyy": "fill_13_P.1",
    "still_yes": "cb_6_P.1", "still_no": "cb_7_P.1",
    "presenter_name": "fill_14_P.1", "presenter_address": "fill_15_P.1",
    "presenter_tel": "fill_16_P.1", "presenter_fax": "fill_17_P.1",
    "presenter_email": "fill_18_P.1", "presenter_reference": "fill_19_P.1",
}
SHEET_A = _cessation(PAGE_SHEET_A)


def _natural(page: int) -> dict:
    p = f"P.{page}"
    return {
        "br_number": f"fill_1_{p}",
        "cap_secretary": f"cb_1_{p}", "cap_director": f"cb_2_{p}",
        "cap_alternate": f"cb_3_{p}", "alternate_to": f"fill_2_{p}",
        "name_zh": f"fill_3_{p}", "surname_en": f"fill_4_{p}",
        "other_names_en": f"fill_5_{p}", "prev_name_zh": f"fill_6_{p}",
        "prev_name_en": f"fill_7_{p}", "alias_zh": f"fill_8_{p}",
        "alias_en": f"fill_9_{p}", "addr_flat": f"fill_10_{p}",
        "addr_building": f"fill_11_{p}", "addr_street": f"fill_12_{p}",
        "addr_district": f"fill_13_{p}", "addr_country": f"fill_14_{p}",
        "email": f"fill_15_{p}", "hkid_partial": f"fill_16_{p}",
        "passport_country": f"fill_17_{p}", "passport_partial": f"fill_18_{p}",
        "tcsp_licence": f"fill_19_{p}", "tcsp_not_required": f"cb_4_{p}",
        "tcsp_reason": f"fill_20_{p}", "date_dd": f"fill_21_{p}",
        "date_mm": f"fill_22_{p}", "date_yyyy": f"fill_23_{p}",
        "already_yes": f"cb_5_{p}", "already_no": f"cb_6_{p}",
        # Consent to act: strike the word that does not apply.
        "consent_strike_director": f"Dropdown_1_{p}",
        "consent_strike_alternate": f"Dropdown_2_{p}",
    }


MAIN_2 = _natural(PAGE_MAIN_2)
SHEET_B = _natural(PAGE_SHEET_B)


def _corporate(page: int) -> dict:
    p = f"P.{page}"
    return {
        "br_number": f"fill_1_{p}",
        "cap_secretary": f"cb_1_{p}", "cap_director": f"cb_2_{p}",
        "cap_alternate": f"cb_3_{p}", "alternate_to": f"fill_2_{p}",
        "name_zh": f"fill_3_{p}", "name_en": f"fill_4_{p}",
        "addr_flat": f"fill_5_{p}", "addr_building": f"fill_6_{p}",
        "addr_street": f"fill_7_{p}", "addr_district": f"fill_8_{p}",
        "addr_country": f"fill_9_{p}", "email": f"fill_10_{p}",
        "own_br_number": f"fill_11_{p}", "tcsp_licence": f"fill_12_{p}",
        "tcsp_not_required": f"cb_4_{p}", "tcsp_reason": f"fill_13_{p}",
        "date_dd": f"fill_14_{p}", "date_mm": f"fill_15_{p}",
        "date_yyyy": f"fill_16_{p}", "already_yes": f"cb_5_{p}",
        "already_no": f"cb_6_{p}",
        "consent_strike_director": f"Dropdown_1_{p}",
        "consent_strike_alternate": f"Dropdown_2_{p}",
        "consent_signer_name": f"fill_17_{p}",
        # "Director / Company Secretary / Authorized Person of the Director
        # (Body Corporate)": the consent signer's office, by deletion.
        "signer_strike_director": f"Dropdown_3_{p}",
        "signer_strike_secretary": f"Dropdown_4_{p}",
        "signer_strike_authorized": f"Dropdown_5_{p}",
    }


MAIN_3 = {
    **_corporate(PAGE_MAIN_3),
    "count_sheet_a": "fill_18_P.3", "count_sheet_b": "fill_19_P.3",
    "count_sheet_c": "fill_20_P.3", "count_pi": "fill_21_P.3",
    "signed_name": "fill_22_P.3", "signed_date": "fill_23_P.3",
    "signature_strike_director": "Dropdown_6_P.3",
    "signature_strike_secretary": "Dropdown_7_P.3",
}
SHEET_C = _corporate(PAGE_SHEET_C)

PI = {
    "br_number": "fill_1_P.7",
    "cap_secretary": "cb_1_P.7", "cap_director": "cb_2_P.7",
    "cap_alternate": "cb_3_P.7",
    "name_zh": "fill_2_P.7", "surname_en": "fill_3_P.7",
    "other_names_en": "fill_4_P.7", "hkid_full": "fill_5_P.7",
    "hkid_check_digit": "fill_6_P.7", "passport_country": "fill_7_P.7",
    "passport_full": "fill_8_P.7", "res_flat": "fill_9_P.7",
    "res_building": "fill_10_P.7", "res_street": "fill_11_P.7",
    "res_district": "fill_12_P.7", "res_country": "fill_13_P.7",
}

#: Every header BR number, set at 14pt and centred as on NAR1.
BR_NUMBER_FIELDS = frozenset(block["br_number"] for block in
                             (MAIN_1, MAIN_2, MAIN_3, SHEET_A, SHEET_B, SHEET_C, PI))

#: What CR centres, by NAR1's measured rule: the header box, the company name,
#: an identity or registration number or a date part in its own ruled cell, the
#: sheet counts, and the signature's name and date. Everything else is left.
CENTRED_FIELDS = frozenset(
    set(BR_NUMBER_FIELDS) | {MAIN_1["company_name"]}
    | {b[k] for b in (MAIN_1, SHEET_A) for k in
       ("hkid_partial", "date_dd", "date_mm", "date_yyyy")}
    | {b[k] for b in (MAIN_2, SHEET_B) for k in
       ("hkid_partial", "tcsp_licence", "date_dd", "date_mm", "date_yyyy")}
    | {b[k] for b in (MAIN_3, SHEET_C) for k in
       ("own_br_number", "tcsp_licence", "date_dd", "date_mm", "date_yyyy")}
    | {MAIN_3[k] for k in ("count_sheet_a", "count_sheet_b", "count_sheet_c",
                           "count_pi", "signed_name", "signed_date")}
    | {PI["hkid_full"], PI["hkid_check_digit"]}
)

#: The presenter's block is CR's administrative note, set REGULAR (NAR1 measure).
REGULAR_WEIGHT_FIELDS = frozenset(MAIN_1[k] for k in (
    "presenter_name", "presenter_address", "presenter_tel", "presenter_fax",
    "presenter_email", "presenter_reference"))

FIELD_SIZES = {**{name: 14.0 for name in BR_NUMBER_FIELDS},
               MAIN_1["company_name"]: 12.0}

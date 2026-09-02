"""Semantic names for the 365 AcroForm fields in CR's Form NAR1.

WHY THIS FILE EXISTS. `docs/NAR1_fillable.pdf` is CR's official form and every
field in it is named `fill_7_P.3` / `cb_1_P.5` — a sequence number, a page
number, and nothing else. No tooltips, no export names, no map. Filling it
without one means writing `writer.update_page_form_field_values(page,
{"fill_12_P.9": member_address})` and hoping.

WHERE THESE NAMES CAME FROM. Not guesswork and not the specimens:

  1. The widget RECTANGLES. The geometry reads straight off the printed form —
     page 1's three checkboxes sit exactly under 私人公司 / 公眾公司 /
     擔保有限公司, the DD/MM/YYYY triplets are three adjacent boxes, the
     registered office is four stacked full-width boxes.
  2. The form's OWN printed labels. Every box has its label immediately to its
     left ("英文姓名 Name in English", "姓氏 Surname"), and the label text is
     recoverable from the blank form by position.
  3. CR's specimens, as a CHECK. `NAR1(private)_Specimen-e.pdf` is flattened —
     `get_fields()` returns 0 — but its rendered text carries coordinates that
     land inside these rectangles. `tests/test_nar1_field_map.py` re-derives
     both and fails if either stops agreeing.

  A trap worth naming: the specimens also carry instructional CALLOUTS ("Please
  fill in the first 8 digits of the business registration number") positioned
  next to the boxes they describe. Those are annotations, not filled values,
  and a map built from specimen text alone would swallow them.

COMMITTED RATHER THAN DERIVED AT RUNTIME. If CR revises the form, the
regeneration shows up as a reviewable diff instead of silently shifting every
value one box to the left. `scripts/build_nar1_form_map.py` rebuilds it.

PAGE LAYOUT of the fillable (1-based, as the field names count them):

     1  s1-6   name, business name, type, nature, return date, financial
                period, registered office, presenter block
     2  s7-11  email, phone, mortgages, members (no share capital),
                share capital table
     3  s12A   company secretary — natural person
     4  s12B   company secretary — body corporate
     5  s13A   director — natural person
     6  s13B   director — body corporate  (TWO slots on this page)
     7  s13C   reserve director
     8  s14-16 members, company records, statement, sheet counts, signature
     9  Schedule 1 — non-listed members   (TWO slots)
    10  Schedule 2 — listed members       (TWO slots)
    11  Continuation Sheet A — secretary, natural person
    12  Continuation Sheet B — secretary, body corporate
    13  Continuation Sheet C — director, natural person
    14  Continuation Sheet D — director, body corporate  (TWO slots)
    15  Continuation Sheet E — company records
    16+ printed Notes for Completion — NO fields, and dropped from output
"""

#: Checkbox "on" state. Every /Btn in this form uses /On (verified across all
#: 15 field-bearing pages), so tick with this rather than the widget's own
#: state list — a mixed vocabulary would be a silent no-op on the odd box.
CHECKBOX_ON = "/On"

#: The pages that carry fields. Everything after this is CR's printed guidance.
LAST_FIELD_PAGE = 15

#: 1-based page numbers, by role.
PAGE_MAIN_1 = 1
PAGE_MAIN_2 = 2
PAGE_SECRETARY_INDIVIDUAL = 3
PAGE_SECRETARY_CORPORATE = 4
PAGE_DIRECTOR_INDIVIDUAL = 5
PAGE_DIRECTOR_CORPORATE = 6
PAGE_RESERVE_DIRECTOR = 7
PAGE_MEMBERS_AND_SIGNATURE = 8
PAGE_SCHEDULE_1 = 9
PAGE_SCHEDULE_2 = 10
PAGE_SHEET_A = 11
PAGE_SHEET_B = 12
PAGE_SHEET_C = 13
PAGE_SHEET_D = 14
PAGE_SHEET_E = 15


# ---------------------------------------------------------------------------
# Page 1 — sections 1 to 6, and the presenter block
# ---------------------------------------------------------------------------

MAIN_1 = {
    "br_number":            "fill_1_P.1",
    "company_name":         "fill_2_P.1",   # s1 — English and Chinese together
    "business_name":        "fill_3_P.1",   # s2 — "if any"

    # s3. Exactly one is ticked. CR's own order, left to right.
    "type_private":         "cb_1_P.1",
    "type_public":          "cb_2_P.1",
    "type_guarantee":       "cb_3_P.1",

    "business_nature_code": "fill_4_P.1",
    "business_nature_desc": "fill_5_P.1",

    # s4 — the return date, one digit-pair per box.
    "return_date_dd":       "fill_6_P.1",
    "return_date_mm":       "fill_7_P.1",
    "return_date_yyyy":     "fill_8_P.1",

    # s5 — financial period. "A private company needs not complete this
    # section", so these stay empty for the overwhelming majority of GSHK's
    # book. Left in the map because a public company must fill them.
    "fin_period_from_dd":   "fill_9_P.1",
    "fin_period_from_mm":   "fill_10_P.1",
    "fin_period_from_yyyy": "fill_11_P.1",
    "fin_period_to_dd":     "fill_12_P.1",
    "fin_period_to_mm":     "fill_13_P.1",
    "fin_period_to_yyyy":   "fill_14_P.1",

    # s6 — registered office. Hong Kong only; CR rejects a non-HK address, a
    # "care of" address and a PO box here.
    "ro_flat_floor_block":  "fill_15_P.1",
    "ro_building":          "fill_16_P.1",
    "ro_street":            "fill_17_P.1",
    "ro_district":          "fill_18_P.1",

    # The presenter box, bottom left. This is GSHK, not the client — it is who
    # CR contacts about the filing, and it is the one block on the form that is
    # about us rather than about the company.
    "presenter_name":       "fill_19_P.1",
    "presenter_address":    "fill_20_P.1",
    "presenter_tel":        "fill_21_P.1",
    "presenter_fax":        "fill_22_P.1",
    "presenter_email":      "fill_23_P.1",
    "presenter_reference":  "fill_24_P.1",
}


# ---------------------------------------------------------------------------
# Page 2 — sections 7 to 11
# ---------------------------------------------------------------------------

MAIN_2 = {
    "br_number":            "fill_1_P.2",   # repeated in every page header
    "email_address":        "fill_2_P.2",   # s7
    "phone":                "fill_3_P.2",   # s8 — the +852 is preprinted
    "mortgages_total":      "fill_4_P.2",   # s9 — "NIL" when not applicable
    "members_no_capital":   "fill_5_P.2",   # s10 — guarantee companies only
}

#: s11, the share capital table: four rows of five columns, then a totals row
#: with four (no class name). Row 0 is the top row.
SHARE_CAPITAL_ROWS = 4
_SHARE_CAPITAL_FIRST = 6   # fill_6_P.2 .. fill_25_P.2, five per row


def share_capital(row: int, column: str) -> str:
    """One cell of the section 11 table.

    `column` is one of: class, currency, total_number, total_amount, paid_up.
    """
    order = ("class", "currency", "total_number", "total_amount", "paid_up")
    if not 0 <= row < SHARE_CAPITAL_ROWS:
        raise IndexError(
            f"the printed share capital table has {SHARE_CAPITAL_ROWS} rows; "
            f"row {row} would have to go on a continuation sheet, and CR does "
            f"not provide one for section 11"
        )
    return f"fill_{_SHARE_CAPITAL_FIRST + row * len(order) + order.index(column)}_P.2"


#: The totals row carries no class name, so it is four fields, not five.
SHARE_CAPITAL_TOTALS = {
    "currency":     "fill_26_P.2",
    "total_number": "fill_27_P.2",
    "total_amount": "fill_28_P.2",
    "paid_up":      "fill_29_P.2",
}


# ---------------------------------------------------------------------------
# Officer blocks
#
# The same four shapes recur on the main form and again on the continuation
# sheets, with only the page number and the field offsets differing. They are
# spelled out per page rather than generated, because the offsets are NOT
# uniform: page 6 carries two director slots, the continuation sheets carry a
# return-date header the main pages do not, and a generator that assumed
# regularity would be wrong in exactly the places that matter.
# ---------------------------------------------------------------------------

#: s12A — company secretary, natural person. Hong Kong address only.
SECRETARY_INDIVIDUAL = {
    "br_number":        "fill_1_P.3",
    "name_zh":          "fill_2_P.3",
    "surname_en":       "fill_3_P.3",
    "other_names_en":   "fill_4_P.3",
    "prev_name_zh":     "fill_5_P.3",
    "prev_name_en":     "fill_6_P.3",
    "alias_zh":         "fill_7_P.3",
    "alias_en":         "fill_8_P.3",
    "addr_flat_floor":  "fill_9_P.3",
    "addr_building":    "fill_10_P.3",
    "addr_street":      "fill_11_P.3",
    "addr_district":    "fill_12_P.3",
    "email":            "fill_13_P.3",
    # "Partial number" is CR's term: the first half of the identifier, rounded
    # up on an odd length. A123456(7) -> "A123". See the form's note 18(a).
    "hkid_partial":     "fill_14_P.3",
    "passport_country": "fill_15_P.3",
    "passport_partial": "fill_16_P.3",
    "tcsp_licence":     "fill_17_P.3",
    "tcsp_not_required": "cb_1_P.3",
    "tcsp_reason":      "fill_18_P.3",
}

#: s12B — company secretary, body corporate. This is GSHK on every
#: GSHK-managed company. No identity documents; a BR number and a TCSP licence
#: instead.
SECRETARY_CORPORATE = {
    "br_number":        "fill_1_P.4",
    "name_zh":          "fill_2_P.4",
    "name_en":          "fill_3_P.4",
    "addr_flat_floor":  "fill_4_P.4",
    "addr_building":    "fill_5_P.4",
    "addr_street":      "fill_6_P.4",
    "addr_district":    "fill_7_P.4",
    "email":            "fill_8_P.4",
    "own_br_number":    "fill_9_P.4",
    "tcsp_licence":     "fill_10_P.4",
    "tcsp_not_required": "cb_1_P.4",
    "tcsp_reason":      "fill_11_P.4",
}

#: s13A — director, natural person. The address here is a CORRESPONDENCE
#: address and may be outside Hong Kong, which is why it carries country and
#: region fields the secretary block does not.
DIRECTOR_INDIVIDUAL = {
    "br_number":        "fill_1_P.5",
    "capacity_director":  "cb_1_P.5",
    "capacity_alternate": "cb_2_P.5",
    "alternate_to":     "fill_2_P.5",
    "name_zh":          "fill_3_P.5",
    "surname_en":       "fill_4_P.5",
    "other_names_en":   "fill_5_P.5",
    "prev_name_zh":     "fill_6_P.5",
    "prev_name_en":     "fill_7_P.5",
    "alias_zh":         "fill_8_P.5",
    "alias_en":         "fill_9_P.5",
    "addr_flat_floor":  "fill_10_P.5",
    "addr_building":    "fill_11_P.5",
    "addr_street":      "fill_12_P.5",
    "addr_district_city_state": "fill_13_P.5",
    "addr_country":     "fill_14_P.5",
    "email":            "fill_15_P.5",
    "hkid_partial":     "fill_16_P.5",
    "passport_country": "fill_17_P.5",
    "passport_partial": "fill_18_P.5",
}

#: s13B — director, body corporate. TWO slots on the one page; the form says
#: "Use Continuation Sheet D if more than 2 directors are body corporate".
DIRECTOR_CORPORATE_SLOTS = 2
DIRECTOR_CORPORATE = (
    {
        "capacity_director":  "cb_1_P.6",
        "capacity_alternate": "cb_2_P.6",
        "alternate_to":     "fill_2_P.6",
        "name_zh":          "fill_3_P.6",
        "name_en":          "fill_4_P.6",
        "addr_flat_floor":  "fill_5_P.6",
        "addr_building":    "fill_6_P.6",
        "addr_street":      "fill_7_P.6",
        "addr_district_city_state": "fill_8_P.6",
        "addr_country":     "fill_9_P.6",
        "email":            "fill_10_P.6",
        "own_br_number":    "fill_11_P.6",
    },
    {
        "capacity_director":  "cb_3_P.6",
        "capacity_alternate": "cb_4_P.6",
        "alternate_to":     "fill_12_P.6",
        "name_zh":          "fill_13_P.6",
        "name_en":          "fill_14_P.6",
        "addr_flat_floor":  "fill_15_P.6",
        "addr_building":    "fill_16_P.6",
        "addr_street":      "fill_17_P.6",
        "addr_district_city_state": "fill_18_P.6",
        "addr_country":     "fill_19_P.6",
        "email":            "fill_20_P.6",
        "own_br_number":    "fill_21_P.6",
    },
)
DIRECTOR_CORPORATE_HEADER = {"br_number": "fill_1_P.6"}

#: s13C — reserve director. Only ever one, and only for a private company with
#: a single member who is also its sole director.
RESERVE_DIRECTOR = {
    "br_number":        "fill_1_P.7",
    "name_zh":          "fill_2_P.7",
    "surname_en":       "fill_3_P.7",
    "other_names_en":   "fill_4_P.7",
    "prev_name_zh":     "fill_5_P.7",
    "prev_name_en":     "fill_6_P.7",
    "alias_zh":         "fill_7_P.7",
    "alias_en":         "fill_8_P.7",
    "addr_flat_floor":  "fill_9_P.7",
    "addr_building":    "fill_10_P.7",
    "addr_street":      "fill_11_P.7",
    "addr_district_city_state": "fill_12_P.7",
    "addr_country":     "fill_13_P.7",
    "email":            "fill_14_P.7",
    "hkid_partial":     "fill_15_P.7",
    "passport_country": "fill_16_P.7",
    "passport_partial": "fill_17_P.7",
}


# ---------------------------------------------------------------------------
# Page 8 — members, company records, statement, sheet counts, signature
# ---------------------------------------------------------------------------

MEMBERS_AND_SIGNATURE = {
    "br_number":              "fill_1_P.8",

    # s14 — where the member particulars are. Exactly one.
    "members_in_schedule_1":  "cb_1_P.8",
    "members_in_schedule_2":  "cb_2_P.8",
    "members_on_cdrom":       "cb_3_P.8",

    # s15 — company records, when NOT kept at the registered office.
    "records_description":    "fill_2_P.8",
    "records_address":        "fill_3_P.8",

    # s16 — the private-company statement. Ticked only for a private company,
    # and it is a STATEMENT OF FACT about not having invited public
    # subscription, so it is never ticked speculatively.
    "statement_private":      "cb_4_P.8",

    # "This Return includes the following Continuation Sheet(s)/Schedule(s)" —
    # a page count per sheet. Left blank when none.
    "count_sheet_a":          "fill_4_P.8",
    "count_sheet_b":          "fill_5_P.8",
    "count_sheet_c":          "fill_6_P.8",
    "count_sheet_d":          "fill_7_P.8",
    "count_sheet_e":          "fill_8_P.8",
    "count_schedule_1":       "fill_9_P.8",
    "count_schedule_2":       "fill_10_P.8",

    # The signature block. THESE TWO WERE THE WRONG WAY ROUND until 2026-09-02:
    # the signatory's name was written to fill_12, which is the DATE box, so
    # every rendered return showed "Get Started HK Limited" sitting above
    # "日DD / 月MM / 年YYYY" and left the "姓名 Name" line blank. The give-away
    # in the template is that fill_12 is the one field on page 8 CR sets in
    # `/TimesNewRoman 12 Tf` and quads centre in a 136pt box, while fill_11 is
    # the 231pt auto-sized rule that follows "姓名 Name :".
    "signed_name":            "fill_11_P.8",
    "signed_date":            "fill_12_P.8",
}

#: The printed line reads "董事 Director／公司秘書 Company Secretary *" with
#: "*請刪去不適用者 Delete whichever does not apply" beneath it. CR implements
#: the deletion as two dropdowns whose only non-blank option is a long rule —
#: selecting it strikes the word through. So the capacity is expressed by
#: striking out the one that does NOT apply, which is the opposite of what a
#: reader expects and is why this is spelled out here.
STRIKE_THROUGH = "—————————————————————————————————————————————————————————————————————————————————————————————"
SIGNATURE_STRIKE = {
    "strike_director":          "Dropdown_1_P.8",
    "strike_company_secretary": "Dropdown_2_P.8",
}


# ---------------------------------------------------------------------------
# Schedules 1 and 2 — member particulars
#
# Two member slots per page. Beyond that the form says to add another copy of
# the schedule, which is what the filler's overflow does.
# ---------------------------------------------------------------------------

SCHEDULE_SLOTS = 2

SCHEDULE_1_HEADER = {
    "return_date_dd":   "fill_1_P.9",
    "return_date_mm":   "fill_2_P.9",
    "return_date_yyyy": "fill_3_P.9",
    "br_number":        "fill_4_P.9",
    "share_class":      "fill_5_P.9",
    # "This number must agree with the total number of issued shares of all the
    # classes stated in Section 11" — the form's own note 33(a).
    "class_total_issued": "fill_6_P.9",
}

#: THE NUMBERING IS NOT IN READING ORDER. `shares_held` is `fill_16` in the
#: first slot and `fill_27` in the second — the right-hand column was numbered
#: after the rest of the page, so a map that walked `/Annots` in order and
#: assumed the suffixes followed would put the share count in the address.
#: Every entry here is assigned from a MEASURED widget rectangle cross-checked
#: against the form's printed label; `tests/test_nar1_field_map.py` re-derives
#: both. The first draft of this file did assume regularity, and those tests
#: are what caught it.
SCHEDULE_1 = (
    {
        "name_zh":        "fill_7_P.9",
        "shares_held":    "fill_16_P.9",
        "surname_en":     "fill_8_P.9",
        "other_names_en": "fill_9_P.9",
        "jointly_held":   "cb_1_P.9",
        "name_en_corp":   "fill_10_P.9",
        "addr_flat_floor": "fill_11_P.9",
        "addr_building":  "fill_12_P.9",
        "addr_street":    "fill_13_P.9",
        "addr_city":      "fill_14_P.9",
        "addr_country":   "fill_15_P.9",
        "remarks":        "fill_17_P.9",
    },
    {
        "name_zh":        "fill_18_P.9",
        "shares_held":    "fill_27_P.9",
        "surname_en":     "fill_19_P.9",
        "other_names_en": "fill_20_P.9",
        "jointly_held":   "cb_2_P.9",
        "name_en_corp":   "fill_21_P.9",
        "addr_flat_floor": "fill_22_P.9",
        "addr_building":  "fill_23_P.9",
        "addr_street":    "fill_24_P.9",
        "addr_city":      "fill_25_P.9",
        "addr_country":   "fill_26_P.9",
        "remarks":        "fill_28_P.9",
    },
)

#: Bottom of every schedule page: "第 __ 頁，共 __ 頁  Page __ of __".
SCHEDULE_1_PAGING = {"page_no": "fill_29_P.9", "page_of": "fill_30_P.9"}

SCHEDULE_2_HEADER = {
    "return_date_dd":   "fill_1_P.10",
    "return_date_mm":   "fill_2_P.10",
    "return_date_yyyy": "fill_3_P.10",
    "br_number":        "fill_4_P.10",
    "share_class":      "fill_5_P.10",
    "class_total_issued": "fill_6_P.10",
}

#: Schedule 2 carries one column Schedule 1 does not: the percentage of the
#: class held. A listed company reports only members holding >= 5%.
#:
#: Same numbering irregularity as Schedule 1 — `shares_held` and `percentage`
#: are the late-numbered right-hand column (fill_16/fill_17, then
#: fill_28/fill_29), not the next suffix in sequence.
SCHEDULE_2 = (
    {
        "name_zh":        "fill_7_P.10",
        "shares_held":    "fill_16_P.10",
        "surname_en":     "fill_8_P.10",
        "other_names_en": "fill_9_P.10",
        "name_en_corp":   "fill_10_P.10",
        "percentage":     "fill_17_P.10",
        "jointly_held":   "cb_1_P.10",
        "addr_flat_floor": "fill_11_P.10",
        "addr_building":  "fill_12_P.10",
        "addr_street":    "fill_13_P.10",
        "addr_city":      "fill_14_P.10",
        "addr_country":   "fill_15_P.10",
        "remarks":        "fill_18_P.10",
    },
    {
        "name_zh":        "fill_19_P.10",
        "shares_held":    "fill_28_P.10",
        "surname_en":     "fill_20_P.10",
        "other_names_en": "fill_21_P.10",
        "name_en_corp":   "fill_22_P.10",
        "percentage":     "fill_29_P.10",
        "jointly_held":   "cb_2_P.10",
        "addr_flat_floor": "fill_23_P.10",
        "addr_building":  "fill_24_P.10",
        "addr_street":    "fill_25_P.10",
        "addr_city":      "fill_26_P.10",
        "addr_country":   "fill_27_P.10",
        "remarks":        "fill_30_P.10",
    },
)

SCHEDULE_2_PAGING = {"page_no": "fill_31_P.10", "page_of": "fill_32_P.10"}


# ---------------------------------------------------------------------------
# Continuation sheets
#
# Each repeats the return date and BR number in its own header, so a sheet
# separated from the form still identifies its company.
# ---------------------------------------------------------------------------

#: The continuation sheets DO run dd/mm/yyyy/br in annot order — unlike the
#: schedules, whose header starts with the BR number. Measured, not assumed.
_SHEET_HEADER = {
    "return_date_dd":   "fill_1_P.{p}",
    "return_date_mm":   "fill_2_P.{p}",
    "return_date_yyyy": "fill_3_P.{p}",
    "br_number":        "fill_4_P.{p}",
}


def sheet_header(page: int) -> dict:
    return {k: v.format(p=page) for k, v in _SHEET_HEADER.items()}


#: Sheet A — secretary, natural person. Same shape as s12A, offset by the
#: four header fields.
SHEET_A = {
    "name_zh":          "fill_5_P.11",
    "surname_en":       "fill_6_P.11",
    "other_names_en":   "fill_7_P.11",
    "prev_name_zh":     "fill_8_P.11",
    "prev_name_en":     "fill_9_P.11",
    "alias_zh":         "fill_10_P.11",
    "alias_en":         "fill_11_P.11",
    "addr_flat_floor":  "fill_12_P.11",
    "addr_building":    "fill_13_P.11",
    "addr_street":      "fill_14_P.11",
    "addr_district":    "fill_15_P.11",
    "email":            "fill_16_P.11",
    "hkid_partial":     "fill_17_P.11",
    "passport_country": "fill_18_P.11",
    "passport_partial": "fill_19_P.11",
    "tcsp_licence":     "fill_20_P.11",
    "tcsp_not_required": "cb_1_P.11",
    "tcsp_reason":      "fill_21_P.11",
}

#: Sheet B — secretary, body corporate.
SHEET_B = {
    "name_zh":          "fill_5_P.12",
    "name_en":          "fill_6_P.12",
    "addr_flat_floor":  "fill_7_P.12",
    "addr_building":    "fill_8_P.12",
    "addr_street":      "fill_9_P.12",
    "addr_district":    "fill_10_P.12",
    "email":            "fill_11_P.12",
    "own_br_number":    "fill_12_P.12",
    "tcsp_licence":     "fill_13_P.12",
    "tcsp_not_required": "cb_1_P.12",
    "tcsp_reason":      "fill_14_P.12",
}

#: Sheet C — director, natural person.
SHEET_C = {
    "capacity_director":  "cb_1_P.13",
    "capacity_alternate": "cb_2_P.13",
    "alternate_to":     "fill_5_P.13",
    "name_zh":          "fill_6_P.13",
    "surname_en":       "fill_7_P.13",
    "other_names_en":   "fill_8_P.13",
    "prev_name_zh":     "fill_9_P.13",
    "prev_name_en":     "fill_10_P.13",
    "alias_zh":         "fill_11_P.13",
    "alias_en":         "fill_12_P.13",
    "addr_flat_floor":  "fill_13_P.13",
    "addr_building":    "fill_14_P.13",
    "addr_street":      "fill_15_P.13",
    "addr_district_city_state": "fill_16_P.13",
    "addr_country":     "fill_17_P.13",
    "email":            "fill_18_P.13",
    "hkid_partial":     "fill_19_P.13",
    "passport_country": "fill_20_P.13",
    "passport_partial": "fill_21_P.13",
}

#: Sheet D — director, body corporate. Two slots, like page 6.
SHEET_D_SLOTS = 2
SHEET_D = (
    {
        "capacity_director":  "cb_1_P.14",
        "capacity_alternate": "cb_2_P.14",
        "alternate_to":     "fill_5_P.14",
        "name_zh":          "fill_6_P.14",
        "name_en":          "fill_7_P.14",
        "addr_flat_floor":  "fill_8_P.14",
        "addr_building":    "fill_9_P.14",
        "addr_street":      "fill_10_P.14",
        "addr_district_city_state": "fill_11_P.14",
        "addr_country":     "fill_12_P.14",
        "email":            "fill_13_P.14",
        "own_br_number":    "fill_14_P.14",
    },
    {
        "capacity_director":  "cb_3_P.14",
        "capacity_alternate": "cb_4_P.14",
        "alternate_to":     "fill_15_P.14",
        "name_zh":          "fill_16_P.14",
        "name_en":          "fill_17_P.14",
        "addr_flat_floor":  "fill_18_P.14",
        "addr_building":    "fill_19_P.14",
        "addr_street":      "fill_20_P.14",
        "addr_district_city_state": "fill_21_P.14",
        "addr_country":     "fill_22_P.14",
        "email":            "fill_23_P.14",
        "own_br_number":    "fill_24_P.14",
    },
)

#: Sheet E — company records kept away from the registered office.
SHEET_E_ROWS = 1
SHEET_E = {
    "records_description": "fill_5_P.15",
    "records_address":     "fill_6_P.15",
}

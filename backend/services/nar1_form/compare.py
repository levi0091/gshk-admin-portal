"""What moved between the return the client approved and the one CR validated.

Levi 2026-09-18: "In the stage 2 pdf viewer I need you to highlight the fields
that are different between stage 1 and stage 2. you should also list the fields
and what was changed in a warning message."

WHY THERE ARE TWO DOCUMENTS AT ALL. Client Verification is the first stage
(migration 046): the client approves the return built from the company record,
mailed as CR's Form NAR1 and kept verbatim in `nar1_cases.verification_xml`.
CR sees it only afterwards, at Data Verification, and what it validates can
differ — the operator fixed the record after a rejection, or CR wrote in fields
of its own (the made-up date, the business-nature description). The approval
deliberately stands through that (Levi 2026-09-17), so the reviewer needs to
see, on the form itself, where the filed return has moved away from the one a
director said yes to.

THE DIFF IS TAKEN ON THE PRINTED FORM, BOX BY BOX — not on the XML. Both
documents go through the renderer's own composer (`fill._composed`), and what
is compared is the text each box would print. That makes three things true by
construction rather than by care:

  * every highlight is exactly one listed change, and every listed change is a
    box the reader can find — there is no XML field that "changed" without a
    visible trace, and no box that lights up without a line explaining it;
  * a change CR made by filling a field the request did not carry (it writes
    `natureDesc` and `dateReturnMadeUp` itself) is reported when, and only
    when, it changes what is printed. The made-up date is derived on the
    client's copy from the same anniversary rule CR uses, so it normally
    matches and is silent;
  * values are compared as the reader sees them — "1,000.00", "N/A", the
    partial passport number — so a formatting-only difference in the XML that
    prints identically is not a change to anyone looking at the form.

`drift.compare` is the other diff in this codebase and asks a different
question (does a stored snapshot still match a fresh build from the live
record, element for element) for a gate that refuses. This one warns.

IGNORED: the signature DATE, and nothing else. The client's copy is dated the
day it was mailed and the validated copy the day it is shown or signed; they
differ by construction and neither is a particular of the company.

PAGES ARE MATCHED BY TEMPLATE PAGE AND OCCURRENCE — the second Continuation
Sheet C in one document against the second in the other — not by position, so
a return that gained a sheet compares everything before it correctly. A page in
only one of the two reports every value on it as added or removed. Removed
values have no box in the validated document to highlight; they are listed
with no page.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.nar1_form import field_map as fm
from services.nar1_form import fill

# ---------------------------------------------------------------------------
# Where each box is: widget name -> (block, slot, key)
# ---------------------------------------------------------------------------

_PAGE_OF = re.compile(r"_P\.(\d+)$")

_SHARE_COLUMNS = ("class", "currency", "total_number", "total_amount", "paid_up")


def _build_index() -> dict:
    index: dict[str, tuple] = {}

    def add(block, mapping, slot=None):
        for key, widget in mapping.items():
            index[widget] = (block, slot, key)

    add("company", fm.MAIN_1)
    add("company", fm.MAIN_2)
    for row in range(fm.SHARE_CAPITAL_ROWS):
        for column in _SHARE_COLUMNS:
            index[fm.share_capital(row, column)] = ("share_capital", row, column)
    add("share_capital_total", fm.SHARE_CAPITAL_TOTALS)
    add("secretary_individual", fm.SECRETARY_INDIVIDUAL)
    add("secretary_corporate", fm.SECRETARY_CORPORATE)
    add("director_individual", fm.DIRECTOR_INDIVIDUAL)
    add("director_corporate", fm.DIRECTOR_CORPORATE_HEADER)
    for slot, mapping in enumerate(fm.DIRECTOR_CORPORATE):
        add("director_corporate", mapping, slot)
    add("reserve_director", fm.RESERVE_DIRECTOR)
    add("signature", fm.MEMBERS_AND_SIGNATURE)
    add("signature", fm.SIGNATURE_STRIKE)
    for header in (fm.SCHEDULE_1_HEADER, fm.SCHEDULE_2_HEADER,
                   fm.SCHEDULE_1_PAGING, fm.SCHEDULE_2_PAGING):
        add("schedule", header)
    for slots in (fm.SCHEDULE_1, fm.SCHEDULE_2):
        for slot, mapping in enumerate(slots):
            add("member", mapping, slot)
    for page in (fm.PAGE_SHEET_A, fm.PAGE_SHEET_B, fm.PAGE_SHEET_C,
                 fm.PAGE_SHEET_D, fm.PAGE_SHEET_E):
        add("sheet", fm.sheet_header(page))
    add("secretary_individual", fm.SHEET_A)
    add("secretary_corporate", fm.SHEET_B)
    add("director_individual", fm.SHEET_C)
    for slot, mapping in enumerate(fm.SHEET_D):
        add("director_corporate", mapping, slot)
    add("records", fm.SHEET_E)
    return index


INDEX = _build_index()

#: (template page, block, slot, key) -> widget. The reverse of INDEX, so a
#: changed key can be turned back into the box to highlight on that page.
_WIDGET = {
    (int(_PAGE_OF.search(widget).group(1)), block, slot, key): widget
    for widget, (block, slot, key) in INDEX.items()
    if _PAGE_OF.search(widget)
}

#: Boxes left out of the comparison. See the module docstring.
IGNORED = frozenset({("signature", "signed_date")})

# ---------------------------------------------------------------------------
# Several boxes, one fact
# ---------------------------------------------------------------------------

#: A date is three boxes. Reported once, as the date, not as "month changed".
_DATE_GROUPS = {
    "return_date": ("return_date_dd", "return_date_mm", "return_date_yyyy"),
    "fin_period_from": ("fin_period_from_dd", "fin_period_from_mm",
                        "fin_period_from_yyyy"),
    "fin_period_to": ("fin_period_to_dd", "fin_period_to_mm",
                      "fin_period_to_yyyy"),
}

#: Tick-one-of groups, reported as the option that is ticked.
_CHOICE_GROUPS = {
    "company_type": (("type_private", "Private"), ("type_public", "Public"),
                     ("type_guarantee", "Guarantee")),
    "capacity": (("capacity_director", "Director"),
                 ("capacity_alternate", "Alternate director")),
    "members_listed": (("members_in_schedule_1", "Schedule 1"),
                       ("members_in_schedule_2", "Schedule 2"),
                       ("members_on_cdrom", "CD-ROM")),
    "capacity_struck": (("strike_director", "Director"),
                        ("strike_company_secretary", "Company Secretary")),
}

#: Single boxes whose only content is a tick.
_TICKS = frozenset({"jointly_held", "tcsp_not_required", "statement_private"})

_GROUP_OF: dict[str, str] = {}
for _group, _keys in _DATE_GROUPS.items():
    for _key in _keys:
        _GROUP_OF[_key] = _group
for _group, _options in _CHOICE_GROUPS.items():
    for _key, _label in _options:
        _GROUP_OF[_key] = _group

# ---------------------------------------------------------------------------
# Words for the reader
# ---------------------------------------------------------------------------

_SECTIONS = {
    "company": "Company particulars",
    "share_capital": "Share capital",
    "share_capital_total": "Share capital — total",
    "secretary_individual": "Company secretary",
    "secretary_corporate": "Company secretary (body corporate)",
    "director_individual": "Director",
    "director_corporate": "Director (body corporate)",
    "reserve_director": "Reserve director",
    "signature": "Members, records and signature",
    "schedule": "Schedule of members",
    "member": "Member",
    "sheet": "Continuation sheet",
    "records": "Company records",
}

#: Keys that repeat in the header of page after page. A change to one of
#: these is reported ONCE, under the company, with every page it is on — not
#: once per page.
_HEADER_KEYS = frozenset({"br_number", "return_date"})

_LABELS = {
    # groups
    "return_date": "Date to which this return is made up",
    "fin_period_from": "Financial statements — period from",
    "fin_period_to": "Financial statements — period to",
    "company_type": "Type of company",
    "capacity": "Capacity",
    "members_listed": "Members listed on",
    "capacity_struck": "Capacity struck out on the signature line",
    # company
    "br_number": "Business Registration number",
    "company_name": "Company name",
    "business_name": "Business name",
    "business_nature_code": "Business nature code",
    "business_nature_desc": "Business nature",
    "ro_flat_floor_block": "Registered office — flat / floor / block",
    "ro_building": "Registered office — building",
    "ro_street": "Registered office — street",
    "ro_district": "Registered office — district",
    "presenter_name": "Presenter's name",
    "presenter_address": "Presenter's address",
    "presenter_tel": "Presenter's telephone",
    "presenter_fax": "Presenter's fax",
    "presenter_email": "Presenter's email",
    "presenter_reference": "Presenter's reference",
    "email_address": "Company email address",
    "phone": "Company telephone",
    "mortgages_total": "Mortgages and charges outstanding",
    "members_no_capital": "Members (company without share capital)",
    # share capital
    "class": "Class of shares",
    "currency": "Currency",
    "total_number": "Total number issued",
    "total_amount": "Total amount issued",
    "paid_up": "Total amount paid up",
    # officers and members
    "name_zh": "Name (Chinese)",
    "name_en": "Name (English)",
    "name_en_corp": "Name (body corporate)",
    "surname_en": "Surname",
    "other_names_en": "Other names",
    "prev_name_zh": "Previous name (Chinese)",
    "prev_name_en": "Previous name (English)",
    "alias_zh": "Alias (Chinese)",
    "alias_en": "Alias (English)",
    "alternate_to": "Alternate to",
    "addr_flat_floor": "Address — flat / floor / block",
    "addr_building": "Address — building",
    "addr_street": "Address — street",
    "addr_district": "Address — district",
    "addr_district_city_state": "Address — district / city / state",
    "addr_city": "Address — city / state",
    "addr_country": "Address — country / region",
    "email": "Email address",
    "hkid_partial": "HKID number (partial)",
    "passport_country": "Passport issuing country",
    "passport_partial": "Passport number (partial)",
    "own_br_number": "Business Registration number",
    "tcsp_licence": "TCSP licence number",
    "tcsp_not_required": "TCSP licence not required",
    "tcsp_reason": "Reason no TCSP licence is required",
    "shares_held": "Shares held",
    "percentage": "Percentage of the class",
    "jointly_held": "Held jointly",
    "remarks": "Remarks",
    # schedule header and paging
    "share_class": "Class of shares",
    "class_total_issued": "Total issued in this class",
    "page_no": "Schedule page number",
    "page_of": "Schedule pages in total",
    # page 8
    "records_description": "Company records kept elsewhere — description",
    "records_address": "Company records kept elsewhere — address",
    "statement_private": "Private company statement",
    "count_sheet_a": "Continuation Sheet A — pages attached",
    "count_sheet_b": "Continuation Sheet B — pages attached",
    "count_sheet_c": "Continuation Sheet C — pages attached",
    "count_sheet_d": "Continuation Sheet D — pages attached",
    "count_sheet_e": "Continuation Sheet E — pages attached",
    "count_schedule_1": "Schedule 1 — pages attached",
    "count_schedule_2": "Schedule 2 — pages attached",
    "signed_name": "Signatory's name",
    "signed_date": "Date signed",
}

#: Boxes CR writes itself when it validates, which the client's copy — built
#: before CR had seen the return — could only derive or leave blank.
_CR_FILLED = frozenset({"return_date", "business_nature_desc"})

_CR_FILLED_NOTE = ("Filled in by the Companies Registry when it validated the "
                   "return; the client's copy was prepared before CR had seen "
                   "it.")


@dataclass
class Comparison:
    """The warning list, and the boxes to mark on the validated document.

    `changes`   — one entry per changed fact, in page order, each
                  {pages, section, field, approved, validated, note}. `pages`
                  are 1-based pages of the VALIDATED document; empty when the
                  value was removed and has no box left there.
    `highlight` — (page index, field name) pairs for `fill.render(highlight=)`.
    """
    changes: list = field(default_factory=list)
    highlight: frozenset = frozenset()


def _shown(value) -> str:
    """What the box prints, as the reader would compare it."""
    if value is None:
        return ""
    return str(value).strip()


def _display(group: str, values: dict) -> str:
    """One fact's printed value — a date read as a date, a tick as an answer."""
    if group in _DATE_GROUPS:
        parts = [_shown(values.get(k)) for k in _DATE_GROUPS[group]]
        return "/".join(p for p in parts if p)
    if group in _CHOICE_GROUPS:
        return ", ".join(label for key, label in _CHOICE_GROUPS[group]
                         if _shown(values.get(key)))
    if group in _TICKS:
        return "Ticked" if _shown(values.get(group)) else ""
    return _shown(values.get(group))


#: What the renderer prints in a box that has nothing in it. Not a name.
_PLACEHOLDERS = frozenset({fill.NONE_GIVEN, fill.NOT_APPLICABLE})


def _who(block: str, values: dict) -> str | None:
    """The person, company or share class a slot is about, for the section."""
    def name(key):
        text = _shown(values.get(key))
        return "" if text in _PLACEHOLDERS else text

    if block == "share_capital":
        return name("class") or None
    if block not in ("secretary_individual", "secretary_corporate",
                     "director_individual", "director_corporate",
                     "reserve_director", "member"):
        return None
    person = " ".join(n for n in (name("surname_en"), name("other_names_en")) if n)
    return (person or name("name_en") or name("name_en_corp")
            or name("name_zh") or None)


def _structure(pages) -> dict:
    """{(template page, occurrence): (page index, {(block, slot): {key: value}})}"""
    out: dict = {}
    seen: dict[int, int] = {}
    for page_index, (template_page, values) in enumerate(pages.items):
        occurrence = seen.get(template_page, 0)
        seen[template_page] = occurrence + 1
        slots: dict = {}
        for widget, value in values.items():
            block, slot, key = INDEX.get(widget, ("other", None, widget))
            slots.setdefault((block, slot), {})[key] = value
        out[(template_page, occurrence)] = (page_index, slots)
    return out


def compare_pages(approved_pages, validated_pages) -> Comparison:
    """The comparison of two composed documents (`fill._Pages`)."""
    approved = _structure(approved_pages)
    validated = _structure(validated_pages)

    rows: list[dict] = []
    highlight: set = set()
    for page_key in sorted(set(approved) | set(validated)):
        template_page = page_key[0]
        _, before_slots = approved.get(page_key, (None, {}))
        page_index, after_slots = validated.get(page_key, (None, {}))

        for block, slot in sorted(set(before_slots) | set(after_slots),
                                  key=lambda bs: (bs[0], -1 if bs[1] is None else bs[1])):
            before = before_slots.get((block, slot), {})
            after = after_slots.get((block, slot), {})

            groups: dict[str, list] = {}
            for key in set(before) | set(after):
                if (block, key) in IGNORED:
                    continue
                groups.setdefault(_GROUP_OF.get(key, key), []).append(key)

            for group, keys in groups.items():
                changed = [k for k in keys
                           if _shown(before.get(k)) != _shown(after.get(k))]
                if not changed:
                    continue
                old, new = _display(group, before), _display(group, after)
                if old == new:
                    continue
                if page_index is not None:
                    for key in changed:
                        widget = _WIDGET.get((template_page, block, slot, key))
                        if widget:
                            highlight.add((page_index, widget))

                if group in _HEADER_KEYS:
                    # The same fact wherever it is printed — section 4 on page
                    # 1, the header of every schedule and sheet — so one
                    # section for all of them, and `_merge` folds them together.
                    section = _SECTIONS["company"]
                else:
                    section = _SECTIONS.get(block, "Other")
                    who = _who(block, after) or _who(block, before)
                    if who:
                        section = f"{section} — {who}"
                rows.append({
                    "page": page_index + 1 if page_index is not None else None,
                    "section": section,
                    "field": _LABELS.get(group, group),
                    "approved": old or None,
                    "validated": new or None,
                    "note": _CR_FILLED_NOTE if group in _CR_FILLED else None,
                })

    return Comparison(changes=_merge(rows), highlight=frozenset(highlight))


def _merge(rows: list[dict]) -> list[dict]:
    """One entry per fact, carrying every page it appears on.

    The BR number and the made-up date are printed in the header of most pages;
    a change to either is one change, and nine identical lines would bury the
    rest of the list.
    """
    merged: dict[tuple, dict] = {}
    for row in rows:
        key = (row["section"], row["field"], row["approved"], row["validated"])
        entry = merged.get(key)
        if entry is None:
            entry = {k: v for k, v in row.items() if k != "page"}
            entry["pages"] = []
            merged[key] = entry
        if row["page"] is not None and row["page"] not in entry["pages"]:
            entry["pages"].append(row["page"])
    out = list(merged.values())
    for entry in out:
        entry["pages"].sort()
    out.sort(key=lambda e: (e["pages"][0] if e["pages"] else 10_000))
    return out


def compare(approved_xml: str, validated_xml: str, *,
            company_type: str = "private", incorporated_on=None,
            presenter: dict | None = None) -> Comparison:
    """Compare the approved return with the validated one, as printed.

    Both are composed exactly as `fill.render` composes them — the same company
    type, the same incorporation date for the derived made-up date, the same
    presenter — so a difference here is a difference between the two PDFs.
    Raises what `fill.render` raises for a document that cannot be laid out.
    """
    kwargs = dict(company_type=company_type, presenter=presenter,
                  signed_on="", incorporated_on=incorporated_on)
    return compare_pages(fill._composed(approved_xml, **kwargs),
                         fill._composed(validated_xml, **kwargs))

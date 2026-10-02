"""CR's Form ND2B, composed from the form model and filled onto CR's template.

Spec §7. Output, in CR's order: pages 1-3 always; one Continuation Sheet A per
natural person after the first; one Sheet B per body corporate after the first;
then one PI-ND2B per natural person whose identity number or residential
address changed ("Please place all PI-ND2B sheets at the end").

Part A prints the officer AS REGISTERED (the form model carries what CR holds,
`nd2b_mapper` having taken it from the baseline); Part B prints only the items
that changed — "Please complete item(s) with change(s) only" — so an unchanged
item's boxes stay empty rather than dashed.
"""
from __future__ import annotations

from datetime import datetime

from services.officer_change_form import kit
from services.officer_change_form import nd2b_map as m
from services.officer_change_form.nd2a import (
    _HKT, _ON, _capacity, _dash, _get, _node, _partial_hkid, _partial_passport, address,
    beans,
)
from services.tpsi.forms.cr_vocabularies import display_country

TEMPLATE = kit.FORM_DIR / "ND2B_fillable.pdf"
_DASH = kit.NONE_GIVEN


def _dated(block: dict, prefix: str, value: str) -> dict:
    dd, mm, yyyy = kit.split_date(value or "")
    return {block[f"{prefix}_dd"]: dd, block[f"{prefix}_mm"]: mm,
            block[f"{prefix}_yyyy"]: yyyy}


def part_a(block: dict, bean: dict) -> dict:
    values = {**_capacity(block, _get(bean, "cpty")),
              block["name_zh"]: _get(bean, "indvChiName"),
              block["surname_en"]: _get(bean, "indvEngSname"),
              block["other_names_en"]: _get(bean, "indvEngOname"),
              block["hkid_partial"]: _get(bean, "indvHkidPartial"),
              block["passport_partial"]: _get(bean, "indvPptNoPartial")}
    _dash(values, block, ("name_zh", "hkid_partial", "passport_partial"))
    return values


def part_b(block: dict, bean: dict) -> dict:
    values: dict = {}
    if _get(bean, "indvNewChiNameEffDt"):
        values[block["new_name_zh"]] = _get(bean, "indvNewChiName") or _DASH
        values.update(_dated(block, "name_zh_date", _get(bean, "indvNewChiNameEffDt")))
    if _get(bean, "indvNewEngNameEffDt"):
        values[block["new_surname_en"]] = _get(bean, "indvNewEngSname")
        values[block["new_other_names_en"]] = _get(bean, "indvNewEngOname")
        values.update(_dated(block, "name_en_date", _get(bean, "indvNewEngNameEffDt")))
    if _get(bean, "indvNewAlsNameEffDt"):
        values[block["new_alias_zh"]] = _get(bean, "indvNewAlsChiName") or _DASH
        values[block["new_alias_en"]] = _get(bean, "indvNewAlsEngName") or _DASH
        values.update(_dated(block, "alias_date", _get(bean, "indvNewAlsNameEffDt")))
    if _get(bean, "indvNewResAddrEffDt"):
        values.update(_dated(block, "res_date", _get(bean, "indvNewResAddrEffDt")))
    if _get(bean, "indvNewAddrEffDt"):
        corr = address(_node(bean, "indvNewAddr"))
        values.update({block["corr_flat"]: corr["flat"] or _DASH,
                       block["corr_building"]: corr["building"] or _DASH,
                       block["corr_street"]: corr["street"],
                       block["corr_district"]: corr["district"],
                       block["corr_country"]: corr["country"]})
        values.update(_dated(block, "corr_date", _get(bean, "indvNewAddrEffDt")))
    if _get(bean, "indvNewEmailAddrEffDt"):
        values[block["new_email"]] = _get(bean, "indvNewEmailAddr") or _DASH
        values.update(_dated(block, "email_date", _get(bean, "indvNewEmailAddrEffDt")))
    if _get(bean, "indvNewHkidNoEffDt"):
        values[block["new_hkid_partial"]] = _partial_hkid(_get(bean, "indvNewHkidNo")) or _DASH
        values.update(_dated(block, "hkid_date", _get(bean, "indvNewHkidNoEffDt")))
    if _get(bean, "indvNewPptNoEffDt"):
        country = _get(bean, "indvNewPptIssCtry")
        values[block["new_passport_country"]] = display_country(country) if country else _DASH
        values[block["new_passport_partial"]] = (_partial_passport(_get(bean, "indvNewPptNo"))
                                                 or _DASH)
        values.update(_dated(block, "passport_date", _get(bean, "indvNewPptNoEffDt")))
    if _get(bean, "indvNewTcspNoEffDt"):
        values[block["new_tcsp_licence"]] = _get(bean, "indvNewTcspNo")
        if _get(bean, "indvNewTcspLicNotReq").upper() == "Y":
            values[block["new_tcsp_not_required"]] = _ON
            values[block["new_tcsp_reason"]] = _get(bean, "indvNewTcspLicNotReqRsn")
        values.update(_dated(block, "tcsp_date", _get(bean, "indvNewTcspNoEffDt")))
    return values


def corporate_values(block: dict, bean: dict) -> dict:
    values = {**_capacity(block, _get(bean, "cpty")),
              block["name_zh"]: _get(bean, "corpChiName"),
              block["name_en"]: _get(bean, "corpEngName"),
              block["own_br_number"]: _get(bean, "corpBrNo")}
    _dash(values, block, ("name_zh",))
    if _get(bean, "corpNewNameEffDt"):
        values[block["new_name_zh"]] = _get(bean, "corpNewChiName") or _DASH
        values[block["new_name_en"]] = _get(bean, "corpNewEngName")
        values.update(_dated(block, "name_date", _get(bean, "corpNewNameEffDt")))
    if _get(bean, "corpNewAddrEffDt"):
        office = address(_node(bean, "corpNewAddr"))
        values.update({block["addr_flat"]: office["flat"] or _DASH,
                       block["addr_building"]: office["building"] or _DASH,
                       block["addr_street"]: office["street"],
                       block["addr_district"]: office["district"],
                       block["addr_country"]: office["country"]})
        values.update(_dated(block, "addr_date", _get(bean, "corpNewAddrEffDt")))
    if _get(bean, "corpNewEmailAddrEffDt"):
        values[block["new_email"]] = _get(bean, "corpNewEmailAddr") or _DASH
        values.update(_dated(block, "email_date", _get(bean, "corpNewEmailAddrEffDt")))
    if _get(bean, "corpNewTcspNoEffDt"):
        values[block["new_tcsp_licence"]] = _get(bean, "corpNewTcspNo")
        if _get(bean, "corpNewTcspLicNotReq").upper() == "Y":
            values[block["new_tcsp_not_required"]] = _ON
            values[block["new_tcsp_reason"]] = _get(bean, "corpNewTcspLicNotReqRsn")
        values.update(_dated(block, "tcsp_date", _get(bean, "corpNewTcspNoEffDt")))
    return values


def needs_pi(bean: dict) -> bool:
    return any(_get(bean, k) for k in ("indvNewHkidNoEffDt", "indvNewPptNoEffDt",
                                       "indvNewResAddrEffDt"))


def pi_values(br: str, bean: dict) -> dict:
    values = {m.PI["br_number"]: br, **_capacity(m.PI, _get(bean, "cpty")),
              m.PI["name_zh"]: _get(bean, "indvChiName") or _DASH,
              m.PI["surname_en"]: _get(bean, "indvEngSname"),
              m.PI["other_names_en"]: _get(bean, "indvEngOname")}
    if _get(bean, "indvNewHkidNoEffDt"):
        number = "".join(c for c in _get(bean, "indvNewHkidNo") if c.isalnum()).upper()
        values[m.PI["hkid_full"]] = _DASH if number in ("", "NIL") else number
        if number not in ("", "NIL"):
            values[m.PI["hkid_check_digit"]] = _get(bean, "indvNewHkidChkDgt")
    if _get(bean, "indvNewPptNoEffDt"):
        country = _get(bean, "indvNewPptIssCtry")
        values[m.PI["passport_country"]] = display_country(country) if country else _DASH
        values[m.PI["passport_full"]] = _get(bean, "indvNewPptNo") or _DASH
    if _get(bean, "indvNewResAddrEffDt"):
        home = address(_node(bean, "indvNewResAddr"))
        values.update({m.PI["res_flat"]: home["flat"] or _DASH,
                       m.PI["res_building"]: home["building"] or _DASH,
                       m.PI["res_street"]: home["street"],
                       m.PI["res_district"]: home["district"],
                       m.PI["res_country"]: home["country"]})
    return values


_DATE_FIELDS = ("indvNewChiNameEffDt", "indvNewEngNameEffDt", "indvNewAlsNameEffDt",
                "indvNewAddrEffDt", "indvNewEmailAddrEffDt", "indvNewHkidNoEffDt",
                "indvNewPptNoEffDt", "indvNewTcspNoEffDt", "indvNewResAddrEffDt",
                "corpNewNameEffDt", "corpNewAddrEffDt", "corpNewEmailAddrEffDt",
                "corpNewTcspNoEffDt")


def _year(natural, corporate) -> str:
    years = sorted(kit.split_date(_get(b, k))[2] for b in natural + corporate
                   for k in _DATE_FIELDS if kit.split_date(_get(b, k))[2])
    return years[0] if years else str(datetime.now(_HKT).year)


def compose(model: dict, *, company_name: str, submitted_on, presenter: dict | None,
            public_only: bool, strike: str) -> list[tuple[int, dict, str]]:
    br = _get(model, "brNo")
    natural = beans(model, "npBeans", "npBean")
    corporate = beans(model, "bcBeans", "bcBean")
    presenter = presenter or kit.DEFAULT_PRESENTER

    page1 = {m.MAIN_1["br_number"]: br, m.MAIN_1["company_name"]: company_name,
             m.MAIN_1["presenter_name"]: presenter.get("name", ""),
             m.MAIN_1["presenter_address"]: presenter.get("address", ""),
             m.MAIN_1["presenter_tel"]: presenter.get("tel", ""),
             m.MAIN_1["presenter_fax"]: presenter.get("fax", ""),
             m.MAIN_1["presenter_email"]: presenter.get("email", ""),
             m.MAIN_1["presenter_reference"]: presenter.get("reference") or
             kit.presenter_reference("ND2B", _year(natural, corporate),
                                     company_name.split("  ")[0])}
    page2 = {m.MAIN_2["br_number"]: br}
    if natural:
        page1.update(part_a(m.MAIN_1, natural[0]))
        page2.update(part_b(m.MAIN_2, natural[0]))
    page3 = {m.MAIN_3["br_number"]: br}
    if corporate:
        page3.update(corporate_values(m.MAIN_3, corporate[0]))

    sheets = [(m.PAGE_SHEET_A, {m.SHEET_A["br_number"]: br, **part_a(m.SHEET_A, bean),
                                **part_b(m.SHEET_A, bean)}, "A") for bean in natural[1:]]
    sheets += [(m.PAGE_SHEET_B, {m.SHEET_B["br_number"]: br,
                                 **corporate_values(m.SHEET_B, bean)}, "B")
               for bean in corporate[1:]]
    pi = [(m.PAGE_PI, pi_values(br, bean), "PI") for bean in natural if needs_pi(bean)]

    page3.update({m.MAIN_3["count_sheet_a"]: str(len(natural[1:])),
                  m.MAIN_3["count_sheet_b"]: str(len(corporate[1:])),
                  m.MAIN_3["count_pi"]: str(len(pi)),
                  m.MAIN_3["signed_name"]: _get(model, "selectPersonName"),
                  m.MAIN_3["signed_date"]: kit.signature_date(submitted_on)})
    office = kit.signature_capacity_office(_get(model, "selectCapacityDesc"))
    if office == "company secretary":
        page3[m.MAIN_3["signature_strike_director"]] = strike
    elif office in ("director", "reserve director"):
        page3[m.MAIN_3["signature_strike_secretary"]] = strike

    pages = [(m.PAGE_MAIN_1, page1, "1"), (m.PAGE_MAIN_2, page2, "2"),
             (m.PAGE_MAIN_3, page3, "3"), *sheets]
    if not public_only:
        pages += pi
    _assert_nothing_dropped(natural, corporate, pi, pages, public_only)
    return pages


def _assert_nothing_dropped(natural, corporate, pi, pages, public_only) -> None:
    def placed(fields):
        return sorted(v for _p, values, _s in pages for f in fields
                      if (v := values.get(f)) and v != _DASH)

    problems = []
    want_np = sorted(_get(b, "indvEngSname") for b in natural if _get(b, "indvEngSname"))
    got_np = placed({m.MAIN_1["surname_en"], m.SHEET_A["surname_en"]})
    if want_np != got_np:
        problems.append(f"natural persons {want_np} placed as {got_np}")
    want_bc = sorted(_get(b, "corpEngName") for b in corporate if _get(b, "corpEngName"))
    got_bc = placed({m.MAIN_3["name_en"], m.SHEET_B["name_en"]})
    if want_bc != got_bc:
        problems.append(f"bodies corporate {want_bc} placed as {got_bc}")
    pi_pages = sum(1 for page, _v, _s in pages if page == m.PAGE_PI)
    if pi_pages != (0 if public_only else len(pi)):
        problems.append(f"{pi_pages} PI-ND2B sheets for {len(pi)} persons")
    if problems:
        raise kit.FormFillError("ND2B would drop an officer: " + "; ".join(problems))

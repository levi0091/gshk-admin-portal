"""CR's Form ND2A, composed from the form model and filled onto CR's template.

Spec §7 (answer 15: "exactly the same as the ND2A template ... font size
standardised with NAR1 ... do not miss out on generating additional pages").

Output, in CR's order:
  pages 1-3 always (CR's form is static: a section keeps its page whether or
  not it has content), then one Continuation Sheet A per cessation after the
  first, one Sheet B per natural-person appointment after the first, one Sheet
  C per body-corporate appointment after the first, then one PI-ND2A per
  natural person appointed — "Please place all PI-ND2A sheets at the end" —
  except a company secretary with neither HKID nor passport, whose PI sheet
  would be empty (a secretary's residential address is not collected).

Public pages print PARTIAL identity numbers (note 10 on the form); the PI sheet
prints the full number with the HKID check digit in its own box. Page 3's
counts always state how many PI sheets the FILED form carries, also on the
`public_only` rendering the client is sent without them.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.officer_change_form import kit
from services.officer_change_form import nd2a_map as m
from services.nar1_form import fill as nar1_fill
from services.tpsi.forms import nar1_mapper
from services.tpsi.forms.cr_vocabularies import HKG, display_country, display_district

TEMPLATE = kit.FORM_DIR / "ND2A_fillable.pdf"
_HKT = timezone(timedelta(hours=8))
_ON = kit.CHECKBOX_ON
_DASH = kit.NONE_GIVEN
_get, _node = nar1_fill._get, nar1_fill._node


def beans(model: dict, wrapper: str, item: str) -> list[dict]:
    value = model.get(wrapper)
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        return nar1_fill._as_list(value.get(item))
    return []


def address(node: dict) -> dict:
    country = _get(node, "ctryRegion")
    district = _get(node, "dstCtyStatePostal")
    return {"flat": _get(node, "flatFlrBlk"), "building": _get(node, "bldg"),
            "street": _get(node, "stEstLotVlg"),
            "district": display_district(district) if country.upper() == HKG else district,
            "country": display_country(country) if country else ""}


def _dash(values: dict, block: dict, keys) -> None:
    """NAR1's rule from CR's filed specimen: inside a block that HAS an officer,
    an absent particular is "-", because an empty box on a statutory form
    reads as "not answered"."""
    for key in keys:
        name = block.get(key)
        if name and not values.get(name):
            values[name] = _DASH


def _capacity(block: dict, cpty: str) -> dict:
    key = {"D": "cap_director", "S": "cap_secretary", "AD": "cap_alternate"}.get(cpty)
    return {block[key]: _ON} if key else {}


def _partial_hkid(number: str) -> str:
    digits = "".join(c for c in (number or "") if c.isalnum()).upper()
    if not digits or digits == "NIL":
        return ""
    return nar1_mapper._partial_hkid(digits) or ""


def _partial_passport(number: str) -> str:
    if not number or number.strip().upper() == "NIL":
        return ""
    return nar1_mapper._partial_passport(number)


def cessation_values(block: dict, bean: dict) -> dict:
    values = {**_capacity(block, _get(bean, "cpty")),
              **kit.date_parts(block, _get(bean, "dtResign"))}
    if _get(bean, "corpEngName") or _get(bean, "corpChiName"):
        values.update({block["corp_name_en"]: _get(bean, "corpEngName"),
                       block["corp_name_zh"]: _get(bean, "corpChiName")})
        _dash(values, block, ("corp_name_zh", "alternate_to"))
    else:
        values.update({block["name_zh"]: _get(bean, "indvChiName"),
                       block["surname_en"]: _get(bean, "indvEngSname"),
                       block["other_names_en"]: _get(bean, "indvEngOname"),
                       block["hkid_partial"]: _get(bean, "indvHkidPartial"),
                       block["passport_partial"]: _get(bean, "indvPptNoPartial")})
        reason = {"R": "reason_resign", "D": "reason_deceased"}.get(_get(bean, "rsnCes"))
        if reason:
            values[block[reason]] = _ON
        _dash(values, block, ("name_zh", "hkid_partial", "passport_partial",
                              "alternate_to"))
    still = {"Y": "still_yes", "N": "still_no"}.get(_get(bean, "dirAfterCesInd"))
    if still:
        values[block[still]] = _ON
    return values


def _tcsp(values: dict, block: dict, bean: dict, prefix: str) -> None:
    values[block["tcsp_licence"]] = _get(bean, f"{prefix}TcspNo")
    if _get(bean, f"{prefix}TcspLicNotReq").upper() == "Y":
        values[block["tcsp_not_required"]] = _ON
        values[block["tcsp_reason"]] = _get(bean, f"{prefix}TcspLicNotReqRsn")


def _already(values: dict, block: dict, bean: dict) -> None:
    key = {"Y": "already_yes", "N": "already_no"}.get(_get(bean, "dirBeforeApptInd"))
    if key:
        values[block[key]] = _ON


def natural_values(block: dict, bean: dict, strike: str) -> dict:
    corr = address(_node(bean, "indvCorrAddr"))
    values = {
        **_capacity(block, _get(bean, "cpty")),
        block["name_zh"]: _get(bean, "indvChiName"),
        block["surname_en"]: _get(bean, "indvEngSname"),
        block["other_names_en"]: _get(bean, "indvEngOname"),
        block["prev_name_zh"]: _get(bean, "indvPrevChiName"),
        block["prev_name_en"]: _get(bean, "indvPrevEngName"),
        block["alias_zh"]: _get(bean, "indvAlsChiName"),
        block["alias_en"]: _get(bean, "indvAlsEngName"),
        block["addr_flat"]: corr["flat"], block["addr_building"]: corr["building"],
        block["addr_street"]: corr["street"], block["addr_district"]: corr["district"],
        block["addr_country"]: corr["country"],
        block["email"]: _get(bean, "indvEmailAddr"),
        block["hkid_partial"]: _partial_hkid(_get(bean, "indvHkidNo")),
        block["passport_partial"]: _partial_passport(_get(bean, "indvPptNo")),
        block["passport_country"]: (display_country(_get(bean, "indvPptIssCtry"))
                                    if _get(bean, "indvPptIssCtry") else ""),
        **kit.date_parts(block, _get(bean, "indvDtAppt")),
    }
    _tcsp(values, block, bean, "indv")
    _already(values, block, bean)
    if _get(bean, "cpty") == "D":
        values[block["consent_strike_alternate"]] = strike
    _dash(values, block, ("name_zh", "prev_name_zh", "prev_name_en", "alias_zh",
                          "alias_en", "addr_flat", "addr_building", "hkid_partial",
                          "passport_country", "passport_partial", "alternate_to"))
    return values


def _signer_strikes(block: dict, capacity: str, strike: str) -> dict:
    office = (capacity or "").casefold()
    keeps = ("signer_strike_authorized" if "authori" in office
             else "signer_strike_secretary" if "secretary" in office
             else "signer_strike_director" if "director" in office else None)
    if keeps is None:
        return {}
    return {block[k]: strike for k in ("signer_strike_director", "signer_strike_secretary",
                                       "signer_strike_authorized") if k != keeps}


def corporate_values(block: dict, bean: dict, strike: str) -> dict:
    office = address(_node(bean, "corpAddr"))
    values = {
        **_capacity(block, _get(bean, "cpty")),
        block["name_zh"]: _get(bean, "corpChiName"),
        block["name_en"]: _get(bean, "corpEngName") or _get(bean, "selectPersonName"),
        block["addr_flat"]: office["flat"], block["addr_building"]: office["building"],
        block["addr_street"]: office["street"], block["addr_district"]: office["district"],
        block["addr_country"]: office["country"],
        block["email"]: _get(bean, "corpEmailAddr"),
        block["own_br_number"]: _get(bean, "corpBrNo") or _get(bean, "selectAssoBrNo"),
        **kit.date_parts(block, _get(bean, "corpDtAppt")),
    }
    _tcsp(values, block, bean, "corp")
    _already(values, block, bean)
    if _get(bean, "cpty") == "D":
        values[block["consent_strike_alternate"]] = strike
        values[block["consent_signer_name"]] = _get(bean, "associatedPersonName")
        values.update(_signer_strikes(block, _get(bean, "associatedCapacityDesc"), strike))
    _dash(values, block, ("name_zh", "addr_flat", "addr_building", "alternate_to"))
    return values


def pi_values(br: str, bean: dict) -> dict:
    hkid = "".join(c for c in _get(bean, "indvHkidNo") if c.isalnum()).upper()
    passport = _get(bean, "indvPptNo")
    home = address(_node(bean, "indvResAddr"))
    values = {
        m.PI["br_number"]: br, **_capacity(m.PI, _get(bean, "cpty")),
        m.PI["name_zh"]: _get(bean, "indvChiName"),
        m.PI["surname_en"]: _get(bean, "indvEngSname"),
        m.PI["other_names_en"]: _get(bean, "indvEngOname"),
        m.PI["hkid_full"]: "" if hkid == "NIL" else hkid,
        m.PI["hkid_check_digit"]: _get(bean, "indvHkidChkDgt"),
        m.PI["passport_full"]: "" if passport.upper() == "NIL" else passport,
        m.PI["passport_country"]: (display_country(_get(bean, "indvPptIssCtry"))
                                   if _get(bean, "indvPptIssCtry") else ""),
    }
    if _get(bean, "cpty") != "S":
        values.update({m.PI["res_flat"]: home["flat"], m.PI["res_building"]: home["building"],
                       m.PI["res_street"]: home["street"],
                       m.PI["res_district"]: home["district"],
                       m.PI["res_country"]: home["country"]})
        _dash(values, m.PI, ("res_flat", "res_building"))
    _dash(values, m.PI, ("name_zh", "hkid_full", "passport_full", "passport_country"))
    if not values.get(m.PI["hkid_full"]) or values[m.PI["hkid_full"]] == _DASH:
        values.pop(m.PI["hkid_check_digit"], None)
    return values


def needs_pi(bean: dict) -> bool:
    if _get(bean, "cpty") != "S":
        return True
    ids = [_get(bean, "indvHkidNo"), _get(bean, "indvPptNo")]
    return any(v and v.upper() != "NIL" for v in ids)


def _year(model: dict) -> str:
    dates = [_get(b, k) for w, i, k in (("resCesBeans", "resCesBean", "dtResign"),
                                        ("appOfNpBeans", "appOfNpBean", "indvDtAppt"),
                                        ("appOfBcBeans", "appOfBcBean", "corpDtAppt"))
             for b in beans(model, w, i)]
    years = sorted(kit.split_date(d)[2] for d in dates if kit.split_date(d)[2])
    return years[0] if years else str(datetime.now(_HKT).year)


def compose(model: dict, *, company_name: str, submitted_on, presenter: dict | None,
            public_only: bool, strike: str) -> list[tuple[int, dict, str]]:
    """`[(template_page, values, sheet)]` in CR's order."""
    br = _get(model, "brNo")
    ceased = beans(model, "resCesBeans", "resCesBean")
    natural = beans(model, "appOfNpBeans", "appOfNpBean")
    corporate = beans(model, "appOfBcBeans", "appOfBcBean")
    presenter = presenter or kit.DEFAULT_PRESENTER

    page1 = {m.MAIN_1["br_number"]: br, m.MAIN_1["company_name"]: company_name,
             m.MAIN_1["presenter_name"]: presenter.get("name", ""),
             m.MAIN_1["presenter_address"]: presenter.get("address", ""),
             m.MAIN_1["presenter_tel"]: presenter.get("tel", ""),
             m.MAIN_1["presenter_fax"]: presenter.get("fax", ""),
             m.MAIN_1["presenter_email"]: presenter.get("email", ""),
             m.MAIN_1["presenter_reference"]: presenter.get("reference") or
             kit.presenter_reference("ND2A", _year(model), company_name.split("  ")[0])}
    if ceased:
        page1.update(cessation_values(m.MAIN_1, ceased[0]))
    page2 = {m.MAIN_2["br_number"]: br}
    if natural:
        page2.update(natural_values(m.MAIN_2, natural[0], strike))
    page3 = {m.MAIN_3["br_number"]: br}
    if corporate:
        page3.update(corporate_values(m.MAIN_3, corporate[0], strike))

    sheets = []
    for bean in ceased[1:]:
        sheets.append((m.PAGE_SHEET_A, {m.SHEET_A["br_number"]: br,
                                        **cessation_values(m.SHEET_A, bean)}, "A"))
    for bean in natural[1:]:
        sheets.append((m.PAGE_SHEET_B, {m.SHEET_B["br_number"]: br,
                                        **natural_values(m.SHEET_B, bean, strike)}, "B"))
    for bean in corporate[1:]:
        sheets.append((m.PAGE_SHEET_C, {m.SHEET_C["br_number"]: br,
                                        **corporate_values(m.SHEET_C, bean, strike)}, "C"))
    pi = [(m.PAGE_PI, pi_values(br, bean), "PI") for bean in natural if needs_pi(bean)]

    page3.update({
        m.MAIN_3["count_sheet_a"]: str(len(ceased[1:])),
        m.MAIN_3["count_sheet_b"]: str(len(natural[1:])),
        m.MAIN_3["count_sheet_c"]: str(len(corporate[1:])),
        m.MAIN_3["count_pi"]: str(len(pi)),
        m.MAIN_3["signed_name"]: _get(model, "selectPersonName"),
        m.MAIN_3["signed_date"]: kit.signature_date(submitted_on),
    })
    office = kit.signature_capacity_office(_get(model, "selectCapacityDesc"))
    if office == "company secretary":
        page3[m.MAIN_3["signature_strike_director"]] = strike
    elif office in ("director", "reserve director"):
        page3[m.MAIN_3["signature_strike_secretary"]] = strike

    pages = [(m.PAGE_MAIN_1, page1, "1"), (m.PAGE_MAIN_2, page2, "2"),
             (m.PAGE_MAIN_3, page3, "3"), *sheets]
    if not public_only:
        pages += pi
    _assert_nothing_dropped(ceased, natural, corporate, pi, pages, public_only)
    return pages


def _assert_nothing_dropped(ceased, natural, corporate, pi, pages, public_only) -> None:
    """Re-count the output against the form model before any bytes leave."""
    def placed(key_sets):
        out = []
        for _page, values, _sheet in pages:
            for keys in key_sets:
                name = values.get(keys)
                if name and name != _DASH:
                    out.append(name)
        return sorted(out)

    want_ceased = sorted(_get(b, "indvEngSname") or _get(b, "corpEngName") for b in ceased)
    got_ceased = placed({m.MAIN_1["surname_en"], m.SHEET_A["surname_en"],
                         m.MAIN_1["corp_name_en"], m.SHEET_A["corp_name_en"]})
    want_natural = sorted(_get(b, "indvEngSname") for b in natural)
    got_natural = placed({m.MAIN_2["surname_en"], m.SHEET_B["surname_en"]})
    want_corp = sorted(_get(b, "corpEngName") or _get(b, "selectPersonName") for b in corporate)
    got_corp = placed({m.MAIN_3["name_en"], m.SHEET_C["name_en"]})
    pi_pages = sum(1 for page, _v, _s in pages if page == m.PAGE_PI)
    expected_pi = 0 if public_only else len(pi)
    problems = []
    if want_ceased != got_ceased:
        problems.append(f"cessations {want_ceased} placed as {got_ceased}")
    if want_natural != got_natural:
        problems.append(f"natural-person appointments {want_natural} placed as {got_natural}")
    if want_corp != got_corp:
        problems.append(f"body-corporate appointments {want_corp} placed as {got_corp}")
    if pi_pages != expected_pi:
        problems.append(f"{pi_pages} PI-ND2A sheets for {expected_pi} natural persons")
    if problems:
        raise kit.FormFillError("ND2A would drop an officer: " + "; ".join(problems))

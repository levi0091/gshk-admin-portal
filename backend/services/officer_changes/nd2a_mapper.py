"""Entries + company graph -> CR's ND2A form model (a dict for `form_xml.build`).

Pure, and every problem is reported at once as a `MappingError` (spec §8).
Element names and their meaning are CR's worksheet (sheet ND2A) checked against
CR's ten ND2A examples; addresses, dates, partial identity numbers and the
form-level signatory block reuse NAR1's mapper, so the district codes, country
codes and the body-corporate signing scheme CR's live register verified on
2026-09-16 are the ones in use here too.

  * Cessation: PARTIAL identity numbers (`indvHkidPartial`, `indvPptNoPartial`),
    CR's reason (`rsnCes`) for a natural person, and `dirAfterCesInd` = N for a
    director — alternate directors are out of scope (answer 5), so nobody stays
    on as one.
  * Appointment: the FULL HKID with the check digit split out, or the full
    passport with its issuing country; "NIL" in both only when the person holds
    neither, as CR's remark says. `dirBeforeApptInd` = N for a director, absent
    for a secretary — the examples carry it on directors only.
  * Every new DIRECTOR's bean carries `id="S<n>"`, which its consent signature
    points at. A natural person consents with their own e-Registry account
    (`selectPersonId` / `selectPersonName`); a body corporate through the person
    signing for it (`associatedPerson*`, `selectAssoBrNo`).

`for_esign` decides whether a missing e-Registry account is a problem. On the
manual route nothing is sent to CR — the XML only renders the PDF — so a
director without an account must not stop the draft being produced.
"""
from __future__ import annotations

import re

from services.tpsi.forms import nar1_mapper as nm
from services.tpsi.forms.cr_vocabularies import resolve_country

MappingError = nm.MappingError

_CPTY = {"director": "D", "company_secretary": "S"}
_FULL_HKID = re.compile(r"^([A-Z]{1,2}[0-9]{6})([0-9A])$")


def _s(value) -> str:
    return str(value or "").strip()


def _alnum(value) -> str:
    return "".join(c for c in str(value or "") if c.isalnum()).upper()


def cr_address(addr: dict | None, problems: list[str], where: str, *,
               hkg_only: bool = False) -> dict:
    """NAR1's five address lines, district codes and country codes — without
    NAR1's `addrLangInd`, which the ND2A/ND2B address blocks do not carry."""
    block = nm._address(addr, problems, where, hkg_only=hkg_only)
    block.pop("addrLangInd", None)
    return block


def cr_date(value, problems: list[str], where: str, *, required: bool = True) -> str:
    """DD/MM/YYYY. A missing date is a problem only when `required`: the
    client's draft may leave it blank (Jacqueline A1), anything sent to CR may
    not."""
    if not value:
        if required:
            problems.append(f"{where}: no date")
        return ""
    return nm._format_date(value, problems, where)


def documents(graph: dict, person_id: str) -> tuple[dict | None, dict | None]:
    docs = (graph.get("identity_documents") or {}).get(person_id) or []

    def pick(kind):
        of_kind = [d for d in docs if d.get("id_type") == kind and _s(d.get("id_number"))]
        return next((d for d in of_kind if d.get("is_primary")), of_kind[0] if of_kind else None)

    return pick("hkid"), pick("passport")


def english_name(person: dict) -> tuple[str, str]:
    surname, given = _s(person.get("surname")), _s(person.get("given_names"))
    if not surname and not given:
        surname = _s(person.get("full_name"))
    return surname, given


def partial_ids(hkid: str, passport: str, problems: list[str], where: str) -> dict:
    """CR's partial numbers (note 10 on the form): all letters and the first
    three digits of a HKID; the first half of a passport number."""
    out, before = {}, len(problems)
    if hkid:
        partial = nm._partial_hkid(_alnum(hkid))
        if partial is None:
            problems.append(f"{where}: HKID {hkid!r} does not yield the partial number "
                            "CR identifies the officer by")
        else:
            out["indvHkidPartial"] = partial
    if passport:
        partial = nm._partial_passport(passport)
        if partial:
            out["indvPptNoPartial"] = partial
    if not out and len(problems) == before:
        problems.append(f"{where}: no HKID or passport on record — CR identifies a "
                        "natural person on this form by a partial identity number")
    return out


def split_hkid(number: str, problems: list[str], where: str) -> tuple[str, str] | None:
    match = _FULL_HKID.match(_alnum(number))
    if not match:
        problems.append(f"{where}: HKID {number!r} is not a full HKID number with its "
                        "check digit (e.g. A123456(3))")
        return None
    return match.group(1), match.group(2)


def full_ids(graph: dict, person_id: str, problems: list[str], where: str,
             prefix: str = "indv") -> dict:
    hkid, passport = documents(graph, person_id)
    if not hkid and not passport:
        return {f"{prefix}HkidNo": "NIL", f"{prefix}PptNo": "NIL"}
    out = {}
    if hkid:
        split = split_hkid(hkid.get("id_number"), problems, where)
        if split:
            out[f"{prefix}HkidNo"], out[f"{prefix}HkidChkDgt"] = split
    if passport:
        code = resolve_country(passport.get("issuing_country"))
        if not code:
            problems.append(f"{where}: passport issuing country "
                            f"{passport.get('issuing_country')!r} has no CR code, and CR "
                            "refuses a passport number without it")
        out[f"{prefix}PptNo"] = _s(passport.get("id_number"))
        if code:
            out[f"{prefix}PptIssCtry"] = code
    return out


def tcsp(prefix: str, licence: str, reason: str, problems: list[str], where: str) -> dict:
    if _s(licence):
        return {f"{prefix}TcspNo": _s(licence)}
    if _s(reason):
        return {f"{prefix}TcspLicNotReq": "Y", f"{prefix}TcspLicNotReqRsn": _s(reason)}
    problems.append(f"{where}: a company secretary needs a TCSP licence number or the "
                    "reason no licence is required")
    return {}


def _cessation(graph: dict, entry: dict, problems: list[str],
               require_dates: bool = True) -> dict:
    """The officer as CR HOLDS them: the ND2B baseline when there is one (an
    edit on the profile that no ND2B has filed is not on CR's register), else
    the profile — which, with no baseline, has not changed since CR was told."""
    bean = {"cpty": _CPTY[entry["capacity"]]}
    held = (graph.get("baselines") or {}).get(
        entry.get("person_id") or entry.get("corporate_entity_id")) or None
    if entry.get("person_id"):
        person = (graph.get("persons") or {}).get(entry["person_id"]) or {}
        where = f"cessation of {person.get('full_name') or entry['person_id']}"
        if held and held.get("party_type") == "individual":
            name = held.get("name_en") or {}
            surname, given = _s(name.get("surname")), _s(name.get("given_names"))
            chinese = _s(held.get("name_zh"))
            hkid_no = _s(held.get("hkid"))
            passport_no = _s((held.get("passport") or {}).get("number"))
        else:
            surname, given = english_name(person)
            chinese = _s(person.get("full_name_zh"))
            hkid, passport = documents(graph, entry["person_id"])
            hkid_no = (hkid or {}).get("id_number")
            passport_no = (passport or {}).get("id_number")
        bean.update({"indvChiName": chinese, "indvEngSname": surname, "indvEngOname": given})
        bean.update(partial_ids(hkid_no, passport_no, problems, where))
        if entry.get("cessation_reason") not in ("R", "D"):
            problems.append(f"{where}: CR needs the reason for cessation")
        bean["rsnCes"] = entry.get("cessation_reason") or ""
    else:
        corp = (graph.get("entities") or {}).get(entry.get("corporate_entity_id")) or {}
        where = f"cessation of {corp.get('company_name') or entry.get('corporate_entity_id')}"
        name = (held or {}).get("name") if (held or {}).get("party_type") == "corporate" else None
        bean.update({"corpChiName": _s((name or {}).get("name_zh") if name
                                       else corp.get("company_name_zh")),
                     "corpEngName": _s((name or {}).get("name") if name
                                       else corp.get("company_name"))})
        if not bean["corpEngName"]:
            problems.append(f"{where}: the body corporate has no name on record")
    bean["dtResign"] = cr_date(entry.get("effective_date"), problems, f"{where}: date",
                               required=require_dates)
    if entry["capacity"] == "director":
        bean["dirAfterCesInd"] = "N"
    return bean


def _natural_appointment(graph, entry, bean_id, problems, for_esign,
                         require_dates=True) -> dict:
    person = (graph.get("persons") or {}).get(entry["person_id"]) or {}
    where = f"appointment of {person.get('full_name') or entry['person_id']}"
    secretary = entry["capacity"] == "company_secretary"
    surname, given = english_name(person)
    bean = {"@id": bean_id} if bean_id else {}
    bean.update({
        "cpty": _CPTY[entry["capacity"]],
        "indvChiName": _s(person.get("full_name_zh")),
        "indvEngSname": surname, "indvEngOname": given,
        "indvPrevChiName": _s(person.get("former_name_zh")),
        "indvPrevEngName": _s(person.get("former_name")),
        "indvAlsChiName": _s(person.get("alias_zh")),
        "indvAlsEngName": _s(person.get("alias_en")),
    })
    if not surname:
        problems.append(f"{where}: no English name on record")
    home = (graph.get("addresses") or {}).get(person.get("residential_address_id"))
    correspondence = (entry.get("correspondence_address")
                      if entry.get("correspondence_same_as_residential") is False else home)
    bean["indvCorrAddr"] = cr_address(correspondence, problems,
                                      f"{where} (correspondence address)", hkg_only=secretary)
    if not secretary:
        bean["indvResAddr"] = cr_address(home, problems, f"{where} (residential address)")
    bean["indvEmailAddr"] = _s(person.get("email"))
    bean.update(full_ids(graph, entry["person_id"], problems, where))
    if secretary:
        bean.update(tcsp("indv", person.get("tcsp_licence_no"),
                         person.get("tcsp_exemption_reason"), problems, where))
    bean["indvDtAppt"] = cr_date(entry.get("effective_date"), problems, f"{where}: date",
                                 required=require_dates)
    if not secretary:
        bean["dirBeforeApptInd"] = "N"
        account = (graph.get("eservice") or {}).get(entry["person_id"]) or {}
        if account.get("eservice_user_id") and account.get("eservice_person_name"):
            bean["selectPersonId"] = account["eservice_user_id"]
            bean["selectPersonName"] = account["eservice_person_name"]
        elif for_esign:
            problems.append(f"{where}: CR needs the new director's own e-Registry user ID "
                            "and the name on that account for their consent signature — "
                            "store them on the person's profile, or file on the manual route")
    return bean


def _corporate_appointment(graph, entry, bean_id, problems, for_esign,
                           require_dates=True) -> dict:
    corp = (graph.get("entities") or {}).get(entry.get("corporate_entity_id")) or {}
    where = f"appointment of {corp.get('company_name') or entry.get('corporate_entity_id')}"
    secretary = entry["capacity"] == "company_secretary"
    office = (graph.get("addresses") or {}).get(corp.get("registered_address_id"))
    bean = {"@id": bean_id} if bean_id else {}
    bean.update({
        "cpty": _CPTY[entry["capacity"]],
        "corpChiName": _s(corp.get("company_name_zh")),
        "corpEngName": _s(corp.get("company_name")),
        "corpAddr": cr_address(office, problems, f"{where} (address)", hkg_only=secretary),
        "corpEmailAddr": _s(corp.get("email")),
        "corpBrNo": _s(corp.get("br_number")),
    })
    if not bean["corpEngName"]:
        problems.append(f"{where}: the body corporate has no name on record")
    if secretary:
        bean.update(tcsp("corp", corp.get("tcsp_licence_no"),
                         corp.get("tcsp_exemption_reason"), problems, where))
    bean["corpDtAppt"] = cr_date(entry.get("effective_date"), problems, f"{where}: date",
                                 required=require_dates)
    if not secretary:
        bean["dirBeforeApptInd"] = "N"
        signer = (graph.get("persons") or {}).get(entry.get("consent_person_id")) or {}
        account = (graph.get("eservice") or {}).get(entry.get("consent_person_id")) or {}
        if account.get("eservice_user_id") and account.get("eservice_person_name"):
            bean["associatedPersonId"] = account["eservice_user_id"]
            bean["associatedPersonName"] = account["eservice_person_name"]
        elif for_esign:
            problems.append(f"{where}: CR needs the e-Registry account of "
                            f"{signer.get('full_name') or 'the person'} signing the "
                            "consent for the body corporate")
        if not _s(entry.get("consent_capacity")):
            problems.append(f"{where}: the consent signer's capacity is missing")
        bean["associatedCapacityDesc"] = _s(entry.get("consent_capacity"))
        # NOT a problem when empty. CR's worksheet marks corpBrNo and
        # selectAssoBrNo Mandatory = N, and its printed ND2A says the BR box is
        # "only applicable to body corporate registered in Hong Kong" — an
        # overseas holding company has none. Empty values are left out of the
        # XML by `form_xml._emit`, and the body corporate is named instead.
        bean["selectAssoBrNo"] = bean["corpBrNo"]
        bean["selectPersonName"] = bean["corpEngName"]
    return bean


def signatory(graph: dict, problems: list[str], *, signatory_capacity, signing_identity,
              for_esign: bool) -> dict:
    """NAR1's form-level block, unchanged. Off the e-Sign route the person
    signing for a body corporate secretary is not needed (nothing goes to CR),
    so only a block with no name at all is a problem."""
    found: list[str] = []
    block = nm._signatory_block(graph, None, found, capacity_override=signatory_capacity,
                                signing_identity=signing_identity)
    if for_esign or not block.get("selectPersonName"):
        problems.extend(found)
    return block


def map_case(graph: dict, entries: list[dict], *, signatory_capacity: str | None = None,
             signing_identity: dict | None = None, for_esign: bool = False,
             require_dates: bool | None = None) -> dict:
    """`require_dates` defaults to `for_esign`: CR is sent only dated changes,
    while the client's draft and the manual route's PDF may wait for them."""
    require_dates = for_esign if require_dates is None else require_dates
    problems: list[str] = []
    entity = graph.get("entity") or {}
    data = {"language": "E", "brNo": _s(entity.get("br_number"))}
    if not data["brNo"]:
        problems.append("company: no BR number on record")
    ceased, natural, corporate = [], [], []
    seq = 0
    for entry in entries:
        kind = entry.get("kind")
        if kind == "cessation":
            ceased.append(_cessation(graph, entry, problems, require_dates))
        elif kind == "appointment":
            bean_id = None
            if entry.get("capacity") == "director":
                seq += 1
                bean_id = f"S{seq}"
            if entry.get("person_id"):
                natural.append(_natural_appointment(graph, entry, bean_id, problems, for_esign,
                                                    require_dates))
            else:
                corporate.append(_corporate_appointment(graph, entry, bean_id, problems,
                                                        for_esign, require_dates))
        else:
            problems.append("an ND2A carries cessations and appointments only")
    if not (ceased or natural or corporate):
        problems.append("the form reports no change")
    if ceased:
        data["resCesBeans"] = ceased
    if natural:
        data["appOfNpBeans"] = natural
    if corporate:
        data["appOfBcBeans"] = corporate
    data.update(signatory(graph, problems, signatory_capacity=signatory_capacity,
                          signing_identity=signing_identity, for_esign=for_esign))
    if problems:
        raise MappingError(problems)
    return data

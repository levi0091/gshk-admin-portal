"""Entries + company graph -> CR's ND2B form model.

Pure; every problem at once as a `MappingError`.

Part A ("particulars currently registered") is printed from `entry.registered`
— the BASELINE, what CR holds — never from the profile (spec §4): a renamed
director is identified to CR by the name CR knows, and a partial identity number
CR already has. Part B carries only the items the operator did not omit, each
with its own effective date; an item with no date is a problem naming the
officer and the item.
"""
from __future__ import annotations

from services.officer_changes.nd2a_mapper import (
    MappingError, _alnum, _s, cr_address, cr_date, partial_ids, signatory, split_hkid,
    tcsp,
)
from services.tpsi.forms.cr_vocabularies import resolve_country

_CPTY = {"director": "D", "company_secretary": "S"}


def _who(registered: dict) -> str:
    if registered.get("party_type") == "corporate":
        return (registered.get("name") or {}).get("name") or "body corporate"
    name = registered.get("name_en") or {}
    return " ".join(p for p in (_s(name.get("surname")), _s(name.get("given_names"))) if p) \
        or "officer"


def _natural(entry: dict, problems: list[str]) -> dict:
    reg = entry.get("registered") or {}
    who = _who(reg)
    name = reg.get("name_en") or {}
    secretary = entry.get("capacity") == "company_secretary"
    bean = {"cpty": _CPTY[entry["capacity"]],
            "indvChiName": _s(reg.get("name_zh")),
            "indvEngSname": _s(name.get("surname")),
            "indvEngOname": _s(name.get("given_names"))}
    bean.update(partial_ids(reg.get("hkid"), (reg.get("passport") or {}).get("number"),
                            problems, f"{who} (as registered)"))
    for item in entry.get("items") or []:
        if item.get("omitted"):
            continue
        key, new = item["key"], item.get("new")
        where = f"{who}: {item.get('label') or key}"
        when = cr_date(item.get("effective_date"), problems, f"{where} effective date")
        if key == "name_zh":
            bean.update(indvNewChiName=_s(new), indvNewChiNameEffDt=when)
        elif key == "name_en":
            bean.update(indvNewEngSname=_s((new or {}).get("surname")),
                        indvNewEngOname=_s((new or {}).get("given_names")),
                        indvNewEngNameEffDt=when)
        elif key == "alias":
            bean.update(indvNewAlsChiName=_s((new or {}).get("alias_zh")),
                        indvNewAlsEngName=_s((new or {}).get("alias_en")),
                        indvNewAlsNameEffDt=when)
        elif key == "correspondence_address":
            bean.update(indvNewAddr=cr_address(new, problems, where, hkg_only=secretary),
                        indvNewAddrEffDt=when)
        elif key == "email":
            bean.update(indvNewEmailAddr=_s(new), indvNewEmailAddrEffDt=when)
        elif key == "hkid":
            if _alnum(new):
                split = split_hkid(new, problems, where)
                if split:
                    bean.update(indvNewHkidNo=split[0], indvNewHkidChkDgt=split[1])
            else:
                bean["indvNewHkidNo"] = "NIL"  # CR's remark: NIL when no HKID
            bean["indvNewHkidNoEffDt"] = when
        elif key == "passport":
            number = _s((new or {}).get("number"))
            code = resolve_country((new or {}).get("issuing_country")) if number else ""
            if number and not code:
                problems.append(f"{where}: the issuing country has no CR code")
            bean.update(indvNewPptNo=number, indvNewPptIssCtry=code or "",
                        indvNewPptNoEffDt=when)
        elif key == "tcsp":
            bean.update(tcsp("indvNew", (new or {}).get("licence_no"),
                             (new or {}).get("exemption_reason"), problems, where))
            bean["indvNewTcspNoEffDt"] = when
        elif key == "residential_address":
            bean.update(indvNewResAddr=cr_address(new, problems, where),
                        indvNewResAddrEffDt=when)
    return bean


def _corporate(graph: dict, entry: dict, problems: list[str]) -> dict:
    reg = entry.get("registered") or {}
    who = _who(reg)
    corp = (graph.get("entities") or {}).get(entry.get("corporate_entity_id")) or {}
    secretary = entry.get("capacity") == "company_secretary"
    bean = {"cpty": _CPTY[entry["capacity"]],
            "corpChiName": _s((reg.get("name") or {}).get("name_zh")),
            "corpEngName": _s((reg.get("name") or {}).get("name")),
            "corpBrNo": _s(corp.get("br_number"))}
    for item in entry.get("items") or []:
        if item.get("omitted"):
            continue
        key, new = item["key"], item.get("new")
        where = f"{who}: {item.get('label') or key}"
        when = cr_date(item.get("effective_date"), problems, f"{where} effective date")
        if key == "name":
            bean.update(corpNewChiName=_s((new or {}).get("name_zh")),
                        corpNewEngName=_s((new or {}).get("name")), corpNewNameEffDt=when)
        elif key == "address":
            bean.update(corpNewAddr=cr_address(new, problems, where, hkg_only=secretary),
                        corpNewAddrEffDt=when)
        elif key == "email":
            bean.update(corpNewEmailAddr=_s(new), corpNewEmailAddrEffDt=when)
        elif key == "tcsp":
            bean.update(tcsp("corpNew", (new or {}).get("licence_no"),
                             (new or {}).get("exemption_reason"), problems, where))
            bean["corpNewTcspNoEffDt"] = when
    return bean


def map_case(graph: dict, entries: list[dict], *, signatory_capacity: str | None = None,
             signing_identity: dict | None = None, for_esign: bool = False) -> dict:
    problems: list[str] = []
    entity = graph.get("entity") or {}
    data = {"language": "E", "brNo": _s(entity.get("br_number"))}
    if not data["brNo"]:
        problems.append("company: no BR number on record")
    natural, corporate = [], []
    for entry in entries:
        if entry.get("kind") != "change":
            problems.append("an ND2B carries changes of particulars only")
            continue
        if not any(not i.get("omitted") for i in entry.get("items") or []):
            continue  # an officer whose every line is omitted is not on the form
        if entry.get("party_type") == "corporate" or entry.get("corporate_entity_id"):
            corporate.append(_corporate(graph, entry, problems))
        else:
            natural.append(_natural(entry, problems))
    if not (natural or corporate):
        problems.append("the form reports no change")
    if natural:
        data["npBeans"] = natural
    if corporate:
        data["bcBeans"] = corporate
    data.update(signatory(graph, problems, signatory_capacity=signatory_capacity,
                          signing_identity=signing_identity, for_esign=for_esign))
    if problems:
        raise MappingError(problems)
    return data

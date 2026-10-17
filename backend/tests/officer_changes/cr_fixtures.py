"""CR's ND2A / ND2B worked examples, read back into the graph + entries that
would produce them — so a mapper test can say "this is CR's own document".

Each example is parsed; its beans become persons, body corporates, addresses,
identity documents and change-list entries; the form-level signatory becomes a
natural-person company secretary. `expected_pairs` flattens the example's form
model into (path, text) pairs in document order, for an element-for-element
comparison.
"""
from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET

from services.tpsi.forms.cr_vocabularies import to_alpha2

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures/cr-examples/validateForm"
NS = "http://interfaces.service.webservice.icris3e.cr.gov.hk/"
#: Filled in by CR after validation, or by us at signing; never compared.
IGNORED = {"formCode", "compNameE", "compNameC", "signatoryDate"}
#: Values the build DERIVES rather than takes (spec §2): without alternate
#: directors, an appointee was not already a director and a leaver does not stay.
DERIVED = {"dirBeforeApptInd": "N", "dirAfterCesInd": "N"}


def files(form: str) -> list[pathlib.Path]:
    return sorted(FIXTURES.glob(f"validate_{form}(*.xml"))


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def form_model(path: pathlib.Path) -> ET.Element:
    text = path.read_text(encoding="utf8").replace("<</", "</")  # CR's own typo
    root = ET.fromstring(text)
    return next(el for el in root.iter() if _local(el.tag) == "formModel")


def parse_inner(inner_xml: str) -> ET.Element:
    return ET.fromstring(f'<cr:formModel xmlns:cr="{NS}">{inner_xml}</cr:formModel>')


def pairs(model: ET.Element) -> list[tuple[str, str]]:
    out = []

    def walk(el, path):
        name = _local(el.tag)
        here = f"{path}/{name}" if path else name
        if el.get("id"):
            out.append((f"{here}@id", el.get("id")))
        children = list(el)
        if children:
            for child in children:
                walk(child, here)
        else:
            text = (el.text or "").strip()
            if text and name not in IGNORED:
                out.append((here, DERIVED.get(name, text)))

    for child in model:
        walk(child, "")
    return out


def _v(bean: ET.Element, name: str) -> str:
    el = next((c for c in bean if _local(c.tag) == name), None)
    return (el.text or "").strip() if el is not None else ""


def _address(bean: ET.Element, name: str) -> dict | None:
    el = next((c for c in bean if _local(c.tag) == name), None)
    if el is None:
        return None
    return {"line1": _v(el, "flatFlrBlk") or None, "line2": _v(el, "bldg") or None,
            "line3": _v(el, "stEstLotVlg") or None, "city": _v(el, "dstCtyStatePostal"),
            "state_region": None, "postal_code": None,
            "country": to_alpha2(_v(el, "ctryRegion")) or _v(el, "ctryRegion")}


def _full_passport(partial: str) -> str:
    # A number whose CR partial is `partial`: ceil(n/2) characters of it.
    return partial + "4567"[: max(len(partial) - 1, 0)] if partial else ""


def _full_hkid(partial: str) -> str:
    # "A123" -> "A1234563" (any six digits and a check digit keep the partial).
    return partial + "4563"[: 8 - len(partial)] if partial else ""


class World:
    def __init__(self):
        self.persons, self.entities, self.addresses = {}, {}, {}
        self.docs, self.eservice = {}, {}
        self.entries = []
        self._n = 0

    def _id(self, prefix):
        self._n += 1
        return f"{prefix}{self._n}"

    def address(self, addr):
        if addr is None:
            return None
        aid = self._id("A")
        self.addresses[aid] = {"id": aid, **addr}
        return aid

    def person(self, **fields):
        pid = self._id("P")
        self.persons[pid] = {"id": pid, **fields}
        return pid

    def entity(self, **fields):
        cid = self._id("C")
        self.entities[cid] = {"id": cid, **fields}
        return cid

    def graph(self, signatory_pid: str) -> dict:
        return {
            "entity": {"id": "E1", "br_number": "00000001"},
            "officers": [],
            "secretaries": [{"id": "SEC", "person_id": signatory_pid, "is_current": True,
                             "is_gshk": False}],
            "persons": self.persons, "entities": self.entities,
            "addresses": self.addresses, "identity_documents": self.docs,
            "eservice": self.eservice,
        }


_CPTY = {"D": "director", "S": "company_secretary"}


def _ids(world, pid, hkid_no, chk, ppt, ctry):
    docs = []
    if hkid_no and hkid_no != "NIL":
        docs.append({"person_id": pid, "id_type": "hkid", "id_number": hkid_no + chk,
                     "is_primary": True})
    if ppt and ppt != "NIL":
        docs.append({"person_id": pid, "id_type": "passport", "id_number": ppt,
                     "issuing_country": to_alpha2(ctry) or ctry})
    world.docs[pid] = docs


def build_world(path: pathlib.Path) -> tuple[dict, list[dict]]:
    model = form_model(path)
    world = World()
    for el in model:
        name = _local(el.tag)
        for bean in el:
            bean_name = _local(bean.tag)
            if bean_name == "resCesBean":
                _cessation(world, bean)
            elif bean_name == "appOfNpBean":
                _natural(world, bean)
            elif bean_name == "appOfBcBean":
                _corporate(world, bean)
            elif bean_name == "npBean":
                _np_change(world, bean)
            elif bean_name == "bcBean":
                _bc_change(world, bean)
    sig = world.person(full_name=_v(model, "selectPersonName"),
                       eservice_user_id=_v(model, "selectPersonId"))
    return world.graph(sig), world.entries


def _cessation(world, bean):
    entry = {"id": world._id("N"), "kind": "cessation", "capacity": _CPTY[_v(bean, "cpty")],
             "effective_date": _v(bean, "dtResign")}
    if _v(bean, "indvEngSname"):
        pid = world.person(full_name_zh=_v(bean, "indvChiName"),
                           surname=_v(bean, "indvEngSname"),
                           given_names=_v(bean, "indvEngOname"))
        _ids(world, pid, _full_hkid(_v(bean, "indvHkidPartial"))[:-1],
             _full_hkid(_v(bean, "indvHkidPartial"))[-1:],
             _full_passport(_v(bean, "indvPptNoPartial")), "GBR")
        entry.update(party_type="individual", person_id=pid,
                     cessation_reason=_v(bean, "rsnCes"))
    else:
        cid = world.entity(company_name=_v(bean, "corpEngName"),
                           company_name_zh=_v(bean, "corpChiName"))
        entry.update(party_type="corporate", corporate_entity_id=cid)
    world.entries.append(entry)


def _natural(world, bean):
    corr, home = _address(bean, "indvCorrAddr"), _address(bean, "indvResAddr")
    pid = world.person(
        full_name_zh=_v(bean, "indvChiName"), surname=_v(bean, "indvEngSname"),
        given_names=_v(bean, "indvEngOname"), former_name_zh=_v(bean, "indvPrevChiName"),
        former_name=_v(bean, "indvPrevEngName"), alias_zh=_v(bean, "indvAlsChiName"),
        alias_en=_v(bean, "indvAlsEngName"), email=_v(bean, "indvEmailAddr"),
        residential_address_id=world.address(home or corr),
        tcsp_licence_no=_v(bean, "indvTcspNo"),
        tcsp_exemption_reason=_v(bean, "indvTcspLicNotReqRsn"))
    _ids(world, pid, _v(bean, "indvHkidNo"), _v(bean, "indvHkidChkDgt"),
         _v(bean, "indvPptNo"), _v(bean, "indvPptIssCtry"))
    if _v(bean, "selectPersonId"):
        world.eservice[pid] = {"eservice_user_id": _v(bean, "selectPersonId"),
                               "eservice_person_name": _v(bean, "selectPersonName"),
                               "configured": True, "has_password": True}
    same = home is None or corr == home
    world.entries.append({
        "id": world._id("N"), "kind": "appointment", "capacity": _CPTY[_v(bean, "cpty")],
        "party_type": "individual", "person_id": pid,
        "effective_date": _v(bean, "indvDtAppt"),
        "correspondence_same_as_residential": same,
        "correspondence_address": None if same else corr})


def _corporate(world, bean):
    cid = world.entity(company_name=_v(bean, "corpEngName") or _v(bean, "selectPersonName")
                       or "TEST COMPANY LIMITED",
                       company_name_zh=_v(bean, "corpChiName"),
                       registered_address_id=world.address(_address(bean, "corpAddr")),
                       email=_v(bean, "corpEmailAddr"),
                       br_number=_v(bean, "corpBrNo") or _v(bean, "selectAssoBrNo"),
                       tcsp_licence_no=_v(bean, "corpTcspNo"),
                       tcsp_exemption_reason=_v(bean, "corpTcspLicNotReqRsn"))
    entry = {"id": world._id("N"), "kind": "appointment",
             "capacity": _CPTY[_v(bean, "cpty")], "party_type": "corporate",
             "corporate_entity_id": cid, "effective_date": _v(bean, "corpDtAppt")}
    if _v(bean, "associatedPersonId"):
        signer = world.person(full_name=_v(bean, "associatedPersonName"))
        world.eservice[signer] = {"eservice_user_id": _v(bean, "associatedPersonId"),
                                  "eservice_person_name": _v(bean, "associatedPersonName"),
                                  "configured": True, "has_password": True}
        entry.update(consent_person_id=signer,
                     consent_capacity=_v(bean, "associatedCapacityDesc"))
    world.entries.append(entry)


_HANDLERS = {"resCesBean": "_cessation", "appOfNpBean": "_natural",
             "appOfBcBean": "_corporate", "npBean": "_np_change", "bcBean": "_bc_change"}


def combined_world(form: str, names: list[str], renames: dict | None = None):
    """One world holding the beans of several examples — for the cases that
    need more officers than one example has (continuation sheets). `renames`
    maps an entry index to new person fields so repeated people differ."""
    world = World()
    for name in names:
        model = form_model(FIXTURES / f"validate_{form}({name}).xml")
        for wrapper in model:
            for bean in wrapper:
                handler = _HANDLERS.get(_local(bean.tag))
                if handler:
                    globals()[handler](world, bean)
    for index, fields in (renames or {}).items():
        entry = world.entries[index]
        if entry.get("person_id"):
            world.persons[entry["person_id"]].update(fields)
        if entry.get("registered"):
            entry["registered"]["name_en"] = {"surname": fields.get("surname", ""),
                                              "given_names": fields.get("given_names", "")}
    sig = world.person(full_name="CHAN, TAI MAN", eservice_user_id="TEST1234")
    return world.graph(sig), world.entries


#: 3 cessations, 3 natural appointments (2 directors, 1 secretary) and 2
#: body-corporate directors: Sheets A x2, B x2, C x1 and three PI sheets.
ND2A_OVERFLOW = ["Cease Individual Director", "Cease Corporate Director",
                 "Cease Individual Secretary", "Appoint Individual Director",
                 "Appoint Individual Secretary", "Appoint Individual Director",
                 "Appoint Corporate Director - BR", "Appoint Corporate Director - CR"]
ND2A_OVERFLOW_RENAMES = {2: {"surname": "LEE", "given_names": "SIU MING"},
                         4: {"surname": "HO", "given_names": "KA YAN"},
                         5: {"surname": "WONG", "given_names": "SIU MING"}}


def _item(key, new, when, label=None):
    return {"key": key, "label": label or key, "new": new, "effective_date": when,
            "omitted": False}


def _np_change(world, bean):
    registered = {
        "party_type": "individual", "name_zh": _v(bean, "indvChiName"),
        "name_en": {"surname": _v(bean, "indvEngSname"),
                    "given_names": _v(bean, "indvEngOname")},
        "hkid": _full_hkid(_v(bean, "indvHkidPartial")),
        "passport": ({"number": _full_passport(_v(bean, "indvPptNoPartial")),
                      "issuing_country": "GB"} if _v(bean, "indvPptNoPartial") else None),
    }
    items = []
    if _v(bean, "indvNewChiNameEffDt"):
        items.append(_item("name_zh", _v(bean, "indvNewChiName"), _v(bean, "indvNewChiNameEffDt")))
    if _v(bean, "indvNewEngNameEffDt"):
        items.append(_item("name_en", {"surname": _v(bean, "indvNewEngSname"),
                                       "given_names": _v(bean, "indvNewEngOname")},
                           _v(bean, "indvNewEngNameEffDt")))
    if _v(bean, "indvNewAlsNameEffDt"):
        items.append(_item("alias", {"alias_zh": _v(bean, "indvNewAlsChiName"),
                                     "alias_en": _v(bean, "indvNewAlsEngName")},
                           _v(bean, "indvNewAlsNameEffDt")))
    if _v(bean, "indvNewAddrEffDt"):
        items.append(_item("correspondence_address", _address(bean, "indvNewAddr"),
                           _v(bean, "indvNewAddrEffDt")))
    if _v(bean, "indvNewEmailAddrEffDt"):
        items.append(_item("email", _v(bean, "indvNewEmailAddr"), _v(bean, "indvNewEmailAddrEffDt")))
    if _v(bean, "indvNewHkidNoEffDt"):
        items.append(_item("hkid", _v(bean, "indvNewHkidNo") + _v(bean, "indvNewHkidChkDgt"),
                           _v(bean, "indvNewHkidNoEffDt")))
    if _v(bean, "indvNewPptNoEffDt"):
        items.append(_item("passport", {"number": _v(bean, "indvNewPptNo"),
                                        "issuing_country": to_alpha2(_v(bean, "indvNewPptIssCtry"))},
                           _v(bean, "indvNewPptNoEffDt")))
    if _v(bean, "indvNewTcspNoEffDt"):
        items.append(_item("tcsp", {"licence_no": _v(bean, "indvNewTcspNo"),
                                    "exemption_reason": _v(bean, "indvNewTcspLicNotReqRsn")},
                           _v(bean, "indvNewTcspNoEffDt")))
    if _v(bean, "indvNewResAddrEffDt"):
        items.append(_item("residential_address", _address(bean, "indvNewResAddr"),
                           _v(bean, "indvNewResAddrEffDt")))
    world.entries.append({"id": world._id("N"), "kind": "change",
                          "capacity": _CPTY[_v(bean, "cpty")], "party_type": "individual",
                          "person_id": world.person(), "registered": registered,
                          "items": items})


def _bc_change(world, bean):
    cid = world.entity(br_number=_v(bean, "corpBrNo"))
    registered = {"party_type": "corporate",
                  "name": {"name": _v(bean, "corpEngName"), "name_zh": _v(bean, "corpChiName")}}
    items = []
    if _v(bean, "corpNewNameEffDt"):
        items.append(_item("name", {"name": _v(bean, "corpNewEngName"),
                                    "name_zh": _v(bean, "corpNewChiName")},
                           _v(bean, "corpNewNameEffDt")))
    if _v(bean, "corpNewAddrEffDt"):
        items.append(_item("address", _address(bean, "corpNewAddr"), _v(bean, "corpNewAddrEffDt")))
    if _v(bean, "corpNewEmailAddrEffDt"):
        items.append(_item("email", _v(bean, "corpNewEmailAddr"), _v(bean, "corpNewEmailAddrEffDt")))
    if _v(bean, "corpNewTcspNoEffDt"):
        items.append(_item("tcsp", {"licence_no": _v(bean, "corpNewTcspNo"),
                                    "exemption_reason": _v(bean, "corpNewTcspLicNotReqRsn")},
                           _v(bean, "corpNewTcspNoEffDt")))
    world.entries.append({"id": world._id("N"), "kind": "change",
                          "capacity": _CPTY[_v(bean, "cpty") or "S"], "party_type": "corporate",
                          "corporate_entity_id": cid, "registered": registered, "items": items})

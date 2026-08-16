"""G-FlowDesk entity graph -> the CR-schema dict build_nar1_xml() consumes.

Pure functions: dict in, dict out, no I/O. The same reason nar1.py is pure --
CR's TEST form APIs are open Mon-Fri 10:00-16:00 HKT, so the riskiest logic in
the system has to be provable without them.

SHAPE SOURCE OF TRUTH, in this order and no other (spec §5 BE-1):
  1. docs/Web Form Example/validateForm/validate_NAR1(*).xml   -- CR's own
  2. the parameter worksheet baked into nar1_schema.json
  3. the API .docx (whose embedded examples are known to be wrong)
NEVER NAR1_Data_Specification.v1.4.xls -- those are web-UI fields, not the XML,
and a builder written from it produces documents CR rejects.

Where 1 and 2 disagree, 1 wins. Specifically: the worksheet marks
dateReturnFrom / dateReturnTo / selectPersonId / selectPersonName /
selectCapacityDesc / signatoryDate mandatory and CR's shipped example contains
none of them, so this mapper emits none of them.
"""

#: country/region -> CR's ctryRegion code (max 4 chars). Deliberately a fixed
#: table, not a library: an unknown country must FAIL, because the alternative
#: is a plausible-looking guess that CR rejects after the fee is taken.
_COUNTRY_CODES = {
    "hong kong": "HKG", "hongkong": "HKG", "hk": "HKG", "hkg": "HKG",
    "china": "CHN", "prc": "CHN", "macau": "MAC", "macao": "MAC",
    "taiwan": "TWN", "singapore": "SGP", "malaysia": "MYS", "japan": "JPN",
    "south korea": "KOR", "korea": "KOR", "india": "IND", "australia": "AUS",
    "new zealand": "NZL", "canada": "CAN", "united states": "USA",
    "united states of america": "USA", "usa": "USA", "us": "USA",
    "united kingdom": "GBR", "uk": "GBR", "britain": "GBR",
    "british virgin islands": "VGB", "bvi": "VGB", "cayman islands": "CYM",
    "samoa": "WSM", "seychelles": "SYC", "germany": "DEU", "france": "FRA",
    "netherlands": "NLD", "switzerland": "CHE", "thailand": "THA",
    "vietnam": "VNM", "indonesia": "IDN", "philippines": "PHL",
}

#: allotteeType, per CR's example.
_ALLOTTEE_INDIVIDUAL = "I"
_ALLOTTEE_CORPORATE = "C"

#: shType 1 = fully paid, 2 = partly paid (CR's example uses both).
_SHTYPE_FULLY_PAID = "1"
_SHTYPE_PARTLY_PAID = "2"


class MappingError(Exception):
    """The entity cannot be expressed as a NAR1 — every problem at once.

    Every problem, not the first: CR returns a full fault list and so should we,
    or the user fixes one field per round trip against an API that is open six
    hours a day.
    """

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def _country_code(country: str | None, problems: list[str], where: str) -> str:
    if not country:
        # HK is the overwhelming default and the only place a company can have
        # a registered office, so a blank is HK rather than a hard failure.
        return "HKG"
    code = _COUNTRY_CODES.get(country.strip().lower())
    if code is None:
        problems.append(
            f"{where}: no CR region code is known for country {country!r} — "
            "add it to nar1_mapper._COUNTRY_CODES rather than guessing"
        )
        return ""
    return code


def _address(addr: dict | None, problems: list[str], where: str) -> dict:
    """CR's five address lines. G-FlowDesk stores seven fields; the district
    line absorbs city, region and postcode because CR has one box for all
    three and separating them there loses the postcode entirely."""
    if not addr:
        problems.append(f"{where}: no address on record")
        return {}
    district = " ".join(
        part for part in (addr.get("city"), addr.get("state_region"),
                          addr.get("postal_code")) if part
    )
    return {
        # E = the address is written in English. G-FlowDesk holds *_zh variants
        # but the NAR1 is filed in one language and `language` is already E.
        "addrLangInd": "E",
        "flatFlrBlk": addr.get("line1") or "",
        "bldg": addr.get("line2") or "",
        "stEstLotVlg": addr.get("line3") or "",
        "dstCtyStatePostal": district,
        "ctryRegion": _country_code(addr.get("country"), problems, where),
    }


def _identity(docs: list[dict]) -> dict:
    """HKID if there is one, otherwise a passport. CR takes one or the other.

    The bracketed check digit is stripped: indvHkidNo is 8 characters and
    "A123456(7)" is 10, so sending it raw fails on length.
    """
    if not docs:
        return {}
    primary = next((d for d in docs if d.get("is_primary")), docs[0])
    hkid = next((d for d in docs if d.get("id_type") == "hkid"), None)
    if hkid:
        digits = "".join(c for c in hkid["id_number"] if c.isalnum())
        return {"indvHkidNo": digits.upper()}
    passport = next((d for d in docs if d.get("id_type") == "passport"), primary)
    if passport.get("id_type") != "passport":
        return {}
    out = {"indvPptNo": passport["id_number"]}
    code = _COUNTRY_CODES.get((passport.get("issuing_country") or "").strip().lower())
    if code:
        out["indvPptIssCtry"] = code
    return out


def _individual(person: dict, addresses: dict, identity_documents: dict,
                problems: list[str]) -> dict:
    where = f"person {person.get('full_name') or person.get('id')}"
    block = {
        "indvChiName": person.get("full_name_zh") or "",
        "indvEngSname": person.get("surname") or "",
        "indvEngOname": person.get("given_names") or "",
        "stdAddress": _address(
            addresses.get(person.get("residential_address_id")), problems, where
        ),
    }
    if person.get("former_name"):
        block["indvPrevEngName"] = person["former_name"]
    if person.get("email"):
        block["indvEmailAddr"] = person["email"]
    block.update(_identity(identity_documents.get(person["id"], [])))
    return {k: v for k, v in block.items() if v not in ("", None, {})}


def _corporate(name: str, addr: dict | None, problems: list[str],
               *, br_no: str | None = None, tcsp_no: str | None = None,
               name_zh: str | None = None, prefix: str = "corp") -> dict:
    block = {
        f"{prefix}ChiName": name_zh or "",
        f"{prefix}EngName": name,
        "stdAddress": _address(addr, problems, f"corporate party {name}"),
    }
    if br_no:
        block[f"{prefix}BrNo"] = br_no
    if tcsp_no:
        block[f"{prefix}TcspNo"] = tcsp_no
    return {k: v for k, v in block.items() if v not in ("", None, {})}


def _officer_lists(graph: dict, problems: list[str]) -> dict:
    persons = graph["persons"]
    addresses = graph["addresses"]
    ids = graph["identity_documents"]
    ro = graph.get("registered_address")

    ind_dir, corp_dir, res_dir, ind_sec, corp_sec = [], [], [], [], []

    # Roles the NAR1 schema has a place for. `authorised_rep` (a valid
    # entity_officers.role) is NOT one of these -- the annual return has no
    # authorised-representative field at all, so that officer never appears in
    # the output. Skipping BEFORE building/validating their block matters:
    # without this, a missing residential address on an authorised-rep-only
    # person would raise a MappingError over data that was never going to be
    # sent, blocking a filing that is otherwise perfectly valid.
    _MAPPED_ROLES = {"director", "reserve_director", "company_secretary"}

    for officer in graph["officers"]:
        if not officer.get("is_current", True):
            continue
        role = officer.get("role")
        if role not in _MAPPED_ROLES:
            continue
        if officer.get("party_type") == "corporate":
            block = _corporate(
                officer.get("corporate_name") or "", ro, problems
            )
            if role == "director":
                # dirInd Y marks a director as opposed to an alternate; CR's
                # example sets it on every director row.
                corp_dir.append({"dirInd": "Y", **block})
            elif role == "company_secretary":
                corp_sec.append(block)
            continue

        person = persons.get(officer.get("person_id"))
        if not person:
            problems.append(f"officer {officer.get('id')}: no person on record")
            continue
        block = _individual(person, addresses, ids, problems)
        if role == "director":
            ind_dir.append({"dirInd": "Y", **block})
        elif role == "reserve_director":
            res_dir.append(block)
        elif role == "company_secretary":
            ind_sec.append(block)

    for sec in graph["secretaries"]:
        if not sec.get("is_current", True):
            continue
        if sec.get("person_id") and persons.get(sec["person_id"]):
            ind_sec.append(_individual(persons[sec["person_id"]], addresses, ids, problems))
            continue
        corp_sec.append(
            _corporate(sec.get("secretary_name") or "", ro, problems,
                       tcsp_no=sec.get("tcsp_number"))
        )

    # Omit an empty wrapper entirely -- build_nar1_xml drops empty lists, and an
    # emitted-but-empty <cr:indDirList/> is not what CR's example shows.
    return {
        key: value
        for key, value in (
            ("indSecList", ind_sec), ("corpSecList", corp_sec),
            ("indDirList", ind_dir), ("corpDirList", corp_dir),
            ("resDirList", res_dir),
        )
        if value
    }


def _schedule_1(graph: dict, problems: list[str]) -> dict:
    """One <share> per class, one <shareHolderGrp> per holding.

    Grouped by class rather than by holder because that is how CR's own example
    nests it, and the grouping is what Schedule 1 is FOR.
    """
    by_class: dict[str, list[dict]] = {}
    for holding in graph["shareholdings"]:
        if not holding.get("is_current", True):
            continue
        by_class.setdefault(holding["share_class_id"], []).append(holding)

    shares = []
    for share_class in graph["share_classes"]:
        holdings = by_class.get(share_class["id"], [])
        if not holdings:
            continue
        groups = []
        for holding in holdings:
            if holding.get("party_type") == "corporate":
                allottee = {
                    "allotteeType": _ALLOTTEE_CORPORATE,
                    "corpEngName": holding.get("corporate_name") or "",
                    "allotteeAddr": _address(
                        graph.get("registered_address"), problems,
                        f"shareholder {holding.get('corporate_name')}"
                    ),
                }
            else:
                person = graph["persons"].get(holding.get("person_id"))
                if not person:
                    problems.append(
                        f"shareholding {holding.get('id')}: no person on record"
                    )
                    continue
                allottee = {
                    "allotteeType": _ALLOTTEE_INDIVIDUAL,
                    "indvChiName": person.get("full_name_zh") or "",
                    "indvSurname": person.get("surname") or "",
                    "indvOtherName": person.get("given_names") or "",
                    "allotteeAddr": _address(
                        graph["addresses"].get(person.get("residential_address_id")),
                        problems, f"shareholder {person.get('full_name')}"
                    ),
                }
            paid = holding.get("amount_paid")
            groups.append({
                "sharesAlloted": int(holding.get("shares_held") or 0),
                # Partly paid only when the record says so. Defaulting to fully
                # paid when amount_paid is unknown matches how the register is
                # kept: a blank means nothing outstanding was recorded.
                "shType": (
                    _SHTYPE_PARTLY_PAID
                    if paid is not None and float(paid) < float(holding.get("shares_held") or 0)
                    else _SHTYPE_FULLY_PAID
                ),
                "allotteeRec": [
                    {k: v for k, v in allottee.items() if v not in ("", None, {})}
                ],
            })
        shares.append({
            "clsOfShares": share_class["class_name"],
            "shareHolderGrps": groups,
        })
    return {"shares": shares}


def map_entity(graph: dict, *, year: int) -> dict:
    """The CR-schema dict for one entity's annual return.

    `graph` is what nar1_source.load_entity_graph() returns.
    `year`  is yearAnnualReturn — the return's own year, not today's.
    """
    problems: list[str] = []
    entity = graph["entity"]

    if not entity.get("br_number"):
        problems.append("entity: no BR number — CR rejects a NAR1 without one")

    data: dict = {
        # Filed in English. G-FlowDesk holds Chinese variants but a NAR1 carries
        # one language indicator and CR's example sends E.
        "language": "E",
        "brNo": entity.get("br_number") or "",
        "yearAnnualReturn": year,
        "roAddr": _address(graph.get("registered_address"), problems,
                           "registered office"),
    }
    if entity.get("company_name"):
        data["compNameE"] = entity["company_name"]
    if entity.get("company_name_zh"):
        data["compNameC"] = entity["company_name_zh"]

    data.update(_officer_lists(graph, problems))

    share_capitals = [
        {
            "clsOfShares": sc["class_name"],
            "currency": sc.get("currency") or "HKD",
            "noOfShareIssuedOnThisCls": int(sc.get("total_issued") or 0),
            "issuedCapital": int(sc.get("total_issued") or 0),
            "paidUpCapital": int(sc.get("total_paid") or 0),
        }
        for sc in graph["share_classes"]
    ]
    if share_capitals:
        data["shareCapitals"] = share_capitals

    # A private HK company lists its members in Schedule 1. Schedule 2 is for
    # listed companies and the CD-ROM option is for very large registers;
    # neither applies to anything GSHK files (spec: R1 is private companies).
    data["shareholderListedInSch1"] = "Y"
    data["shareholderListedInSch2"] = "N"
    data["shareholderListedInCdrom"] = "N"
    data["schedule1"] = _schedule_1(graph, problems)

    if problems:
        raise MappingError(problems)
    return data

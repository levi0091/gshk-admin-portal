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

Where 1 and 2 disagree, 1 wins. Exactly TWO fields are covered by that rule:
dateReturnFrom and dateReturnTo. The worksheet marks both mandatory, but both
of its remarks end "(Non Private Company)" and CR's shipped private-company
example omits them, so a private-company NAR1 emits neither.

Nothing else is omitted on that basis. In particular the statutory signatory
block -- selectCapacityDesc / selectPersonId / selectPersonName / signatoryDate
-- IS emitted: it is mandatory in the worksheet AND present in CR's example
(lines 236-239), so the two sources agree. nar1.validate() enforces max_length
but never `mandatory`, so an unsigned return would pass every local gate and
fail no earlier than CR's server, after the fee is taken.

KNOWN LIMITATION -- joint shareholders. CR files joint holders as ONE
<shareHolderGrp> with shType=2 and N <allottee> children (see the Preference
class in the example). G-FlowDesk's `shareholdings` table (migration 003) has
no column saying "these rows hold the same block jointly", so with today's data
every group has exactly one allottee and shType is always "1". The mapper
groups on an optional `joint_group_id` key on the holding row so that the day
that column lands, joint members file the way CR's example shows instead of
being silently split into separate sole holdings.
"""
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

#: HKT is a fixed UTC+8 offset with no DST (since 1979), so a fixed-offset
#: tzinfo is exact and, unlike zoneinfo, needs no tz database -- Windows ships
#: none and `tzdata` is not a dependency of this project. The DB server runs
#: UTC, which is the wrong calendar day in Hong Kong for eight hours of every
#: twenty-four, so a naive date.today() would date-stamp filings wrongly.
_HKT = timezone(timedelta(hours=8))

#: CR's date format, per signatoryDate in the example: 01/06/2022.
_CR_DATE_FORMAT = "%d/%m/%Y"
_CR_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")

#: selectCapacityDesc for the default signatory. Per Q-030 GSHK signs on the
#: client's behalf, and it does so in its capacity as company secretary.
_CAPACITY_COMPANY_SECRETARY = "Company Secretary"

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

#: indvHkidNo max_length in the worksheet. A stripped HKID longer than this is
#: caught here, where the intent to strip lives, not only by nar1.validate().
_HKID_MAX_LENGTH = 8

#: shType is the SHAREHOLDER TYPE of a shareHolderGrp, not a payment state:
#: "1" = sole shareholder, "2" = joint (worksheet: "Shareholder Type: 1 -
#: Individual Shareholder, 2 - Joint Shareholder"). CR's example has a shType=1
#: group whose only allottee is corporate (lines 172-191), so "1" means ONE
#: holder, not "natural person". It is a function of the allottee count and
#: nothing else -- amount_paid has no bearing on it.
_SHTYPE_SOLE = "1"
_SHTYPE_JOINT = "2"


class MappingError(Exception):
    """The entity cannot be expressed as a NAR1 — every problem at once.

    Every problem, not the first: CR returns a full fault list and so should we,
    or the user fixes one field per round trip against an API that is open six
    hours a day.
    """

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def _decimal(value, problems: list[str], where: str) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, ValueError):
        problems.append(f"{where}: {value!r} is not a number")
        return Decimal(0)


def _as_whole_number(amount: Decimal, value, problems: list[str],
                     where: str) -> int:
    """Every share/capital field in the worksheet is an Integer, but the columns
    behind them are numeric(20,4). int() would silently truncate a value CR
    cannot represent, so a fraction is a problem rather than a rounding.

    Takes an ALREADY-PARSED Decimal so a caller that also needs the value as a
    Decimal parses it once — parsing twice reports one unparseable number as two
    identical problems.
    """
    if amount != amount.to_integral_value():
        problems.append(
            f"{where}: {value!r} is not a whole number and the CR field is an "
            "Integer — filing it would silently drop the fraction"
        )
        return 0
    return int(amount)


def _whole_number(value, problems: list[str], where: str) -> int:
    return _as_whole_number(_decimal(value, problems, where), value, problems,
                            where)


def _hk_today() -> date:
    return datetime.now(_HKT).date()


def _format_date(value, problems: list[str], where: str) -> str:
    """CR's DD/MM/YYYY. Anything unparseable is a problem, never a guess."""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime(_CR_DATE_FORMAT)
    text = str(value or "").strip()
    if _CR_DATE_RE.match(text):
        return text
    try:
        # Postgres/JSON hands dates over as ISO 'YYYY-MM-DD' (or a timestamp).
        return date.fromisoformat(text[:10]).strftime(_CR_DATE_FORMAT)
    except ValueError:
        problems.append(
            f"{where}: {value!r} is not a date CR can read (DD/MM/YYYY)"
        )
        return ""


def _country_code(country: str | None, problems: list[str], where: str,
                  default: str = "") -> str:
    if not country:
        # `default` is "HKG" at exactly ONE call site: roAddr, the registered
        # office of a Hong Kong company. Everywhere else -- directors'
        # residential addresses, shareholders' addresses, corporate parties --
        # a blank is a blank, and defaulting it would file a UK-resident
        # director as resident in Hong Kong. Silently, and CR would accept it.
        if default:
            return default
        problems.append(
            f"{where}: no country on the address, and a blank country may only "
            "be assumed to be Hong Kong for the registered office"
        )
        return ""
    code = _COUNTRY_CODES.get(country.strip().lower())
    if code is None:
        problems.append(
            f"{where}: no CR region code is known for country {country!r} — "
            "add it to nar1_mapper._COUNTRY_CODES rather than guessing"
        )
        return ""
    return code


def _address(addr: dict | None, problems: list[str], where: str,
             *, default_country: str = "") -> dict:
    """CR's five address lines. G-FlowDesk stores seven fields; the district
    line absorbs city, region and postcode because CR has one box for all
    three and separating them there loses the postcode entirely.

    `default_country` is passed only by the roAddr call site — see
    _country_code().
    """
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
        "ctryRegion": _country_code(addr.get("country"), problems, where,
                                    default_country),
    }


def _identity(docs: list[dict], problems: list[str], where: str) -> dict:
    """HKID if there is one, otherwise a passport. CR takes one or the other.

    The bracketed check digit is stripped: indvHkidNo is 8 characters and
    "A123456(7)" is 10, so sending it raw fails on length.

    A person with NO document at all is fine — indvHkidNo and indvPptNo are
    both mandatory:false. A person whose only documents are `china_id` or
    `other` is NOT: the NAR1 has no field for either (checked node by node
    against nar1_schema.json), so filing them means filing no identity number
    at all, and that must be said out loud rather than dropped.
    """
    if not docs:
        return {}
    hkid = next((d for d in docs if d.get("id_type") == "hkid"), None)
    if hkid:
        digits = "".join(c for c in str(hkid.get("id_number") or "")
                         if c.isalnum()).upper()
        if len(digits) > _HKID_MAX_LENGTH:
            problems.append(
                f"{where}: HKID {digits!r} is {len(digits)} characters after "
                f"stripping punctuation and indvHkidNo takes "
                f"{_HKID_MAX_LENGTH} — check the number on record"
            )
        return {"indvHkidNo": digits}
    passport = next((d for d in docs if d.get("id_type") == "passport"), None)
    if passport is None:
        kinds = sorted({str(d.get("id_type")) for d in docs})
        problems.append(
            f"{where}: identity document type(s) {', '.join(kinds)} — the NAR1 "
            "carries only indvHkidNo and indvPptNo, so this person would be "
            "filed with no identity number at all; record a HKID or passport"
        )
        return {}
    # .get(), like every other column read in this helper: a null id_number is
    # a KeyError -> an unhandled 500, not a fault the caller can act on.
    # indvPptNo is mandatory:false, so an absent number is omitted downstream by
    # the same filter that drops it for a person with no document at all.
    number = str(passport.get("id_number") or "")
    out = {"indvPptNo": number}
    code = _COUNTRY_CODES.get((passport.get("issuing_country") or "").strip().lower())
    # Only alongside a number: indvPptIssCtry on its own declares the issuer of
    # a passport the return does not name.
    if code and number:
        out["indvPptIssCtry"] = code
    return out


def _identity_number(docs: list[dict]) -> str:
    """The raw number behind _identity(), for selectPersonId.

    Same precedence as _identity() so the signatory block and the officer block
    never disagree about which document identifies a person.
    """
    hkid = next((d for d in docs if d.get("id_type") == "hkid"), None)
    if hkid:
        return "".join(c for c in str(hkid.get("id_number") or "")
                       if c.isalnum()).upper()
    passport = next((d for d in docs if d.get("id_type") == "passport"), None)
    return str(passport.get("id_number") or "") if passport else ""


def _signatory_candidates(graph: dict) -> list[dict]:
    """Who may sign, best first.

    GSHK-flagged secretary before any other (Q-030: GSHK signs on the client's
    behalf), and a `company_secretaries` row before a secretary that exists only
    as an entity_officers row, because the former is the record GSHK maintains.
    """
    secretaries = [s for s in graph.get("secretaries") or []
                   if s.get("is_current", True)]
    officer_secs = [o for o in graph.get("officers") or []
                    if o.get("is_current", True)
                    and o.get("role") == "company_secretary"]
    return (
        [s for s in secretaries if s.get("is_gshk")]
        + [s for s in secretaries if not s.get("is_gshk")]
        + officer_secs
    )


def _derive_signatory(graph: dict) -> dict | None:
    persons = graph.get("persons") or {}
    ids = graph.get("identity_documents") or {}
    for row in _signatory_candidates(graph):
        person = persons.get(row.get("person_id"))
        if person:
            return {
                "name": person.get("full_name") or person.get("full_name_zh") or "",
                "capacity": _CAPACITY_COMPANY_SECRETARY,
                "person_id": _identity_number(ids.get(person["id"], [])),
                "date": None,
                "is_corporate": False,
            }
        name = row.get("secretary_name") or row.get("corporate_name") or ""
        if name:
            return {
                "name": name,
                "capacity": _CAPACITY_COMPANY_SECRETARY,
                "person_id": None,
                "date": None,
                "is_corporate": True,
            }
    return None


def _signatory_block(graph: dict, signatory: dict | None,
                     problems: list[str]) -> dict:
    """The statutory declaration: who signed, in what capacity, when.

    An absent block is not a smaller filing, it is an UNSIGNED filing -- and
    nar1.validate() would wave it through, because it checks max_length and
    never `mandatory`. So a signatory that cannot be resolved is a MappingError.
    """
    resolved = signatory if signatory is not None else _derive_signatory(graph)
    if not resolved or not str(resolved.get("name") or "").strip():
        problems.append(
            "signatory: no current company secretary on record to sign the "
            "return — a NAR1 without selectPersonName / selectCapacityDesc / "
            "signatoryDate is an unsigned statutory declaration; record the "
            "secretary or pass signatory= explicitly"
        )
        return {}

    block = {
        "selectCapacityDesc": (resolved.get("capacity")
                               or _CAPACITY_COMPANY_SECRETARY),
        "selectPersonName": str(resolved["name"]).strip(),
        "signatoryDate": _format_date(
            resolved.get("date") or _hk_today(), problems, "signatoryDate"
        ),
    }
    person_id = str(resolved.get("person_id") or "").strip()
    if person_id:
        block["selectPersonId"] = person_id
    elif resolved.get("is_corporate") is not True:
        # Worksheet remark: "Signatory User ID (Empty if sign by Body
        # Corporate)". Empty is CORRECT for a corporate secretary and MISSING
        # for a natural person, so only the latter is a problem.
        # `is not True`, not `is False`: an explicit signatory= override need
        # not carry `is_corporate` at all, and an absent key must NOT read as
        # "body corporate" -- that would let the caller drop a mandatory
        # statutory field by omission, which nar1.validate() would wave through.
        # An unstated kind is a natural person and must supply an id.
        problems.append(
            f"signatory {block['selectPersonName']}: signs as a natural person "
            "but has no identity document on record, and selectPersonId is "
            "mandatory for a signatory who is not a body corporate"
        )
    return {k: v for k, v in block.items() if v}


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
    block.update(_identity(identity_documents.get(person["id"], []), problems, where))
    return {k: v for k, v in block.items() if v not in ("", None, {})}


def _corporate(name: str, addr: dict | None, problems: list[str],
               *, br_no: str | None = None, tcsp_no: str | None = None,
               name_zh: str | None = None, default_country: str = "") -> dict:
    """A corporate officer/secretary block.

    `addr` is the corporate party's OWN registered office. It is never the
    filing entity's — that would put a wrong address on a statutory return,
    and CR's schema gate would accept it. A missing one is a problem, and a
    problem is a MappingError.

    `default_country` is passed by exactly one caller: the GSHK secretary,
    which files the filing company's registered office (see _officer_lists).
    It is literally the same dict roAddr is built from, so it must resolve a
    blank country the same way — otherwise the roAddr default is unreachable
    in production, because every GSHK-managed company has a GSHK secretary.
    """
    block = {
        "corpChiName": name_zh or "",
        "corpEngName": name,
        "stdAddress": _address(addr, problems, f"corporate party {name}",
                               default_country=default_country),
    }
    if br_no:
        block["corpBrNo"] = br_no
    if tcsp_no:
        block["corpTcspNo"] = tcsp_no
    return {k: v for k, v in block.items() if v not in ("", None, {})}


def _officer_lists(graph: dict, problems: list[str]) -> dict:
    persons = graph["persons"]
    addresses = graph["addresses"]
    ids = graph["identity_documents"]
    ro = graph.get("registered_address")

    ind_dir, corp_dir, res_dir, ind_sec, corp_sec = [], [], [], [], []

    # A secretary can be recorded in BOTH tables -- officer_role includes
    # 'company_secretary' -- and two indSec/corpSec entries for one secretary is
    # a false return. Dedup on person_id, falling back to a normalised name for
    # the rows (corporate secretaries) that have none.
    seen_secretaries: set = set()

    def _sec_key(person_id=None, name=None) -> tuple:
        if person_id:
            return ("person", str(person_id))
        return ("name", " ".join(str(name or "").split()).casefold())

    def _first_secretary(key: tuple) -> bool:
        if key in seen_secretaries:
            return False
        seen_secretaries.add(key)
        return True

    # The secretary register is walked FIRST: it is the record GSHK maintains
    # and the only one carrying the TCSP number, so when the same secretary
    # appears in both tables this is the row that should survive.
    for sec in graph["secretaries"]:
        if not sec.get("is_current", True):
            continue
        person = persons.get(sec.get("person_id")) if sec.get("person_id") else None
        if person:
            if _first_secretary(_sec_key(person_id=person["id"])):
                ind_sec.append(_individual(person, addresses, ids, problems))
            continue
        name = sec.get("secretary_name") or ""
        if not _first_secretary(_sec_key(name=name)):
            continue
        # `company_secretaries` has no corporate_entity_id -- migration 007 put
        # that FK on entity_officers / shareholdings / beneficial_owners only --
        # so a corporate secretary has no address of its own to file. For the
        # GSHK secretary the filing company's registered office IS GSHK's own
        # address by construction (GSHK provides the registered office), so `ro`
        # is defensible there and nowhere else: any other body corporate falls
        # through to _address(None) and becomes a problem rather than a guess.
        # ASSUMPTION, load-bearing: this holds only while GSHK provides the
        # registered office. A client keeping its own would be misfiled here,
        # and the real fix is a corporate_entity_id on company_secretaries —
        # logged as a follow-up migration, deliberately not written here.
        corp_addr = sec.get("corporate_address")
        ro_default = ""
        if corp_addr is None and sec.get("is_gshk"):
            corp_addr = ro
            # Same dict as roAddr, so it must resolve a blank country the same
            # way — see _corporate().
            ro_default = "HKG"
        corp_sec.append(
            _corporate(name, corp_addr, problems, tcsp_no=sec.get("tcsp_number"),
                       default_country=ro_default)
        )

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
            name = officer.get("corporate_name") or ""
            # Dedup BEFORE building the block: a duplicate that happens to be
            # missing its address would otherwise raise on data we discard.
            if role == "company_secretary" and not _first_secretary(_sec_key(name=name)):
                continue
            # The corporate party's OWN address, attached by nar1_source via
            # entity_officers.corporate_entity_id (migration 007). Never `ro`.
            block = _corporate(
                name,
                officer.get("corporate_address"),
                problems,
                br_no=officer.get("corporate_br_no"),
                name_zh=officer.get("corporate_name_zh"),
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
        if role == "company_secretary" and not _first_secretary(
                _sec_key(person_id=person["id"])):
            continue
        block = _individual(person, addresses, ids, problems)
        if role == "director":
            ind_dir.append({"dirInd": "Y", **block})
        elif role == "reserve_director":
            res_dir.append(block)
        elif role == "company_secretary":
            ind_sec.append(block)

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


def _allottee(holding: dict, graph: dict, problems: list[str]) -> dict | None:
    if holding.get("party_type") == "corporate":
        # The shareholder's OWN address, attached by nar1_source via
        # shareholdings.corporate_entity_id (migration 007). Filing the filer's
        # registered office here would put a wrong address in the statutory
        # register of members.
        allottee = {
            "allotteeType": _ALLOTTEE_CORPORATE,
            "corpChiName": holding.get("corporate_name_zh") or "",
            "corpEngName": holding.get("corporate_name") or "",
            "allotteeAddr": _address(
                holding.get("corporate_address"), problems,
                f"shareholder {holding.get('corporate_name')}"
            ),
        }
    else:
        person = graph["persons"].get(holding.get("person_id"))
        if not person:
            problems.append(
                f"shareholding {holding.get('id')}: no person on record"
            )
            return None
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
    return {k: v for k, v in allottee.items() if v not in ("", None, {})}


def _joint_key(holding: dict):
    """Holdings sharing a joint_group_id are ONE block held jointly.

    G-FlowDesk's `shareholdings` table has no such column yet (migration 003),
    so with today's data every holding keys uniquely and every group is sole.
    Grouping on it anyway means the day the column lands, joint members file as
    CR's example shows instead of being silently split into separate holdings.
    """
    gid = holding.get("joint_group_id")
    return ("joint", gid) if gid else ("sole", id(holding))


def _schedule_1(graph: dict, problems: list[str]) -> dict:
    """One <share> per class, one <shareHolderGrp> per (jointly) held block.

    Grouped by class rather than by holder because that is how CR's own example
    nests it, and the grouping is what Schedule 1 is FOR.
    """
    by_class: dict[str, list[dict]] = {}
    for holding in graph["shareholdings"]:
        if not holding.get("is_current", True):
            continue
        by_class.setdefault(holding["share_class_id"], []).append(holding)

    shares = []
    consumed: set = set()
    for share_class in graph["share_classes"]:
        holdings = by_class.get(share_class["id"], [])
        consumed.add(share_class["id"])
        blocks: dict = {}
        for holding in holdings:
            blocks.setdefault(_joint_key(holding), []).append(holding)

        cls_name = share_class.get("class_name")
        groups = []
        allotted = Decimal(0)
        for members in blocks.values():
            allottees = [
                rec for rec in
                (_allottee(m, graph, problems) for m in members)
                if rec is not None
            ]
            if not allottees:
                continue
            sizes = {str(m.get("shares_held") or 0) for m in members}
            if len(sizes) > 1:
                problems.append(
                    f"share class {cls_name}: joint holders of one block record "
                    f"different sizes {sorted(sizes)} — a joint block has one "
                    "size, so sharesAlloted is ambiguous"
                )
            # Parsed ONCE and used for both the class total and sharesAlloted:
            # parsing it twice reported one unparseable value as two identical
            # problems, i.e. the same field to fix twice.
            held = members[0].get("shares_held")
            size = _decimal(held, problems, f"share class {cls_name}")
            # A jointly held block counts ONCE towards the class total: two
            # rows holding 2000 jointly is 2000 allotted, not 4000.
            allotted += size
            groups.append({
                "sharesAlloted": _as_whole_number(size, held, problems,
                                                  f"share class {cls_name}"),
                # Derived from the BUILT ALLOTTEE LIST, never from the holding
                # row -- shType is the shareholder TYPE (sole vs joint), not a
                # payment state, and it is a function of the allottee count and
                # nothing else.
                "shType": _SHTYPE_JOINT if len(allottees) > 1 else _SHTYPE_SOLE,
                "allotteeRec": allottees,
            })
        # Schedule 1 IS the register of members, so what it accounts for has to
        # equal what the class says it issued. 1000 issued against 900 allotted
        # is a hundred shares belonging to nobody, and CR accepts it.
        #
        # EVERY loaded class is reconciled, held or not. Gating this on `groups`
        # exempted the extreme case -- a class whose only holding is former, or
        # which has no holding at all -- and that one files an empty Schedule 1
        # while shareCapitals still declares the full issued count.
        issued = _decimal(share_class.get("total_issued"), problems,
                          f"share class {cls_name}")
        if allotted != issued:
            problems.append(
                f"share class {cls_name}: Schedule 1 accounts for {allotted} "
                f"shares but the class records {issued} issued — the register "
                "of members must account for every issued share"
            )

        if not holdings:
            continue
        shares.append({
            "clsOfShares": share_class["class_name"],
            "shareHolderGrps": groups,
        })

    # Every holding must have landed in some class. by_class is keyed off the
    # holdings and the loop above iterates share_classes, so a holding pointing
    # at a class that was never loaded used to vanish without a trace.
    for orphan in set(by_class) - consumed:
        problems.append(
            f"share class {orphan}: {len(by_class[orphan])} current "
            "shareholding(s) point at a share class that is not on record, so "
            "those shareholders would be left off Schedule 1 entirely"
        )
    return {"shares": shares}


def map_entity(graph: dict, *, year: int, signatory: dict | None = None) -> dict:
    """The CR-schema dict for one entity's annual return.

    `graph` is what nar1_source.load_entity_graph() returns.
    `year`  is yearAnnualReturn — the return's own year, not today's.
    `signatory`, when given, overrides the derived signer:
        {"name": str, "capacity": str,
         "person_id": str | None, "date": date | str | None,
         "is_corporate": bool}          # optional, defaults to False
        `date` defaults to today in Asia/Hong_Kong. `person_id` may be left
        empty ONLY for a body corporate, per the worksheet — and only when
        `is_corporate: True` says so. Omitting the key means a natural person,
        so a missing `person_id` is a MappingError rather than a field that
        quietly vanishes from the statutory declaration.
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
        # The ONLY call site that may assume Hong Kong for a blank country.
        "roAddr": _address(graph.get("registered_address"), problems,
                           "registered office", default_country="HKG"),
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
            "noOfShareIssuedOnThisCls": _whole_number(
                sc.get("total_issued"), problems,
                f"share class {sc.get('class_name')} total_issued"),
            "issuedCapital": _whole_number(
                sc.get("total_issued"), problems,
                f"share class {sc.get('class_name')} total_issued"),
            "paidUpCapital": _whole_number(
                sc.get("total_paid"), problems,
                f"share class {sc.get('class_name')} total_paid"),
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
    data.update(_signatory_block(graph, signatory, problems))

    if problems:
        raise MappingError(problems)
    return data

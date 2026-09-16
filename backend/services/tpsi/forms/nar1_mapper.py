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

CONTROLLED VOCABULARIES live in cr_vocabularies.py, transcribed from the same
worksheet and re-verified against it by test:
  * ctryRegion  -- CR's 250 Country & Region codes. NOT ISO alpha-3: Guernsey,
    Jersey and the Isle of Man are GBR1/GBR2/GBR3, which is why the field is
    max_length 4 and why no ISO library may be substituted.
  * selectCapacityDesc -- TWO vocabularies, Individual (5 NAR1 values) and Body
    Corporate (15). They do not overlap, and CR's field is String(500), so a
    value from the wrong list is one CR ACCEPTS.

Three ctryRegion nodes -- roAddr, indSec/stdAddress, corpSec/stdAddress -- carry
the schema remark "Region. Must be HKG" and emit HKG unconditionally. Every
other ctryRegion says "Refer to Country sheet" and is mapped from the record.

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

from services.tpsi.forms.cr_vocabularies import (
    CAPACITY_BODY_CORPORATE,
    CAPACITY_INDIVIDUAL,
    HKG,
    default_capacity,
    resolve_country,
    resolve_district,
)

#: HKT is a fixed UTC+8 offset with no DST (since 1979), so a fixed-offset
#: tzinfo is exact and, unlike zoneinfo, needs no tz database -- Windows ships
#: none and `tzdata` is not a dependency of this project. The DB server runs
#: UTC, which is the wrong calendar day in Hong Kong for eight hours of every
#: twenty-four, so a naive date.today() would date-stamp filings wrongly.
_HKT = timezone(timedelta(hours=8))

#: CR's date format, per signatoryDate in the example: 01/06/2022.
_CR_DATE_FORMAT = "%d/%m/%Y"
_CR_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")

#: ctryRegion comes from CR's own "Country & Region" sheet — all 250 codes, with
#: the alpha-2 form G-FlowDesk stores — see cr_vocabularies.py. Deliberately a
#: committed table and not an ISO library: CR's GBR1/GBR2/GBR3 (Guernsey/Jersey/
#: Isle of Man) are CR's own invention, a library emits GGY/JEY/IMN, and CR
#: rejects those after the fee is taken. An unresolvable country still FAILS.
#:
#: The 38-name table this replaced keyed on English names only, while DEV stores
#: ISO alpha-2 in 100% of its address rows: 6,953 of 8,027 real addresses (87%)
#: could not be filed at all.

#: allotteeType, per CR's example.
_ALLOTTEE_INDIVIDUAL = "I"
_ALLOTTEE_CORPORATE = "C"

#: indvHkidNo carries the PARTIAL HKID, not the full one. Verified live against
#: CR TEST on 2026-08-21: a full 8-character HKID is refused with "HKID No.
#: length must be at most 5", and a 5-character one that is not letters+3-digits
#: with "The partial HKID number is invalid. Please input the partial HKID
#: number correctly, e.g. A123 or XA123."
#:
#: The worksheet's max_length of 8 is WRONG — it describes the full number. CR's
#: own validate_NAR1 example carries "A123", and the CR test workbook has a
#: dedicated "Partial HKID" column ("T001"). Filing the full number would also
#: send CR more personal data than it asks for.
_HKID_MAX_LENGTH = 5

#: One or two letters followed by exactly three digits — CR's own two examples.
_PARTIAL_HKID = re.compile(r"^[A-Z]{1,2}[0-9]{3}$")

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


def _issued_amount(share_class: dict):
    """Section 11's "Total Amount": `issued_amount`, else `total_paid`.

    `is None`, not falsiness: an issued amount of 0 is an answer, and falling
    back past it to the paid figure would file a number nobody entered.
    """
    amount = share_class.get("issued_amount")
    return share_class.get("total_paid") if amount is None else amount


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


def _unknown_country(country, where: str) -> str:
    return (
        f"{where}: no CR region code is known for country {country!r} — "
        "CR's Country & Region sheet (worksheet v1.0.14) carries no code, "
        "alpha-2 or English name matching it; correct the address rather "
        "than guessing a code CR would take the fee for and then reject"
    )


def _country_code(country: str | None, problems: list[str], where: str) -> str:
    """ctryRegion for the nodes whose remark is "Refer to Country sheet".

    Directors, reserve directors and allottees. A blank is a blank here: reading
    it as Hong Kong would file a UK-resident director as resident in Hong Kong,
    silently, and CR would accept it.
    """
    if not country:
        problems.append(
            f"{where}: no country on the address, and a blank country may only "
            "be read as Hong Kong on the three nodes whose schema remark is "
            "'Region. Must be HKG'"
        )
        return ""
    code = resolve_country(country)
    if code is None:
        problems.append(_unknown_country(country, where))
        return ""
    return code


def _hkg_region(country: str | None, problems: list[str], where: str) -> str:
    """ctryRegion for the three nodes whose remark is "Region. Must be HKG".

    roAddr, indSec/stdAddress and corpSec/stdAddress — checked node by node
    against nar1_schema.json; every other ctryRegion in the form says "Refer to
    Country sheet" instead.

    HKG unconditionally, because CR accepts exactly one value here and deriving
    it from the row can only ever produce a rejection. A country that is on
    record and is NOT Hong Kong is still reported: overwriting it in silence
    files a return saying the registered office is in Hong Kong when the
    company's own records say otherwise, and CR's schema gate accepts that.
    """
    if country:
        code = resolve_country(country)
        if code is None:
            problems.append(_unknown_country(country, where))
        elif code != HKG:
            problems.append(
                f"{where}: the address on record is in {country!r} ({code}), "
                f"but CR's schema requires ctryRegion {HKG} on this node "
                "(remark 'Region. Must be HKG') — a Hong Kong company's "
                "registered office and its company secretary's address must "
                "both be in Hong Kong"
            )
    return HKG


def _address(addr: dict | None, problems: list[str], where: str,
             *, hkg_only: bool = False) -> dict:
    """CR's five address lines. G-FlowDesk stores seven fields; the district
    line absorbs city, region and postcode because CR has one box for all
    three and separating them there loses the postcode entirely.

    `hkg_only` marks the three "Region. Must be HKG" nodes — see _hkg_region().
    """
    if not addr:
        problems.append(f"{where}: no address on record")
        return {}
    district = " ".join(
        part for part in (addr.get("city"), addr.get("state_region"),
                          addr.get("postal_code")) if part
    )
    region = _hkg_region if hkg_only else _country_code
    region_code = region(addr.get("country"), problems, where)

    # For a HONG KONG address CR's District is a CONTROLLED CODE, not free
    # text. Proven live 2026-08-27: "WAN CHAI" was refused with
    # "ERR_ES_FORM_INVALID_VALUE: Please input valid District." while "CENTRAL"
    # passed, because the code is the name with its spaces removed — WANCHAI.
    # Refused HERE, naming the value, rather than one CR round trip later.
    # Everywhere else the field really is city/state/postcode free text.
    if region_code == HKG and district:
        code = resolve_district(district)
        if code is None:
            problems.append(
                f"{where}: {district!r} is not a Hong Kong district CR "
                "recognises — dstCtyStatePostal must be one of CR's 125 "
                "District codes for a HKG address"
            )
        district = code or district

    return {
        # E = the address is written in English. G-FlowDesk holds *_zh variants
        # but the NAR1 is filed in one language and `language` is already E.
        "addrLangInd": "E",
        "flatFlrBlk": addr.get("line1") or "",
        "bldg": addr.get("line2") or "",
        "stEstLotVlg": addr.get("line3") or "",
        "dstCtyStatePostal": district,
        "ctryRegion": region_code,
    }


def _partial_hkid(digits: str) -> str | None:
    """The PARTIAL HKID CR wants on a NAR1: leading letters + first 3 digits.

    "A1234567" -> "A123", "XA1234567" -> "XA123". A number already stored in
    partial form passes through unchanged. Returns None when no such form can
    be derived, so the caller reports it rather than filing something CR will
    reject (verified live 2026-08-21).
    """
    if _PARTIAL_HKID.match(digits):
        return digits
    match = re.match(r"^([A-Z]{1,2})([0-9]{3})", digits)
    return f"{match.group(1)}{match.group(2)}" if match else None


def _partial_passport(number: str) -> str:
    """The PARTIAL passport number CR wants, per note 18(a) on the NAR1 itself.

    Count the alphanumeric characters, ignoring spaces, punctuation marks and
    symbols. An EVEN count gives the first half; an ODD count gives the part
    beginning at the first character and ending at the one that falls at the
    middle. Both are ceil(n/2) characters of the cleaned string, which is why
    there is no branch here -- CR states the two cases separately because the
    form is read by people, not because they compute differently.

        ABCD1234567    -> ABCD12    (11 -> 6)
        ABCD12345678   -> ABCD12    (12 -> 6)
        ABCD123456789  -> ABCD123   (13 -> 7)
        ABC-123-4      -> ABC1      (7 after dropping punctuation -> 4)
        #A1234567H(*)  -> A1234     (9 after dropping symbols -> 5)

    Every example above is CR's own. Applied to a HKID the same rule yields
    "all the alphabets and the first three digits", which is what note 18(a)
    says and what `_partial_hkid` produces by a different route.

    WHY THIS EXISTS AT ALL. indvPptNo's remark in CR's worksheet is "Passport
    Number (Partial ID)", and note 18(c) is explicit: "Please DO NOT fill in
    the full identification number in the box provided. Information provided
    in the box is available for public inspection." The HKID half was
    implemented and verified live on 2026-08-21; the passport half was missed,
    so every return produced before this carried a full passport number.

    Returns "" when nothing alphanumeric survives -- the caller reports that
    rather than filing an empty identity box.
    """
    cleaned = "".join(c for c in number if c.isalnum()).upper()
    return cleaned[:(len(cleaned) + 1) // 2]


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
        # CR's escape for a person who genuinely holds neither is the literal
        # NIL -- and it goes in BOTH identity fields at once. CR's own
        # validate_NNC1 example shows the rule with two individuals side by
        # side: the one with a passport carries <hkid></hkid> EMPTY alongside
        # his number, while the one with neither carries hkid=NIL AND
        # passportNo=NIL together, with the issuing country left empty.
        #
        # (An earlier note here claimed CR rejects NIL. That was wrong: NIL was
        # tested in one field at a time with the other omitted, which is why CR
        # kept answering "please input the partial HKID number OR partial
        # passport number". Never verified live for NAR1 -- CR's NAR1 examples
        # all carry a real A123, so they never exercise it.)
        #
        # Still a refusal, deliberately. An ABSENT document row means we do not
        # know, and NIL asserts to the Registry that the person holds no
        # identity document at all -- a statement of fact we have not
        # established. 24 current officers on DEV are in this state; that is
        # chaseable data, not a mapping problem. If GSHK confirms a person
        # genuinely holds neither, that needs recording as such before it can
        # be filed.
        problems.append(
            f"{where}: no HKID or passport on record. CR needs a partial "
            "identity number for every individual, and 'no document on file' "
            "is not the same as 'holds none' — chase the number, or have GSHK "
            "confirm the person holds neither"
        )
        return {}
    hkid = next((d for d in docs if d.get("id_type") == "hkid"), None)
    if hkid:
        digits = "".join(c for c in str(hkid.get("id_number") or "")
                         if c.isalnum()).upper()
        partial = _partial_hkid(digits)
        if partial is None:
            problems.append(
                f"{where}: HKID {digits!r} does not yield a partial number CR "
                "accepts — indvHkidNo on the NAR1 is one or two letters "
                "followed by three digits (e.g. A123 or XA123)"
            )
            return {}
        return {"indvHkidNo": partial}
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
    # It goes through the same resolver as every other country: DEV's
    # person_identity_documents.issuing_country is alpha-2 too, so the old
    # name-only table dropped most of them silently.
    code = resolve_country(passport.get("issuing_country"))
    if not number:
        problems.append(
            f"{where}: passport on record with no number — CR needs a partial "
            "passport number for every individual without a HKID"
        )
        return {}
    # BOTH OR NEITHER. The schema marks indvPptIssCtry mandatory:false, so this
    # used to be omitted when the country would not resolve — but CR refuses
    # that combination outright: "Passport number and issuing country/region
    # should be reported together." (verified live 2026-08-21). An unresolvable
    # issuing country is therefore a problem to report, not a field to drop.
    if not code:
        problems.append(
            f"{where}: passport issuing country "
            f"{passport.get('issuing_country')!r} has no CR code, and CR "
            "refuses a passport number without its issuing country"
        )
        return {}
    # PARTIAL, never the full number -- see _partial_passport. A number made
    # entirely of punctuation masks to nothing, and an empty indvPptNo is the
    # same as filing no identity number at all, so it is reported like every
    # other gap here rather than sent.
    partial = _partial_passport(number)
    if not partial:
        problems.append(
            f"{where}: passport number {number!r} contains no letters or "
            "digits, so it yields no partial number for CR — record the "
            "passport number as it appears on the document"
        )
        return {}
    return {"indvPptNo": partial, "indvPptIssCtry": code}


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
                # The Individual default, from the ONE place every caller
                # takes it (`default_capacity`). This was a hardcoded "Company
                # Secretary" while the Data Verification picker showed blank —
                # the filing and the screen disagreed (Levi 2026-09-14).
                "capacity": default_capacity(is_corporate=False),
                # The e-SERVICE USER ID, not an identity document number.
                #
                # CR proved this live on 2026-08-27: sending the signatory's
                # HKID here was refused with "Please check selectPersonId
                # field." selectPersonId is the signer's e-Filing account, which
                # CR checks is real and authorised for THIS company -- an HKID
                # is neither. D-4 added persons.eservice_user_id for exactly
                # this (an identifier, not a secret, hence plaintext) and the
                # seeder populates it; the mapper simply never read it.
                "person_id": str(person.get("eservice_user_id") or "").strip(),
                "date": None,
                "is_corporate": False,
            }
        name = row.get("secretary_name") or row.get("corporate_name") or ""
        if name:
            return {
                "name": name,
                # NOT "Company Secretary": that is an Individual-vocabulary
                # value and this signatory is a body corporate. Which of CR's
                # 15 Body Corporate values applies depends on who at GSHK signs
                # on its behalf, which nobody has decided -- so the mapper
                # refuses rather than guesses. See _signatory_block().
                "capacity": None,
                "person_id": None,
                # The body corporate's OWN BR, filed as selectAssoBrNo. Carried
                # on the signatory rather than looked up later so an explicit
                # signatory= override can state it — the same completeness
                # `person_id` has for a natural person. Derived here from the
                # officer register, because the `company_secretaries` row this
                # signatory comes from has no corporate_entity_id to resolve.
                "br_no": _corporate_secretary_br(graph),
                "date": None,
                "is_corporate": True,
            }
    return None


def _check_capacity(name: str, capacity: str, is_corporate: bool,
                    problems: list[str]) -> None:
    """selectCapacityDesc is a controlled vocabulary, and there are TWO of them.

    Worksheet remark: "Signatory capacity description. Refer to Capacity sheet
    for description". CR ships "Capacity (Individual)" (5 NAR1 values) and
    "Capacity (Body Coporate)" (15), and they do not overlap: an Individual
    value on a body-corporate signatory is a wrong value CR's schema gate
    ACCEPTS, because the field is just String(500).
    """
    valid = CAPACITY_BODY_CORPORATE if is_corporate else CAPACITY_INDIVIDUAL
    if capacity in valid:
        return
    if not capacity and is_corporate:
        problems.append(
            f"signatory {name}: signs as a body corporate, and a body corporate "
            "signs through a natural person — CR's Capacity (Body Corporate) "
            "vocabulary says which one, e.g. 'Director of the Company Secretary "
            "(Body Corporate)'. GSHK's own default is not decided, so pass "
            "signatory={'capacity': ...} explicitly rather than let the mapper "
            "invent a capacity CR would accept and the filing would misstate"
        )
        return
    kind = "Body Corporate" if is_corporate else "Individual"
    problems.append(
        f"signatory {name}: selectCapacityDesc {capacity!r} is not in CR's "
        f"Capacity ({kind}) vocabulary for a signatory of that kind — CR takes "
        f"any string here and rejects it server-side, after the fee. Valid: "
        + "; ".join(sorted(valid))
    )


#: CR's 15 Body Corporate capacities are "<individual role> of the <corporate
#: role> (Body Corporate)" -- the 5 Individual roles times the 3 corporate ones,
#: exactly. The half BEFORE " of the " is the capacity the signing human holds
#: in the body corporate, and CR requires associatedCapacityDesc to be that
#: value and no other: sending "Company Secretary" against "Director of the
#: Company Secretary (Body Corporate)" is refused with
#:
#:     Capcity is not matched between associate and selected.
#:
#: (CR's spelling). Verified against CR's test register 2026-09-16, so the
#: operator's capacity choice DERIVES this field -- a second picker for it could
#: only ever disagree with the first and produce that error.
_BODY_CORPORATE_JOIN = " of the "


def _associated_capacity(capacity: str) -> str:
    """The signing human's own capacity, from the body-corporate capacity."""
    head = capacity.split(_BODY_CORPORATE_JOIN, 1)[0].strip()
    return head if head in CAPACITY_INDIVIDUAL else ""


def _corporate_secretary_br(graph: dict) -> str:
    """The BR number of the body corporate acting as company secretary.

    CR requires it as selectAssoBrNo and CHECKS it -- a wrong one is refused
    with "The signatory <id> is not authorized to sign the document" (verified
    2026-09-16), so a guess here costs a round trip and reads as an
    authorisation problem rather than a wrong number.

    Read from entity_officers, NOT from the `company_secretaries` row the
    signatory itself comes from: migration 007 put `corporate_entity_id` on
    entity_officers only, and nar1_source resolves it to `corporate_br_no`
    there. THE TWO ROWS CANNOT BE MATCHED BY NAME -- on the live register the
    same secretary is 'Get Started HK Limited' in company_secretaries and
    'GETSTA' in entity_officers -- so the officer register is asked on its own
    terms. More than one distinct BR is an ambiguity for a human to resolve,
    never a coin toss: 5,970 of the 5,971 companies holding a secretary row
    have exactly one, and the one that does not should stop rather than file a
    guess.
    """
    numbers = {
        str(officer.get("corporate_br_no") or "").strip()
        for officer in (graph.get("officers") or [])
        if officer.get("is_current", True)
        and officer.get("role") == "company_secretary"
        and officer.get("party_type") == "corporate"
        and str(officer.get("corporate_br_no") or "").strip()
    }
    return numbers.pop() if len(numbers) == 1 else ""


def _signatory_block(graph: dict, signatory: dict | None,
                     problems: list[str],
                     capacity_override: str | None = None,
                     signing_identity: dict | None = None) -> dict:
    """The statutory declaration: who signed, in what capacity, when.

    An absent block is not a smaller filing, it is an UNSIGNED filing -- and
    nar1.validate() would wave it through, because it checks max_length and
    never `mandatory`. So a signatory that cannot be resolved is a MappingError.

    `capacity_override` sets selectCapacityDesc on whoever is resolved, and
    changes nothing else. It is a SEPARATE argument from `signatory` on purpose.
    Merging a partial dict into the derived signatory would have been the
    obvious alternative and is quietly unsafe: `signatory` is documented so that
    an ABSENT key means something -- no `is_corporate` means a natural person,
    and a natural person with no `person_id` is a MappingError rather than a
    statutory field that vanishes. A merge would let those absent keys be
    filled in from the derived signer, so a caller who meant to override the
    whole signer would silently inherit half of another one.

    This exists because the capacity is the ONE thing about a GSHK-signed
    return that the portal cannot derive: the company secretary is a body
    corporate, and which of CR's 15 Body Corporate values applies depends on
    who at GSHK signs on its behalf. That is now an operator choice on the Data
    Verification stage rather than a refusal (Levi 2026-08-30).
    """
    resolved = signatory if signatory is not None else _derive_signatory(graph)
    if capacity_override and resolved:
        resolved = {**resolved, "capacity": capacity_override}
    if not resolved or not str(resolved.get("name") or "").strip():
        problems.append(
            "signatory: no current company secretary on record to sign the "
            "return — a NAR1 without selectPersonName / selectCapacityDesc / "
            "signatoryDate is an unsigned statutory declaration; record the "
            "secretary or pass signatory= explicitly"
        )
        return {}

    is_corporate = resolved.get("is_corporate") is True
    name = str(resolved["name"]).strip()
    capacity = str(resolved.get("capacity") or "").strip()
    if not capacity and not is_corporate:
        # A natural person with no capacity takes the Individual default --
        # the same value the picker shows. A body corporate still gets none
        # HERE: its default is applied by the callers that know the case
        # (`prepare`, `drift`, `nar1_return_data`), and an unanswered
        # body-corporate capacity reaching the mapper stays a refusal below.
        capacity = default_capacity(is_corporate=False)
    _check_capacity(name, capacity, is_corporate, problems)

    block = {
        "selectCapacityDesc": capacity,
        "selectPersonName": name,
        "signatoryDate": _format_date(
            resolved.get("date") or _hk_today(), problems, "signatoryDate"
        ),
    }
    person_id = str(resolved.get("person_id") or "").strip()
    if is_corporate:
        # THE BODY-CORPORATE SCHEME, verified against CR's test register
        # 2026-09-16 after the live register refused every return GSHK sent.
        #
        # CR's worksheet remark "Signatory User ID (Empty if sign by Body
        # Corporate)" is correct but incomplete, and reading it alone is what
        # broke this. selectPersonId is empty AND the signer is named in a
        # parallel block: selectAssoBrNo (the body corporate's own BR) plus
        # associatedPersonId / associatedPersonName / associatedCapacityDesc
        # (the human signing for it). All four are mandatory and all four are
        # CHECKED. Emitting none of them -- which is what this branch used to do
        # -- is refused with "Please check selectPersonId field.", a message
        # about the one element that must stay EMPTY, which is why this took a
        # live filing to find.
        #
        # Putting the signer's id in selectPersonId instead is NOT the fix and
        # was tried: CR answers "the signatory is not an individual user",
        # because selectPersonName is the company. So a person_id offered here
        # is deliberately dropped rather than filed.
        block.update(
            _associated_signatory(
                block["selectPersonName"],
                capacity,
                # Stated on the signatory when the caller knows it (an explicit
                # override, or _derive_signatory having resolved it); the
                # officer register is the fallback for a caller that does not.
                str(resolved.get("br_no") or "").strip()
                or _corporate_secretary_br(graph),
                signing_identity,
                problems,
            )
        )
    elif person_id:
        block["selectPersonId"] = person_id
    else:
        # MISSING for a natural person, who must supply one. `is_corporate` is
        # tested as `is True` above, never `is False`: an explicit signatory=
        # override need not carry the key at all, and an absent key must NOT
        # read as "body corporate" -- that would let a caller drop a mandatory
        # statutory field by omission, which nar1.validate() would wave through.
        problems.append(
            f"signatory {block['selectPersonName']}: signs as a natural person "
            "but has no e-Service (e-Filing) user ID on record, and "
            "selectPersonId is "
            "mandatory for a signatory who is not a body corporate"
        )
    return {k: v for k, v in block.items() if v}


def _associated_signatory(corporate_name: str, capacity: str, br_no: str,
                          signing_identity: dict | None,
                          problems: list[str]) -> dict:
    """Who signs FOR the body corporate — CR's four mandatory elements.

    Every one of them is validated by CR, so every one of them is a refusal
    here rather than a guess:

      selectAssoBrNo          a wrong BR reads as "not authorized to sign"
      associatedPersonId      absent -> "Please check selectPersonId field."
      associatedPersonName    absent -> "Please input the associatedPersonName";
                              WRONG -> "not authorized to sign", so it cannot be
                              taken from users.display_name and hoped for
      associatedCapacityDesc  must match the first half of selectCapacityDesc,
                              or "Capcity is not matched between associate and
                              selected" (CR's spelling)
    """
    block: dict = {}

    if br_no:
        block["selectAssoBrNo"] = br_no
    else:
        problems.append(
            f"signatory {corporate_name}: signs as a body corporate, and CR "
            "requires that company's own BR number (selectAssoBrNo) — no "
            "current corporate company secretary on the officer register "
            "carries one, or more than one does and they disagree. Record the "
            "secretary as a corporate officer linked to its own company record"
        )

    identity = signing_identity or {}
    user_id = str(identity.get("eservice_user_id") or "").strip()
    person_name = str(identity.get("person_name") or "").strip()
    if user_id:
        block["associatedPersonId"] = user_id
    else:
        problems.append(
            f"signatory {corporate_name}: signs as a body corporate, so CR "
            "requires the e-Service account of the person signing for it "
            "(associatedPersonId). The signed-in user has none stored — add it "
            "under CR Credentials"
        )
    if person_name:
        block["associatedPersonName"] = person_name
    else:
        problems.append(
            f"signatory {corporate_name}: CR requires the name held on the "
            "signing person's e-Service account (associatedPersonName) and "
            "checks it against that account. It is not stored for the "
            "signed-in user — add it under CR Credentials. It cannot be taken "
            "from their display name, which CR would reject as an "
            "unauthorised signatory"
        )

    associated = _associated_capacity(capacity)
    if associated:
        block["associatedCapacityDesc"] = associated
    elif capacity:
        problems.append(
            f"signatory {corporate_name}: selectCapacityDesc {capacity!r} does "
            "not name the capacity the signing person holds in the body "
            "corporate, so associatedCapacityDesc cannot be derived and CR "
            "refuses the pair as mismatched. Choose one of CR's Body Corporate "
            "capacities, e.g. 'Director of the Company Secretary (Body "
            "Corporate)'"
        )
    return block


def _individual(person: dict, addresses: dict, identity_documents: dict,
                problems: list[str], *, hkg_only: bool = False) -> dict:
    """`hkg_only` is set for an individual COMPANY SECRETARY and nobody else:
    indSec/stdAddress carries "Region. Must be HKG", indDir/resDir do not."""
    where = f"person {person.get('full_name') or person.get('id')}"
    block = {
        "indvChiName": person.get("full_name_zh") or "",
        "indvEngSname": person.get("surname") or "",
        "indvEngOname": person.get("given_names") or "",
        "stdAddress": _address(
            addresses.get(person.get("residential_address_id")), problems, where,
            hkg_only=hkg_only,
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
               name_zh: str | None = None, hkg_only: bool = False) -> dict:
    """A corporate officer/secretary block.

    `addr` is the corporate party's OWN registered office. It is never the
    filing entity's — that would put a wrong address on a statutory return,
    and CR's schema gate would accept it. A missing one is a problem, and a
    problem is a MappingError.

    `hkg_only` is set for a corporate COMPANY SECRETARY and nobody else:
    corpSec/stdAddress carries "Region. Must be HKG", corpDir does not.
    """
    block = {
        "corpChiName": name_zh or "",
        "corpEngName": name,
        "stdAddress": _address(addr, problems, f"corporate party {name}",
                               hkg_only=hkg_only),
    }
    if br_no:
        block["corpBrNo"] = br_no
    if tcsp_no:
        block["corpTcspNo"] = tcsp_no
    return {k: v for k, v in block.items() if v not in ("", None, {})}


def _check_secretary_resolved(sec: dict, name: str, problems: list[str]) -> None:
    """Say WHY a corporate secretary has no details, when nar1_source knows.

    `_address(None)` already refuses a secretary with no address, but its
    message ("has no address on record") sends an operator to look for an
    address on a record that does not have a field for one. The register holds
    a NAME; everything else comes from the entity that name points at, so the
    actionable fault is almost always that the name matches no company, or
    matches more than one.
    """
    resolution = sec.get("corporate_entity_resolution")
    if resolution == "not_found":
        problems.append(
            f"company secretary {name!r}: no company of that name is on record, "
            "so the return has no address or BR number to give for it — add the "
            "secretary to the Body Corporate Registry, or correct the name on "
            "the company's secretary record"
        )
    elif resolution == "ambiguous":
        problems.append(
            f"company secretary {name!r}: more than one company on record has "
            "that name, so which one is the secretary cannot be decided here — "
            "the return would state an address and BR number that may belong to "
            "the wrong company"
        )


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

    def _sec_key(person_id=None, entity_id=None, name=None) -> tuple:
        if person_id:
            return ("person", str(person_id))
        # The corporate party's ENTITY, when nar1_source resolved one. Keying
        # on a normalised name is what let the same secretary through twice:
        # `entity_officers.corporate_name` holds Viewpoint's entity CODE
        # ("GETSTA") and `company_secretaries.secretary_name` holds the real
        # name, so the two keys never matched and one appointment became two
        # corpSec blocks -- a second body-corporate secretary the company does
        # not have, spilling onto Continuation Sheet B.
        if entity_id:
            return ("entity", str(entity_id))
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
                ind_sec.append(_individual(person, addresses, ids, problems,
                                           hkg_only=True))
            continue
        name = sec.get("secretary_name") or ""
        if not _first_secretary(_sec_key(entity_id=sec.get("corporate_entity_id"),
                                         name=name)):
            continue
        # THE FILING COMPANY'S REGISTERED OFFICE IS NOT THE SECRETARY'S ADDRESS.
        # It used to be substituted here whenever the secretary was GSHK, on the
        # reasoning that GSHK provides its clients' registered office so the two
        # coincide "by construction". They coincide for 4,326 of 5,604 companies
        # on DEV and differ for 1,043, each of which filed a return stating the
        # company's own address as its secretary's.
        #
        # `company_secretaries` still has no FK to the party (migration 007 put
        # corporate_entity_id on entity_officers / shareholdings /
        # beneficial_owners only), so nar1_source resolves the secretary's own
        # entity and attaches its address, BR number and Chinese name here, the
        # same shape it attaches to a corporate officer row. When it cannot,
        # `corporate_address` is None and this becomes a problem -- never a
        # substitution.
        _check_secretary_resolved(sec, name, problems)
        corp_sec.append(
            _corporate(name, sec.get("corporate_address"), problems,
                       br_no=sec.get("corporate_br_no"),
                       tcsp_no=sec.get("tcsp_number"),
                       name_zh=sec.get("corporate_name_zh"),
                       hkg_only=True)
        )

    #: Whether the secretary REGISTER named a body corporate at all. Read by
    #: the officer loop below, which must not add a second one.
    register_named_a_body_corporate = bool(corp_sec)

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
            #
            # THE SECRETARY REGISTER WINS OUTRIGHT. Not merely "is deduped
            # against": where `company_secretaries` named any body corporate,
            # an entity_officers row for the same company is the SAME
            # appointment recorded twice, even when the two disagree about who
            # it is -- which they do for 796 companies on DEV, where the ETL
            # stamped a GSHK secretary onto every company while the officer
            # register names another firm (see the PRD of 2026-09-16, §2).
            # Keying on the entity alone would emit both and file a company
            # with two company secretaries, which no Hong Kong company has.
            # Two rows in the REGISTER still produce two blocks.
            if role == "company_secretary":
                if register_named_a_body_corporate:
                    continue
                if not _first_secretary(
                        _sec_key(entity_id=officer.get("corporate_entity_id"),
                                 name=name)):
                    continue
            # The corporate party's OWN address, attached by nar1_source via
            # entity_officers.corporate_entity_id (migration 007). Never `ro`.
            block = _corporate(
                name,
                officer.get("corporate_address"),
                problems,
                br_no=officer.get("corporate_br_no"),
                name_zh=officer.get("corporate_name_zh"),
                hkg_only=role == "company_secretary",
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
        block = _individual(person, addresses, ids, problems,
                            hkg_only=role == "company_secretary")
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


def map_entity(graph: dict, *, year: int, signatory: dict | None = None,
               signatory_capacity: str | None = None,
               signing_identity: dict | None = None) -> dict:
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
        `capacity` must come from CR's vocabulary for that kind of signatory
        (cr_vocabularies.CAPACITY_INDIVIDUAL / CAPACITY_BODY_CORPORATE); it
        defaults to "Company Secretary" for a natural person and has NO default
        for a body corporate.
    `signatory_capacity`, when given, sets selectCapacityDesc on whoever is
        resolved and changes nothing else — the operator's choice from CR's
        vocabulary, made on the Data Verification stage. It is the answer to the
        one thing about a GSHK-signed return the portal cannot derive: the
        secretary is a body corporate, and which of CR's 15 Body Corporate
        values applies depends on who at GSHK signs on its behalf. Deliberately
        NOT folded into `signatory` — see `_signatory_block` for why a partial
        merge there would be unsafe.
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
        # "Region. Must be HKG" — see _hkg_region().
        "roAddr": _address(graph.get("registered_address"), problems,
                           "registered office", hkg_only=True),
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
            # THREE DIFFERENT QUANTITIES, and only the first is a count.
            # CR's worksheet: noOfShareIssuedOnThisCls is "Total Number",
            # issuedCapital is "Total Amount", paidUpCapital is "Total Amount
            # Paid up or Regarded as Paid up".
            #
            # issuedCapital used to be filled from total_issued -- the share
            # COUNT into a money field. Invisible on CR's examples and on most
            # of our data because the two coincide, but 61 of 5,740 real DEV
            # classes disagree, and unmistakably: 1,000 shares against
            # 5,000,000 paid, and one class paid 61,460.68, which no share
            # count is.
            #
            # total_issued is the count (Viewpoint Issued). nominal_value cannot
            # turn it into an amount -- it is 0 or 1 on all but 3 classes,
            # because Hong Kong shares have had NO PAR VALUE since Cap. 622
            # (2014), so there is no per-share price to multiply by.
            #
            # issuedCapital IS `share_classes.issued_amount` -- the profile's
            # "Total Amount" box (migration 028, Viewpoint StatedCap), and the
            # column the CR form contract maps this field to. It used to be
            # filled from total_paid, from before that column existed, so an
            # operator who typed Total Amount 200 against 100 paid up got a
            # return -- and a PDF -- saying 100 (Levi 2026-09-14). The two
            # differ exactly when shares are partly paid, which is the case
            # section 11 has two columns for.
            #
            # total_paid stays the FALLBACK for a class with no issued_amount
            # (1 of 5,746 on DEV): CR's own two NAR1 examples show the two
            # equal, which is right for fully-paid shares, and blank is not an
            # amount CR will take.
            "noOfShareIssuedOnThisCls": _whole_number(
                sc.get("total_issued"), problems,
                f"share class {sc.get('class_name')} total_issued"),
            "issuedCapital": _whole_number(
                _issued_amount(sc), problems,
                f"share class {sc.get('class_name')} issued_amount"),
            "paidUpCapital": _whole_number(
                sc.get("total_paid"), problems,
                f"share class {sc.get('class_name')} total_paid"),
        }
        for sc in graph["share_classes"]
    ]
    # A class with shares issued but no amount recorded for them would file
    # issuedCapital = 0, and zero issued capital against issued shares is not a
    # credible statutory return -- it is missing data. Six classes on DEV looked
    # like this (10,000-20,000 shares, nothing paid). Filing the share count
    # there, as this used to, was not better; it was just less obviously wrong.
    # Say it out loud instead, like every other gap in this mapper.
    #
    # Keyed on the ISSUED amount, not the paid one: an issued class paid up to
    # nil is a partly-paid class CR's section 11 can state, not a gap.
    for sc in graph["share_classes"]:
        issued = _decimal(sc.get("total_issued"), [], "") or Decimal(0)
        amount = _decimal(_issued_amount(sc), [], "") or Decimal(0)
        if issued > 0 and amount == 0:
            problems.append(
                f"share class {sc.get('class_name')}: {issued} shares issued "
                "but no Total Amount is recorded for them, so the return would "
                "declare no issued capital — record the amount before filing"
            )

    if share_capitals:
        data["shareCapitals"] = share_capitals

    # A private HK company lists its members in Schedule 1. Schedule 2 is for
    # listed companies and the CD-ROM option is for very large registers;
    # neither applies to anything GSHK files (spec: R1 is private companies).
    data["shareholderListedInSch1"] = "Y"
    data["shareholderListedInSch2"] = "N"
    data["shareholderListedInCdrom"] = "N"
    data["schedule1"] = _schedule_1(graph, problems)
    data.update(_signatory_block(graph, signatory, problems, signatory_capacity,
                                 signing_identity))

    if problems:
        raise MappingError(problems)
    return data

"""Regenerate `services/cr_forms/contract.py` from CR's worksheet.

    uv run python scripts/build_cr_form_contract.py

WHY GENERATED AND COMMITTED. Same reason as `services/nar1_form/field_map.py`:
if CR revises a form, the change arrives as a reviewable diff in a committed
file rather than silently altering behaviour at runtime. Nothing in the running
service reads the spreadsheet.

WHAT A HUMAN EDITS. `RULES` below — the decisions. Everything else is
mechanical. A CR field matching no rule makes this script **exit non-zero and
name the field**, which is the whole point: an unaccounted-for field must stop
someone, not default to something.

THE FOUR DISPOSITIONS.

  mapped        a profile column holds it
  derived       computed on the way out; never stored independently
  form_instance belongs to one filing, not to a company or person
  unsourced     CR wants it, we hold no column and Viewpoint has no data.
                Deliberately not built (PRD D7). Carries the evidence.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.cr_forms import worksheet  # noqa: E402

FORMS = ("NAR1", "NNC1")

MAPPED, DERIVED, FORM_INSTANCE, UNSOURCED = (
    "mapped", "derived", "form_instance", "unsourced")

#: (context-substring or None, field name) -> (disposition, target-or-reason).
#: A None context matches any. More specific entries are listed first and win.
#: `context` is the field's ancestry with the `submission/Eform/formModel`
#: prefix stripped, e.g. `indDirList/indDir/correspondingAddress`.
RULES: list[tuple] = [

    # -- Addresses ---------------------------------------------------------
    # Which address a line belongs to is carried by the path, so every
    # occurrence targets the same table. CR gives each line 60 characters,
    # which is the limit the ETL's _collapse_line3 used to violate.
    (None, "flatFlrBlk",        MAPPED, "addresses.line1"),
    (None, "bldg",              MAPPED, "addresses.line2"),
    (None, "stEstLotVlg",       MAPPED, "addresses.line3"),
    (None, "dstCtyStatePostal", MAPPED, "addresses.city"),
    (None, "ctryRegion",        MAPPED, "addresses.country"),
    (None, "stdAddress",        MAPPED, "addresses"),
    (None, "correspondingAddress", MAPPED, "entity_officers.correspondence_address_id"),
    (None, "addrLangInd",       FORM_INSTANCE,
     "language of THIS filing's addresses; the profile stores one address, "
     "not one per language"),

    # -- The company -------------------------------------------------------
    (None, "brNo",              MAPPED, "entities.br_number"),
    (None, "corpBrNo",          MAPPED, "entities.br_number"),
    (None, "ubino",             MAPPED, "entities.br_number"),
    (None, "brName",            MAPPED, "business_names.business_name"),
    (None, "coyStatus",         MAPPED, "entities.company_type"),
    (None, "nature",            MAPPED, "entities.business_nature_code"),
    (None, "bnCode",            MAPPED, "entities.business_nature_code"),
    (None, "totalAmountMortCharge", MAPPED, "entities.mortgages_total"),
    (None, "telNo",             MAPPED, "contacts.contact_value"),
    (None, "intendedEngName",   MAPPED, "entities.company_name"),
    (None, "intendedChiName",   MAPPED, "entities.company_name_zh"),
    # An INDIVIDUAL secretary's TCSP licence is their own, not the company's.
    # These must precede the generic rules below or they resolve to
    # entities.tcsp_licence_no, which would file GSHK's licence number against
    # a natural person.
    ("indSecList", "tcspNo",    UNSOURCED,
     "an individual secretary's own TCSP licence; no persons column holds it "
     "and Viewpoint's only %tcsp% matches are workflow-template flags"),
    ("indSecList", "exempted",  UNSOURCED, "as tcspNo on an individual secretary"),
    ("indSecList", "reason",    UNSOURCED, "as tcspNo on an individual secretary"),

    (None, "tcspNo",            MAPPED, "entities.tcsp_licence_no"),
    (None, "corpTcspNo",        MAPPED, "entities.tcsp_licence_no"),
    (None, "reason",            MAPPED, "entities.tcsp_exemption_reason"),
    (None, "exempted",          DERIVED,
     "true exactly when tcsp_exemption_reason is set"),
    (None, "natureDesc",        DERIVED,
     "CR fills it from the code after web-form validation; we denormalise it "
     "from the seeded vocabulary so the facsimile PDF can print it"),
    (None, "bnDesc",            DERIVED, "as natureDesc"),
    (None, "compNameE",         DERIVED,
     "CR fills from the BR number after validation; entities.company_name is "
     "the profile's copy"),
    (None, "compNameC",         DERIVED, "as compNameE"),

    # s16 — where the statutory registers are kept (PRD OQ-3).
    (None, "companyRecord",     MAPPED, "entity_record_locations.record_type"),
    ("(top)", "address",        MAPPED, "entity_record_locations.address_id"),

    # -- Share capital -----------------------------------------------------
    # CR keeps the share COUNT and the share VALUE in different columns, and
    # the schema conflated them until this PRD. See the PRD's B7.
    (None, "clsOfShares",       MAPPED, "share_classes.class_name"),
    (None, "classOfShare",      MAPPED, "share_classes.class_name"),
    (None, "currency",          MAPPED, "share_classes.currency"),
    (None, "currCode",          MAPPED, "share_classes.currency"),
    (None, "noOfShareIssuedOnThisCls", MAPPED, "share_classes.total_issued"),
    (None, "issuedCapital",     MAPPED, "share_classes.issued_amount"),
    (None, "issuedShareCapital", MAPPED, "share_classes.issued_amount"),
    (None, "paidUpCapital",     MAPPED, "share_classes.total_paid"),
    (None, "paidUpShareCapital", MAPPED, "share_classes.total_paid"),
    (None, "remainUnpaid",      UNSOURCED,
     "no Viewpoint column matches %unpaid% in 1,563 tables; NNC1-mandatory, "
     "so the NNC1 build (R3) must answer it"),
    (None, "particluarOfRights", UNSOURCED,
     "no Viewpoint column matches %rights%. CR's spelling, preserved"),

    # -- Members / shareholders -------------------------------------------
    (None, "personType",        MAPPED, "shareholdings.party_type"),
    (None, "allotteeType",      MAPPED, "shareholdings.party_type"),
    (None, "shType",            MAPPED, "shareholdings.party_type"),
    (None, "totalNo",           MAPPED, "shareholdings.shares_held"),
    (None, "sharesAlloted",     MAPPED, "shareholdings.shares_held"),
    (None, "amt",               MAPPED, "shareholdings.amount_paid"),
    (None, "perOfShares",       DERIVED,
     "this holding's shares over the class total"),
    (None, "remarks",           FORM_INSTANCE,
     "free text about one allotment on one return"),

    # -- People ------------------------------------------------------------
    # NAR1 and NNC1 spell the same fields differently; both map to one column.
    (None, "indvChiName",       MAPPED, "persons.full_name_zh"),
    (None, "chiName",           MAPPED, "persons.full_name_zh"),
    (None, "indvEngSname",      MAPPED, "persons.surname"),
    (None, "engSurName",        MAPPED, "persons.surname"),
    (None, "surNameEng",        MAPPED, "persons.surname"),
    (None, "indvSurname",       MAPPED, "persons.surname"),
    (None, "indvEngOname",      MAPPED, "persons.given_names"),
    (None, "engOtherName",      MAPPED, "persons.given_names"),
    (None, "otherNameEng",      MAPPED, "persons.given_names"),
    (None, "indvOtherName",     MAPPED, "persons.given_names"),
    (None, "indvPrevEngName",   MAPPED, "persons.former_name"),
    (None, "prevNameEng",       MAPPED, "persons.former_name"),
    (None, "indvPrevChiName",   MAPPED, "persons.former_name_zh"),
    (None, "prevNameChi",       MAPPED, "persons.former_name_zh"),
    (None, "indvAlsEngName",    MAPPED, "persons.alias_en"),
    (None, "aliasNameEng",      MAPPED, "persons.alias_en"),
    (None, "indvAlsChiName",    MAPPED, "persons.alias_zh"),
    (None, "aliasNameChi",      MAPPED, "persons.alias_zh"),
    (None, "indvEmailAddr",     MAPPED, "persons.email"),

    # Identity documents. CR splits the HKID into number and check digit;
    # we store the whole thing as typed ("A1234567(8)") and split on the way
    # out, which is also what makes the check digit verifiable.
    (None, "hkid",              MAPPED, "person_identity_documents.id_number"),
    (None, "hkidChkDtg",        DERIVED,
     "the parenthesised check digit of person_identity_documents.id_number"),
    (None, "indvHkidNo",        DERIVED,
     "CR's PARTIAL id: first half of the HKID, rounded up (A123456(7) -> A123)"),
    (None, "passportNo",        MAPPED, "person_identity_documents.id_number"),
    (None, "indvPptNo",         DERIVED,
     "CR's PARTIAL passport number, as indvHkidNo"),
    (None, "passportCtry",      MAPPED,
     "person_identity_documents.issuing_country"),
    (None, "indvPptIssCtry",    MAPPED,
     "person_identity_documents.issuing_country"),

    # -- Corporate parties -------------------------------------------------
    (None, "corpChiName",       MAPPED, "entities.company_name_zh"),
    (None, "corpEngName",       MAPPED, "entities.company_name"),
    (None, "engName",           MAPPED, "entities.company_name"),
    (None, "corpEmailAddr",     MAPPED, "entities.email"),

    # `email` is the person's on an individual block and the company's at the
    # top of the form. The company one has no source (PRD 7.2).
    ("indDirList", "email",     MAPPED, "persons.email"),
    ("indSecList", "email",     MAPPED, "persons.email"),
    ("corpDirList", "email",    MAPPED, "entities.email"),
    ("corpSecList", "email",    MAPPED, "entities.email"),
    (None, "email",             UNSOURCED,
     "company-level email; no entity-level Email column in Entity, CR_Entity "
     "or RefMaster"),
    (None, "emailAddr",         UNSOURCED, "as email at (top)"),

    # -- Directors ---------------------------------------------------------
    (None, "dirInd",            DERIVED,
     "true when the entity_officers row has role='director'"),
    (None, "altDirInd",         UNSOURCED,
     "alternate directors: Viewpoint's only %alternate% columns are "
     "meeting-attendance codes"),
    (None, "altTo",             UNSOURCED, "as altDirInd"),
    (None, "consentSigned",     FORM_INSTANCE,
     "consent to act, given for one incorporation"),

    # -- One filing, not a profile ----------------------------------------
    (None, "formCode",          FORM_INSTANCE, "assigned by CR per submission"),
    (None, "language",          FORM_INSTANCE, "filing language"),
    (None, "aaLang",            FORM_INSTANCE, "articles language for this NNC1"),
    (None, "sampleAA",          FORM_INSTANCE, "whether CR's model articles are adopted"),
    (None, "proposedCoySecure", FORM_INSTANCE, "NNC1 delivery option"),
    (None, "brcYear",           FORM_INSTANCE, "BR certificate term bought with this filing"),
    (None, "fileEncode256",     FORM_INSTANCE, "attachment digest"),
    (None, "docReferenceNo",    FORM_INSTANCE, "CR's reference for a redelivered return"),
    (None, "dateReturnMadeUp",  FORM_INSTANCE, "the return's own made-up-to date"),
    (None, "dateReturnFrom",    FORM_INSTANCE, "financial period of this return"),
    (None, "dateReturnTo",      FORM_INSTANCE, "financial period of this return"),
    (None, "yearAnnualReturn",  FORM_INSTANCE, "which year this return covers"),
    (None, "signatoryDate",     FORM_INSTANCE, "when this return was signed"),
    (None, "memberNumAtDateReturn", DERIVED,
     "count of members at the return date, for companies with no share capital"),
    (None, "attachSpeRez",      FORM_INSTANCE, "allottee spreadsheet attachment"),
    (None, "finStatAttachSpeRez", FORM_INSTANCE, "financial statement attachment"),
    (None, "shareholderListedInSch1", FORM_INSTANCE, "which schedule carries the members"),
    (None, "shareholderListedInSch2", FORM_INSTANCE, "which schedule carries the members"),
    (None, "shareholderListedInCdrom", FORM_INSTANCE, "which schedule carries the members"),

    # Signing. Who signs is the logged-in user's e-Service identity, decided
    # at signing time and never stored on a profile (Levi, Q1 2026-08-30).
    (None, "selectPersonId",    FORM_INSTANCE, "signatory's e-Service user id"),
    (None, "selectPersonName",  FORM_INSTANCE, "signatory name"),
    (None, "selectCapacityDesc", FORM_INSTANCE, "signing capacity, per case"),
    (None, "selectAssoBrNo",    FORM_INSTANCE, "BR of the signing body corporate"),
    (None, "associatedPersonId", FORM_INSTANCE, "individual signing for a body corporate"),
    (None, "associatedPersonName", FORM_INSTANCE, "individual signing for a body corporate"),
    (None, "associatedCapacityDesc", FORM_INSTANCE, "individual signing for a body corporate"),
    (None, "Signature",         FORM_INSTANCE, "CR XML signature"),
    (None, "UserCredentialHash", FORM_INSTANCE, "PIN-signing credential; never stored"),
    (None, "UserSignature",     FORM_INSTANCE, "PIN signature; never stored"),
    (None, "EncryptionKey",     FORM_INSTANCE, "PIN-signing key; never stored"),
    (None, "depositAccountNo",  FORM_INSTANCE, "CR deposit account charged"),
]

_PREFIX = "submission/Eform/formModel/"


def context_of(path: str) -> str:
    inner = path[len(_PREFIX):] if path.startswith(_PREFIX) else path
    parent = "/".join(inner.split("/")[:-1])
    return parent or "(top)"


def rule_for(context: str, name: str):
    for ctx, rule_name, disposition, note in RULES:
        if rule_name == name and (ctx is None or ctx in context or ctx == context):
            return disposition, note
    return None


def main() -> int:
    entries, unmatched = {}, []
    for form in FORMS:
        for field in worksheet.load_fields(form):
            rule = rule_for(context_of(field.path), field.name)
            if rule is None:
                unmatched.append(f"{form} {field.path}")
                continue
            entries[(form, field.path)] = (*rule, field.mandatory, field.max_length)

    if unmatched:
        print(f"{len(unmatched)} CR field(s) match no rule in RULES:",
              file=sys.stderr)
        for item in unmatched:
            print(f"  {item}", file=sys.stderr)
        print("\nAdd a rule for each. An unaccounted-for CR field must stop "
              "someone rather than default to something.", file=sys.stderr)
        return 1

    out = Path(__file__).resolve().parents[1] / "services" / "cr_forms" / "contract.py"
    lines = [
        '"""The CR form contract — GENERATED, do not edit by hand.',
        "",
        "Regenerate with `uv run python scripts/build_cr_form_contract.py`;",
        "the decisions live in RULES there. `tests/test_cr_form_contract.py`",
        "fails if any field on NAR1 or NNC1 is missing from this file.",
        "",
        f"{len(entries)} fields across {', '.join(FORMS)}.",
        '"""',
        "",
        "#: (form, xml path) -> (disposition, target-or-reason, mandatory, max_length)",
        "FIELDS: dict[tuple[str, str], tuple[str, str, bool, int | None]] = {",
    ]
    for (form, path), (disposition, note, mandatory, length) in entries.items():
        lines.append(f"    ({form!r}, {path!r}):")
        lines.append(f"        ({disposition!r}, {note!r}, {mandatory!r}, {length!r}),")
    lines += [
        "}",
        "",
        "",
        "def disposition_for(form: str, path: str):",
        '    """The disposition of one CR field, or None if nobody has ruled."""',
        "    entry = FIELDS.get((form, path))",
        "    return entry[0] if entry else None",
        "",
        "",
        "def entry_for(form: str, path: str):",
        '    """The full contract entry, or None."""',
        "    return FIELDS.get((form, path))",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} with {len(entries)} fields")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

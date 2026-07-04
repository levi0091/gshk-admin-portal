"""Decode dictionaries pinned from live ViewPoint data on 2026-07-04.

Source: `SELECT IdType, COUNT(*) FROM IdentityRegister GROUP BY IdType` and
`SELECT OfficerType, COUNT(*) FROM Officers GROUP BY OfficerType` run directly
against the restored localhost ViewPoint database. No MfIdentityType /
MfRelationType decode rows exist in the schema dump with real values, so this
maps the observed codes directly instead of joining to those (UI-metadata-only)
tables.
"""

# IdentityRegister.IdType -> person_identity_documents.id_type (id_document_type enum)
# Observed distribution: PSP=6136, BRN=3428, IDC=480, INC=190, BACT=105,
# TCSPN=8, EIN=3, IMC=1, PRC=1, LEI=1, CTZ=1.
# BRN/INC/BACT/TCSPN/EIN/IMC/LEI/CTZ are company-level registration numbers,
# not personal ID documents — they are only reachable here if a corporate
# RefCode slips through; the extract query filters to RefMaster.RefType='I'
# so in practice only PSP/IDC/PRC/other individual codes should appear.
ID_TYPE_MAP: dict[str, str] = {
    "PSP": "passport",
    "IDC": "hkid",
    "PRC": "china_id",
}


def decode_id_type(vp_code: str | None) -> str:
    if not vp_code:
        return "other"
    return ID_TYPE_MAP.get(vp_code.strip().upper(), "other")


# Officers.OfficerType -> entity_officers.role (officer_role enum)
# Observed distribution: DIR=6948, SEC=5785, RPD=2, DRE=1, AUO=1.
# DIR/SEC cover 99.98% of rows and are unambiguous. RPD/DRE/AUO are rare and
# their exact VP meaning isn't documented anywhere in the schema — mapped as
# a best-effort guess and every row using one of these three codes is written
# to the Task 9 error log for manual confirmation, never silently dropped.
OFFICER_ROLE_MAP: dict[str, str] = {
    "DIR": "director",
    "SEC": "company_secretary",
    "RPD": "reserve_director",
    "DRE": "reserve_director",
    "AUO": "authorised_rep",
}

AMBIGUOUS_OFFICER_CODES = {"RPD", "DRE", "AUO"}


def decode_officer_role(vp_code: str | None) -> str:
    if not vp_code:
        return "director"
    return OFFICER_ROLE_MAP.get(vp_code.strip().upper(), "director")

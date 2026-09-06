"""What a document section IS, and which fields each document type carries.

ONE OWNER FOR THIS VOCABULARY. `/documents/sections` serves it and the profile
screens render from what it returns — the same rule the CR form contract follows
(CLAUDE.md §3). A screen that hardcoded "a passport needs an issuing country"
would drift from the API that enforces it, and the way you would find out is a
NAR1 rejected at CR.

TWO LEVELS, which the screen makes visible:

  section       the heading and the card — Identity Documents, Proof of Address,
                Other Documents. Rendered even when EMPTY, with its own upload
                button, because an operator has to be able to add the first one.
  document type the row in the picker — Passport, HKID, Utility Bill. This is
                what `documents` versions on, so re-uploading a passport
                supersedes the passport and leaves the HKID alone (migration 036).

WHAT CR ACTUALLY ASKS FOR, and why the fields differ by type. NAR1 and NNC1 have
exactly two identity boxes per individual (`services/cr_forms/contract.py`):

    hkid + hkidChkDtg           the HKID and its parenthesised check digit
    passportNo + passportCtry   a partial passport number AND its issuing
                                country — `nar1_mapper` refuses the number
                                without a country CR has a code for

So an HKID needs a number and nothing else: CR has no country box for it, and a
Hong Kong identity card does not expire. A passport needs its issuing country or
it cannot be filed. Issue and expiry dates are ours, not CR's — GSHK works from
them, so they are offered, and never required.

`china_id` and `other` are CR-invisible: `nar1_mapper` matches `id_type` on
'hkid' and 'passport' only, and a person holding neither blocks the return. They
are still recorded, because refusing to store what the client gave us is not a
fix; the profile says what they are worth.
"""

#: `document_types.category` for identity documents. The section that carries
#: id_number / issuing country / dates, and the only one that does.
IDENTITY_CATEGORY = "identity"

#: `id_document_type` enum value  ->  `document_types.code` (migration 036).
#: Both directions are needed: an upload arrives as a type code and has to become
#: an identity row, and an identity row has to find its scan.
CODE_BY_ID_TYPE = {
    "hkid": "id_hkid",
    "passport": "id_passport",
    "china_id": "id_china_id",
    "other": "id_other",
}
ID_TYPE_BY_CODE = {code: id_type for id_type, code in CODE_BY_ID_TYPE.items()}

#: The retired catch-all (migration 036). Rows uploaded under it still exist and
#: still render, but it maps to no `id_type` — it never said which document it
#: was, which is exactly why it was retired.
LEGACY_IDENTITY_CODE = "id_scan"

#: Per identity type: which fields the screen shows, and which the API refuses to
#: save without. `id_number` is required everywhere — an identity document with
#: no number is not a record of anything.
IDENTITY_FIELDS: dict[str, dict[str, list[str]]] = {
    "hkid": {
        # No country: CR's <hkid> has no companion country box, and the card is
        # Hong Kong's by definition. No dates: an HKID does not expire.
        "fields": ["id_number"],
        "required": ["id_number"],
    },
    "passport": {
        "fields": ["id_number", "issuing_country", "issue_date", "expiry_date"],
        # `nar1_mapper._individual_id` refuses a passport number whose issuing
        # country has no CR code, so an empty one is a filing blocked later
        # rather than a field refused now.
        "required": ["id_number", "issuing_country"],
    },
    "china_id": {
        "fields": ["id_number", "issuing_country", "issue_date", "expiry_date"],
        "required": ["id_number"],
    },
    "other": {
        "fields": ["id_number", "issuing_country", "issue_date", "expiry_date"],
        "required": ["id_number"],
    },
}

#: Ordered sections, and which owner each belongs to. A section renders whether
#: or not it holds anything, so this list — not the uploaded rows — is what
#: decides the headings on a profile.
SECTIONS = [
    {
        "key": IDENTITY_CATEGORY,
        "label": "Identity Documents",
        "description": "Passport, HKID and other identity documents — the numbers filed with CR",
        "owner_types": ["person"],
        # The scan is evidence for the number; the number is the filing. A
        # passport recorded without a scan is still filable, so the file is
        # optional here and required in every other section, where the file is
        # the only thing there is.
        "file_required": False,
    },
    {
        "key": "address_proof",
        "label": "Proof of Address",
        "description": "Evidence of the residential or registered address on file",
        "owner_types": ["person", "company"],
        "file_required": True,
    },
    {
        "key": "government_form",
        "label": "Government Forms",
        "description": "Forms filed with the Companies Registry",
        "owner_types": ["company"],
        "file_required": True,
    },
    {
        "key": "statutory",
        "label": "Statutory Documents",
        "description": "Constitutional and resolution documents",
        "owner_types": ["company"],
        "file_required": True,
    },
    {
        "key": "certificate",
        "label": "Certificates",
        "description": "Certificates issued for this company",
        "owner_types": ["company"],
        "file_required": True,
    },
    {
        "key": "kyc",
        "label": "KYC Documents",
        "description": "Screening and due-diligence material",
        "owner_types": ["person", "company"],
        "file_required": True,
    },
    {
        "key": "internal",
        "label": "Other Documents",
        "description": "Anything that does not belong to a section above",
        "owner_types": ["person", "company"],
        "file_required": True,
    },
]

#: Where a document whose category matches no section is shown. A category can
#: only arrive here by a migration adding one without touching this file, and a
#: document that renders nowhere is worse than one under the wrong heading.
FALLBACK_SECTION = "internal"

_SECTION_KEYS = {s["key"] for s in SECTIONS}


def sections_for(owner_type: str) -> list[dict]:
    """The sections a profile of this owner type renders, in order."""
    return [s for s in SECTIONS if owner_type in s["owner_types"]]


def section_of(category: str | None) -> str:
    """Which section a `document_types.category` belongs under."""
    return category if category in _SECTION_KEYS else FALLBACK_SECTION


def id_type_for_code(code: str | None) -> str | None:
    """The `id_document_type` an uploaded document type records, or None.

    None means "this upload is a file and nothing more" — every non-identity
    type, and the retired `id_scan`, which could not say which document it was.
    """
    return ID_TYPE_BY_CODE.get(code or "")


def is_identity_code(code: str | None) -> bool:
    return id_type_for_code(code) is not None


def required_identity_fields(id_type: str) -> list[str]:
    return IDENTITY_FIELDS.get(id_type, IDENTITY_FIELDS["other"])["required"]


def identity_fields(id_type: str) -> list[str]:
    return IDENTITY_FIELDS.get(id_type, IDENTITY_FIELDS["other"])["fields"]

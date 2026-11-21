"""What a document section IS, and which fields each document type carries.

ONE OWNER FOR THIS VOCABULARY. `/documents/sections` serves it and the profile
screens render from what it returns — the same rule the CR form contract follows
(CLAUDE.md §3). A screen that hardcoded "a passport needs an issuing country"
would drift from the API that enforces it, and the way you would find out is a
NAR1 rejected at CR.

TWO SHAPES, which the screen makes visible (GSHK 2026-11-21):

  identity      a person's Identity Documents: typed RECORDS (Passport, HKID)
                carrying the number CR files. A re-uploaded passport scan
                supersedes the passport and leaves the HKID alone (migration 036).
  bucket        everything else, on both profiles. Files are dropped in many at
                a time with no type to choose, then tagged and described in bulk.
                See BUCKETS below.

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

#: The one section that is not a bucket: a person's identity RECORDS, each
#: carrying a number CR files. Unchanged by the 2026-11-21 bucket redesign.
SECTIONS = [
    {
        "key": IDENTITY_CATEGORY,
        "label": "Identity Documents",
        "description": "Passport, HKID and other identity documents — the numbers filed with CR",
        "owner_types": ["person"],
        # The scan is evidence for the number; the number is the filing. A
        # passport recorded without a scan is still filable.
        "file_required": False,
    },
]


def sections_for(owner_type: str) -> list[dict]:
    """The typed sections a profile of this owner type renders, in order."""
    return [s for s in SECTIONS if owner_type in s["owner_types"]]


# ── BUCKETS (GSHK 2026-11-21) ───────────────────────────────────────────────
#
# GSHK do not have time to pick a document type and type a description for
# every file. Everything that is not an identity record is now dropped into one
# of a few BUCKETS, many files at a time, and described afterwards in bulk.
#
# A bucket is NOT a document type. `documents.bucket` is its own column
# (migration 065) and a bucket upload is filed under the generic `other` type,
# so it never versions over another file: twenty payment slips are twenty
# rows, not version 20 of one. The `suggestions` are what GSHK listed as
# typically living in each bucket; the screen offers them as tags and never
# requires one.
#
# A row whose `bucket` is NULL was written by something that still files by
# TYPE (a signed NAR1, an ND2A's resignation letter, everything uploaded before
# this change). `bucket_of()` places it from its type, so no backfill is needed
# and none of those callers had to learn about buckets.

#: Where a document that fits no bucket is shown. It renders only while it
#: holds something, and the screen invites the operator to move what is in it.
OTHER_BUCKET = "other"

BUCKETS = [
    {
        "key": "annual_return",
        "label": "Annual Return (NAR1)",
        "description": "Filed annual returns",
        "owner_types": ["company"],
        "suggestions": ["Filed NAR1"],
    },
    {
        "key": "corporate_identity",
        "label": "Corporate Identity & Due Diligence",
        "description": "Licence, constitution, address proof and AML of the corporate entity",
        "owner_types": ["company"],
        "suggestions": [
            "Business Licence", "Articles of Association", "Address Proof",
            "AML Case Report",
        ],
    },
    {
        "key": "br_renewal",
        "label": "Business Registration Renewal",
        "description": "Renewed business registration certificates",
        "owner_types": ["company"],
        "suggestions": ["Renewed BR"],
    },
    {
        "key": "maintenance",
        "label": "Maintenance",
        "description": "Filings and instruments after incorporation",
        "owner_types": ["company"],
        "suggestions": [
            "Filed ND2A", "Filed ND2B", "Filed NR1", "Filed NNC2", "Filed NSC1",
            "Stamped Share Transfer", "Filed IRC3111A",
        ],
    },
    {
        "key": "payments",
        "label": "Payments",
        "description": "Payment slips",
        "owner_types": ["company"],
        "suggestions": ["Payment Slip"],
    },
    {
        "key": "incorporation",
        "label": "Incorporation / Statutory Registers",
        "description": "Incorporation papers and the statutory registers",
        "owner_types": ["company"],
        "suggestions": [
            "Filed NNC1", "Certificate of Incorporation", "Articles of Association",
            "First Business Licence", "First Written Resolution",
            "Certificate of Incumbency", "Register of Members",
            "Register of Directors", "Register of Secretaries",
            "Significant Controller Register", "Onboarding Forms",
        ],
    },
    {
        "key": "kyc",
        "label": "KYC & AML",
        "description": "Address proof and AML reports for this individual",
        "owner_types": ["person"],
        "suggestions": ["Address Proof", "AML Case Report", "AML Passport Report"],
    },
    {
        "key": OTHER_BUCKET,
        "label": "Other Documents",
        "description": "Not in a bucket yet. Select them and choose Move to",
        "owner_types": ["person", "company"],
        "suggestions": [],
        # Shown only while it holds something: it is where unplaced files
        # wait, not a place anyone should choose to file into.
        "fallback": True,
    },
]

BUCKET_KEYS = tuple(b["key"] for b in BUCKETS)

#: Type codes whose bucket is not decided by their category alone.
_BUCKET_BY_CODE = {
    "company": {
        "nar1": "annual_return",
        # The client's emailed approval of a NAR1 (migration 061): evidence for
        # one annual return, filed beside it.
        "approval_receipt": "annual_return",
        "nnc1": "incorporation",
        "nd2a": "maintenance",
        "nd2b": "maintenance",
    },
    "person": {},
}

#: `document_types.category` -> bucket, per owner. `identity` is absent on
#: purpose: a person's identity scans render on their identity records.
_BUCKET_BY_CATEGORY = {
    "company": {
        "statutory": "incorporation",
        "certificate": "incorporation",
        "government_form": "maintenance",
        "address_proof": "corporate_identity",
        "kyc": "corporate_identity",
        "officer_change": "maintenance",
    },
    "person": {
        "address_proof": "kyc",
        "kyc": "kyc",
    },
}

#: Per drop. GSHK asked for the existing cap of twenty to stay.
MAX_FILES_PER_UPLOAD = 20
#: Supabase Storage's default per-object ceiling. A larger file would be
#: refused by Storage after the whole body had crossed the wire; refusing it
#: first, by name, is the kinder answer.
MAX_FILE_BYTES = 50 * 1024 * 1024
#: As permissive as GSHK asked for (any document, sheet, slide, image, text,
#: e-mail or archive) and closed only to what EXECUTES when opened. A file
#: stored here is later downloaded onto a colleague's machine; a script is the
#: one thing this portal must not hand out.
BLOCKED_EXTENSIONS = frozenset({
    "exe", "msi", "bat", "cmd", "com", "scr", "pif", "cpl", "dll", "sys",
    "vbs", "vbe", "js", "jse", "wsf", "wsh", "ps1", "psm1", "hta", "jar",
    "sh", "app", "lnk", "reg", "msc", "gadget", "inf",
})
MAX_TAGS = 12
MAX_TAG_LENGTH = 60
MAX_DESCRIPTION_LENGTH = 500


def upload_limits() -> dict:
    """What the screen must refuse before sending — served, so the two agree."""
    return {
        "max_files": MAX_FILES_PER_UPLOAD,
        "max_file_bytes": MAX_FILE_BYTES,
        "blocked_extensions": sorted(BLOCKED_EXTENSIONS),
        "max_tags": MAX_TAGS,
        "max_tag_length": MAX_TAG_LENGTH,
        "max_description_length": MAX_DESCRIPTION_LENGTH,
    }


def owner_type_of(owner_kind: str) -> str:
    """`documents` owner kind ('entity' | 'person') -> 'company' | 'person'."""
    return "person" if owner_kind == "person" else "company"


def buckets_for(owner_type: str) -> list[dict]:
    """The buckets a profile of this owner type renders, in order."""
    return [b for b in BUCKETS if owner_type in b["owner_types"]]


def is_bucket_for(owner_type: str, key) -> bool:
    return any(b["key"] == key for b in buckets_for(owner_type))


def bucket_of(owner_type: str, doc: dict):
    """Which bucket a stored `documents` row is shown in.

    The row's own `bucket` wins: a person chose it. Otherwise it is placed by
    its type. None means "not a bucket document at all": a person's identity
    scan, which renders on its identity record instead.
    """
    chosen = doc.get("bucket")
    if chosen and is_bucket_for(owner_type, chosen):
        return chosen
    code = doc.get("document_type_code")
    category = (doc.get("document_types") or {}).get("category")
    if owner_type == "person" and (
            category == IDENTITY_CATEGORY or is_identity_code(code)
            or code == LEGACY_IDENTITY_CODE):
        return None
    return (_BUCKET_BY_CODE.get(owner_type, {}).get(code or "")
            or _BUCKET_BY_CATEGORY.get(owner_type, {}).get(category or "")
            or OTHER_BUCKET)


def extension_of(file_name) -> str:
    name = (file_name or "").strip().lower()
    return name.rsplit(".", 1)[1] if "." in name else ""


def upload_refusal(file_name, size: int):
    """Why this file may not be stored, in words an operator can act on, or None."""
    if size <= 0:
        return "The file is empty"
    if size > MAX_FILE_BYTES:
        return f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB"
    ext = extension_of(file_name)
    if ext in BLOCKED_EXTENSIONS:
        return f".{ext} files can run code when opened, so they cannot be stored here"
    return None


def normalise_tags(tags) -> list[str]:
    """Trimmed, single-spaced, de-duplicated ignoring case, order kept."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        tag = " ".join(str(raw or "").split())[:MAX_TAG_LENGTH]
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            out.append(tag)
    return out


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

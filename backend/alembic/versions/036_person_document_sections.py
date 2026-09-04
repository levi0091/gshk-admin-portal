"""Give a person's documents a shape: sections by category, types under them.

Revision ID: 036
Revises: 035
Create Date: 2026-09-04

THE DEFECT THIS FIXES. `id_scan` — "Identity Document Scan" — was ONE document
type for every identity document a person can hold. `document_service.
upload_document` versions in place on `(owner, document_type_code)`, so a
passport uploaded after an HKID did not sit beside it: it became **version 2 of
the HKID's row**, and the only trace on screen was a version count going up.
Worse, `person_identity_documents` — the table CR is actually filed from — was
never touched by an upload at all, so a scan and the number it shows had no
relationship whatsoever.

Splitting `id_scan` into one type per `id_document_type` enum value restores the
thing versioning is supposed to mean: re-uploading a passport supersedes the
PASSPORT, and leaves the HKID alone.

`category` becomes load-bearing rather than decorative — it is what the profile
draws a section from, and it is why a section can render before anything has
been uploaded into it. Two new categories:

  identity        the four identity types (nothing else may join them: the
                  Identity Documents section carries id_number, issuing country
                  and dates, which mean nothing on a utility bill)
  address_proof   proof of residential address

`id_scan` and the generic `address_proof` are DEACTIVATED, not deleted. There is
a FK from `documents.document_type_code`, and rows already exist in DEV — an
inactive type still resolves through the `document_types(...)` embed, so history
uploaded before today keeps its label and lands in the right section. It just
stops being offered, because "Identity Document Scan" is no longer an answer to
"which identity document is this?".
"""
from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


#: (code, label, category, applies_to, sort_order).
#:
#: The identity codes are `id_` + the `id_document_type` enum value, and
#: `services/documents_sections.py` relies on that exact spelling to turn an
#: upload into a `person_identity_documents` row. Renaming one without the other
#: silently stops identity uploads recording a number.
NEW_TYPES = [
    ("id_hkid", "Hong Kong Identity Card", "identity", "person", 81),
    ("id_passport", "Passport", "identity", "person", 82),
    ("id_china_id", "Mainland China Identity Card", "identity", "person", 83),
    ("id_other", "Other Identity Document", "identity", "person", 84),
    ("addr_utility_bill", "Utility Bill", "address_proof", "both", 91),
    ("addr_bank_statement", "Bank Statement", "address_proof", "both", 92),
    ("addr_tenancy", "Tenancy Agreement", "address_proof", "both", 93),
    ("addr_govt_letter", "Government Correspondence", "address_proof", "both", 94),
]

#: Existing codes whose category has to change so they land in the new sections
#: rather than under a heading called "kyc".
RECATEGORISED = [
    ("id_scan", "identity"),
    ("address_proof", "address_proof"),
]


def upgrade() -> None:
    for code, label, category, applies_to, sort_order in NEW_TYPES:
        op.execute(
            f"""
            INSERT INTO public.document_types
                (code, label, category, applies_to, is_generated, sort_order, is_active)
            VALUES
                ('{code}', '{label}', '{category}', '{applies_to}', false, {sort_order}, true)
            ON CONFLICT (code) DO UPDATE SET
                label = EXCLUDED.label,
                category = EXCLUDED.category,
                applies_to = EXCLUDED.applies_to,
                sort_order = EXCLUDED.sort_order,
                is_active = true
            """
        )

    for code, category in RECATEGORISED:
        op.execute(
            f"UPDATE public.document_types SET category = '{category}' "
            f"WHERE code = '{code}'"
        )

    # Retired, not removed. `id_scan` cannot say WHICH document it is, and the
    # bare `address_proof` is now the vaguest of five ways to say the same
    # thing. Existing rows keep their label through the embed.
    op.execute(
        "UPDATE public.document_types SET is_active = false, "
        "label = 'Identity Document Scan (retired)' WHERE code = 'id_scan'"
    )
    op.execute(
        "UPDATE public.document_types SET is_active = false, "
        "label = 'Proof of Address (retired)' WHERE code = 'address_proof'"
    )


def downgrade() -> None:
    """Reverse only what is reversible.

    A DELETE of the new types is blocked by `documents.document_type_code` the
    moment anything has been uploaded under one, so it is guarded: the rows are
    deactivated when they are in use and removed when they are not. Downgrading
    on top of live uploads must not fail, and must not orphan them either.
    """
    op.execute(
        "UPDATE public.document_types SET is_active = true, "
        "label = 'Identity Document Scan' WHERE code = 'id_scan'"
    )
    op.execute(
        "UPDATE public.document_types SET is_active = true, "
        "label = 'Proof of Address' WHERE code = 'address_proof'"
    )

    codes = ", ".join(f"'{code}'" for code, *_ in NEW_TYPES)
    op.execute(
        f"""
        UPDATE public.document_types SET is_active = false
         WHERE code IN ({codes})
           AND EXISTS (SELECT 1 FROM public.documents d
                        WHERE d.document_type_code = document_types.code)
        """
    )
    op.execute(
        f"""
        DELETE FROM public.document_types
         WHERE code IN ({codes})
           AND NOT EXISTS (SELECT 1 FROM public.documents d
                            WHERE d.document_type_code = document_types.code)
        """
    )

    for code, category in [("id_scan", "kyc"), ("address_proof", "kyc")]:
        op.execute(
            f"UPDATE public.document_types SET category = '{category}' "
            f"WHERE code = '{code}'"
        )

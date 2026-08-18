"""BE-6 fix round 1: record WHICH version of the signed form proves this case.

Migration 021 gave nar1_cases a `manual_signed_document_id` pointing at the
wet-signed NAR1. That pointer is not sufficient on its own, and the reason is in
`services/document_service.py:118-147`: `upload_document` finds the existing
ACTIVE documents row for a `(owner, document_type_code)` pair, bumps
`current_version`, and rewrites `storage_path` / `file_name` / `checksum` ON THAT
SAME ROW. The `documents.id` is stable across years by design.

So company X's 2027 manual-sign returns the same id already stored on the 2026
case AND mutates the row that id points at. Case NAR-2026-xxxx would still claim
its signed NAR1 is document `d1`, but fetching `d1` now serves the 2027 scan. The
2026 bytes survive in `document_versions` — nothing was lost — but nothing on
`nar1_cases` said which of them was the evidence for that case.

For the one record whose entire job is to prove a given statutory return was
signed, a pointer that silently resolves to a different year's form is not
adequate. `(manual_signed_document_id, manual_signed_document_version)` is
exactly the pair `document_versions` is keyed on
(`document_versions.document_id` + `version_number`), so the stored pair resolves
to the right bytes forever.

Nullable and with no backfill, deliberately: a NULL means "signed before this
column existed", which is honest. Inventing a version for existing rows would
assert evidence this migration cannot actually verify — and on DEV there is
exactly one such row shape to be wrong about, none on PROD.

NOT applied to PROD. DEV only.
"""
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS, matching 021's style: re-applying against a database that
    # already has the column is a no-op rather than an error.
    op.execute(
        "ALTER TABLE public.nar1_cases "
        "ADD COLUMN IF NOT EXISTS manual_signed_document_version integer"
    )


def downgrade() -> None:
    # Reversible on purpose: CI's migrations job runs `upgrade head` then
    # `downgrade base`, so an irreversible migration breaks the pipeline.
    op.execute(
        "ALTER TABLE public.nar1_cases "
        "DROP COLUMN IF EXISTS manual_signed_document_version"
    )

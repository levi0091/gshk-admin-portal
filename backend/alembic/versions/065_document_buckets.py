"""Document buckets: `documents.bucket` and `documents.tags`.

Revision ID: 065
Revises: 064
Create Date: 2026-11-21

GSHK, 2026-11-21: the operators "do not have the time to select individually
the document types and enter the descriptions". A profile's documents are now
a handful of BUCKETS (Annual Return, Corporate Identity & Due Diligence,
Business Registration Renewal, Maintenance, Payments, Incorporation / Statutory
Registers on a company; KYC & AML on a person) that files are dropped into many
at a time, then tagged and described in bulk.

  bucket   which bucket a person PUT the file in. NULL means "placed by its
           type": everything uploaded before today, and everything the system
           still files by type (a signed NAR1, an ND2A's resignation letter).
           `services/document_sections.bucket_of` reads it that way, so there
           is NO backfill. Checked against the known keys, so a typo in a
           future caller fails here rather than rendering nowhere.
  tags     free text, suggested per bucket by the screen. `{}` by default, so
           every existing row is valid as it stands.

The description is the existing `title` column. It was already free text, and
the signed-form uploads already write a sentence into it.

`GF_DOC_UPDATED` is seeded because a move, a description or a tag change is a
base-data change and is audited (CLAUDE.md §2), and an unseeded code renders
with a blank Action (migrations 022, 034). `origin` and `category` are explicit
because the column default is origin='viewpoint'.

Apply to DEV, then PROD, BEFORE the code deploys: the profile writes both
columns. REVERSIBLE: the downgrade drops both columns, which discards every
bucket choice and tag made since; the files themselves are untouched.
"""
from alembic import op

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None

#: Must match `services/document_sections.BUCKET_KEYS`;
#: tests/test_document_buckets.py fails if the two drift.
BUCKET_KEYS = (
    "annual_return", "corporate_identity", "br_renewal", "maintenance",
    "payments", "incorporation", "kyc", "other",
)

AUDIT_CODE = ("GF_DOC_UPDATED", "Document Moved, Described or Tagged", "document")


def upgrade() -> None:
    keys = ", ".join(f"'{k}'" for k in BUCKET_KEYS)
    op.execute(
        f"""
        ALTER TABLE public.documents
          ADD COLUMN IF NOT EXISTS bucket text,
          ADD COLUMN IF NOT EXISTS tags text[] NOT NULL DEFAULT '{{}}';
        ALTER TABLE public.documents
          DROP CONSTRAINT IF EXISTS documents_bucket_valid;
        ALTER TABLE public.documents
          ADD CONSTRAINT documents_bucket_valid
          CHECK (bucket IS NULL OR bucket IN ({keys}));
        """
    )
    code, name, category = AUDIT_CODE
    op.execute(
        "INSERT INTO public.audit_event_types (code, name, category, origin) "
        f"VALUES ('{code}', '{name}', '{category}', 'g_flowdesk') "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.documents DROP CONSTRAINT IF EXISTS documents_bucket_valid;
        ALTER TABLE public.documents DROP COLUMN IF EXISTS tags;
        ALTER TABLE public.documents DROP COLUMN IF EXISTS bucket;
        """
    )
    # The code is left seeded: audit rows written under it are insert-only and
    # must keep their label.

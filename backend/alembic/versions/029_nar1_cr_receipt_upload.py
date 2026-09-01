"""The CR filing receipt, as a file — `cr_receipt` documents owned by a case.

Spec §4 (2026-09-01). The MANUAL path only: a return signed on paper and filed
through CR's own web portal comes back with a receipt PDF, and until now the
portal recorded only what an operator TYPED off it. Typed figures are what the
audit trail and fee reconciliation read, so they stay — but nothing proved the
filing happened. This adds the proof.

WHY THE RECEIPT IS OWNED BY THE CASE AND NOT THE COMPANY.

`documents` has been polymorphic over (entity, person) since migration 007. A
receipt owned by the ENTITY would be ambiguous between years: `upload_document`
versions in place on (owner, document_type), so a company's 2027 receipt would
overwrite the row the 2026 case points at, and the 2026 case's evidence would
silently become the wrong year's. The same trap was already found and fixed for
the wet-signed scan (migration 023, which is why that one stores a VERSION as
well as an id). A case owns exactly one annual return, so a case-owned receipt
cannot collide.

So `documents` gains a third owner column and the owner CHECK is widened. The
old constraint would reject every receipt row outright.

`applies_to` gains 'case' rather than reusing 'company'. That column drives
which types appear in the document-upload dropdowns (`routers/documents.py`
filters `applies_to IN (owner_type, 'both')`), and a CR receipt has no business
being uploadable as a loose company document — it is evidence attached to one
filing, produced by one endpoint that also gates the submission behind it.
'case' keeps it out of both dropdowns without a special case in that router.

MIGRATION NUMBERING. This was written against head 027 while a parallel branch
held an unmerged 028. That branch landed first (`028_registry_cr_form_fields`),
so `down_revision` is '028' — the two were rebased onto one chain at merge time
rather than left as two alembic heads, which `upgrade head` refuses to resolve.

Applied to DEV ONLY. Nothing applied to PROD.
"""
from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- documents: a third owner, the NAR1 case ---
    op.execute(
        "ALTER TABLE public.documents "
        "  ADD COLUMN IF NOT EXISTS nar1_case_id uuid "
        "  REFERENCES public.nar1_cases(id) ON DELETE CASCADE;"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_nar1_case "
        "ON public.documents (nar1_case_id);"
    )
    # Widened, not replaced by a weaker rule: a document with NO owner at all is
    # still refused. Migration 007 named this constraint; drop by that name.
    op.execute(
        "ALTER TABLE public.documents "
        "  DROP CONSTRAINT IF EXISTS documents_owner_present;"
    )
    op.execute(
        "ALTER TABLE public.documents ADD CONSTRAINT documents_owner_present "
        "CHECK (entity_id IS NOT NULL "
        "    OR person_id IS NOT NULL "
        "    OR nar1_case_id IS NOT NULL);"
    )

    # --- document_types: a scope that is neither a company nor a person ---
    op.execute(
        "ALTER TABLE public.document_types "
        "  DROP CONSTRAINT IF EXISTS document_types_applies_to_valid;"
    )
    op.execute(
        "ALTER TABLE public.document_types "
        "  ADD CONSTRAINT document_types_applies_to_valid "
        "  CHECK (applies_to IN ('company', 'person', 'both', 'case'));"
    )
    op.execute(
        """
        INSERT INTO public.document_types
            (code, label, category, is_generated, sort_order, applies_to)
        VALUES
            ('cr_receipt', 'CR Filing Receipt', 'filing', false, 55, 'case')
        ON CONFLICT (code) DO NOTHING
        """
    )

    # --- nar1_cases: the pointer the manual-submit gate reads ---
    # id AND version, for migration 023's reason: upload_document versions in
    # place, so an id alone stops resolving to THIS case's evidence the moment
    # anything re-uploads against the same owner and type.
    op.execute(
        "ALTER TABLE public.nar1_cases "
        "  ADD COLUMN IF NOT EXISTS manual_receipt_document_id uuid "
        "    REFERENCES public.documents(id) ON DELETE SET NULL, "
        "  ADD COLUMN IF NOT EXISTS manual_receipt_document_version integer;"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.nar1_cases "
        "  DROP COLUMN IF EXISTS manual_receipt_document_version, "
        "  DROP COLUMN IF EXISTS manual_receipt_document_id;"
    )
    op.execute("DELETE FROM public.document_types WHERE code = 'cr_receipt'")
    op.execute(
        "ALTER TABLE public.document_types "
        "  DROP CONSTRAINT IF EXISTS document_types_applies_to_valid;"
    )
    op.execute(
        "ALTER TABLE public.document_types "
        "  ADD CONSTRAINT document_types_applies_to_valid "
        "  CHECK (applies_to IN ('company', 'person', 'both'));"
    )
    op.execute(
        "ALTER TABLE public.documents "
        "  DROP CONSTRAINT IF EXISTS documents_owner_present;"
    )
    op.execute(
        "ALTER TABLE public.documents ADD CONSTRAINT documents_owner_present "
        "CHECK (entity_id IS NOT NULL OR person_id IS NOT NULL);"
    )
    op.execute("DROP INDEX IF EXISTS public.idx_documents_nar1_case")
    op.execute("ALTER TABLE public.documents DROP COLUMN IF EXISTS nar1_case_id")

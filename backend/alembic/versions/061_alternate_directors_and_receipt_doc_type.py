"""Alternate directors (PBI-70 revived) and the `approval_receipt` document type.

Revision ID: 061
Revises: 060
Create Date: 2026-11-06

ALTERNATE DIRECTORS ARE BACK. Jacqueline, 2026-11-04, on PBI-70: "Alternate
directors are not out of scope. We can still provide the service if client
requests." That reverses the ND2 PRD's answer 5 and the comment 050 left beside
`officer_change_entries.capacity` ("Alternate directors are out of scope (Levi
2026-09-30)"). The pieces CR's forms already carry -- `cpty` = `AD`, the
`altTo` element, the "Alternate Director" box on NAR1, ND2A and ND2B -- were
never the obstacle; the portal simply had no way to RECORD one. Three changes
give it one:

  * `officer_role` gains `alternate_director`, so `entity_officers.role` can hold
    it. It is a separate role, not a flag on a director row, on purpose: every
    place that counts directors (`person_registry`'s `is_director`, the ND2A
    "natural person director remains" rule, NAR1's `dirInd`) reads
    `role = 'director'`, and an alternate must NOT satisfy any of them. A
    company with one director and one alternate has one director. Checked: no
    SQL view restated since 003 enumerates the role list in a way an alternate
    would be miscounted by -- 009 and 049 test `role = 'director'` exactly, and
    057/060 never read the column -- so none is restated here.

  * `officer_change_entries_capacity_valid` accepts `alternate_director`, so an
    ND2A can appoint, cease and (as an ND2B) change one.

  * `alternate_to_officer_id` on BOTH tables: the director an alternate acts
    for. CR prints it ("Alternate to") and the portal needs it to refuse ceasing
    a director while leaving their alternate behind. It points at the director's
    `entity_officers` row, not at the person, because the same person may be a
    director of one company and an alternate in another and "alternate to" is a
    statement about THIS company. `ON DELETE SET NULL`, never CASCADE, for the
    reason 050 gives `officer_id`: removing a director's row by hand must not
    take the alternate -- or the record that a form reported one -- with it.

There is deliberately NO CHECK tying `capacity = 'alternate_director'` to a
non-null `alternate_to_officer_id`. SET NULL would then make deleting a director
row impossible while any alternate pointed at it, which turns a data repair into
a constraint error. The API refuses an alternate with no director
(`cases._check_appointment`, the company officer routes); the database only
guarantees the link, when present, names a real row. Each new column carries a
partial index: the foreign key points at a table of hundreds of thousands of
rows, and without one every `DELETE FROM entity_officers` would scan it.

THE DOCUMENT TYPE. `approval_receipt` ("Client Approval Receipt", Levi
2026-11-06): the receipt the client is mailed when they approve a form is now
filed on the company, in the body-corporate profile's document section. The
seed uses 050 §7's `ON CONFLICT (code) DO UPDATE`, so re-running restores a
type someone deactivated.

ADD VALUE runs inside Alembic's transaction safely on PG 12+ (Supabase is 15+),
as 021 and 050 rely on, as long as the new value is not USED in the same
transaction. Nothing here uses it; the first row to hold it is written by the
application. (Autocommit was considered and not needed.)

Apply to DEV, then PROD, BEFORE the code deploys: the new endpoints write the
role, the capacity and the link column, and a CHECK or an unknown column would
refuse them.

DOWNGRADE drops both columns, restores the narrower CHECK and deletes the
document type (or deactivates it when documents already exist, as 050 does). It
CANNOT remove the enum value: PostgreSQL has no `DROP VALUE`, and recreating the
type would mean rewriting `entity_officers`. A downgraded database therefore
still ACCEPTS `alternate_director` in `entity_officers.role`; the narrower CHECK
on entries and the absence of the link column are what stop the old code using
it. The downgrade also refuses to run while an `alternate_director` row exists
in `entity_officers` or `officer_change_entries`: it would otherwise strand a
role no code of that vintage can display.
"""
from alembic import op

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None

_RECEIPT = ("approval_receipt", "Client Approval Receipt", "government_form",
            "company", 15)


def upgrade() -> None:
    op.execute("ALTER TYPE officer_role ADD VALUE IF NOT EXISTS 'alternate_director'")

    op.execute(
        """
        ALTER TABLE public.officer_change_entries
          DROP CONSTRAINT IF EXISTS officer_change_entries_capacity_valid;
        ALTER TABLE public.officer_change_entries
          ADD CONSTRAINT officer_change_entries_capacity_valid
          CHECK (capacity IN ('director', 'company_secretary', 'alternate_director'));

        ALTER TABLE public.entity_officers
          ADD COLUMN IF NOT EXISTS alternate_to_officer_id uuid
            REFERENCES public.entity_officers(id) ON DELETE SET NULL;
        ALTER TABLE public.officer_change_entries
          ADD COLUMN IF NOT EXISTS alternate_to_officer_id uuid
            REFERENCES public.entity_officers(id) ON DELETE SET NULL;

        CREATE INDEX IF NOT EXISTS ix_entity_officers_alternate_to
          ON public.entity_officers (alternate_to_officer_id)
          WHERE alternate_to_officer_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS ix_officer_change_entries_alternate_to
          ON public.officer_change_entries (alternate_to_officer_id)
          WHERE alternate_to_officer_id IS NOT NULL;
        """
    )

    code, label, category, applies_to, sort_order = _RECEIPT
    op.execute(
        f"""
        INSERT INTO public.document_types
            (code, label, category, applies_to, is_generated, sort_order, is_active)
        VALUES
            ('{code}', '{label}', '{category}', '{applies_to}', false,
             {sort_order}, true)
        ON CONFLICT (code) DO UPDATE SET
            label = EXCLUDED.label,
            category = EXCLUDED.category,
            applies_to = EXCLUDED.applies_to,
            sort_order = EXCLUDED.sort_order,
            is_active = true
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM public.officer_change_entries
                      WHERE capacity = 'alternate_director')
             OR EXISTS (SELECT 1 FROM public.entity_officers
                         WHERE role::text = 'alternate_director') THEN
            RAISE EXCEPTION
              '061 downgrade refused: alternate directors are on record. '
              'Remove or convert them first; the enum value itself cannot be dropped.';
          END IF;
        END $$;
        """
    )
    op.execute(
        """
        DROP INDEX IF EXISTS public.ix_officer_change_entries_alternate_to;
        DROP INDEX IF EXISTS public.ix_entity_officers_alternate_to;
        ALTER TABLE public.officer_change_entries
          DROP COLUMN IF EXISTS alternate_to_officer_id;
        ALTER TABLE public.entity_officers
          DROP COLUMN IF EXISTS alternate_to_officer_id;
        ALTER TABLE public.officer_change_entries
          DROP CONSTRAINT IF EXISTS officer_change_entries_capacity_valid;
        ALTER TABLE public.officer_change_entries
          ADD CONSTRAINT officer_change_entries_capacity_valid
          CHECK (capacity IN ('director', 'company_secretary'));
        """
    )
    code = _RECEIPT[0]
    op.execute(
        f"""
        UPDATE public.document_types SET is_active = false
         WHERE code = '{code}'
           AND EXISTS (SELECT 1 FROM public.documents d
                        WHERE d.document_type_code = document_types.code)
        """
    )
    op.execute(
        f"""
        DELETE FROM public.document_types
         WHERE code = '{code}'
           AND NOT EXISTS (SELECT 1 FROM public.documents d
                            WHERE d.document_type_code = document_types.code)
        """
    )

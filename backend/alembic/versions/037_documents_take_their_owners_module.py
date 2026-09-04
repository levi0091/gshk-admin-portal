"""Audit trail: a document takes its OWNER's module — there is no `documents`.

Revision ID: 037
Revises: 036
Create Date: 2026-09-04

Migration 034 gave every audit row a `module`, and made `documents` one of the
five. That was wrong, and the Audit Log screen showed why within a day: an id
scan uploaded against a director rendered

    Documents | Document Uploaded | Person  Brian YIU | id_scan v1 (HKID.pdf)

directly above

    Natural Person | Change Master File Details | Person  Brian YIU | line1: ...

— the same person, the same afternoon, filed under two different modules. The
module filter exists so an operator can ask "everything that happened in Natural
Person", and a `documents` module made that question unanswerable in one go: it
split every record's history in two, and the operator had to know in advance
that a document upload was not filed where the record is.

A document is not a thing that happens to nobody. It is uploaded AGAINST a
person, a company or a case, and it belongs to that record's module:

    person-owned  (an id scan, a proof of address)   -> natural_person
    entity-owned  (a certificate, an AoA)            -> body_corporate
    case-owned    (a CR receipt, a wet-signed NAR1)  -> post_incorporation

which is exactly what `subject_kind` already records, on every one of these rows
— so this migration reads the answer rather than re-deriving it. The case arm
has no rows yet on DEV; it is here because `document_service._audit_owner` can
write one the moment a receipt is uploaded.

`subject_kind` IS NOT TOUCHED. What the row is ABOUT has not changed — only
which module it is filed under. A row that somehow has no subject_kind keeps
`module = 'documents'`, because the honest answer is that we cannot tell whose
document it was, and inventing a module for it would put it in a filter result
where an operator would then take it for a person's or a company's history.
DEV has none: all 15 rows resolve (9 company, 6 person, verified 2026-09-04).

DOWNGRADE CANNOT BE EXACT and does not pretend to be. Going back would mean
re-labelling document rows `documents`, which IS reversible — but only for rows
whose entity_type is still 'document'. That is the whole set, so the downgrade
is written and is exact for these rows; what it cannot restore is a module some
future writer set deliberately.
"""
from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


#: `subject_kind` -> the module that kind belongs to. The same three pairs as
#: `services/audit_subject._MODULE_FOR_KIND` and
#: `etl/transform/checkpoint_c._MODULE_FOR_KIND`. Three copies of one rule is
#: two too many, but a migration must not import application code — it has to
#: keep working against a checkout years older than itself.
MODULE_FOR_KIND = {
    "person": "natural_person",
    "company": "body_corporate",
    "case": "post_incorporation",
}


def upgrade() -> None:
    # 15 rows on DEV. The bound is not the row count, it is that `module` is a
    # plain TEXT column with a btree index (034) and no dependants.
    op.execute("SET LOCAL statement_timeout = '600s'")

    op.execute(
        """
        UPDATE audit_log
        SET module = CASE subject_kind
              WHEN 'person'  THEN 'natural_person'
              WHEN 'company' THEN 'body_corporate'
              WHEN 'case'    THEN 'post_incorporation'
            END
        WHERE module = 'documents'
          -- Only where the CASE resolves. Without this, a row with no
          -- subject_kind is rewritten to NULL — worse than the wrong module,
          -- because a NULL module renders as a dash and reads as "imported
          -- from Viewpoint", which a document upload never is.
          AND subject_kind IN ('person', 'company', 'case')
        """
    )

    # The other half of the same rule, and the reason this is not just a data
    # fix: an ADDRESS on a person was already labelled natural_person, but a
    # document on that person was not, and both now come from subject_kind.
    # Any row that reached the table with entity_type='document' and no module
    # at all (written during a deploy gap — see the 2026-09-04 note in
    # etl/backfill_audit_context.py) is labelled here too, so the repair does
    # not depend on someone remembering to run the backfill.
    op.execute(
        """
        UPDATE audit_log
        SET module = CASE subject_kind
              WHEN 'person'  THEN 'natural_person'
              WHEN 'company' THEN 'body_corporate'
              WHEN 'case'    THEN 'post_incorporation'
            END
        WHERE module IS NULL
          AND source = 'g_flowdesk'
          AND entity_type = 'document'
          AND subject_kind IN ('person', 'company', 'case')
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL statement_timeout = '600s'")
    op.execute(
        """
        UPDATE audit_log
        SET module = 'documents'
        WHERE source = 'g_flowdesk'
          AND entity_type = 'document'
          AND module IN ('natural_person', 'body_corporate', 'post_incorporation')
        """
    )

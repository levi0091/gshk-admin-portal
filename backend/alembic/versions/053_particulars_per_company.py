"""Identification and addresses per company (Levi 2026-10-05).

Design: `docs/superpowers/specs/2026-10-05-nd2-levi-revisions-design.md` §6.

"We do have clients holding 2 passports, say French and US passports. The same
situation might apply to addresses too. The client might use different
addresses for different companies. It seems you need to build a link between
person's identification and person's residential and correspondence address
with different companies."

  person_addresses
      The person's address book: every residential and correspondence address
      they have given, whether or not a company uses it yet — the "New" button
      on the profile adds a row here. Backfilled from the residential address
      on every person and the correspondence address on every officer row.
      RLS on, no policy, revoked from the browser roles, like 050's tables:
      the backend reads it with the service role.

  entity_officers.residential_address_id
  entity_officers.identity_document_id
      What ONE appointment files. NULL is the person's default — their
      residential address, their primary document of each type — which is what
      every reader did before this migration, so nothing changes until someone
      links. `correspondence_address_id` (028) is the third of the set.
      ON DELETE SET NULL: deleting a passport sends the company back to the
      person's primary, never to a dangling id.

REVERSIBLE; the downgrade refuses while any appointment carries a link or the
address book holds an address no backfill would recreate, rather than lose a
statement of which company files what.

Revision ID: 053
Revises: 052
"""
from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None

UPGRADE_SQL = [
    """
    CREATE TABLE IF NOT EXISTS public.person_addresses (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      person_id   uuid NOT NULL REFERENCES public.persons(id) ON DELETE CASCADE,
      address_id  uuid NOT NULL REFERENCES public.addresses(id) ON DELETE CASCADE,
      kind        text NOT NULL CHECK (kind IN ('residential', 'correspondence')),
      created_by  uuid REFERENCES public.users(id) ON DELETE SET NULL,
      created_at  timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_person_addresses UNIQUE (person_id, address_id, kind)
    );
    CREATE INDEX IF NOT EXISTS ix_person_addresses_person
      ON public.person_addresses (person_id);
    """,
    """
    ALTER TABLE public.entity_officers
      ADD COLUMN IF NOT EXISTS residential_address_id uuid REFERENCES public.addresses(id) ON DELETE SET NULL,
      ADD COLUMN IF NOT EXISTS identity_document_id uuid REFERENCES public.person_identity_documents(id) ON DELETE SET NULL;
    """,
    """
    INSERT INTO public.person_addresses (person_id, address_id, kind)
      SELECT id, residential_address_id, 'residential' FROM public.persons
      WHERE residential_address_id IS NOT NULL
      ON CONFLICT DO NOTHING;
    INSERT INTO public.person_addresses (person_id, address_id, kind)
      SELECT DISTINCT person_id, correspondence_address_id, 'correspondence' FROM public.entity_officers
      WHERE person_id IS NOT NULL AND correspondence_address_id IS NOT NULL
      ON CONFLICT DO NOTHING;
    """,
]

LOCK_DOWN = """
    ALTER TABLE public.person_addresses ENABLE ROW LEVEL SECURITY;
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON public.person_addresses FROM anon;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON public.person_addresses FROM authenticated;
      END IF;
    END $$;
"""

DOWNGRADE_GUARD = """
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM public.entity_officers
                 WHERE residential_address_id IS NOT NULL
                    OR identity_document_id IS NOT NULL) THEN
        RAISE EXCEPTION
          'migration 053 cannot be downgraded while an appointment links its own '
          'residential address or identity document. Clear the links first, knowingly.';
      END IF;
      IF EXISTS (
        SELECT 1 FROM public.person_addresses pa
        WHERE NOT EXISTS (SELECT 1 FROM public.persons p
                          WHERE p.id = pa.person_id AND p.residential_address_id = pa.address_id)
          AND NOT EXISTS (SELECT 1 FROM public.entity_officers o
                          WHERE o.person_id = pa.person_id
                            AND o.correspondence_address_id = pa.address_id)) THEN
        RAISE EXCEPTION
          'migration 053 cannot be downgraded while the address book holds an address '
          'no company or person uses. Remove those first, knowingly.';
      END IF;
    END $$;
"""


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)
    op.execute(LOCK_DOWN)


def downgrade() -> None:
    op.execute(DOWNGRADE_GUARD)
    op.execute("""
        ALTER TABLE public.entity_officers
          DROP COLUMN IF EXISTS identity_document_id,
          DROP COLUMN IF EXISTS residential_address_id;
    """)
    op.execute("DROP TABLE IF EXISTS public.person_addresses")

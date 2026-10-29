"""A director's drawn signature on an ND2A / ND2B -- `officer_change_signatures`.

Revision ID: 059
Revises: 058
Create Date: 2026-10-29

Levi 2026-10-29 (e-signature-nd2): a director opening the Confirm & File page
for an ND2A or ND2B draws their signature and presses the button; the portal
prints it on its own rendered copies of the form and the written resolution. One
row per press: `approval_id` is UNIQUE, so the claim that settles "first approval
wins" can never leave two signatures behind it.

WHY `image_b64 text` AND NOT `bytea`. PostgREST exchanges bytea as `\\x<hex>`
strings, which is easy to get wrong in both directions and yields a column that
looks right in a unit test with a mock and returns garbage against the real
service. A base64 string is what the page already posts; the 200 KB cap that the
route enforces keeps it small.

WHY NO POLICY. RLS is ON and nothing is granted to anon or authenticated, so the
table is reachable by the service role only -- exactly like
`nar1_client_approvals`. A drawn signature is personal data; the portal never
needs the browser to read it back. There is no UPDATE or DELETE path in code.

`case_id` cascades with the case (the officer-change case is a `nar1_cases` row,
form_code Nd2a / Nd2b). `approval_id` does NOT cascade: the approval row is the
record that somebody confirmed a statutory filing and must not be erased by
deleting a signature, nor the reverse.

Apply to DEV, then PROD, BEFORE the code deploys: the new code inserts into it.
REVERSIBLE: the downgrade drops the table (and with it every stored image).
"""
from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.officer_change_signatures (
          id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          case_id      uuid NOT NULL
                         REFERENCES public.nar1_cases(id) ON DELETE CASCADE,
          approval_id  uuid NOT NULL UNIQUE
                         REFERENCES public.nar1_client_approvals(id),
          person_id    uuid NOT NULL,
          -- The verification revision the director's link belonged to: a
          -- re-send supersedes older signatures exactly as it supersedes links.
          revision     integer NOT NULL,
          image_b64    text NOT NULL,
          signed_at    timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_officer_change_signatures_case
          ON public.officer_change_signatures (case_id, revision);
        """
    )
    # Drawn signatures are personal data: locked down exactly as migration 050
    # locks its personal-data tables — RLS on, no policy, and no grant left to
    # anon or authenticated. The backend reaches it as service_role.
    op.execute(
        """
        ALTER TABLE public.officer_change_signatures ENABLE ROW LEVEL SECURITY;
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            REVOKE ALL ON public.officer_change_signatures FROM anon;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            REVOKE ALL ON public.officer_change_signatures FROM authenticated;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.officer_change_signatures")

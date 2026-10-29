"""Multi-director signing on an ND2A / ND2B -- `multi_signer`, `required_signers`.

Revision ID: 060
Revises: 059
Create Date: 2026-10-29

Levi 2026-10-29 (nd2-multi-signer): "do not change the nar1 flow. however, we
should add on an option when multiple signatures are required from multiple
directors. then we should see 2 separate sending features and the signatures
should converge once all are collected." Two columns on `nar1_cases` carry it,
beside the ND2-only `signing_method` and `signatory_capacity` that already live
on this table:

  multi_signer      the "Multiple directors must sign" option. Off by default,
                    and off means today's flow exactly.
  required_signers  the signer set for the current revision, as
                    [{"person_id", "name", "roles"}], NULL until the first send
                    of a round and cleared by Restart verification.

WHY THE SET IS FROZEN, NOT COMPUTED. Who must sign is read from live company
data (the current officers and the signatory register). If a director were
marked ceased on the profile in the middle of a round, a live count could drop
to "everyone has signed" with nobody left to press anything, and the case would
never converge. Freezing the set at the first send -- the moment the change
list locks -- gives each round a fixed target; if the board really has changed,
the operator restarts verification and the set is recomputed.

WHY THE CHECK. NAR1 must behave exactly as it does today, and a NAR1 row that
carried `multi_signer = true` would be the one way the new mode could leak onto
that path. `CHECK (NOT multi_signer OR form_code IN ('Nd2a', 'Nd2b'))` makes it
impossible rather than merely unexpected. Existing rows default to false and
pass it. The upgrade drops the constraint IF EXISTS before adding it, as 050
does, so a re-run after a partial or manual apply succeeds. No view reads either column (the case view lists its columns
explicitly), so none is restated, and no policy changes: the table's access
rules are not this migration's business.

On PostgreSQL 11 and later `ADD COLUMN ... DEFAULT false` does not rewrite the
table, and the CHECK scans a table of a few thousand rows.

Apply to DEV, then PROD, BEFORE the code deploys: the new PATCH writes
`multi_signer`, and an unknown column would be refused by PostgREST.
REVERSIBLE: the downgrade drops the constraint and both columns (and with them
any frozen signer set).
"""
from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.nar1_cases
          ADD COLUMN IF NOT EXISTS multi_signer boolean NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS required_signers jsonb;
        ALTER TABLE public.nar1_cases
          DROP CONSTRAINT IF EXISTS nar1_cases_multi_signer_officer_change_only;
        ALTER TABLE public.nar1_cases
          ADD CONSTRAINT nar1_cases_multi_signer_officer_change_only
          CHECK (NOT multi_signer OR form_code IN ('Nd2a', 'Nd2b'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.nar1_cases
          DROP CONSTRAINT IF EXISTS nar1_cases_multi_signer_officer_change_only;
        ALTER TABLE public.nar1_cases
          DROP COLUMN IF EXISTS required_signers,
          DROP COLUMN IF EXISTS multi_signer;
        """
    )

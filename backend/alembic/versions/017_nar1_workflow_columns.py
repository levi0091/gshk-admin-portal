"""PRD nar1-wireframe-amend-frontend §8: the three columns decisions D-3/D-4/D-6 need.

One revision, so a rollback returns the schema to a single known state (same
discipline as 016).

  D-6  nar1_cases gains the client-response columns. The displayed workflow
       status is a function of TWO sources: tpsi_filings.stage owns the CR-chain
       facts, and these columns own the client facts. Splitting it that way gives
       every fact exactly one writer. Extending case_status to carry CR-chain
       state was rejected -- it duplicates tpsi_filings.stage, and the two
       disagree on every failure path.

       nnc1_cases already carries client_approved/client_response_at; nar1_cases
       simply never got them.

  D-3  tpsi_presenter_credentials gains the deposit account. Both
       /filings/{id}/preview and /filings/{id}/submit require it and it lived
       nowhere -- it belongs with the presenter identity that spends it, and
       survives unchanged if GSHK ever adds a second presenter account.

  D-4  persons gains the signatory's CR e-Service user ID. verifyPinSigning
       takes a CR e-Service ID, NOT a G-FlowDesk user UUID. This is an
       identifier, not a secret, so it is stored in plaintext deliberately --
       the signing PASSWORD is still never persisted for a non-GSHK signer
       (locked decision D4).

Deliberately NOT here: signing_started_at. D-6 collapses "Client Approved" and
"Client Signatory" into a single "Signing" status, so nothing needs to record
that an admin opened the signing screen.
"""
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # D-6 · client-response state on the NAR1 case.
    op.execute("""
        ALTER TABLE public.nar1_cases
          ADD COLUMN IF NOT EXISTS verification_sent_at timestamptz,
          ADD COLUMN IF NOT EXISTS client_approved      boolean,
          ADD COLUMN IF NOT EXISTS client_response_at   timestamptz;
    """)

    # Partial index: the dashboard's "Awaiting Client" filter looks for cases
    # that were sent and have not answered. Those are a small slice of the
    # table and the only rows this predicate ever returns.
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_nar1_cases_awaiting_client
          ON public.nar1_cases (verification_sent_at)
          WHERE verification_sent_at IS NOT NULL AND client_approved IS NULL;
    """)

    # D-3 · the deposit account the filing fee is drawn from.
    op.execute("""
        ALTER TABLE public.tpsi_presenter_credentials
          ADD COLUMN IF NOT EXISTS deposit_account_no text;
    """)

    # D-4 · the signatory's CR e-Service user ID.
    op.execute("""
        ALTER TABLE public.persons
          ADD COLUMN IF NOT EXISTS eservice_user_id text;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_nar1_cases_awaiting_client")
    op.execute("ALTER TABLE public.persons DROP COLUMN IF EXISTS eservice_user_id")
    op.execute(
        "ALTER TABLE public.tpsi_presenter_credentials "
        "DROP COLUMN IF EXISTS deposit_account_no"
    )
    op.execute("""
        ALTER TABLE public.nar1_cases
          DROP COLUMN IF EXISTS client_response_at,
          DROP COLUMN IF EXISTS client_approved,
          DROP COLUMN IF EXISTS verification_sent_at;
    """)

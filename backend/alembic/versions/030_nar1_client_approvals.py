"""Client self-approval — `nar1_client_approvals`, provenance, audit codes.

Spec §5 (2026-09-01). Until now the only way a client's answer reached the
portal was a staff member reading a reply and typing it in. This adds a second
path — the client presses a button in the email — and a third, the 14-day
timeout job, and makes all three say WHICH one happened.

WHY THE TOKEN IS STORED AS A HASH. The row holds `sha256(token)`, never the
token. A database read — a backup, a support query, an ETL dump — must not be
enough to approve somebody's annual return. The plaintext exists only in that
director's mailbox, and the lookup hashes what arrives and compares.

WHY `outcome` IS A VOCABULARY AND NOT A BOOLEAN. Three end states matter and
only one of them is "approved":

  NULL         issued, nobody has clicked
  approved     this director approved; the case is decided
  superseded   invalidated before it was used — either because another
               director got there first, or because verification was restarted
               and the document this token approves no longer exists

The third is the load-bearing one. Without it, a director holding the PREVIOUS
email could approve a snapshot that has since been corrected and re-validated,
and the portal would record an approval of a document CR is not being asked to
file. That is the same class of defect `filings.supersede()` was written for,
arriving through a different door.

PROVENANCE ON THE CASE. `client_approved` is a boolean and cannot say how the
answer arrived. Three columns carry that, because a workflow screen or an audit
trail that renders a bare "Approved" over a director who never answered is
making a claim nobody made:

  client_approval_source     self_service | staff_relay | system_timeout
  client_approval_person_id  which director, when we know
  client_approval_name       their name as displayed at the time

The name is DENORMALISED on purpose. It is what the trail should keep saying
years later even if the person row is renamed, merged by the party-master work,
or deleted — an audit record of who approved a statutory filing must not be
rewritable by an unrelated edit to a contact record.

MIGRATION NUMBERING. Head was 027 when this branch started; 029 (spec §4) sits
between. A parallel branch (`worktree-registry-form-fidelity`, unmerged) adds
its own 028. If that branch lands first, 029's `down_revision` moves to '028'
and this one keeps pointing at '029'.

Applied to DEV ONLY. Nothing applied to PROD.
"""
from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None

#: category/origin explicit — the column default is origin='viewpoint', which
#: would mislabel these as imported Viewpoint history, and there is NO FK from
#: audit_log to this table, so an unseeded code writes fine and then renders
#: unlabelled in the trail. Migration 022 exists because exactly that happened.
AUDIT_CODES = [
    ("CLIENT_APPROVAL_LINK_SENT", "Approval Link Sent"),
    ("CLIENT_APPROVAL_SELF_SERVICE", "Client Approved Online"),
    ("CLIENT_APPROVAL_AUTO_APPROVED", "Auto-Approved After 14 Days"),
]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.nar1_client_approvals (
          id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          nar1_case_id     uuid NOT NULL
                             REFERENCES public.nar1_cases(id) ON DELETE CASCADE,
          -- Nullable: an operator may type an address that belongs to no
          -- director on record, and a token issued to it is still a real token.
          -- ON DELETE SET NULL, never CASCADE: deleting a person must not erase
          -- the record that somebody approved a statutory filing.
          person_id        uuid REFERENCES public.persons(id) ON DELETE SET NULL,
          recipient_email  text NOT NULL,
          -- The name as it stood when the link was sent. See the module
          -- docstring: the trail must not be rewritable by a later rename.
          recipient_name   text,
          -- sha256 hex of the token. NEVER the token.
          token_hash       text NOT NULL,
          sent_at          timestamptz NOT NULL DEFAULT now(),
          expires_at       timestamptz NOT NULL,
          responded_at     timestamptz,
          outcome          text,
          ip_address       inet,
          user_agent       text,
          created_at       timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT nar1_client_approvals_outcome_valid
            CHECK (outcome IS NULL OR outcome IN ('approved', 'superseded'))
        );
        -- UNIQUE, and it is the lookup: a token resolves to exactly one row or
        -- to nothing. A duplicate hash would make "which case did this approve"
        -- ambiguous on the one route that has no authenticated user behind it.
        CREATE UNIQUE INDEX ux_nar1_client_approvals_token
          ON public.nar1_client_approvals (token_hash);
        CREATE INDEX ix_nar1_client_approvals_case
          ON public.nar1_client_approvals (nar1_case_id);
        -- The 14-day job's own query: outstanding tokens past their expiry.
        CREATE INDEX ix_nar1_client_approvals_pending
          ON public.nar1_client_approvals (expires_at)
          WHERE outcome IS NULL;
        """
    )

    op.execute(
        """
        ALTER TABLE public.nar1_cases
          ADD COLUMN IF NOT EXISTS client_approval_source text,
          ADD COLUMN IF NOT EXISTS client_approval_person_id uuid
            REFERENCES public.persons(id) ON DELETE SET NULL,
          ADD COLUMN IF NOT EXISTS client_approval_name text;
        """
    )
    # No CHECK on the source vocabulary, for migration 026's reason: the values
    # live in services/nar1_approvals.py and a constraint that disagreed with
    # the code would refuse a value the application considers valid. NULL means
    # "approved before this column existed, or not approved at all" — which is
    # the honest state of every existing row, so there is no backfill.

    values = ", ".join(
        f"('{code}', '{name}', 'nar1', 'g_flowdesk')" for code, name in AUDIT_CODES
    )
    op.execute(
        f"INSERT INTO public.audit_event_types (code, name, category, origin) "
        f"VALUES {values} ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    codes = ", ".join(f"'{c}'" for c, _ in AUDIT_CODES)
    op.execute(f"DELETE FROM public.audit_event_types WHERE code IN ({codes})")
    op.execute(
        "ALTER TABLE public.nar1_cases "
        "  DROP COLUMN IF EXISTS client_approval_name, "
        "  DROP COLUMN IF EXISTS client_approval_person_id, "
        "  DROP COLUMN IF EXISTS client_approval_source;"
    )
    op.execute("DROP TABLE IF EXISTS public.nar1_client_approvals")

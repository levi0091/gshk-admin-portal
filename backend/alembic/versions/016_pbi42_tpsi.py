"""PBI-42: TPSI integration — presenter credentials, token store, filing ledger.

Three tables plus the permission and audit-registry changes, in ONE revision so
a rollback returns the schema to a single known state.

  tpsi_presenter_credentials  the GSHK filer's CR identity (user-scoped).
                              NOT tpsi_accounts, which is entity-scoped and
                              holds the CLIENT company's own e-Registry account.
  tpsi_tokens                 one live token per CR account, shared across
                              workers/replicas. An in-process cache breaks
                              silently under more than one worker.
  tpsi_filings                per-attempt chain state, so the irreversible
                              submit gate is server-enforced.
"""
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None

AUDIT_CODES = [
    ("TPSI_AUTH", "CR Session Opened"),
    ("TPSI_FILING_CREATED", "CR Filing Prepared"),
    ("TPSI_VALIDATE", "CR Form Validated"),
    ("TPSI_SIGN", "CR Form Signed"),
    ("TPSI_EDRIVE", "CR Form Sent to e-Drive"),
    ("TPSI_PREVIEWED", "CR Submission Previewed"),
    ("TPSI_SUBMIT_ATTEMPTED", "CR Submission Attempted"),
    ("TPSI_SUBMIT_SUCCESS", "CR Submission Succeeded"),
    ("TPSI_SUBMIT_FAILED", "CR Submission Failed"),
    ("TPSI_BALANCE_CHECK", "CR Deposit Balance Checked"),
    ("TPSI_STATUS", "CR Case Status Enquired"),
    ("TPSI_CRED_SET", "CR Credential Set"),
    ("TPSI_CRED_ROTATE", "CR Credential Rotated"),
    ("TPSI_PW_CHANGE", "CR Password Changed"),
]


def upgrade() -> None:
    op.execute("""
        CREATE TABLE tpsi_presenter_credentials (
          id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id                   uuid NOT NULL UNIQUE
                                      REFERENCES users(id) ON DELETE CASCADE,
          presentor_account_id      text NOT NULL,
          tpsi_password_enc         text NOT NULL,
          eservice_user_id          text,
          eservice_password_enc     text,
          tpsi_password_expires_at  timestamptz,
          is_test                   boolean NOT NULL DEFAULT true,
          last_rotated_at           timestamptz,
          created_at                timestamptz NOT NULL DEFAULT now(),
          updated_at                timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE tpsi_tokens (
          presentor_account_id  text PRIMARY KEY,
          access_token_enc      text NOT NULL,
          expires_at            timestamptz NOT NULL,
          updated_at            timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE tpsi_filings (
          id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id             uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          form_filing_id        uuid REFERENCES form_filings(id),
          nar1_case_id          uuid REFERENCES nar1_cases(id),
          form_code             text NOT NULL,
          stage                 text NOT NULL DEFAULT 'draft'
                                  CHECK (stage IN ('draft','validated','signed',
                                                   'submitted','edrive','failed')),
          request_xml           text,
          validated_xml         text,
          signed_xml            text,
          presenter_user_id     uuid REFERENCES users(id),
          presentor_account_id  text,
          fee_amount            numeric(12,2),
          balance_at_submit     numeric(14,2),
          receipt               jsonb,
          cr_error              jsonb,
          validated_at          timestamptz,
          signed_at             timestamptz,
          submitted_at          timestamptz,
          created_at            timestamptz NOT NULL DEFAULT now(),
          updated_at            timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_tpsi_filings_entity ON tpsi_filings(entity_id);
        CREATE INDEX idx_tpsi_filings_stage  ON tpsi_filings(stage);
    """)

    # The double-charge guard. A double-clicked submit hits this, not CR.
    op.execute(
        "CREATE UNIQUE INDEX uq_tpsi_filings_submitted "
        "ON tpsi_filings(form_filing_id) WHERE stage = 'submitted'"
    )

    for table in ("tpsi_presenter_credentials", "tpsi_tokens", "tpsi_filings"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f'CREATE POLICY "{table}_authenticated_all" ON public.{table} '
            "FOR ALL TO authenticated USING (true) WITH CHECK (true);"
        )

    for table in ("tpsi_presenter_credentials", "tpsi_filings"):
        op.execute(
            f"CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )

    # Widen the permission CHECK for the distinct 'submit' level (spec D7).
    op.execute(
        "ALTER TABLE public.role_permissions "
        "DROP CONSTRAINT IF EXISTS role_permissions_permission_check"
    )
    op.execute(
        "ALTER TABLE public.role_permissions "
        "ADD CONSTRAINT role_permissions_permission_check "
        "CHECK (permission IN ('read', 'write', 'delete', 'submit'))"
    )

    # super_admin only, role-existence-guarded, idempotent — as migration 008.
    op.execute("""
        INSERT INTO public.role_permissions (role_id, module, permission)
        SELECT r.id, m.module, m.permission
        FROM public.roles r
        CROSS JOIN (VALUES ('tpsi','read'), ('tpsi','write'), ('tpsi','submit'))
             AS m(module, permission)
        WHERE r.name = 'super_admin'
        ON CONFLICT (role_id, module, permission) DO NOTHING
    """)

    values = ", ".join(f"('{c}', '{n}')" for c, n in AUDIT_CODES)
    op.execute(
        f"INSERT INTO public.audit_event_types (code, name) VALUES {values} "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    codes = ", ".join(f"'{c}'" for c, _ in AUDIT_CODES)
    op.execute(f"DELETE FROM public.audit_event_types WHERE code IN ({codes})")
    # Remove seeded rows before reverting the CHECK, or the constraint fails.
    op.execute(
        "DELETE FROM public.role_permissions rp USING public.roles r "
        "WHERE rp.role_id = r.id AND r.name = 'super_admin' AND rp.module = 'tpsi'"
    )
    op.execute(
        "ALTER TABLE public.role_permissions "
        "DROP CONSTRAINT IF EXISTS role_permissions_permission_check"
    )
    op.execute(
        "ALTER TABLE public.role_permissions "
        "ADD CONSTRAINT role_permissions_permission_check "
        "CHECK (permission IN ('read', 'write', 'delete'))"
    )
    op.execute("DROP TABLE IF EXISTS tpsi_filings")
    op.execute("DROP TABLE IF EXISTS tpsi_tokens")
    op.execute("DROP TABLE IF EXISTS tpsi_presenter_credentials")

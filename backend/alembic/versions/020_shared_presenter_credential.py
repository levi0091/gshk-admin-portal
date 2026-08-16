"""BE-5: the CR presenter credential becomes ONE shared GSHK record.

Reverses PBI-44 AC5/AC8 (Levi, W-6). Two credentials, two scopes:

  tpsi_shared_presenter       the GSHK filing identity — presenter account,
                              TPSI login password, deposit account. ONE row,
                              admin-only. Every user files under it.
  tpsi_presenter_credentials  now the per-user e-SERVICE SIGNING credential.
                              A signature is a personal act and stays personal
                              (W-7), so this table survives — but a user who
                              only signs must not be forced to invent a CR
                              login password, hence the two DROP NOT NULLs.

Why a singleton table rather than a settings row in an existing table: the
presenter identity carries encrypted material, an is_test flag that must match
TPSI_ENV, and an expiry CR enforces every 180 days. That is a record with its
own lifecycle, not a key-value setting.

`deposit_account_no` moves here (spec §5 BE-5). The column stays on the per-user
table for now and is read as a fallback -- dropping it in the same revision
would strand any value an existing user already saved. It is removed in a later
revision once BE-5 is confirmed on DEV.
"""
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None

AUDIT_CODES = [
    ("TPSI_CRED_CONFIG", "CR Shared Presenter Configured"),
]


def upgrade() -> None:
    # `id boolean PRIMARY KEY DEFAULT true CHECK (id)` is the singleton idiom:
    # the only value the primary key admits is true, so the table can hold at
    # most one row and every write is an upsert onto it.
    op.execute("""
        CREATE TABLE tpsi_shared_presenter (
          id                        boolean PRIMARY KEY DEFAULT true CHECK (id),
          presentor_account_id      text NOT NULL,
          tpsi_password_enc         text NOT NULL,
          deposit_account_no        text,
          tpsi_password_expires_at  timestamptz,
          is_test                   boolean NOT NULL DEFAULT true,
          last_rotated_at           timestamptz,
          updated_by                uuid REFERENCES users(id),
          created_at                timestamptz NOT NULL DEFAULT now(),
          updated_at                timestamptz NOT NULL DEFAULT now()
        );
    """)

    op.execute("ALTER TABLE public.tpsi_shared_presenter ENABLE ROW LEVEL SECURITY;")
    op.execute(
        'CREATE POLICY "tpsi_shared_presenter_authenticated_all" '
        "ON public.tpsi_shared_presenter FOR ALL TO authenticated "
        "USING (true) WITH CHECK (true);"
    )
    op.execute(
        "CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON tpsi_shared_presenter "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # The per-user row is now a SIGNING credential. Its CR-login columns become
    # optional so a director-only signer can hold one without a presenter login.
    op.execute("""
        ALTER TABLE public.tpsi_presenter_credentials
          ALTER COLUMN presentor_account_id DROP NOT NULL,
          ALTER COLUMN tpsi_password_enc DROP NOT NULL;
    """)

    # category/origin explicit — the column default is origin='viewpoint', which
    # would mislabel a G-FlowDesk event as an imported one (precedent: 016).
    values = ", ".join(f"('{c}', '{n}', 'tpsi', 'g_flowdesk')" for c, n in AUDIT_CODES)
    op.execute(
        f"INSERT INTO public.audit_event_types (code, name, category, origin) "
        f"VALUES {values} ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    codes = ", ".join(f"'{c}'" for c, _ in AUDIT_CODES)
    op.execute(f"DELETE FROM public.audit_event_types WHERE code IN ({codes})")
    # Restoring NOT NULL would fail against any signing-only row written while
    # 020 was applied, so clear those first -- they are meaningless once the
    # shared presenter is gone.
    op.execute(
        "DELETE FROM public.tpsi_presenter_credentials "
        "WHERE presentor_account_id IS NULL OR tpsi_password_enc IS NULL"
    )
    op.execute("""
        ALTER TABLE public.tpsi_presenter_credentials
          ALTER COLUMN presentor_account_id SET NOT NULL,
          ALTER COLUMN tpsi_password_enc SET NOT NULL;
    """)
    op.execute("DROP TABLE IF EXISTS tpsi_shared_presenter")

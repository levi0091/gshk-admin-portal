"""PBI-11: audit_log table + RLS (insert-only) + indexes

Revision ID: 002
Revises: 001
Create Date: 2026-06-06
"""
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.audit_log (
          id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
          created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          case_id           UUID,
          user_id           UUID        REFERENCES auth.users(id),
          user_display_name TEXT        NOT NULL,
          action_type       TEXT        NOT NULL,
          entity_type       TEXT        NOT NULL,
          entity_id         TEXT        NOT NULL,
          before_state      JSONB,
          after_state       JSONB,
          metadata          JSONB
        )
    """)

    op.execute("ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY "audit_log_insert" ON public.audit_log
          FOR INSERT TO authenticated WITH CHECK (true)
    """)
    op.execute("""
        CREATE POLICY "audit_log_select" ON public.audit_log
          FOR SELECT TO authenticated USING (true)
    """)
    # No UPDATE or DELETE policies — immutability enforced by omission

    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_case_id    ON public.audit_log(case_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON public.audit_log(created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_user_id    ON public.audit_log(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.audit_log")

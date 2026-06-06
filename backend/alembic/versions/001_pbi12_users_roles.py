"""PBI-12: users, roles, role_permissions tables + RLS

Revision ID: 001
Revises:
Create Date: 2026-06-06
"""
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.roles (
          id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          name       TEXT UNIQUE NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS public.users (
          id           UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
          display_name TEXT NOT NULL,
          email        TEXT NOT NULL,
          role_id      UUID REFERENCES public.roles(id),
          is_active    BOOLEAN NOT NULL DEFAULT TRUE,
          created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS public.role_permissions (
          id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          role_id    UUID NOT NULL REFERENCES public.roles(id) ON DELETE CASCADE,
          module     TEXT NOT NULL,
          permission TEXT NOT NULL CHECK (permission IN ('read', 'write')),
          UNIQUE (role_id, module, permission)
        )
    """)

    # RLS
    op.execute("ALTER TABLE public.roles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.role_permissions ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY "roles_select" ON public.roles
          FOR SELECT TO authenticated USING (true)
    """)
    op.execute("""
        CREATE POLICY "role_permissions_select" ON public.role_permissions
          FOR SELECT TO authenticated USING (true)
    """)
    op.execute("""
        CREATE POLICY "users_select" ON public.users
          FOR SELECT TO authenticated USING (true)
    """)

    # Indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_users_role_id ON public.users(role_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_role_permissions_role_id ON public.role_permissions(role_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.role_permissions")
    op.execute("DROP TABLE IF EXISTS public.users")
    op.execute("DROP TABLE IF EXISTS public.roles")

"""PBI-39 Block 0: register companies/persons/documents modules + seed permissions

Revision ID: 008
Revises: 007
Create Date: 2026-07-11

Block 0 of PBI-39 (Build G-FlowDesk against wireframe_v7). No table DDL beyond
one CHECK-constraint widening — this migration registers the three new PBI-12
modules by seeding their role_permissions rows, and is the only migration in
this PBI (PRD §3, §5a, §9 Block 0).

Changes
-------
1. role_permissions.permission CHECK widened from ('read','write') to
   ('read','write','delete'). The `documents` module needs a `delete` level
   (soft-delete endpoint, OQ-2 / PRD §5a).

2. Seed the new module permissions for `super_admin` ONLY (Levi, 2026-07-11):
     companies  -> read, write
     persons    -> read, write
     documents  -> read, write, delete
   super_admin bypasses require_permission() in code (middleware/auth.py), but
   the row seed is kept explicit for consistency with its existing nar1_data /
   audit_trail rows. nar1_write / all_access get NO new-module access here —
   granted later if needed. Idempotent via UNIQUE(role_id, module, permission)
   + ON CONFLICT DO NOTHING, and role-existence-guarded (super_admin was seeded
   outside Alembic).
"""
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


_MODULE_PERMS = [
    ("companies", "read"),
    ("companies", "write"),
    ("persons", "read"),
    ("persons", "write"),
    ("documents", "read"),
    ("documents", "write"),
    ("documents", "delete"),
]


def upgrade() -> None:
    # 1. Widen the permission CHECK to allow 'delete' (documents module).
    op.execute(
        "ALTER TABLE public.role_permissions "
        "DROP CONSTRAINT IF EXISTS role_permissions_permission_check"
    )
    op.execute(
        "ALTER TABLE public.role_permissions "
        "ADD CONSTRAINT role_permissions_permission_check "
        "CHECK (permission IN ('read', 'write', 'delete'))"
    )

    # 2. Seed the new modules for super_admin only (role-existence-guarded, idempotent).
    op.execute(
        """
        INSERT INTO public.role_permissions (role_id, module, permission)
        SELECT r.id, m.module, m.permission
        FROM public.roles r
        CROSS JOIN (VALUES
            ('companies', 'read'),
            ('companies', 'write'),
            ('persons',   'read'),
            ('persons',   'write'),
            ('documents', 'read'),
            ('documents', 'write'),
            ('documents', 'delete')
        ) AS m(module, permission)
        WHERE r.name = 'super_admin'
        ON CONFLICT (role_id, module, permission) DO NOTHING
        """
    )


def downgrade() -> None:
    # Remove the seeded rows first so the CHECK can be reverted without violation.
    op.execute(
        """
        DELETE FROM public.role_permissions rp
        USING public.roles r
        WHERE rp.role_id = r.id
          AND r.name = 'super_admin'
          AND rp.module IN ('companies', 'persons', 'documents')
        """
    )
    op.execute(
        "ALTER TABLE public.role_permissions "
        "DROP CONSTRAINT IF EXISTS role_permissions_permission_check"
    )
    op.execute(
        "ALTER TABLE public.role_permissions "
        "ADD CONSTRAINT role_permissions_permission_check "
        "CHECK (permission IN ('read', 'write'))"
    )

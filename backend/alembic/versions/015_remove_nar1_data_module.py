"""Remove the nar1_data permission module (cases are not implemented yet).

The portal never shipped a distinct "NAR1 data" surface — companies are managed
through their whole lifecycle from one place. The module only ever guarded the
identity bootstrap (/auth/me, now gated on authentication) and the per-case
audit tab (now gated on audit_trail:read, the same gate as the global audit
page). So the module is dropped rather than renamed.

Also drops the `nar1_write` role, which existed solely to grant this module and
holds no users. `all_access` keeps its other grants (audit_trail); only its
nar1_data rows go.

Roles/permissions are seeded outside Alembic, so on a fresh DB there is nothing
to remove and this is a no-op. Downgrade cannot faithfully reconstruct removed
grants or a deleted role, so it is intentionally a no-op.

Revision ID: 015
Revises: 014
"""
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the module from every role that held it (all_access, nar1_write, ...).
    op.execute("DELETE FROM role_permissions WHERE module = 'nar1_data'")

    # Drop the now-purposeless nar1_write role — but only if no user is assigned
    # to it, so this can never orphan a live account.
    op.execute(
        """
        DELETE FROM roles
        WHERE name = 'nar1_write'
          AND NOT EXISTS (SELECT 1 FROM users WHERE users.role_id = roles.id)
        """
    )


def downgrade() -> None:
    # A data cleanup of removed grants and a deleted role cannot be reversed
    # meaningfully; re-seed via the roles UI/API if the module is ever revived.
    pass

"""`users.must_change_password` — a first sign-in that ends in a password change.

Spec §7 (2026-09-01). An admin no longer chooses a colleague's password: the
portal generates one, mails it, and requires it to be replaced before the
account can do anything.

WHY A COLUMN AND NOT A CONVENTION. The flag is read by `require_user`, which
every authenticated route depends on, so it has to be part of the identity the
middleware already resolves. Anything softer — a frontend redirect, a claim on
the JWT, a naming convention on the password — is walked around by typing a URL.

FALSE FOR EVERY EXISTING ROW, and that is deliberate rather than lazy. Those
users chose (or were given) a password under the old flow and have been signing
in with it; flipping them all to "must change" would lock the whole portal out
at once, including the only super_admin, on the morning this deploys. New users
get TRUE from the application, not from a column default, so the default staying
FALSE cannot lock anybody out if a later insert forgets the field.

MIGRATION NUMBERING. 029 (spec §4) and 030 (spec §5) precede this on the same
branch. A parallel branch (`worktree-registry-form-fidelity`, unmerged) adds its
own 028; if it lands first, 029's `down_revision` moves to '028' and this chain
follows unchanged.

Applied to DEV ONLY. Nothing applied to PROD.
"""
import sqlalchemy as sa
from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None

TABLE = "users"
COLUMN = "must_change_password"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            COLUMN,
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment=(
                "TRUE while this account is still on the password G-FlowDesk "
                "generated and mailed it. `middleware/auth.require_user` "
                "refuses every route except /auth/me and the set-password "
                "endpoint while it is set. Set TRUE by user creation, cleared "
                "only by the user choosing their own password."
            ),
        ),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column(TABLE, COLUMN, schema="public")

"""Permissions: a document takes its OWNER's module — there is no `documents`.

Revision ID: 040
Revises: 039
Create Date: 2026-09-07

THE SECOND HALF OF MIGRATION 037, and for the same reason. 037 fixed the AUDIT
TRAIL: a document was labelled `documents` there, so an id scan uploaded against
a director was filed under a different module from every other change to that
director, and "show me everything that happened in Natural Person" could not
answer in one go. The PERMISSION module had exactly the same shape and exactly
the same problem, one layer down.

`documents` was one of six grantable modules, with its own read/write/delete.
Being separate meant it could disagree with the record it describes, in both
directions:

  * a role granted Companies (edit) could not upload the certificate of
    incorporation for a company it was trusted to edit the CR number of;
  * a role holding `documents:delete` and no `companies` grant at all could
    remove a company's filed papers without ever being able to open the
    company.

Neither is a distinction anybody asked for. The right to read a record is the
right to read the papers filed against it, and the right to change the record is
the right to add and remove them. So the routes now gate on the owner:

    company-owned  (a certificate, an AoA)           -> companies
    person-owned   (an id scan, a proof of address)  -> persons
    case-owned     (a CR receipt, a wet-signed NAR1) -> nar1

`documents:delete` HAS NO SUCCESSOR LEVEL, deliberately. Neither `companies` nor
`persons` has a delete permission, and seeding one here would invent a grant
nobody has asked for on modules that have done without it. Deleting a document
is a WRITE on the owning record — which is what it is: changing what the record
holds.

WHAT THIS MEANS FOR EXISTING ROLES. Nothing is granted; rows are only removed.
A role that held `documents:*` and nothing on the owner module LOSES access to
documents, which is correct — it could not open the record they belong to
either, and that combination was the second bullet above. A role holding both
(the normal case) is unaffected: its `companies`/`persons` grants already say
everything the new gates ask.

Roles and permissions are seeded outside Alembic, so on a fresh database there
is nothing to remove and this is a no-op.

DOWNGRADE CANNOT RECONSTRUCT WHAT IT DELETED. Which roles held which levels on a
module that no longer exists is not derivable from anything left behind, and
guessing would hand out access. The downgrade is deliberately a no-op — the
routes are what enforce this, and reverting the code reverts the behaviour. See
migration 015, which retired `nar1_data` the same way and for the same reason.
"""
from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE module = 'documents'")


def downgrade() -> None:
    # A data cleanup of removed grants cannot be reversed meaningfully, and
    # inventing grants on the way back would hand out access nobody granted.
    # Re-seed through the Roles screen if the module is ever revived.
    pass

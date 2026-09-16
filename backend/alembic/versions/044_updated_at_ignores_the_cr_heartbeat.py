"""Last Updated stops being reset by the CR status poll.

THE BUG, MEASURED ON DEV 2026-09-17. `nar1_cases` carries
`trg_set_updated_at BEFORE UPDATE ... EXECUTE FUNCTION set_updated_at()`, and
that function is one unconditional line:

    BEGIN NEW.updated_at = now(); RETURN NEW; END;

So EVERY update stamps `updated_at`, whatever the update was for. That made a
carefully written piece of application logic a no-op:
`services/nar1_cr_status.refresh` sets `updated_at` in its patch ONLY when CR's
answer actually moved, with a comment explaining that a heartbeat which touched
it "would reset every filed case in the book and make the column say nothing" —
and the trigger overrode that on every single write. Verified against live DEV:
eight cases whose status stayed `Lodged` across three consecutive polls had
`updated_at` bumped by each one.

It was survivable while the poll ran nightly. It is not now that the schedule is
every 15 minutes (Levi 2026-09-16): the dashboard's sortable **Last Updated**
column would be reset 96 times a day for precisely the cases an operator is
tracking — the filed ones — so the column would rank by "is this case still
being polled", which is the same answer for all of them.

THE FIX IS A `WHEN` CLAUSE ON THE TRIGGER, NOT A CHANGE TO THE FUNCTION.
`set_updated_at()` is shared by some thirty tables (migrations 003, 016, 020);
editing it would change all of them to fix one. The trigger on `nar1_cases`
simply stops firing when `cr_status_checked_at` is part of the update, which
hands the decision back to the application patch that already makes it
correctly:

    heartbeat, nothing moved   patch omits updated_at   -> column keeps its value
    CR's answer moved          patch sets updated_at    -> column takes that value
    any other edit             trigger fires            -> now(), as before

`cr_status_checked_at` HAS EXACTLY ONE WRITER — `nar1_cr_status._store`, which
is the module docstring's first claim and is what makes this safe. A future
writer that sets it alongside unrelated business columns would suppress a bump
it wanted; the test in tests/test_migration_044.py pins the behaviour so that
change cannot pass unnoticed.

Revision ID: 044
Revises: 043
"""
from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None

_TABLE = "public.nar1_cases"
_TRIGGER = "trg_set_updated_at"

#: Fire ONLY when the CR heartbeat column is not part of this update. Written as
#: "is not distinct from" rather than "=" so that NULL -> NULL (the no-op case)
#: still counts as unchanged and still stamps, exactly as it does today.
_WHEN = ("WHEN (NEW.cr_status_checked_at IS NOT DISTINCT FROM "
         "OLD.cr_status_checked_at)")


def _recreate(when: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_TABLE};")
    op.execute(
        f"CREATE TRIGGER {_TRIGGER} BEFORE UPDATE ON {_TABLE} "
        f"FOR EACH ROW {when} EXECUTE FUNCTION set_updated_at();"
    )


def upgrade() -> None:
    _recreate(_WHEN)


def downgrade() -> None:
    # Back to 003's unconditional form, byte for byte in behaviour: every update
    # stamps `updated_at`, heartbeat included.
    _recreate("")

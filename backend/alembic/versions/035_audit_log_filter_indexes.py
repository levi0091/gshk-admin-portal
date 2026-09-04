"""Make the audit trail's filters and search actually run.

Revision ID: 035
Revises: 034
Create Date: 2026-09-04

MEASURED ON DEV, against all 226,825 rows — not reasoned about. Every unit test
in this repo mocks PostgREST, so none of them can tell a filter that WORKS from
one the database refuses; these numbers come from running the real queries.

BEFORE (statement_timeout 20s, the 722 MB table as it stood):

    search box, a real BRN ("T0001138")     TIMEOUT   <- already broken, pre-034
    Reference contains "M002"               TIMEOUT
    What-changed contains a rare term       TIMEOUT
    Action contains "incorporation"         15.7s
    Module + Subject-kind, 0 matches        TIMEOUT

The search box was failing on the *narrower* query, which is the worst possible
shape for this: a common word came back and a specific one did not, so the more
precisely an operator knew what they were looking for, the more likely the
screen was to answer "Failed to fetch". `ILIKE '%x%'` cannot use a btree index,
so each of those was a sequential scan of 722 MB.

AFTER (this migration):

    search box, a real BRN                  0.1s
    Reference contains "M002"               0.2s
    What-changed contains a rare term       0.1s
    Action contains "incorporation"         0.2s   (8.7ms of execution)
    Module + Subject-kind, 0 matches        0.1s
    every other combination the screen can send:  under 1s

Cost: +75 MB on a 722 MB table, and ~3 minutes to build.

TWO KINDS OF INDEX, for two different failures.

1. TRIGRAM GIN, one per column any `contains` filter or the search box touches.
   `pg_trgm` turns `ILIKE '%x%'` into an index lookup. The column list is not
   generous — it is exactly the columns `routers/audit.py` will put an `ilike`
   on, and nothing else pays for an index it cannot use.

2. A COMPOSITE (module, subject_kind, created_at DESC). Two equality filters
   that match NOTHING is the pathological case for a paginated listing: with
   separate indexes Postgres walks the whole table in date order to prove the
   answer is empty, which is 25 seconds to render "no rows". Ordering the
   composite by created_at DESC also means the commonest query on this
   screen — one module, newest first — is a plain index walk with no sort.

`IF NOT EXISTS` throughout, so this is safe to re-run and safe to apply to a
database where the indexes were already created by hand.

NOT `CONCURRENTLY`. Alembic runs a migration inside a transaction and
CREATE INDEX CONCURRENTLY cannot. `audit_log` is insert-only and the writes are
low-volume (a form save, a filing step), so the write lock these take for ~3
minutes is acceptable — unlike on a table serving live user traffic. If that
ever stops being true, build them by hand with CONCURRENTLY first; the
`IF NOT EXISTS` above means this migration then does nothing.
"""
from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


#: Every column `routers/audit.py` puts an `ilike` on — the `contains` header
#: filters and the eight terms of the search box's `or_`. Keep the two in step:
#: a column that reaches an `ilike` without an entry here is a sequential scan
#: of the whole table, and the symptom is a bare "Failed to fetch" in the
#: browser that names neither the column nor the filter.
TRIGRAM_COLUMNS = [
    "company_name",       # the subject's name — the Subject filter and search
    "subject_ref",        # BRN / case number / identity number — search
    "action_label",       # the Action filter and search
    "user_display_name",  # the User filter and search
    "event_code",         # search
    "created_by",         # search (the Viewpoint actor code)
    "new_value",          # the What-changed filter and search
    "old_value",          # search
]

COMPOSITE = "idx_audit_log_module_kind_created"


def upgrade() -> None:
    # Each index is minutes of work on 226k rows; the default statement timeout
    # is far shorter. LOCAL, so it lasts exactly this migration's transaction.
    op.execute("SET LOCAL statement_timeout = '1800s'")

    # Supabase has pg_trgm available but not installed. Nothing else in this
    # schema uses it yet, so this is the migration that turns it on.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    for column in TRIGRAM_COLUMNS:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS trgm_audit_log_{column} "
            f"ON public.audit_log USING gin ({column} gin_trgm_ops)"
        )

    op.execute(
        f"CREATE INDEX IF NOT EXISTS {COMPOSITE} "
        f"ON public.audit_log (module, subject_kind, created_at DESC)"
    )

    # Without fresh statistics the planner keeps the plans it chose when these
    # did not exist, and the first operator to open the screen gets the old
    # timeout on a database that no longer needs it.
    op.execute("ANALYZE public.audit_log")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS public.{COMPOSITE}")
    for column in TRIGRAM_COLUMNS:
        op.execute(f"DROP INDEX IF EXISTS public.trgm_audit_log_{column}")
    # The extension is deliberately LEFT INSTALLED. It is shared schema-wide and
    # costs nothing unused, and dropping it would break any other index built on
    # it in the meantime.

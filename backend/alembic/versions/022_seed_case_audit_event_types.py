"""Seed CASE_STATUS_CHANGED / CASE_FIELD_UPDATED into audit_event_types.

CLAUDE.md's PBI-11 audit table mandates nine action_type values, including
these two. Task 6 (BE-4, `services/audit_events.py`) named them as constants
on the assumption they were already seeded by migration 012 — that assumption
was wrong. A per-code check against 012's `_NATIVE` list (and every other
migration that touches `audit_event_types`: 016, 020, 021) found neither code
anywhere in this repo's migration history. Both are nonetheless live on DEV,
confirmed by a direct REST query on 2026-08-16.

That means DEV drifted from the schema history: some row-count or state on
DEV came from outside `alembic upgrade head`, so the migration chain does not
actually reproduce the database this project runs against. A fresh
environment built from this history alone — CI's `migrations` job, and PROD
at cutover — would get every other PBI-11 code but silently lose the
label for these two, which are also the two most common case events (every
workflow transition and every field edit fires one of them). Not cosmetic:
`audit_service.action_label()` looks the code up in this table and leaves
`action_label` unset on a miss, so the audit trail UI would show no generic
action name for the most frequent rows in it.

Seeded with the exact (name, category, origin) already live on DEV, so a
fresh database and DEV converge instead of diverging further. `ON CONFLICT
DO NOTHING` makes re-applying this against DEV itself a no-op — the rows are
already there — but DEV's alembic version still needs to advance to 022, or
the version table and the migration chain drift apart in the other direction.
"""
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None

AUDIT_CODES = [
    ("CASE_STATUS_CHANGED", "Status Changed"),
    ("CASE_FIELD_UPDATED", "Company Details Changed"),
]


def upgrade() -> None:
    # category/origin explicit — the column default is origin='viewpoint',
    # which would mislabel these as imported Viewpoint events (precedent:
    # 016, 020, 021).
    values = ", ".join(f"('{c}', '{n}', 'entity', 'g_flowdesk')" for c, n in AUDIT_CODES)
    op.execute(
        f"INSERT INTO public.audit_event_types (code, name, category, origin) "
        f"VALUES {values} ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    codes = ", ".join(f"'{c}'" for c, _ in AUDIT_CODES)
    op.execute(f"DELETE FROM public.audit_event_types WHERE code IN ({codes})")

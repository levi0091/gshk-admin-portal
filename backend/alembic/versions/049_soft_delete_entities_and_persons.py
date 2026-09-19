"""A company or a natural person can be deleted, and stays in the database.

Levi 2026-09-20: "soft delete a body corporation, so the record is still in the
background but for all things considered the record will no longer be shown
anywhere in the system frontend... you cant open a case for it, you cant see it
in any lists or dropdown lists", and the same for natural persons, behind a new
permission so a role has read, edit AND delete. PRD:
`PRD/Pending/prd-soft-delete-companies-and-persons-2026-09-20.md`.

WHY NOT A REAL DELETE. `entity_id` cascades into nineteen tables (003) -- a
company's cases, filings, documents and share register would go with it -- and
`person_id` has NO ACTION on the link tables, so a person with any history
cannot be deleted at all. Neither is what anybody asking for "delete" means.

WHY NEW COLUMNS, NOT `status` OR `is_client`. The Viewpoint ETL upserts with
`ON CONFLICT (vp_source_key) DO UPDATE` and SETs `status`, `is_client` and
`is_corporate_party` on every re-import (etl/transform/checkpoint_a.py,
checkpoint_d.py). A marker in any of them would be undone, silently, by the
next reload. Nothing in the ETL emits `deleted_*`, so these survive it.

THE SAME SHAPE AS CASE CLOSURE (039): `deleted_at` is the single predicate,
`deleted_by` names who, `deleted_reason` says why in the operator's words. A
CHECK keeps the time and the reason together, so a row can be neither "deleted
for no stated reason" nor "not deleted, with a reason".

HIDING IS DONE IN THE VIEWS, so nothing built on them has to remember:

  * `company_registry` -- the Company Registry, the dashboard's company list
    and both company pickers (New Case, Link Party) all read it -- gains
    `WHERE e.deleted_at IS NULL`. `nar1_case_registry` INNER JOINs it, so a
    deleted company's cases leave the Post-incorporation dashboard with no
    change to that view at all.
  * `person_registry` -- the Persons Registry and the person picker -- gains
    `WHERE p.deleted_at IS NULL`, and its four role flags stop counting links
    to a DELETED company, so a person whose only directorship was at a deleted
    company is no longer filed under Directors.

CREATE OR REPLACE, NOT DROP AND RECREATE. Both views keep EXACTLY their current
columns, in order, so Postgres accepts a replace -- which keeps their grants
and leaves `nar1_case_registry` standing. `company_registry`'s entity columns
are read off the LIVE VIEW rather than off `entities`: that list was frozen by
`e.*` in 033 and is now narrower than the table (045's `email` is not in it).
Rebuilding it from the table would widen it, and 045's downgrade could then no
longer drop `entities.email` from under it. Both views are restated
`security_invoker = true`, because a replace that omits WITH resets the
option -- which for `person_registry` would reopen what 048 closed.

THE DELETE PERMISSION. `role_permissions`' CHECK has accepted 'delete' since
008; nothing has granted it since `documents` was retired (040). This seeds
`companies:delete` and `persons:delete` for super_admin -- who bypasses the
check anyway; the rows exist so the screen's hasPermission() agrees with the
role -- guarded on the role existing, as 021 did.

FOUR AUDIT CODES, seeded with origin and category explicit: there is no FK from
audit_log to audit_event_types, so an unseeded code writes fine and then
renders unlabelled (022).

Revision ID: 049
Revises: 048
"""
import sqlalchemy as sa
from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None

TABLES = ("entities", "persons")

#: The three columns 019/033 append after the entity columns, in order.
_COMPUTED = ("last_anniversary", "next_anniversary", "days_to_anniversary")

#: Verbatim from 033 -- the anniversary arithmetic is not this migration's.
_NEAREST = """
          CASE
            -- No incorporation date -> no anniversary to measure against. The
            -- LEFT JOIN leaves last_on NULL for exactly those rows.
            WHEN a.last_on IS NULL THEN NULL
            -- The anniversary behind us is the closer one: count UP, negative.
            WHEN (public.hk_today() - a.last_on) <= (a.next_on - public.hk_today())
              THEN -(public.hk_today() - a.last_on)
            -- The one ahead is closer: count DOWN, positive.
            ELSE (a.next_on - public.hk_today())
          END::int AS days_to_anniversary
"""

AUDIT_CODES = [
    ("GF_COMPANY_DELETED", "Company Deleted", "entity"),
    ("GF_COMPANY_RESTORED", "Company Restored", "entity"),
    ("GF_PERSON_DELETED", "Person Deleted", "party"),
    ("GF_PERSON_RESTORED", "Person Restored", "party"),
]

PERMISSIONS = [("companies", "delete"), ("persons", "delete")]


def _company_view(entity_columns, *, hide_deleted: bool) -> str:
    """033's view, over an explicit column list, with or without the filter.

    Parameterised because upgrade and downgrade differ in exactly the WHERE
    clause, and two hand-copied definitions would be free to drift.
    """
    select = ",\n          ".join(
        "e.*" if c == "*" else f"e.{c}" for c in entity_columns)
    where = "\n        WHERE e.deleted_at IS NULL" if hide_deleted else ""
    return f"""
        CREATE OR REPLACE VIEW public.company_registry
        WITH (security_invoker = true) AS
        SELECT
          {select},
          a.last_on AS last_anniversary,
          a.next_on AS next_anniversary,
          {_NEAREST.strip()}
        FROM public.entities e
        LEFT JOIN LATERAL (
          SELECT
            CASE WHEN y.this_yr <= public.hk_today() THEN y.this_yr
                 ELSE public.anniversary_in(e.incorporation_date,
                        EXTRACT(YEAR FROM public.hk_today())::int - 1)
            END AS last_on,
            CASE WHEN y.this_yr >= public.hk_today() THEN y.this_yr
                 ELSE public.anniversary_in(e.incorporation_date,
                        EXTRACT(YEAR FROM public.hk_today())::int + 1)
            END AS next_on
          FROM (
            SELECT public.anniversary_in(e.incorporation_date,
                     EXTRACT(YEAR FROM public.hk_today())::int) AS this_yr
          ) y
        ) a ON e.incorporation_date IS NOT NULL{where};
    """


def _person_view(*, hide_deleted: bool) -> str:
    """009's view, with or without the filter.

    The role flags gain a join to the LINKED company when hiding, so that a
    deleted company stops making anybody a director. Columns are 009's, in
    009's order -- a replace must not add, drop or move one.
    """
    def live(alias: str) -> str:
        if not hide_deleted:
            return ""
        return (f"\n              AND EXISTS (SELECT 1 FROM public.entities le "
                f"WHERE le.id = {alias}.entity_id AND le.deleted_at IS NULL)")

    where = "\n        WHERE p.deleted_at IS NULL" if hide_deleted else ""
    return f"""
        CREATE OR REPLACE VIEW public.person_registry
        WITH (security_invoker = true) AS
        SELECT
          p.id,
          p.full_name,
          p.full_name_zh,
          p.email,
          p.phone,
          p.nationality,
          p.date_of_birth,
          p.vp_source_key,
          p.created_at,
          p.updated_at,
          EXISTS (
            SELECT 1 FROM public.entity_officers o
            WHERE o.person_id = p.id AND o.role = 'director'{live("o")}
          ) AS is_director,
          EXISTS (
            SELECT 1 FROM public.shareholdings s
            WHERE s.person_id = p.id{live("s")}
          ) AS is_shareholder,
          (
            EXISTS (
              SELECT 1 FROM public.entity_officers o
              WHERE o.person_id = p.id AND o.role = 'company_secretary'{live("o")}
            )
            OR EXISTS (
              SELECT 1 FROM public.company_secretaries cs
              WHERE cs.person_id = p.id{live("cs")}
            )
          ) AS is_secretary,
          EXISTS (
            SELECT 1 FROM public.beneficial_owners b
            WHERE b.person_id = p.id{live("b")}
          ) AS is_beneficial_owner,
          idoc.id_type   AS primary_id_type,
          idoc.id_number AS primary_id_number
        FROM public.persons p
        LEFT JOIN LATERAL (
          SELECT d.id_type, d.id_number
          FROM public.person_identity_documents d
          WHERE d.person_id = p.id
          ORDER BY d.is_primary DESC, d.created_at ASC
          LIMIT 1
        ) AS idoc ON TRUE{where};
    """


def _registry_entity_columns() -> list[str]:
    """company_registry's entity columns, as the LIVE view has them.

    See the module docstring for why not `entities`. Refuses rather than guesses
    if the view no longer ends in the three computed columns: a replace built
    from a list it misread would fail in Postgres at best.
    """
    names = op.get_bind().execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'company_registry' "
        "ORDER BY ordinal_position"
    )).scalars().all()
    if tuple(names[-len(_COMPUTED):]) != _COMPUTED:
        raise RuntimeError(
            f"company_registry does not end in {_COMPUTED}: {names[-4:]}")
    return list(names[:-len(_COMPUTED)])


def _columns_sql(table: str) -> str:
    return f"""
        ALTER TABLE public.{table}
          ADD COLUMN IF NOT EXISTS deleted_at     timestamptz,
          ADD COLUMN IF NOT EXISTS deleted_by     uuid REFERENCES public.users(id),
          ADD COLUMN IF NOT EXISTS deleted_reason text;
        ALTER TABLE public.{table}
          DROP CONSTRAINT IF EXISTS {table}_deleted_reason_check;
        ALTER TABLE public.{table}
          ADD CONSTRAINT {table}_deleted_reason_check
          CHECK ((deleted_at IS NULL) = (deleted_reason IS NULL));
        COMMENT ON COLUMN public.{table}.deleted_at IS
          'Soft delete (migration 049). Set: the record is hidden from every '
          'registry, picker and profile, and cannot be linked or filed for; the '
          'row and its history stay. NULL: live. Never written by the ETL.';
        COMMENT ON COLUMN public.{table}.deleted_by IS
          'The portal user who deleted it.';
        COMMENT ON COLUMN public.{table}.deleted_reason IS
          'Why, in the operator''s own words. Required with deleted_at.';
    """


def upgrade() -> None:
    for table in TABLES:
        op.execute(_columns_sql(table))

    op.execute(_company_view(_registry_entity_columns(), hide_deleted=True))
    op.execute(_person_view(hide_deleted=True))

    grants = ", ".join(f"('{m}', '{p}')" for m, p in PERMISSIONS)
    op.execute(f"""
        INSERT INTO public.role_permissions (role_id, module, permission)
        SELECT r.id, m.module, m.permission
        FROM public.roles r
        CROSS JOIN (VALUES {grants}) AS m(module, permission)
        WHERE r.name = 'super_admin'
        ON CONFLICT DO NOTHING
    """)

    values = ", ".join(
        f"('{code}', '{name}', '{category}', 'g_flowdesk')"
        for code, name, category in AUDIT_CODES
    )
    op.execute(
        f"INSERT INTO public.audit_event_types (code, name, category, origin) "
        f"VALUES {values} ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    # CI's migrations job runs `upgrade head` then `downgrade base`. The views
    # go FIRST: their WHERE clauses read the columns below, and Postgres will
    # not drop a column another object depends on.
    codes = ", ".join(f"'{c}'" for c, _, _ in AUDIT_CODES)
    op.execute(f"DELETE FROM public.audit_event_types WHERE code IN ({codes})")
    # EVERY role's delete grant on these two modules, not only the seeded
    # super_admin rows: with the feature gone, a grant a colleague made through
    # the Role screen would be a checkbox that governs nothing.
    op.execute(
        "DELETE FROM public.role_permissions "
        "WHERE module IN ('companies', 'persons') AND permission = 'delete'"
    )
    op.execute(_person_view(hide_deleted=False))
    op.execute(_company_view(_registry_entity_columns(), hide_deleted=False))
    for table in TABLES:
        op.execute(f"""
            ALTER TABLE public.{table}
              DROP CONSTRAINT IF EXISTS {table}_deleted_reason_check;
            ALTER TABLE public.{table}
              DROP COLUMN IF EXISTS deleted_reason,
              DROP COLUMN IF EXISTS deleted_by,
              DROP COLUMN IF EXISTS deleted_at;
        """)

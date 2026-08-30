"""Bootstrap the super_admin role, its permissions, and the founding admins.

THE GAP THIS CLOSES. Every permission seed in this repo -- migrations 008, 016
and 021 -- is guarded on `WHERE r.name = 'super_admin'`, and NO migration has
ever created that role. On DEV it was inserted by hand and the step was never
captured, so a fresh project came up with a complete 39-table schema, correct
RLS, all the reference data... and nobody able to sign in: `roles`,
`role_permissions` and `users` were all empty, and every guarded seed had
inserted zero rows.

That is exactly what happened to the new master project on 2026-08-30. This
migration is the missing step, written down so the next environment is not
another undocumented manual job.

WHY THE FULL PERMISSION SET IS RE-SEEDED HERE
On a fresh database 008/016/021 ran BEFORE this role existed, so their guarded
inserts did nothing and will never run again. Re-seeding the complete set here
is what makes a from-scratch database end up matching one that grew
incrementally. On a database where they did fire, every insert is a no-op.

WHY THE ADMINS ARE JOINED BY EMAIL
`public.users.id` is a foreign key to `auth.users(id)`, and those UUIDs differ
per project -- hardcoding DEV's would be wrong everywhere else. Joining on
email keeps the migration portable and makes it a no-op for any founder whose
Supabase Auth account does not exist yet: schema migrations must not fail
because an account has not been created.

Revision ID: 027
Revises: 026
"""
from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


#: The founding Super Admins, with the display names DEV already uses -- Levi
#: asked for "same setup as dev" (2026-08-30), so these are copied verbatim
#: rather than tidied.
FOUNDERS = [
    ("levi@zenexflow.com", "Levi Z."),
    ("vanis@getstarted.hk", "Vanis"),
    ("brian@getstarted.hk", "Brian Yiu"),
    ("roy@zenexflow.com", "roy"),
]

#: super_admin's complete permission set, read off DEV on 2026-08-30. Note that
#: super_admin ALSO bypasses require_permission() in middleware/auth.py -- these
#: rows exist so the sidebar's hasPermission() gating and the audit trail agree
#: with the role, not because the checks depend on them.
PERMISSIONS = [
    ("audit_trail", "read"),
    ("companies", "read"), ("companies", "write"),
    ("documents", "read"), ("documents", "write"), ("documents", "delete"),
    ("nar1", "read"), ("nar1", "write"),
    ("persons", "read"), ("persons", "write"),
    ("tpsi", "read"), ("tpsi", "write"), ("tpsi", "submit"),
]


def _values(rows):
    return ", ".join(
        "(" + ", ".join("'" + c.replace("'", "''") + "'" for c in row) + ")"
        for row in rows
    )


def upgrade() -> None:
    op.execute(
        "INSERT INTO public.roles (name) VALUES ('super_admin') "
        "ON CONFLICT (name) DO NOTHING"
    )

    op.execute(
        f"""
        INSERT INTO public.role_permissions (role_id, module, permission)
        SELECT r.id, m.module, m.permission
        FROM public.roles r
        CROSS JOIN (VALUES {_values(PERMISSIONS)}) AS m(module, permission)
        WHERE r.name = 'super_admin'
        ON CONFLICT (role_id, module, permission) DO NOTHING
        """
    )

    # ON CONFLICT (id) DO NOTHING, so this never overwrites a display name, a
    # role, or an is_active=false someone set deliberately. Deactivating an
    # account must not be undone by re-running a migration.
    #
    # Wrapped in a column-existence guard, and run as DYNAMIC sql, because CI
    # applies these migrations to vanilla Postgres with a hand-built stand-in:
    #
    #     CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY);
    #
    # That is enough for migration 001's foreign key but has no `email`, and a
    # static reference to it is a hard parse error rather than a no-op. EXECUTE
    # defers parsing to the branch actually being taken, so on CI this compiles
    # and skips, and on any real Supabase project it runs.
    op.execute(
        f"""
        DO $do$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'auth'
                  AND table_name = 'users'
                  AND column_name = 'email'
            ) THEN
                EXECUTE $sql$
                    INSERT INTO public.users
                        (id, display_name, email, role_id, is_active)
                    SELECT au.id, f.display_name, au.email, r.id, true
                    FROM auth.users au
                    JOIN (VALUES {_values(FOUNDERS)})
                         AS f(email, display_name)
                      ON lower(au.email) = f.email
                    CROSS JOIN public.roles r
                    WHERE r.name = 'super_admin'
                    ON CONFLICT (id) DO NOTHING
                $sql$;
            END IF;
        END
        $do$
        """
    )


def downgrade() -> None:
    """Destructive: this removes the only accounts that can administer the app.

    CLAUDE.md requires Levi's explicit sign-off before any downgrade on PROD.
    """
    emails = ", ".join("'" + e.replace("'", "''") + "'" for e, _ in FOUNDERS)
    op.execute(f"DELETE FROM public.users WHERE lower(email) IN ({emails})")

    op.execute(
        """
        DELETE FROM public.role_permissions rp
        USING public.roles r
        WHERE rp.role_id = r.id AND r.name = 'super_admin'
        """
    )

    # Guarded: public.users.role_id is NOT NULL and references roles(id), so
    # dropping the role while any OTHER account still holds it would fail on
    # the foreign key rather than downgrade cleanly.
    op.execute(
        """
        DELETE FROM public.roles r
        WHERE r.name = 'super_admin'
          AND NOT EXISTS (SELECT 1 FROM public.users u WHERE u.role_id = r.id)
        """
    )

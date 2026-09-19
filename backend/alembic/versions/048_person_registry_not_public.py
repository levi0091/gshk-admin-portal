"""person_registry stops being readable with the public anon key.

FOUND 2026-09-20, on DEV and PROD alike, while restating this view for the soft
delete (049): `GET /rest/v1/person_registry` with the ANON key returned rows.
That key is not a secret -- it ships in the frontend bundle -- so every natural
person the portal holds was one request away from anybody: name, Chinese name,
email, phone, date of birth, nationality and primary identity-document number.

WHY THIS VIEW AND NO OTHER. Supabase's default privileges GRANT ALL on every new
relation in `public` to `anon` and `authenticated`. On a TABLE that is harmless
while RLS is on and no policy admits them, which is how `persons` itself answers
the same request with nothing. A VIEW is different: unless it is
`security_invoker`, it runs with its OWNER's rights, and the owner bypasses RLS.
009 created this one before any view here was invoker, and nothing revisited it.
`company_registry` (019) and `nar1_case_registry` (024) are both
`security_invoker = true`, so RLS on their base tables still applies. A catalog
sweep of all 44/45 relations in `public` on PROD/DEV found this the ONLY one
readable by anon or authenticated with RLS out of the way.

WHAT CHANGES. Nobody outside the backend reads it: the frontend never queries
Supabase tables (CLAUDE.md -- only the auth token exchange), and the backend
reads with the service key, which bypasses RLS whatever the view's mode. So:

  * `security_invoker = true`, like its two siblings, so RLS on `persons` and
    the link tables governs any caller that is not the service role;
  * `anon` and `authenticated` lose every privilege on it -- the same posture
    `nar1_case_registry` has held since 024;
  * `service_role` keeps SELECT, restated rather than assumed.

Its own migration, not a line in 049, so it can reach PROD on its own and first.

THE DOWNGRADE DOES NOT PUT THE GRANTS BACK. CI runs `downgrade base` on every
push, so it has to run; but a reversal that republishes every client's identity
number is not one anybody wants, and restoring it faithfully would be the one
line in this file that does harm. It resets `security_invoker` and leaves the
revocations standing.

Revision ID: 048
Revises: 047
"""
from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None

VIEW = "public.person_registry"

#: Guarded per role: CI's vanilla Postgres creates all three stand-ins, but a
#: bare local database may have none of them.
_LOCK_DOWN = f"""
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON {VIEW} FROM anon;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON {VIEW} FROM authenticated;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT ON {VIEW} TO service_role;
      END IF;
    END $$;
"""


def upgrade() -> None:
    op.execute(f"ALTER VIEW {VIEW} SET (security_invoker = true)")
    op.execute(_LOCK_DOWN)


def downgrade() -> None:
    # See the module docstring: the revocations stay.
    op.execute(f"ALTER VIEW {VIEW} RESET (security_invoker)")

"""BE-4/BE-6: the NAR1 case workflow — module, case numbers, workflow columns.

One revision, so a rollback returns the schema to a single known state (the
discipline 016/017 already set).

WHAT IS NOT HERE, deliberately: a workflow_status column. The displayed badge is
DERIVED from tpsi_filings.stage x the client columns (D-6, single-writer split)
and computed in services/nar1_case_status.py. Storing it would create a second
writer for facts TPSI already owns, and the two disagree on every failure path.
`nar1_cases.status` survives untouched as the coarse Viewpoint-era field; nothing
in the v11 UI reads it.

nar1_type gains 'annual_return'. The enum shipped with
appointment_of_director / resignation_of_director / appointment_and_resignation
-- director-change semantics inherited from Viewpoint, none of which describe an
annual return, which is what Form NAR1 actually is. The column is NOT NULL, so a
case could not otherwise be created honestly. ADD VALUE runs inside Alembic's
transaction safely on PG 12+ (Supabase is 15+) as long as the new value is not
USED in the same transaction -- and it is not; the first row using it is written
by the application.

Case numbers are NAR-<year>-<0000> (wireframe_v11 s2). Allocated by
UPDATE ... RETURNING against a counter row, which is atomic: two concurrent
POST /cases calls cannot be handed the same number. A plain sequence was
rejected because it cannot restart per year, and SELECT max+1 races.
"""
from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None

AUDIT_CODES = [
    ("NAR1_MANUAL_SIGN_UPLOADED", "NAR1 Wet-Signed Form Uploaded"),
    ("NAR1_MANUAL_SUBMISSION_RECORDED", "NAR1 Off-Portal Submission Recorded"),
    ("NAR1_MANUAL_RECEIPT_ENTERED", "NAR1 Off-Portal Receipt Entered"),
]


def upgrade() -> None:
    # ---- 1. The case type an annual return actually is -----------------------
    op.execute("ALTER TYPE nar1_type ADD VALUE IF NOT EXISTS 'annual_return'")

    # ---- 2. Workflow + manual-flow columns -----------------------------------
    op.execute("""
        ALTER TABLE public.nar1_cases
          ADD COLUMN IF NOT EXISTS case_no                   text,
          ADD COLUMN IF NOT EXISTS aml_cleared               boolean NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS aml_cleared_at            timestamptz,
          ADD COLUMN IF NOT EXISTS accounts_ready            boolean NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS accounts_ready_at         timestamptz,
          ADD COLUMN IF NOT EXISTS signing_method            text
                                     CHECK (signing_method IN ('esign','manual')),
          ADD COLUMN IF NOT EXISTS manual_signed_document_id uuid REFERENCES documents(id),
          ADD COLUMN IF NOT EXISTS manual_receipt            jsonb,
          ADD COLUMN IF NOT EXISTS manual_submitted_at       timestamptz,
          ADD COLUMN IF NOT EXISTS created_by                uuid REFERENCES users(id);
    """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_nar1_cases_case_no "
        "ON public.nar1_cases (case_no) WHERE case_no IS NOT NULL"
    )

    # ---- 3. Atomic per-year case numbering -----------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS case_no_counters (
          prefix    text PRIMARY KEY,
          next_val  integer NOT NULL DEFAULT 1
        );
    """)
    # RLS on, NO policy -- deliberately, and unlike the authenticated-open
    # policy 016/020 pair with RLS on their tables. Nothing but next_case_no()
    # below should ever touch this row set; the backend reaches it as
    # service_role, which bypasses RLS entirely, so a real policy would only
    # ever be exercised by something that shouldn't be querying this table at
    # all. RLS-on-with-no-policy is Postgres's default-deny for every other
    # role, which is exactly the posture wanted -- Supabase's default grants
    # hand anon/authenticated SELECT/INSERT/UPDATE/DELETE on every new public
    # table, and without this line PostgREST would expose a direct
    # `UPDATE case_no_counters SET next_val = 1`, colliding every subsequent
    # allocation against uq_nar1_cases_case_no.
    #
    # Stated explicitly rather than left to Supabase's `ensure_rls` event
    # trigger (which auto-enables RLS on new DEV/PROD tables): that trigger
    # does not exist in the vanilla Postgres the CI `migrations` job runs
    # against, and a security property that holds only by accident of the
    # platform is not expressed in the schema history CLAUDE.md makes the
    # source of truth.
    op.execute("ALTER TABLE public.case_no_counters ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE OR REPLACE FUNCTION public.next_case_no(p_prefix text)
        RETURNS text
        LANGUAGE plpgsql
        AS $$
        DECLARE
          v integer;
        BEGIN
          -- INSERT ... ON CONFLICT DO UPDATE ... RETURNING is one statement, so
          -- it both creates the counter on first use and increments it under a
          -- row lock. Two concurrent callers serialise; neither sees the other's
          -- number. The stored next_val always equals the value most recently
          -- issued: first call inserts 1 and returns it directly; every later
          -- call increments the existing row and returns that same new value,
          -- so RETURNING next_val (no xmax branch needed) is already correct on
          -- both the insert and the update path.
          INSERT INTO case_no_counters (prefix, next_val)
          VALUES (p_prefix, 1)
          ON CONFLICT (prefix)
            DO UPDATE SET next_val = case_no_counters.next_val + 1
          RETURNING next_val INTO v;

          RETURN p_prefix || '-' || lpad(v::text, 4, '0');
        END;
        $$;
    """)

    # ---- 4. The nar1 permission module (OQ-B) --------------------------------
    #   super_admin only, role-existence-guarded, idempotent -- as 008 and 016.
    op.execute("""
        INSERT INTO public.role_permissions (role_id, module, permission)
        SELECT r.id, m.module, m.permission
        FROM public.roles r
        CROSS JOIN (VALUES ('nar1','read'), ('nar1','write')) AS m(module, permission)
        WHERE r.name = 'super_admin'
        ON CONFLICT (role_id, module, permission) DO NOTHING
    """)

    # ---- 5. Audit registry ---------------------------------------------------
    values = ", ".join(f"('{c}', '{n}', 'nar1', 'g_flowdesk')" for c, n in AUDIT_CODES)
    op.execute(
        f"INSERT INTO public.audit_event_types (code, name, category, origin) "
        f"VALUES {values} ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    codes = ", ".join(f"'{c}'" for c, _ in AUDIT_CODES)
    op.execute(f"DELETE FROM public.audit_event_types WHERE code IN ({codes})")
    op.execute(
        "DELETE FROM public.role_permissions rp USING public.roles r "
        "WHERE rp.role_id = r.id AND r.name = 'super_admin' AND rp.module = 'nar1'"
    )
    op.execute("DROP FUNCTION IF EXISTS public.next_case_no(text)")
    op.execute("DROP TABLE IF EXISTS case_no_counters")
    op.execute("DROP INDEX IF EXISTS public.uq_nar1_cases_case_no")
    op.execute("""
        ALTER TABLE public.nar1_cases
          DROP COLUMN IF EXISTS created_by,
          DROP COLUMN IF EXISTS manual_submitted_at,
          DROP COLUMN IF EXISTS manual_receipt,
          DROP COLUMN IF EXISTS manual_signed_document_id,
          DROP COLUMN IF EXISTS signing_method,
          DROP COLUMN IF EXISTS accounts_ready_at,
          DROP COLUMN IF EXISTS accounts_ready,
          DROP COLUMN IF EXISTS aml_cleared_at,
          DROP COLUMN IF EXISTS aml_cleared,
          DROP COLUMN IF EXISTS case_no;
    """)
    # Postgres cannot remove a value from an enum. 'annual_return' is left in
    # place: it is inert once no row references it, and attempting to drop it
    # would fail this downgrade halfway through.

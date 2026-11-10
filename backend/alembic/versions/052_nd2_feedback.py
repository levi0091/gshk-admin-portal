"""ND2A / ND2B: Jacqueline's feedback of 1 October 2026.

Design: `docs/superpowers/specs/2026-10-02-nd2-jacqueline-feedback-design.md`.

  officer_change_entries.date_deferred
      The effective date was blank when the client was sent the form (A1:
      "most clients let us fill in the most recent date"). Only a deferred date
      may be filled in after sending; a date the client saw is changed by a
      restart, as before.

  officer_change_documents.entry_id  -> nullable
      A CASE-level document — the written resolution, or anything else GSHK
      sends with the client email (A3) — belongs to the form, not to one
      officer. Filed to the COMPANY's profile when the form is filed.
  officer_change_documents.send_with_email
      Attached to the verification email.

  (No `nar1_cases.attach_resolution`: the toggle was removed on Levi
  2026-10-05 — the written resolution, now built to GSHK's own sample, always
  goes with an ND2A — before any database ran this migration.)

  (No consent table. A consent-to-act signed in G-FlowDesk was here until
  Levi 2026-10-05 — CR's consent signature over the director's bean IS the
  consent, TPSI API v1.0.14 section 7.1.2 — and was removed before any
  database ran this migration.)

  person_eservice_credentials.registered_id_type / registered_id_number
      The identity document the e-Registry account was opened with (note 1:
      e-Reg and CR's register do not sync, and an account opened with an old
      passport fails the consent signature later).

  nar1_case_registry (restated)
      One branch added to 050's view, after its manual branch: an e-Sign
      officer change marked checked with a date deferred to Signing reads
      'signing' until a live filing exists — as `nar1_case_status` says, so
      the dashboard and the case header agree (review finding 6). Built from
      050's own `_case_view_sql`, so nothing else can drift.

REVERSIBLE; the downgrade refuses while a case-level document exists, rather
than drop it, and restores 050's view.

Revision ID: 052
Revises: 050
"""
import importlib.util
from pathlib import Path

from alembic import op

revision = "052"
down_revision = "050"
branch_labels = None
depends_on = None

#: (code, name). origin/category set explicitly — see 050's AUDIT_CODES note.
AUDIT_CODES = [
    ("OFFICER_CONFIRMATION_WAIVED", "Filed Without Client Confirmation"),
]

UPGRADE_SQL = [
    """
    ALTER TABLE public.officer_change_entries
      ADD COLUMN IF NOT EXISTS date_deferred boolean NOT NULL DEFAULT false;
    """,
    """
    ALTER TABLE public.officer_change_documents
      ALTER COLUMN entry_id DROP NOT NULL,
      ADD COLUMN IF NOT EXISTS send_with_email boolean NOT NULL DEFAULT false;
    """,
    """
    ALTER TABLE public.person_eservice_credentials
      ADD COLUMN IF NOT EXISTS registered_id_type text,
      ADD COLUMN IF NOT EXISTS registered_id_number text;
    ALTER TABLE public.person_eservice_credentials
      DROP CONSTRAINT IF EXISTS person_eservice_credentials_registered_id_type_valid;
    ALTER TABLE public.person_eservice_credentials
      ADD CONSTRAINT person_eservice_credentials_registered_id_type_valid
      CHECK (registered_id_type IS NULL OR registered_id_type IN ('hkid', 'passport'));
    """,
]

DOWNGRADE_GUARD = """
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM public.officer_change_documents WHERE entry_id IS NULL) THEN
        RAISE EXCEPTION
          'migration 052 cannot be downgraded while case-level officer-change '
          'documents exist (entry_id IS NULL). Remove them first, knowingly.';
      END IF;
    END $$;
"""


def _m050():
    """Migration 050's module, for its tested view builder. Loaded by path:
    the versions directory is not a package."""
    path = Path(__file__).with_name("050_officer_changes_nd2a_nd2b.py")
    spec = importlib.util.spec_from_file_location("m050_case_view", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: nar1_case_status._code's e-Sign branch (review finding 6): a case marked
#: checked with a date deferred to Signing is AT Signing until a live filing
#: exists. Placed right after 050's manual branch, as in the Python.
ESIGN_CHECKED_BRANCH = """
              WHEN base.form_code <> 'Nar1'
               AND base.signing_method = 'esign'
               AND base.data_checked_at IS NOT NULL
               AND (base.filing_stage IS NULL
                    OR base.filing_stage NOT IN ('validated', 'signed',
                                                 'signing_failed',
                                                 'submission_failed')) THEN 'signing'"""

#: The last line of 050's manual branch — where the e-Sign branch goes.
_AFTER = """                  ELSE 'submission'
                END"""


def previous_view_sql() -> str:
    """050's case registry — the downgrade target."""
    return _m050()._case_view_sql(officer_changes=True)


def view_sql() -> str:
    """050's case registry with the e-Sign branch, and nothing else changed."""
    sql = previous_view_sql()
    if sql.count(_AFTER) != 1:
        raise RuntimeError("migration 050's manual branch is not where 052 expects it")
    return sql.replace(_AFTER, _AFTER + ESIGN_CHECKED_BRANCH, 1)


def _rebuild_view(sql: str) -> None:
    m050 = _m050()
    op.execute(f"DROP VIEW IF EXISTS {m050.CASE_VIEW};")
    op.execute(sql)
    op.execute(m050._CASE_GRANTS)


def audit_seed_sql() -> str:
    values = ", ".join(f"('{code}', '{name}', 'officer_changes', 'g_flowdesk')"
                       for code, name in AUDIT_CODES)
    return ("INSERT INTO public.audit_event_types (code, name, category, origin) "
            f"VALUES {values} ON CONFLICT (code) DO NOTHING")


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)
    op.execute(audit_seed_sql())
    _rebuild_view(view_sql())


def downgrade() -> None:
    op.execute(DOWNGRADE_GUARD)
    _rebuild_view(previous_view_sql())
    codes = ", ".join(f"'{c}'" for c, _ in AUDIT_CODES)
    op.execute(f"DELETE FROM public.audit_event_types WHERE code IN ({codes})")
    op.execute("""
        ALTER TABLE public.person_eservice_credentials
          DROP CONSTRAINT IF EXISTS person_eservice_credentials_registered_id_type_valid,
          DROP COLUMN IF EXISTS registered_id_number,
          DROP COLUMN IF EXISTS registered_id_type;
    """)
    op.execute("""
        ALTER TABLE public.officer_change_documents
          DROP COLUMN IF EXISTS send_with_email,
          ALTER COLUMN entry_id SET NOT NULL;
    """)
    op.execute("ALTER TABLE public.officer_change_entries "
               "DROP COLUMN IF EXISTS date_deferred")

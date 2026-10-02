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
  officer_change_documents.send_with_email / source / uploaded_by_name
      Attached to the verification email; where the file came from (an
      upload, a consent signed in G-FlowDesk, a generated document); and the
      signer's name when no portal user uploaded it.

  nar1_cases.attach_resolution
      Attach the generated written resolution to the email (off by default:
      its wording is a standard one, GSHK's sample was not available).

  officer_change_consents
      A new director's consent to act, signed in G-FlowDesk (A2). One row per
      link: the token's HASH only, its revision and expiry, and — once signed —
      the typed name, IP address and browser. Separate from the approval
      tokens because the first director to Confirm supersedes every other
      Confirm link, and the incoming director must still be able to sign.
      RLS on, no policy, revoked from the browser roles, like 050's tables.

  person_eservice_credentials.registered_id_type / registered_id_number
      The identity document the e-Registry account was opened with (note 1:
      e-Reg and CR's register do not sync, and an account opened with an old
      passport fails the consent signature later).

REVERSIBLE; the downgrade refuses while a consent or a case-level document
exists, rather than drop either.

Revision ID: 052
Revises: 050
"""
from alembic import op

revision = "052"
down_revision = "050"
branch_labels = None
depends_on = None

#: (code, name). origin/category set explicitly — see 050's AUDIT_CODES note.
AUDIT_CODES = [
    ("OFFICER_ECONSENT_LINK_SENT", "Consent-to-Act Link Sent"),
    ("OFFICER_ECONSENT_SIGNED", "Consent to Act Signed in G-FlowDesk"),
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
      ADD COLUMN IF NOT EXISTS send_with_email boolean NOT NULL DEFAULT false,
      ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'upload',
      ADD COLUMN IF NOT EXISTS uploaded_by_name text;
    ALTER TABLE public.officer_change_documents
      DROP CONSTRAINT IF EXISTS officer_change_documents_source_valid;
    ALTER TABLE public.officer_change_documents
      ADD CONSTRAINT officer_change_documents_source_valid
      CHECK (source IN ('upload', 'econsent', 'generated'));
    """,
    """
    ALTER TABLE public.nar1_cases
      ADD COLUMN IF NOT EXISTS attach_resolution boolean NOT NULL DEFAULT false;
    """,
    """
    CREATE TABLE IF NOT EXISTS public.officer_change_consents (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      case_id       uuid NOT NULL REFERENCES public.nar1_cases(id) ON DELETE CASCADE,
      entry_id      uuid NOT NULL
                      REFERENCES public.officer_change_entries(id) ON DELETE CASCADE,
      person_id     uuid REFERENCES public.persons(id) ON DELETE SET NULL,
      -- SHA-256 of the token. The token itself is only ever in the email.
      token_hash text NOT NULL,
      revision      integer,
      issued_at     timestamptz NOT NULL DEFAULT now(),
      expires_at    timestamptz,
      superseded_at timestamptz,
      signed_at     timestamptz,
      signed_name   text,
      ip_address    inet,
      user_agent    text,
      document_id   uuid
                      REFERENCES public.officer_change_documents(id) ON DELETE SET NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_officer_change_consents_token
      ON public.officer_change_consents (token_hash);
    CREATE INDEX IF NOT EXISTS ix_officer_change_consents_case
      ON public.officer_change_consents (case_id);
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
      IF EXISTS (SELECT 1 FROM public.officer_change_consents) THEN
        RAISE EXCEPTION
          'migration 052 cannot be downgraded while officer_change_consents has '
          'rows: they are signed consents to act. Remove them first, knowingly.';
      END IF;
      IF EXISTS (SELECT 1 FROM public.officer_change_documents WHERE entry_id IS NULL) THEN
        RAISE EXCEPTION
          'migration 052 cannot be downgraded while case-level officer-change '
          'documents exist (entry_id IS NULL). Remove them first, knowingly.';
      END IF;
    END $$;
"""


def _lock_down(table: str) -> str:
    """050's lock-down, verbatim in effect: RLS on, no policy, revoked from the
    two browser-facing roles where they exist (vanilla CI Postgres has none)."""
    return f"""
        ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            REVOKE ALL ON public.{table} FROM anon;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            REVOKE ALL ON public.{table} FROM authenticated;
          END IF;
        END $$;
    """


def audit_seed_sql() -> str:
    values = ", ".join(f"('{code}', '{name}', 'officer_changes', 'g_flowdesk')"
                       for code, name in AUDIT_CODES)
    return ("INSERT INTO public.audit_event_types (code, name, category, origin) "
            f"VALUES {values} ON CONFLICT (code) DO NOTHING")


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)
    op.execute(_lock_down("officer_change_consents"))
    op.execute(audit_seed_sql())


def downgrade() -> None:
    op.execute(DOWNGRADE_GUARD)
    codes = ", ".join(f"'{c}'" for c, _ in AUDIT_CODES)
    op.execute(f"DELETE FROM public.audit_event_types WHERE code IN ({codes})")
    op.execute("""
        ALTER TABLE public.person_eservice_credentials
          DROP CONSTRAINT IF EXISTS person_eservice_credentials_registered_id_type_valid,
          DROP COLUMN IF EXISTS registered_id_number,
          DROP COLUMN IF EXISTS registered_id_type;
    """)
    op.execute("DROP TABLE IF EXISTS public.officer_change_consents")
    op.execute("ALTER TABLE public.nar1_cases DROP COLUMN IF EXISTS attach_resolution")
    op.execute("""
        ALTER TABLE public.officer_change_documents
          DROP CONSTRAINT IF EXISTS officer_change_documents_source_valid,
          DROP COLUMN IF EXISTS uploaded_by_name,
          DROP COLUMN IF EXISTS source,
          DROP COLUMN IF EXISTS send_with_email,
          ALTER COLUMN entry_id SET NOT NULL;
    """)
    op.execute("ALTER TABLE public.officer_change_entries "
               "DROP COLUMN IF EXISTS date_deferred")

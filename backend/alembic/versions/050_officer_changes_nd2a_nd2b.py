"""ND2A and ND2B: a case carries the form it files, and the changes it reports.

R2 (re-scoped 2026-09-25). Design: `docs/superpowers/specs/2026-09-30-nd2a-nd2b-
officer-changes-design.md`, which is the PRD plus Levi's answers of 2026-09-30.

AN OFFICER-CHANGE CASE IS A ROW IN `nar1_cases`. The table's name is a Viewpoint
inheritance — there, "NAR1" meant a notice of appointment or resignation, which
is why `nar1_type` has carried `appointment_and_resignation` since migration 003
with nothing to use it. What the table actually holds is "a case that files one
CR form for one company", and every column the officer-change workflow needs is
already on it: the client-verification columns (017, 046), the approval
provenance (030), the manual signed-form and receipt pointers (021, 023, 029),
closure (039) and CR's document status (043).

A second table would have meant a second approval-token table, a second filing
FK, a second CR poller and a second statement of the workflow badge — and the
badge is already stated twice (Python and this view), which is exactly one more
than anybody wants to keep in step.

WHAT IS NEW.

  nar1_cases.form_code        'Nar1' for every existing row. The CHECK is the
                              vocabulary; `services/nar1_cases` and
                              `services/officer_changes` each refuse the other's.
  nar1_cases.filing_deadline  The earliest change on the case + 15 days. STORED,
                              for the reason `workflow_status` is a view column:
                              the dashboard sorts and flags on it, and PostgREST
                              cannot do either to an expression.
  nar1_cases.data_checked_*   The manual route's stand-in for CR's validation.
                              CR will not validate an ND2A appointing a director
                              without that director's e-Registry ID, so a case
                              with no such ID cannot be validated at all, and
                              this is what lets it leave Data Verification.
  nar1_cases.changes_*        When the filed changes reached the profiles, and
                              when (if CR refused the filing) they were undone.

  officer_change_entries      One row per officer on the form.
  officer_change_documents    Supporting documents, held on the case until it is
                              filed and then filed on the officer's own profile.
  officer_cr_particulars      Per appointment, the officer's particulars AS CR
                              HOLDS THEM. ND2B is the difference between this
                              and the profile.
  person_eservice_credentials A client's e-Registry account. See below.

THE VIEW IS RESTATED, by the discipline 025..047 set: DROP and CREATE, grants
restated, and `_case_view_sql(officer_changes=False)` must equal 047's view
byte for byte once comments and whitespace are out — `tests/test_migration_
050.py` holds it to that, because the downgrade path is the one nobody runs
until a rollback.

Four changes, and a NAR1 row reads exactly as it did:

  case_type           from `form_code`, no longer the literal 'NAR1'.
  days_to_anniversary NULL on an officer-change case. The anniversary belongs to
                      the annual return; on an ND2A it would sort a director's
                      resignation by a date that has nothing to do with it.
  workflow_status     one new branch, gated on `form_code <> 'Nar1'`: the manual
                      route. NAR1's manual path still goes through CR's
                      validation, so its badge follows the filing stage; an
                      officer change on the manual route never calls CR and has
                      no filing stage to follow.
  workflow_overdue    an officer-change case is overdue the day after its
                      15-day deadline. NAR1's 42-day rule is untouched.

`person_eservice_credentials` HOLDS OTHER PEOPLE'S PASSWORDS. GSHK sets up each
new director's CR e-Registry account and keeps the login (Levi 2026-09-30), and
CR requires that director's own PIN signature as their consent to act. So the
password is stored — Fernet, under `TPSI_CRED_KEY`, the same key that protects
staff CR credentials — with RLS on and NO policy, and the table REVOKEd from the
two browser-facing roles. Nothing but the backend's service role may read it,
and no endpoint returns the secret.

THE PERMISSION MODULE `officer_changes` is granted to every role that holds the
matching `nar1` level, so the people who run annual returns today can run these
tomorrow without an administrator visiting Roles first. It is its own module so
it can be taken away on its own.

REVERSIBLE, because CI's migrations job runs `downgrade base`. It REFUSES while
any officer-change case exists: dropping `form_code` would leave those rows
reading as annual returns, which is a worse outcome than a downgrade that stops.

Revision ID: 050
Revises: 049
"""
from alembic import op

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None

CASE_VIEW = "public.nar1_case_registry"

#: `services/officer_changes/cases.FORM_CODES`, plus the annual return.
FORM_CODES = ("Nar1", "Nd2a", "Nd2b")

#: Kept in step with services/nar1_cases.CR_FILED_STAGES, as 024..047.
CR_FILED_STAGES = ("submitted", "registered", "edrive")

#: Kept in step with the guard in nar1_case_status._code, as 024..047.
LIVE_STAGES = ("validated", "signed", "signing_failed", "submission_failed")

#: nar1_case_status.FILING_WINDOW_DAYS.
FILING_WINDOW_DAYS = 42

#: services/tpsi/doc_status.CR_STATUS_CODES, in the same order.
CR_STATUS_CODES = (
    "cr_not_checked", "cr_pending", "cr_approved", "cr_registered",
    "cr_rejected", "cr_unknown",
)

#: services/tpsi/doc_status.NOT_CHECKED.
CR_NOT_CHECKED = "cr_not_checked"

#: Verbatim from 024..047 — Python asks `if case.get("manual_receipt")`, which
#: is TRUTH and not NULL-ness.
_RECEIPT_PRESENT = """
          CASE jsonb_typeof(c.manual_receipt)
            WHEN 'null'    THEN false
            WHEN 'object'  THEN c.manual_receipt <> '{}'::jsonb
            WHEN 'array'   THEN c.manual_receipt <> '[]'::jsonb
            WHEN 'string'  THEN c.manual_receipt <> '""'::jsonb
            WHEN 'number'  THEN c.manual_receipt <> '0'::jsonb
            WHEN 'boolean' THEN c.manual_receipt = 'true'::jsonb
            ELSE false
          END
"""

#: (code, name). `category` and `origin` are set explicitly where these are
#: inserted: the column default is origin='viewpoint', and there is no FK from
#: audit_log to this table, so an unseeded code writes fine and then renders
#: unlabelled in the trail — which is what migrations 022 and 034 exist for.
AUDIT_CODES = [
    ("OFFICER_CHANGE_ADDED", "Officer Change Added"),
    ("OFFICER_CHANGE_UPDATED", "Officer Change Updated"),
    ("OFFICER_CHANGE_REMOVED", "Officer Change Removed"),
    ("OFFICER_SUPPORT_DOC_UPLOADED", "Supporting Document Uploaded"),
    ("OFFICER_SUPPORT_DOC_REMOVED", "Supporting Document Removed"),
    ("OFFICER_CONSENT_SIGNED", "Director Consent Signed"),
    ("OFFICER_SIGNED_FORM_UPLOADED", "Signed Officer-Change Form Uploaded"),
    ("OFFICER_FILING_RECORDED", "CR Portal Filing Recorded"),
    ("OFFICER_CHANGES_APPLIED", "Officer Changes Written to Profile"),
    ("OFFICER_CHANGES_UNDONE", "Officer Changes Undone"),
    ("OFFICER_PARTICULARS_DISMISSED", "Change of Particulars Dismissed"),
    ("PERSON_ESERVICE_CRED_SET", "e-Registry Credential Stored"),
]

#: (code, label, category, applies_to, sort_order).
#:
#: `nd2a` / `nd2b` are the signed form, owned by the COMPANY like `nar1`. The
#: four `officer_change` types are owned by the OFFICER — a person, or the body
#: corporate's own company record — which is why they apply to both.
DOCUMENT_TYPES = [
    ("nd2a", "ND2A — Appointment / Cessation of Officers",
     "government_form", "company", 12),
    ("nd2b", "ND2B — Change in Particulars of Officers",
     "government_form", "company", 13),
    ("resignation_letter", "Resignation Letter", "officer_change", "both", 101),
    ("board_resolution", "Board Resolution", "officer_change", "both", 102),
    ("consent_to_act", "Consent to Act", "officer_change", "both", 103),
    ("officer_change_support", "Other Supporting Document",
     "officer_change", "both", 104),
]

_NEW_TABLES = (
    "officer_change_entries", "officer_change_documents",
    "officer_cr_particulars", "person_eservice_credentials",
)


def _case_view_sql(*, officer_changes: bool) -> str:
    """047's case registry, with or without the officer-change columns.

    Parameterised for the reason 043, 046 and 047 give: upgrade and downgrade
    differ in a handful of lines, and two hand-copied definitions drift — the
    one that drifts being the one nobody runs until a rollback.
    """
    filed = ", ".join(f"'{s}'" for s in CR_FILED_STAGES)
    live = ", ".join(f"'{s}'" for s in LIVE_STAGES)
    finished = ", ".join(f"'{c}'" for c in CR_STATUS_CODES) + ", 'closed'"

    if officer_changes:
        case_type = """CASE c.form_code
                WHEN 'Nd2a' THEN 'ND2A'
                WHEN 'Nd2b' THEN 'ND2B'
                ELSE 'NAR1'
              END                             AS case_type,"""
        # The anniversary is the annual return's. NULL here keeps an ND2A out
        # of every "days to anniversary" sort and filter, and out of NAR1's
        # overdue rule below without that rule having to name the form.
        anniversary = """CASE WHEN c.form_code = 'Nar1'
                   THEN e.days_to_anniversary END AS days_to_anniversary,"""
        extra = """
              c.form_code,
              c.filing_deadline,
              -- date - date is an integer in Postgres. Negative once the
              -- deadline has passed; hk_today() for migration 019's reason.
              (c.filing_deadline - public.hk_today()) AS days_to_deadline,
              c.data_checked_at,
              c.manual_signed_document_id,"""
        # nar1_case_status._code, same place in the order: after the client
        # has approved and before the filing stage is consulted.
        manual_branch = """
              WHEN base.form_code <> 'Nar1'
               AND base.signing_method = 'manual' THEN
                CASE
                  WHEN base.data_checked_at IS NULL           THEN 'data_verification'
                  WHEN base.manual_signed_document_id IS NULL THEN 'signing'
                  ELSE 'submission'
                END"""
        overdue = f"""(
            coded.workflow_status NOT IN ({finished})
            AND (
              (coded.days_to_anniversary IS NOT NULL
               AND coded.days_to_anniversary < -{FILING_WINDOW_DAYS})
              OR
              (coded.form_code <> 'Nar1'
               AND coded.days_to_deadline IS NOT NULL
               AND coded.days_to_deadline < 0)
            )
          ) AS workflow_overdue"""
    else:
        case_type = "'NAR1'::text                    AS case_type,"
        anniversary = "e.days_to_anniversary,"
        extra = ""
        manual_branch = ""
        overdue = f"""(
            coded.workflow_status NOT IN ({finished})
            AND coded.days_to_anniversary IS NOT NULL
            AND coded.days_to_anniversary < -{FILING_WINDOW_DAYS}
          ) AS workflow_overdue"""

    return f"""
        CREATE VIEW {CASE_VIEW}
        WITH (security_invoker = true) AS
        SELECT
          coded.*,
          -- An overlay, never a stage: a case can be overdue at any step, and
          -- the question is meaningless once the case is finished — filed
          -- (033), closed (039), or answered for by CR (043).
          {overdue}
        FROM (
          SELECT
            base.*,
            -- WORKFLOW-STATUS-EXPRESSION-START
            -- Branch for branch, in order, with nar1_case_status._code.
            CASE
              WHEN base.closed_at IS NOT NULL             THEN 'closed'
              WHEN base.manual_receipt_present
                OR base.filing_stage IN ({filed})
                THEN COALESCE(base.cr_doc_status_code, '{CR_NOT_CHECKED}')
              WHEN base.client_approved IS FALSE          THEN 'client_rejected'
              WHEN base.verification_sent_at IS NULL      THEN 'client_verification'
              WHEN base.client_approved IS NULL           THEN 'awaiting_client'{manual_branch}
              WHEN base.filing_stage IS NULL
                OR base.filing_stage NOT IN ({live})      THEN 'data_verification'
              WHEN base.filing_stage IN ('signed',
                                         'submission_failed') THEN 'submission'
              ELSE 'signing'
            END AS workflow_status
            -- WORKFLOW-STATUS-EXPRESSION-END
          FROM (
            SELECT
              c.id,
              c.case_no,
              c.entity_id,
              e.company_name,
              e.company_name_zh,
              e.br_number,
              e.cr_number,
              {case_type}
              c.nar1_type::text               AS nar1_type,
              c.status::text                  AS case_status,
              c.signing_method,
              c.assigned_to,
              c.created_by,
              u.display_name                  AS created_by_name,
              c.closed_at,
              c.closed_by,
              cu.display_name                 AS closed_by_name,
              c.closed_reason,
              c.cr_doc_status,
              c.cr_doc_status_code,
              c.cr_status_checked_at,
              f.id                            AS filing_id,
              f.stage                         AS filing_stage,
              c.verification_sent_at,
              c.client_response_at,
              c.client_approved,
              c.manual_submitted_at,
              c.created_at,
              c.updated_at,
              c.ar_period_year,{extra}
              {anniversary}
              {_RECEIPT_PRESENT}              AS manual_receipt_present,
              COALESCE(f.stage = 'edrive', false) AS workflow_off_portal
            FROM public.nar1_cases c
            JOIN public.company_registry e ON e.id = c.entity_id
            LEFT JOIN public.users u ON u.id = c.created_by
            LEFT JOIN public.users cu ON cu.id = c.closed_by
            LEFT JOIN LATERAL (
              SELECT tf.id, tf.stage
              FROM public.tpsi_filings tf
              WHERE tf.nar1_case_id = c.id
                AND tf.stage <> 'superseded'
              ORDER BY (tf.stage IN ({filed})) DESC, tf.created_at DESC, tf.id DESC
              LIMIT 1
            ) f ON true
          ) base
        ) coded;
    """


#: 024..047's grant posture, restated because DROP VIEW discards it.
_CASE_GRANTS = """
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON public.nar1_case_registry FROM anon;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON public.nar1_case_registry FROM authenticated;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT ON public.nar1_case_registry TO service_role;
      END IF;
    END $$;
"""


def _lock_down(table: str) -> str:
    """RLS on with no policy, and the browser-facing roles revoked.

    Stated here rather than left to Supabase's `ensure_rls` event trigger, for
    migration 021's reason: that trigger does not exist in the vanilla Postgres
    CI migrates against, and a security property that holds by accident of the
    platform is not in the schema history.

    The backend reaches these as service_role, which bypasses RLS, so a policy
    would only ever be exercised by something that should not be asking.
    """
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


def _rebuild(*, officer_changes: bool) -> None:
    op.execute(f"DROP VIEW IF EXISTS {CASE_VIEW};")
    op.execute(_case_view_sql(officer_changes=officer_changes))
    op.execute(_CASE_GRANTS)


def upgrade() -> None:
    # ---- 1. The ND2B case type ----------------------------------------------
    # ND2A uses 003's 'appointment_and_resignation'. ADD VALUE is safe inside
    # Alembic's transaction on PG 12+ as long as the value is not USED in it,
    # and it is not: the first row using it is written by the application.
    op.execute(
        "ALTER TYPE nar1_type ADD VALUE IF NOT EXISTS 'change_of_particulars'")

    # ---- 2. What form a case files, and when it is due ----------------------
    forms = ", ".join(f"'{code}'" for code in FORM_CODES)
    op.execute(f"""
        ALTER TABLE public.nar1_cases
          ADD COLUMN IF NOT EXISTS form_code text NOT NULL DEFAULT 'Nar1',
          ADD COLUMN IF NOT EXISTS filing_deadline date,
          ADD COLUMN IF NOT EXISTS data_checked_at timestamptz,
          ADD COLUMN IF NOT EXISTS data_checked_by uuid
            REFERENCES public.users(id) ON DELETE SET NULL,
          ADD COLUMN IF NOT EXISTS changes_applied_at timestamptz,
          ADD COLUMN IF NOT EXISTS changes_undone_at timestamptz;
    """)
    op.execute(
        "ALTER TABLE public.nar1_cases "
        "  DROP CONSTRAINT IF EXISTS nar1_cases_form_code_valid;")
    op.execute(
        "ALTER TABLE public.nar1_cases ADD CONSTRAINT nar1_cases_form_code_valid "
        f"CHECK (form_code IN ({forms}));")
    # The dashboard's "which officer changes are due" question, and the only
    # filter that makes a partial index worth having: NAR1 rows never carry one.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_nar1_cases_filing_deadline "
        "ON public.nar1_cases (filing_deadline) WHERE filing_deadline IS NOT NULL")

    # ---- 3. The change list --------------------------------------------------
    op.execute("""
        CREATE TABLE public.officer_change_entries (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          case_id           uuid NOT NULL
                              REFERENCES public.nar1_cases(id) ON DELETE CASCADE,
          -- cessation and appointment are ND2A; change is ND2B.
          kind              text NOT NULL,
          party_type        party_type NOT NULL DEFAULT 'individual',
          person_id         uuid REFERENCES public.persons(id),
          corporate_entity_id uuid REFERENCES public.entities(id),
          -- The appointment being ended or changed. For an APPOINTMENT entry it
          -- is NULL until the form is filed, then the row filing created — which
          -- is what Undo removes. SET NULL, never CASCADE: removing an officer
          -- row by hand must not erase the record that a form reported it.
          officer_id        uuid REFERENCES public.entity_officers(id)
                              ON DELETE SET NULL,
          -- `officer_role`'s two values CR's forms carry. Alternate directors
          -- are out of scope (Levi 2026-09-30) and reserve directors are ND5.
          capacity          text NOT NULL,
          -- Date of cessation or of appointment. NULL on a `change` entry,
          -- where every item carries its own date inside `items`.
          effective_date    date,
          -- CR's rsnCes: R (resignation / others) or D (deceased).
          cessation_reason  text,
          correspondence_same_as_residential boolean NOT NULL DEFAULT true,
          -- {line1, line2, line3, city, state_region, postal_code, country},
          -- only when it differs from the residential address.
          correspondence_address jsonb,
          -- Section 5 of the printed ND2A. No TPSI field carries it.
          section5_confirmed boolean NOT NULL DEFAULT false,
          -- A body-corporate DIRECTOR consents through a natural person.
          consent_person_id uuid REFERENCES public.persons(id),
          consent_capacity  text,
          kyc_cleared       boolean NOT NULL DEFAULT false,
          kyc_cleared_at    timestamptz,
          kyc_cleared_by    uuid REFERENCES public.users(id) ON DELETE SET NULL,
          -- ND2B. `registered` is Part A — the officer as CR holds them — and
          -- `items` is Part B: [{key, old, new, effective_date, omitted}].
          registered        jsonb,
          items             jsonb NOT NULL DEFAULT '[]'::jsonb,
          consent_signed_at timestamptz,
          -- What filing wrote to the profiles, so Undo restores exactly that.
          applied           jsonb,
          sort_order        integer NOT NULL DEFAULT 0,
          created_by        uuid REFERENCES public.users(id) ON DELETE SET NULL,
          created_at        timestamptz NOT NULL DEFAULT now(),
          updated_at        timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT officer_change_entries_kind_valid
            CHECK (kind IN ('cessation', 'appointment', 'change')),
          CONSTRAINT officer_change_entries_capacity_valid
            CHECK (capacity IN ('director', 'company_secretary')),
          CONSTRAINT officer_change_entries_reason_valid
            CHECK (cessation_reason IS NULL OR cessation_reason IN ('R', 'D')),
          -- Exactly one party, as routers/companies._resolve_party_type asks.
          CONSTRAINT officer_change_entries_one_party
            CHECK ((person_id IS NOT NULL) <> (corporate_entity_id IS NOT NULL))
        );
        CREATE INDEX ix_officer_change_entries_case
          ON public.officer_change_entries (case_id, sort_order, created_at);
        -- "Change pending" on a profile: every open entry naming this party.
        CREATE INDEX ix_officer_change_entries_person
          ON public.officer_change_entries (person_id) WHERE person_id IS NOT NULL;
        CREATE INDEX ix_officer_change_entries_corporate
          ON public.officer_change_entries (corporate_entity_id)
          WHERE corporate_entity_id IS NOT NULL;
        CREATE TRIGGER trg_set_updated_at BEFORE UPDATE
          ON public.officer_change_entries
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    # ---- 4. Supporting documents, held on the case until it is filed --------
    op.execute("""
        CREATE TABLE public.officer_change_documents (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          case_id           uuid NOT NULL
                              REFERENCES public.nar1_cases(id) ON DELETE CASCADE,
          entry_id          uuid NOT NULL
                              REFERENCES public.officer_change_entries(id)
                              ON DELETE CASCADE,
          document_type_code text NOT NULL
                              REFERENCES public.document_types(code),
          file_name         text NOT NULL,
          storage_bucket    text NOT NULL,
          storage_path      text NOT NULL,
          mime_type         text,
          file_size_bytes   bigint,
          checksum_sha256   text,
          uploaded_by       uuid REFERENCES public.users(id) ON DELETE SET NULL,
          uploaded_at       timestamptz NOT NULL DEFAULT now(),
          -- The profile document this became when the form was filed. id AND
          -- version, for migration 023's reason: upload_document versions in
          -- place, so an id alone stops naming THIS file at the next upload.
          filed_document_id uuid REFERENCES public.documents(id) ON DELETE SET NULL,
          filed_document_version integer,
          filed_at          timestamptz
        );
        CREATE INDEX ix_officer_change_documents_case
          ON public.officer_change_documents (case_id);
        CREATE INDEX ix_officer_change_documents_entry
          ON public.officer_change_documents (entry_id);
    """)

    # ---- 5. What CR holds for each appointment -------------------------------
    op.execute("""
        CREATE TABLE public.officer_cr_particulars (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id         uuid NOT NULL
                              REFERENCES public.entities(id) ON DELETE CASCADE,
          person_id         uuid REFERENCES public.persons(id) ON DELETE CASCADE,
          corporate_entity_id uuid
                              REFERENCES public.entities(id) ON DELETE CASCADE,
          particulars       jsonb NOT NULL,
          -- first_edit | nd2a_filed | nd2b_filed | dismissed | undo
          source            text NOT NULL,
          captured_by       uuid REFERENCES public.users(id) ON DELETE SET NULL,
          captured_at       timestamptz NOT NULL DEFAULT now(),
          updated_at        timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT officer_cr_particulars_one_party
            CHECK ((person_id IS NOT NULL) <> (corporate_entity_id IS NOT NULL))
        );
        -- One baseline per appointment. Two partial indexes because the party
        -- is one of two columns and a NULL never collides in a plain UNIQUE.
        CREATE UNIQUE INDEX uq_officer_cr_particulars_person
          ON public.officer_cr_particulars (entity_id, person_id)
          WHERE person_id IS NOT NULL;
        CREATE UNIQUE INDEX uq_officer_cr_particulars_corporate
          ON public.officer_cr_particulars (entity_id, corporate_entity_id)
          WHERE corporate_entity_id IS NOT NULL;
        CREATE INDEX ix_officer_cr_particulars_person
          ON public.officer_cr_particulars (person_id) WHERE person_id IS NOT NULL;
        CREATE INDEX ix_officer_cr_particulars_corporate
          ON public.officer_cr_particulars (corporate_entity_id)
          WHERE corporate_entity_id IS NOT NULL;
        CREATE TRIGGER trg_set_updated_at BEFORE UPDATE
          ON public.officer_cr_particulars
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    # ---- 6. A client's e-Registry account ------------------------------------
    op.execute("""
        CREATE TABLE public.person_eservice_credentials (
          person_id            uuid PRIMARY KEY
                                 REFERENCES public.persons(id) ON DELETE CASCADE,
          eservice_user_id     text NOT NULL,
          -- The name CR holds for that account. CR checks selectPersonName
          -- against it, so it is stored rather than taken from the profile.
          eservice_person_name text,
          -- Fernet ciphertext under TPSI_CRED_KEY. NEVER the password.
          eservice_password_enc text,
          updated_by           uuid REFERENCES public.users(id) ON DELETE SET NULL,
          created_at           timestamptz NOT NULL DEFAULT now(),
          updated_at           timestamptz NOT NULL DEFAULT now()
        );
        CREATE TRIGGER trg_set_updated_at BEFORE UPDATE
          ON public.person_eservice_credentials
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    for table in _NEW_TABLES:
        op.execute(_lock_down(table))

    # ---- 7. Document types ---------------------------------------------------
    for code, label, category, applies_to, sort_order in DOCUMENT_TYPES:
        op.execute(f"""
            INSERT INTO public.document_types
                (code, label, category, applies_to, is_generated, sort_order, is_active)
            VALUES
                ('{code}', '{label}', '{category}', '{applies_to}', false,
                 {sort_order}, true)
            ON CONFLICT (code) DO UPDATE SET
                label = EXCLUDED.label,
                category = EXCLUDED.category,
                applies_to = EXCLUDED.applies_to,
                sort_order = EXCLUDED.sort_order,
                is_active = true
        """)

    # ---- 8. The permission module --------------------------------------------
    # Every role holding nar1:read or nar1:write gets the same level here.
    # Roles are seeded outside Alembic, so on a fresh database this selects
    # nothing — exactly as 008 and 021 do.
    op.execute("""
        INSERT INTO public.role_permissions (role_id, module, permission)
        SELECT rp.role_id, 'officer_changes', rp.permission
        FROM public.role_permissions rp
        WHERE rp.module = 'nar1' AND rp.permission IN ('read', 'write')
        ON CONFLICT (role_id, module, permission) DO NOTHING
    """)
    op.execute("""
        INSERT INTO public.role_permissions (role_id, module, permission)
        SELECT r.id, 'officer_changes', m.permission
        FROM public.roles r
        CROSS JOIN (VALUES ('read'), ('write')) AS m(permission)
        WHERE r.name = 'super_admin'
        ON CONFLICT (role_id, module, permission) DO NOTHING
    """)

    # ---- 9. Audit registry ---------------------------------------------------
    values = ", ".join(
        f"('{code}', '{name}', 'officer_changes', 'g_flowdesk')"
        for code, name in AUDIT_CODES)
    op.execute(
        "INSERT INTO public.audit_event_types (code, name, category, origin) "
        f"VALUES {values} ON CONFLICT (code) DO NOTHING")

    # ---- 10. The dashboard view ----------------------------------------------
    _rebuild(officer_changes=True)


def downgrade() -> None:
    # REFUSES while any officer-change case exists. Dropping `form_code` would
    # leave those rows reading as annual returns — on the dashboard, in the
    # auto-approval job and in the CR poller — which is worse than stopping.
    op.execute("""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM public.nar1_cases WHERE form_code <> 'Nar1') THEN
            RAISE EXCEPTION
              'migration 050 cannot be downgraded while ND2A/ND2B cases exist: '
              'without form_code they would read as annual returns. Remove them '
              'first, knowingly.';
          END IF;
        END $$;
    """)

    _rebuild(officer_changes=False)

    codes = ", ".join(f"'{c}'" for c, _ in AUDIT_CODES)
    op.execute(f"DELETE FROM public.audit_event_types WHERE code IN ({codes})")
    op.execute(
        "DELETE FROM public.role_permissions WHERE module = 'officer_changes'")

    # Guarded like 036's: a type in use is deactivated, not deleted, because
    # `documents.document_type_code` references it.
    types = ", ".join(f"'{code}'" for code, *_ in DOCUMENT_TYPES)
    op.execute("DROP TABLE IF EXISTS public.officer_change_documents")
    op.execute(f"""
        UPDATE public.document_types SET is_active = false
         WHERE code IN ({types})
           AND EXISTS (SELECT 1 FROM public.documents d
                        WHERE d.document_type_code = document_types.code)
    """)
    op.execute(f"""
        DELETE FROM public.document_types
         WHERE code IN ({types})
           AND NOT EXISTS (SELECT 1 FROM public.documents d
                            WHERE d.document_type_code = document_types.code)
    """)

    op.execute("DROP TABLE IF EXISTS public.person_eservice_credentials")
    op.execute("DROP TABLE IF EXISTS public.officer_cr_particulars")
    op.execute("DROP TABLE IF EXISTS public.officer_change_entries")

    op.execute("DROP INDEX IF EXISTS public.ix_nar1_cases_filing_deadline")
    op.execute(
        "ALTER TABLE public.nar1_cases "
        "  DROP CONSTRAINT IF EXISTS nar1_cases_form_code_valid;")
    op.execute("""
        ALTER TABLE public.nar1_cases
          DROP COLUMN IF EXISTS changes_undone_at,
          DROP COLUMN IF EXISTS changes_applied_at,
          DROP COLUMN IF EXISTS data_checked_by,
          DROP COLUMN IF EXISTS data_checked_at,
          DROP COLUMN IF EXISTS filing_deadline,
          DROP COLUMN IF EXISTS form_code;
    """)
    # Postgres cannot remove a value from an enum. 'change_of_particulars' is
    # left in place, as 021 leaves 'annual_return': inert once no row uses it.

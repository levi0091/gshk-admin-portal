"""PBI-38: G-FlowDesk core schema (Viewpoint migration target)

Revision ID: 003
Revises: 002
Create Date: 2026-06-29

Creates the lean G-FlowDesk PostgreSQL schema designed and signed off in PBI-37
(gshk/outputs/viewpoint-analysis/new-schema/schema.sql), which is the load target
for the Viewpoint -> new-schema ETL scripts.

Documents are GREENFIELD (client-confirmed 2026-07-04): NO Viewpoint documents
are migrated. The document store is empty at go-live; every document is generated
or uploaded in-app and stored in Supabase Storage. §9 therefore creates a
document_types lookup (+seed), a Storage-native `documents` table, and a clean
`document_versions` table — the old document_kind enum and the DocFiles/DocCheckOut/
DocQueueFiles/DocNum-derived columns and document_sequences table are gone.

Reconciliation with existing migrations (IMPORTANT):
  - 001 already created roles / users / role_permissions (UAM, PBI-12).
    This migration does NOT recreate them. Other tables reference users(id).
  - 002 already created audit_log (PBI-11) with action_type as TEXT.
    This migration does NOT recreate it; it ALTERs it additively to carry
    Viewpoint EventLog history (event_code, source_keycode, old_value,
    new_value, created_by, actioned_by, source, form_type).

Judgement calls flagged for review (see PRD §7 / chat):
  - audit_log.action_type is left as TEXT (per 002). The audit_action_type
    enum from schema.sql is NOT introduced, to avoid altering the live
    audit_service.py contract. form_type is added as TEXT NOT NULL DEFAULT 'na'
    (not the audit_form_type enum) for the same consistency reason.
  - RLS: new tables get RLS ENABLED with a permissive ALL policy for the
    `authenticated` role, mirroring 001/002. Real authorization is enforced in
    the backend via require_permission (PBI-12); these baseline policies just
    avoid leaving tables RLS-open. Tighten in a dedicated security pass if wanted.

PostgreSQL DDL is transactional: if upgrade() fails partway, Alembic rolls the
whole revision back, leaving the DB at 002. Run `alembic upgrade head` and only
proceed to the ETL extract/transform/load once it reports success.
"""
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


# --- helpers -----------------------------------------------------------------

ENUMS = [
    "entity_status", "workflow_type", "nar1_type", "party_type",
    "id_document_type", "name_language", "aml_status", "tpsi_account_status",
    "officer_role", "case_status", "filing_status",
]
# NOTE: document_kind enum removed — document classification is a lookup TABLE
# (document_types) per the greenfield documents design (client-confirmed
# 2026-07-04: NO Viewpoint documents are migrated). See schema.sql §9.

# New tables in FK-dependency (creation) order. Used for RLS + downgrade.
# document_types is created before documents (FK document_type_code -> document_types.code).
NEW_TABLES = [
    "addresses", "persons", "person_identity_documents", "entities",
    "entity_officers", "company_secretaries", "beneficial_owners",
    "share_classes", "shareholdings", "share_transactions", "share_certificates",
    "business_names", "entity_name_changes", "nar1_cases", "nnc1_cases",
    "document_types", "documents", "document_versions", "aml_screenings",
    "tpsi_accounts", "form_filings", "contacts", "charges",
    "address_assignments", "tasks", "audit_form_filings",
]

# Tables that carry updated_at and therefore get the touch trigger.
# documents now carries updated_at (greenfield design); document_sequences dropped.
UPDATED_AT_TABLES = [
    "addresses", "persons", "entities", "entity_officers", "beneficial_owners",
    "share_classes", "shareholdings", "nar1_cases", "nnc1_cases",
    "documents", "aml_screenings", "tpsi_accounts", "form_filings", "tasks",
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ---- 1. ENUM TYPES ------------------------------------------------------
    op.execute("""
        CREATE TYPE entity_status AS ENUM (
          'pre_incorporation','pending_aml','pending_client','to_verify',
          'revision_required','submitted_to_cr','cr_approved','client_approved',
          'client_rejected','live','ceased'
        );
        CREATE TYPE workflow_type AS ENUM ('nar1','nnc1','incorporation');
        CREATE TYPE nar1_type AS ENUM (
          'appointment_of_director','resignation_of_director',
          'appointment_and_resignation'
        );
        CREATE TYPE party_type      AS ENUM ('individual','corporate');
        CREATE TYPE id_document_type AS ENUM ('hkid','passport','china_id','other');
        CREATE TYPE name_language    AS ENUM ('english','chinese','bilingual');
        CREATE TYPE aml_status AS ENUM ('pending','cleared','flagged_escalate','not_required');
        CREATE TYPE tpsi_account_status AS ENUM ('pending','created','not_required');
        CREATE TYPE officer_role AS ENUM ('director','company_secretary','reserve_director','authorised_rep');
        CREATE TYPE case_status AS ENUM (
          'draft','pending_aml','pending_client','to_verify','revision_required',
          'ready_to_submit','submitted','approved','rejected'
        );
        CREATE TYPE filing_status AS ENUM ('queued','generated','signed','filed','rejected','cancelled');
    """)

    # ---- 2. updated_at trigger helper --------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN NEW.updated_at = now(); RETURN NEW; END;
        $$ LANGUAGE plpgsql;
    """)

    # ---- 3. ADDRESSES -------------------------------------------------------
    op.execute("""
        CREATE TABLE addresses (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          line1           text, line2 text, line3 text,
          city            text, state_region text, country text, postal_code text,
          line1_zh        text, line2_zh text, city_zh text,
          is_hk_address   boolean NOT NULL DEFAULT true,
          vp_source_key   text,
          created_at      timestamptz NOT NULL DEFAULT now(),
          updated_at      timestamptz NOT NULL DEFAULT now()
        );
    """)

    # ---- 4. PERSONS ---------------------------------------------------------
    op.execute("""
        CREATE TABLE persons (
          id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          full_name           text NOT NULL,
          given_names         text, surname text, full_name_zh text, former_name text,
          email               text, phone text,
          date_of_birth       date, gender text, nationality text, nationality_code text,
          occupation          text, place_of_birth text, marital_status text, date_of_death date,
          residential_address_id uuid REFERENCES addresses(id),
          vp_source_key       text,
          created_at          timestamptz NOT NULL DEFAULT now(),
          updated_at          timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE person_identity_documents (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          person_id       uuid NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
          id_type         id_document_type NOT NULL,
          id_number       text NOT NULL,
          issuing_country text, issue_date date, expiry_date date,
          is_primary      boolean NOT NULL DEFAULT false,
          scan_document_id uuid,
          vp_source_key   text,
          created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_person_id_docs_person ON person_identity_documents(person_id);
    """)

    # ---- 5. ENTITIES + officers / secretaries / owners ----------------------
    op.execute("""
        CREATE TABLE entities (
          id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          company_name          text NOT NULL,
          company_name_zh       text,
          name_language         name_language NOT NULL DEFAULT 'english',
          br_number             text, cr_number text,
          status                entity_status NOT NULL DEFAULT 'pre_incorporation',
          active_workflow       workflow_type,
          registered_address_id uuid REFERENCES addresses(id),
          incorporation_date    date,
          incorporation_place   text DEFAULT 'Hong Kong',
          ar_last_date date, ar_next_date date, ar_due_date date, agm_next_date date,
          aoa_director_min smallint, aoa_director_max smallint, aoa_agm_waived boolean DEFAULT false,
          previous_name text, date_name_changed date,
          case_notes text,
          assigned_to uuid REFERENCES users(id),
          vp_source_key text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_entities_status   ON entities(status);
        CREATE INDEX idx_entities_br        ON entities(br_number);
        CREATE INDEX idx_entities_workflow  ON entities(active_workflow);

        CREATE TABLE entity_officers (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id       uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          person_id       uuid REFERENCES persons(id),
          party_type      party_type NOT NULL DEFAULT 'individual',
          corporate_name  text,
          role            officer_role NOT NULL DEFAULT 'director',
          position        text, appointed_date date, resigned_date date, resignation_reason text,
          is_current      boolean NOT NULL DEFAULT true,
          vp_source_key   text,
          created_at      timestamptz NOT NULL DEFAULT now(),
          updated_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_officers_entity ON entity_officers(entity_id);
        CREATE INDEX idx_officers_person ON entity_officers(person_id);

        CREATE TABLE company_secretaries (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id       uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          is_gshk         boolean NOT NULL DEFAULT true,
          secretary_name  text DEFAULT 'Get Started HK Limited',
          tcsp_number     text DEFAULT 'TC000807',
          person_id       uuid REFERENCES persons(id),
          appointed_date  date,
          is_current      boolean NOT NULL DEFAULT true,
          created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_secretaries_entity ON company_secretaries(entity_id);

        CREATE TABLE beneficial_owners (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id         uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          person_id         uuid REFERENCES persons(id),
          party_type        party_type NOT NULL DEFAULT 'individual',
          corporate_name    text, owner_type text,
          percent_interest  numeric(7,4), percent_vote numeric(7,4),
          date_from date, date_to date,
          is_current        boolean NOT NULL DEFAULT true,
          vp_source_key     text,
          created_at        timestamptz NOT NULL DEFAULT now(),
          updated_at        timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_ben_owners_entity ON beneficial_owners(entity_id);
        CREATE INDEX idx_ben_owners_person ON beneficial_owners(person_id);
    """)

    # ---- 6. SHARES ----------------------------------------------------------
    op.execute("""
        CREATE TABLE share_classes (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id       uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          class_name      text NOT NULL DEFAULT 'Ordinary',
          currency        text NOT NULL DEFAULT 'HKD',
          nominal_value   numeric(18,4), votes_per_share integer DEFAULT 1,
          total_issued    numeric(20,4) DEFAULT 0, total_paid numeric(20,4) DEFAULT 0,
          vp_source_key   text,
          created_at      timestamptz NOT NULL DEFAULT now(),
          updated_at      timestamptz NOT NULL DEFAULT now(),
          UNIQUE (entity_id, class_name)
        );
        CREATE INDEX idx_share_classes_entity ON share_classes(entity_id);

        CREATE TABLE shareholdings (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id       uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          share_class_id  uuid NOT NULL REFERENCES share_classes(id),
          person_id       uuid REFERENCES persons(id),
          party_type      party_type NOT NULL DEFAULT 'individual',
          corporate_name  text,
          shares_held     numeric(20,4) NOT NULL DEFAULT 0,
          amount_paid     numeric(20,4),
          is_current      boolean NOT NULL DEFAULT true,
          vp_source_key   text,
          created_at      timestamptz NOT NULL DEFAULT now(),
          updated_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_shareholdings_entity ON shareholdings(entity_id);
        CREATE INDEX idx_shareholdings_person ON shareholdings(person_id);

        CREATE TABLE share_transactions (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id       uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          share_class_id  uuid REFERENCES share_classes(id),
          person_id       uuid REFERENCES persons(id),
          transaction_type text, transaction_date date,
          shares numeric(20,4), balance numeric(20,4), issue_price numeric(18,4),
          certificate_no text,
          vp_source_key   text,
          created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_share_tx_entity ON share_transactions(entity_id);

        CREATE TABLE share_certificates (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id       uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          share_class_id  uuid REFERENCES share_classes(id),
          person_id       uuid REFERENCES persons(id),
          certificate_no text, shares numeric(20,4), issue_date date, cancelled_date date,
          document_id     uuid,
          vp_source_key   text,
          created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_share_certs_entity ON share_certificates(entity_id);
    """)

    # ---- 7. BUSINESS NAMES & NAME CHANGES -----------------------------------
    op.execute("""
        CREATE TABLE business_names (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id         uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          br_number text, business_name text, business_name_zh text,
          registration_date date, renewal_date date, cessation_date date, status text,
          vp_source_key text,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_business_names_entity ON business_names(entity_id);

        CREATE TABLE entity_name_changes (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id       uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          old_name text, old_name_zh text, new_name text, new_name_zh text,
          applied_date date, confirmed_date date,
          vp_source_key text,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_name_changes_entity ON entity_name_changes(entity_id);
    """)

    # ---- 8. WORKFLOW CASES --------------------------------------------------
    op.execute("""
        CREATE TABLE nar1_cases (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id         uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          nar1_type         nar1_type NOT NULL,
          status            case_status NOT NULL DEFAULT 'draft',
          effective_date date, ar_period_year integer,
          director_full_name text, id_type id_document_type, registered_address_snapshot text,
          assigned_to       uuid REFERENCES users(id),
          submitted_at      timestamptz, submitted_by uuid REFERENCES users(id),
          created_at        timestamptz NOT NULL DEFAULT now(),
          updated_at        timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_nar1_entity ON nar1_cases(entity_id);
        CREATE INDEX idx_nar1_status ON nar1_cases(status);

        CREATE TABLE nnc1_cases (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id         uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          status            case_status NOT NULL DEFAULT 'draft',
          client_approved   boolean, client_response_at timestamptz,
          assigned_to       uuid REFERENCES users(id),
          submitted_at      timestamptz, submitted_by uuid REFERENCES users(id),
          created_at        timestamptz NOT NULL DEFAULT now(),
          updated_at        timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_nnc1_entity ON nnc1_cases(entity_id);
        CREATE INDEX idx_nnc1_status ON nnc1_cases(status);
    """)

    # ---- 9. DOCUMENTS (GREENFIELD — Supabase Storage) -----------------------
    #   Client confirmed 2026-07-04: NO Viewpoint documents are migrated. The
    #   document store is EMPTY at go-live; every document is generated/uploaded
    #   in-app and stored in Supabase Storage. These tables hold metadata + the
    #   storage locator only. document_kind enum -> document_types lookup table.
    #   9a. Document type catalogue (lookup) + seed.
    op.execute("""
        CREATE TABLE document_types (
          code          text PRIMARY KEY,
          label         text NOT NULL,
          category      text,
          is_generated  boolean NOT NULL DEFAULT false,
          template_ref  text,
          sort_order    integer NOT NULL DEFAULT 100,
          is_active     boolean NOT NULL DEFAULT true,
          created_at    timestamptz NOT NULL DEFAULT now()
        );
        INSERT INTO document_types (code, label, category, is_generated, sort_order) VALUES
          ('nar1',              'NAR1 — Annual Return',          'government_form', true,  10),
          ('nnc1',              'NNC1 — Incorporation Form',     'government_form', true,  20),
          ('aoa',               'Articles of Association',       'statutory',       true,  30),
          ('fwr',               'First Written Resolution',      'statutory',       true,  40),
          ('coi',               'Certificate of Incorporation',  'certificate',     false, 50),
          ('incumbency',        'Certificate of Incumbency',     'certificate',     true,  60),
          ('share_certificate', 'Share Certificate',             'certificate',     true,  70),
          ('id_scan',           'Identity Document Scan',        'kyc',             false, 80),
          ('address_proof',     'Proof of Address',              'kyc',             false, 90),
          ('other',             'Other',                         'internal',        false, 100);

        CREATE TABLE documents (
          id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id           uuid REFERENCES entities(id) ON DELETE CASCADE,
          document_type_code  text NOT NULL DEFAULT 'other' REFERENCES document_types(code),
          title               text,
          file_name           text,
          storage_bucket      text NOT NULL DEFAULT 'gflowdesk-documents',
          storage_path        text NOT NULL,
          mime_type           text,
          file_size_bytes     bigint,
          checksum_sha256     text,
          current_version     integer NOT NULL DEFAULT 1,
          status              text NOT NULL DEFAULT 'active',
          is_generated        boolean NOT NULL DEFAULT false,
          generated_at        timestamptz,
          generated_by        uuid REFERENCES users(id),
          uploaded_by         uuid REFERENCES users(id),
          created_at          timestamptz NOT NULL DEFAULT now(),
          updated_at          timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_documents_entity ON documents(entity_id);
        CREATE INDEX idx_documents_type   ON documents(document_type_code);

        CREATE TABLE document_versions (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          document_id     uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          version_number  integer NOT NULL,
          file_name       text,
          storage_bucket  text NOT NULL DEFAULT 'gflowdesk-documents',
          storage_path    text NOT NULL,
          mime_type       text,
          file_size_bytes bigint,
          checksum_sha256 text,
          generated_at    timestamptz,
          created_by      uuid REFERENCES users(id),
          note            text,
          created_at      timestamptz NOT NULL DEFAULT now(),
          UNIQUE (document_id, version_number)
        );
        CREATE INDEX idx_doc_versions_doc ON document_versions(document_id);
    """)

    # back-references now that documents exists
    op.execute("""
        ALTER TABLE person_identity_documents
          ADD CONSTRAINT fk_pid_scan_doc FOREIGN KEY (scan_document_id) REFERENCES documents(id);
        ALTER TABLE share_certificates
          ADD CONSTRAINT fk_cert_doc FOREIGN KEY (document_id) REFERENCES documents(id);
    """)

    # ---- 10-14. AML / TPSI / FILINGS / CONTACTS / CHARGES / ASSIGN / TASKS / SEQ
    op.execute("""
        CREATE TABLE aml_screenings (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id         uuid REFERENCES entities(id) ON DELETE CASCADE,
          person_id         uuid REFERENCES persons(id),
          status            aml_status NOT NULL DEFAULT 'pending',
          worldcheck_ref text, screened_by uuid REFERENCES users(id), screening_date date, notes text,
          created_at        timestamptz NOT NULL DEFAULT now(),
          updated_at        timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_aml_entity ON aml_screenings(entity_id);
        CREATE INDEX idx_aml_person ON aml_screenings(person_id);

        CREATE TABLE tpsi_accounts (
          id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id             uuid REFERENCES entities(id) ON DELETE CASCADE,
          status                tpsi_account_status NOT NULL DEFAULT 'pending',
          presentor_account_id text, presentor_password_enc text, deposit_account_no text,
          created_by uuid REFERENCES users(id), account_created_date date,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_tpsi_entity ON tpsi_accounts(entity_id);

        CREATE TABLE form_filings (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id         uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          form_code text, workflow workflow_type,
          status            filing_status NOT NULL DEFAULT 'queued',
          field_details jsonb, generated_date date, signed_date date, filed_date date,
          file_deadline date, filed_with_cr boolean DEFAULT false,
          document_id uuid REFERENCES documents(id),
          source text NOT NULL DEFAULT 'g_flowdesk',
          vp_source_key text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_filings_entity ON form_filings(entity_id);
        CREATE INDEX idx_filings_status ON form_filings(status);

        CREATE TABLE contacts (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id       uuid REFERENCES entities(id) ON DELETE CASCADE,
          person_id       uuid REFERENCES persons(id),
          contact_type text, contact_value text, is_preferred boolean DEFAULT false,
          vp_source_key text,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_contacts_entity ON contacts(entity_id);

        CREATE TABLE charges (
          id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id           uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
          charge_ref text, charge_type text, mortgagee text,
          registration_date date, discharge_date date, property_description text, currency text,
          vp_source_key text,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_charges_entity ON charges(entity_id);

        CREATE TABLE address_assignments (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          address_id      uuid NOT NULL REFERENCES addresses(id) ON DELETE CASCADE,
          party_type      text NOT NULL CHECK (party_type IN ('entity','person')),
          entity_id       uuid REFERENCES entities(id) ON DELETE CASCADE,
          person_id       uuid REFERENCES persons(id) ON DELETE CASCADE,
          address_role text, effective_date date, cancelled_date date,
          is_current      boolean NOT NULL DEFAULT true,
          vp_source_key text,
          created_at timestamptz NOT NULL DEFAULT now(),
          CHECK (entity_id IS NOT NULL OR person_id IS NOT NULL)
        );
        CREATE INDEX idx_addr_assign_address ON address_assignments(address_id);
        CREATE INDEX idx_addr_assign_entity  ON address_assignments(entity_id);
        CREATE INDEX idx_addr_assign_person  ON address_assignments(person_id);

        CREATE TABLE tasks (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id       uuid REFERENCES entities(id) ON DELETE CASCADE,
          person_id       uuid REFERENCES persons(id),
          task_code text, description text, due_date date,
          is_done boolean NOT NULL DEFAULT false, completed_date date,
          assigned_to uuid REFERENCES users(id),
          vp_source_key text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_tasks_entity ON tasks(entity_id);
        CREATE INDEX idx_tasks_due    ON tasks(due_date) WHERE is_done = false;
    """)
    # NOTE: document_sequences (VP DocNum) dropped — no Viewpoint document
    # numbering is migrated (greenfield documents, client-confirmed 2026-07-04).

    # ---- 15. AUDIT LOG — additive ALTER on existing PBI-11 table ------------
    #   002 created audit_log with action_type TEXT and no form_type. Add the
    #   Viewpoint-history columns without recreating the table or touching the
    #   audit_service.py contract.
    op.execute("""
        ALTER TABLE public.audit_log
          ADD COLUMN IF NOT EXISTS form_type      text NOT NULL DEFAULT 'na',
          ADD COLUMN IF NOT EXISTS event_code     text,
          ADD COLUMN IF NOT EXISTS source_keycode text,
          ADD COLUMN IF NOT EXISTS old_value      text,
          ADD COLUMN IF NOT EXISTS new_value      text,
          ADD COLUMN IF NOT EXISTS created_by     text,
          ADD COLUMN IF NOT EXISTS actioned_by    text,
          ADD COLUMN IF NOT EXISTS source         text NOT NULL DEFAULT 'g_flowdesk';
        CREATE INDEX IF NOT EXISTS idx_audit_keycode   ON public.audit_log(source_keycode);
        CREATE INDEX IF NOT EXISTS idx_audit_eventcode ON public.audit_log(event_code);
    """)

    # 15a. audit <-> form-filing link
    op.execute("""
        CREATE TABLE audit_form_filings (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          audit_log_id    uuid REFERENCES audit_log(id),
          form_filing_id  uuid REFERENCES form_filings(id),
          vp_event_nr text, vp_fq_number text,
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (audit_log_id, form_filing_id)
        );
        CREATE INDEX idx_audit_form_audit  ON audit_form_filings(audit_log_id);
        CREATE INDEX idx_audit_form_filing ON audit_form_filings(form_filing_id);
    """)

    # ---- 16. updated_at triggers -------------------------------------------
    for t in UPDATED_AT_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON {t} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )

    # ---- 17. RLS — enable + permissive authenticated baseline --------------
    #   Mirrors 001/002. Real authorization is enforced in the backend via
    #   require_permission (PBI-12); tighten in a dedicated security pass.
    for t in NEW_TABLES:
        op.execute(f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f'CREATE POLICY "{t}_authenticated_all" ON public.{t} '
            f"FOR ALL TO authenticated USING (true) WITH CHECK (true);"
        )


def downgrade() -> None:
    # Drop new tables (CASCADE removes their policies, triggers, FKs, indexes).
    for t in reversed(NEW_TABLES):
        op.execute(f"DROP TABLE IF EXISTS public.{t} CASCADE;")

    # Revert the additive audit_log changes (leave the PBI-11 table itself).
    op.execute("DROP INDEX IF EXISTS idx_audit_eventcode;")
    op.execute("DROP INDEX IF EXISTS idx_audit_keycode;")
    op.execute("""
        ALTER TABLE public.audit_log
          DROP COLUMN IF EXISTS form_type,
          DROP COLUMN IF EXISTS event_code,
          DROP COLUMN IF EXISTS source_keycode,
          DROP COLUMN IF EXISTS old_value,
          DROP COLUMN IF EXISTS new_value,
          DROP COLUMN IF EXISTS created_by,
          DROP COLUMN IF EXISTS actioned_by,
          DROP COLUMN IF EXISTS source;
    """)

    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")

    for e in reversed(ENUMS):
        op.execute(f"DROP TYPE IF EXISTS {e};")

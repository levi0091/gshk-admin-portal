"""PBI-40 Party Master: corporate-party superset + person/company field restores

Revision ID: 007
Revises: 006
Create Date: 2026-07-09

Block 2 of PBI-40 (party-master registries + corporate-party model). Purely
additive DDL — no data moves here (that is Block 3, run_checkpoint_d.py). See
docs/pbi40-block0-gap-audit.md and docs/schema.sql for rationale.

Changes
-------
entities becomes the company-master SUPERSET (mirrors VP RefMaster RefType='C'):
  * is_client            bool NOT NULL DEFAULT true  — GSHK services it (has a VP Entity row).
                         Existing rows (all PBI-38-loaded) backfill to true, which is correct.
  * is_corporate_party   bool NOT NULL DEFAULT false — acts as a party elsewhere.
                         Block 3 flips the 219 client entities + backfills 68 non-clients.
  * company_type         text — VP Entity.EntType (decode EntityTypes; e.g. CL14).
  * tcsp_licence_no / tcsp_exemption_reason — corporate secretary licence (in-app).

Corporate-relationship repoint targets (replace free-text corporate_name):
  * entity_officers.corporate_entity_id  -> entities(id)
  * beneficial_owners.corporate_entity_id -> entities(id)
  * shareholdings.corporate_entity_id     -> entities(id)
  corporate_name is kept transitionally; the "exactly one of person_id /
  corporate_entity_id per party_type" rule is BACKEND-enforced (not a DB CHECK)
  so transitional backfill rows are not rejected — matches the address_assignments
  precedent and PRD §8.3.

Person / document restores:
  * documents.person_id -> persons(id) ON DELETE CASCADE, plus a polymorphic-owner
    CHECK (entity_id IS NOT NULL OR person_id IS NOT NULL). documents is greenfield
    (empty in dev), so the CHECK applies cleanly.
  * person_identity_documents.place_of_issue (VP Compliance.PasPlaceIssue, ~89% filled)
  * person_identity_documents.reminder_date  (VP IdentityRegister.ReminderDate)
  * persons.nationality_origin (VP Compliance.NationalityOrigin, ~16% filled)

No new vp_source_key indexes: corporate parties reuse the `entities` row (already
indexed by migration 004), and the repoint UPDATEs existing officer/owner/holding
rows keyed by their existing vp_source_key indexes.
"""
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- entities: superset flags + corporate-party field block ---
    op.execute(
        "ALTER TABLE public.entities "
        "  ADD COLUMN IF NOT EXISTS is_client boolean NOT NULL DEFAULT true, "
        "  ADD COLUMN IF NOT EXISTS is_corporate_party boolean NOT NULL DEFAULT false, "
        "  ADD COLUMN IF NOT EXISTS company_type text, "
        "  ADD COLUMN IF NOT EXISTS tcsp_licence_no text, "
        "  ADD COLUMN IF NOT EXISTS tcsp_exemption_reason text;"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_entities_is_client "
        "ON public.entities (is_client);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_entities_corp_party "
        "ON public.entities (is_corporate_party);"
    )

    # --- corporate_entity_id repoint FKs on the three relationship tables ---
    for tbl, idx in [
        ("entity_officers", "idx_officers_corp"),
        ("beneficial_owners", "idx_ben_owners_corp"),
        ("shareholdings", "idx_shareholdings_corp"),
    ]:
        op.execute(
            f"ALTER TABLE public.{tbl} "
            f"  ADD COLUMN IF NOT EXISTS corporate_entity_id uuid "
            f"  REFERENCES public.entities(id);"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {idx} "
            f"ON public.{tbl} (corporate_entity_id);"
        )

    # --- documents: polymorphic owner (person OR entity) ---
    op.execute(
        "ALTER TABLE public.documents "
        "  ADD COLUMN IF NOT EXISTS person_id uuid "
        "  REFERENCES public.persons(id) ON DELETE CASCADE;"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_person "
        "ON public.documents (person_id);"
    )
    op.execute("ALTER TABLE public.documents DROP CONSTRAINT IF EXISTS documents_owner_present;")
    op.execute(
        "ALTER TABLE public.documents ADD CONSTRAINT documents_owner_present "
        "CHECK (entity_id IS NOT NULL OR person_id IS NOT NULL);"
    )

    # --- person / identity-document field restores ---
    op.execute(
        "ALTER TABLE public.person_identity_documents "
        "  ADD COLUMN IF NOT EXISTS place_of_issue text, "
        "  ADD COLUMN IF NOT EXISTS reminder_date date;"
    )
    op.execute(
        "ALTER TABLE public.persons "
        "  ADD COLUMN IF NOT EXISTS nationality_origin text;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE public.persons DROP COLUMN IF EXISTS nationality_origin;")
    op.execute(
        "ALTER TABLE public.person_identity_documents "
        "  DROP COLUMN IF EXISTS place_of_issue, "
        "  DROP COLUMN IF EXISTS reminder_date;"
    )

    op.execute("ALTER TABLE public.documents DROP CONSTRAINT IF EXISTS documents_owner_present;")
    op.execute("DROP INDEX IF EXISTS idx_documents_person;")
    op.execute("ALTER TABLE public.documents DROP COLUMN IF EXISTS person_id;")

    for tbl, idx in [
        ("entity_officers", "idx_officers_corp"),
        ("beneficial_owners", "idx_ben_owners_corp"),
        ("shareholdings", "idx_shareholdings_corp"),
    ]:
        op.execute(f"DROP INDEX IF EXISTS {idx};")
        op.execute(f"ALTER TABLE public.{tbl} DROP COLUMN IF EXISTS corporate_entity_id;")

    op.execute("DROP INDEX IF EXISTS idx_entities_corp_party;")
    op.execute("DROP INDEX IF EXISTS idx_entities_is_client;")
    op.execute(
        "ALTER TABLE public.entities "
        "  DROP COLUMN IF EXISTS is_client, "
        "  DROP COLUMN IF EXISTS is_corporate_party, "
        "  DROP COLUMN IF EXISTS company_type, "
        "  DROP COLUMN IF EXISTS tcsp_licence_no, "
        "  DROP COLUMN IF EXISTS tcsp_exemption_reason;"
    )

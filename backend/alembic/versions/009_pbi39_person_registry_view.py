"""PBI-39 Block 2d: person_registry read-only view (Persons Registry screen)

Revision ID: 009
Revises: 008
Create Date: 2026-07-11

Read-only, additive — NO data-model change. The Persons Registry (wireframe_v7
s10) needs role filter tabs with *distinct-person* counts across four link
tables. PostgREST cannot express that: count='exact' counts rows, not distinct
persons (12,737 entity_officers rows vs 6,259 distinct directors), and filtering
"persons who are directors" would mean pushing 6k+ ids through a URL.

This view flattens the four relationships into per-person boolean flags plus the
primary identity document, so the registry is a single relation PostgREST can
search, filter, count and paginate directly.

Secretaries come from BOTH sources: entity_officers.role='company_secretary' and
the company_secretaries table (the ETL populated both paths).
"""
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE VIEW public.person_registry AS
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
            WHERE o.person_id = p.id AND o.role = 'director'
          ) AS is_director,
          EXISTS (
            SELECT 1 FROM public.shareholdings s
            WHERE s.person_id = p.id
          ) AS is_shareholder,
          (
            EXISTS (
              SELECT 1 FROM public.entity_officers o
              WHERE o.person_id = p.id AND o.role = 'company_secretary'
            )
            OR EXISTS (
              SELECT 1 FROM public.company_secretaries cs
              WHERE cs.person_id = p.id
            )
          ) AS is_secretary,
          EXISTS (
            SELECT 1 FROM public.beneficial_owners b
            WHERE b.person_id = p.id
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
        ) AS idoc ON TRUE
    """)

    # Supabase-only roles. Guarded so the migration also applies to a vanilla
    # Postgres (the CI `migrations` job), where these roles do not exist.
    op.execute("""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            GRANT SELECT ON public.person_registry TO authenticated;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            GRANT SELECT ON public.person_registry TO service_role;
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS public.person_registry")

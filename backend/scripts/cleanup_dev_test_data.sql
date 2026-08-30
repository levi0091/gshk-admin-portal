-- ============================================================================
-- cleanup_dev_test_data.sql  —  DEV ONLY
-- Removes performance/audit test pollution from the G-FlowDesk DEV database.
-- Ref: PRD/Pending/prd-uat-readiness-fixes-2026-07-19.md  (Issue B)
--
-- WHAT THIS TARGETS (test residue created via the API during perf/audit runs):
--   * entities/persons whose name is "<Perf|PerfAddr|AuditProbe> <epoch>"
--   * entities/persons with a blank / "-" / "--" name
--   * the hand-made "test" company (OQ-1: confirmed delete, 2026-07-19)
--   * ALL are guarded by vp_source_key IS NULL, so genuine Viewpoint-migrated
--     records are never in scope even if a name coincidentally matches.
--
-- CASCADE: FKs from child tables to entities(id)/persons(id) are ON DELETE
--   CASCADE (migration 003), so deleting a target row removes its officers,
--   shareholdings, beneficial_owners, documents, contacts, cases, aml, etc.
--   EXCEPTION: shareholdings/entity_officers/beneficial_owners.corporate_entity_id
--   -> entities(id) is NOT cascade (migration 007). Step 3 clears those links
--   first so a test entity used as a corporate party elsewhere still deletes.
--
-- HOW TO RUN:
--   1. Run SECTION 0 + SECTION 1 alone first. Review the counts.
--   2. Take a backup (SECTION 2).
--   3. Run SECTION 3 (transaction). It ends in ROLLBACK — nothing is deleted.
--      Review the verification output, then change the final ROLLBACK to COMMIT
--      and run SECTION 3 again to apply.
-- ============================================================================


-- ========================= SECTION 0 — SAFETY GUARD =========================
-- Must return the DEV database name. If this is PROD, STOP.
SELECT current_database() AS db, current_user AS run_by, now() AS at;


-- ===================== SECTION 1 — DRY RUN (read only) ======================
-- Candidate target sets. Review these counts and the sample before deleting.

WITH target_entities AS (
  SELECT id, company_name, vp_source_key
  FROM public.entities
  WHERE vp_source_key IS NULL
    AND (
         company_name ~ '^(Perf|PerfAddr|AuditProbe)[ ]?[0-9]'   -- perf/audit probe rows
      OR btrim(coalesce(company_name,'')) IN ('', '-', '--')      -- blank-name rows
      OR lower(btrim(company_name)) = 'test'                      -- the hand-made 'test' company
    )
),
target_persons AS (
  SELECT id, full_name, vp_source_key
  FROM public.persons
  WHERE vp_source_key IS NULL
    AND (
         full_name ~ '^(Perf|PerfAddr|AuditProbe|Probe)[ ]?[0-9]'
      OR btrim(coalesce(full_name,'')) IN ('', '-', '--')
    )
)
SELECT 'entities (companies) to delete' AS bucket, count(*) AS rows FROM target_entities
UNION ALL SELECT 'persons to delete', count(*) FROM target_persons
UNION ALL SELECT '  ├ documents (cascade)', count(*) FROM public.documents d
            WHERE d.entity_id IN (SELECT id FROM target_entities)
               OR d.person_id IN (SELECT id FROM target_persons)
UNION ALL SELECT '  ├ entity_officers (cascade)', count(*) FROM public.entity_officers o
            WHERE o.entity_id IN (SELECT id FROM target_entities)
               OR o.person_id IN (SELECT id FROM target_persons)
UNION ALL SELECT '  ├ shareholdings (cascade)', count(*) FROM public.shareholdings s
            WHERE s.entity_id IN (SELECT id FROM target_entities)
               OR s.person_id IN (SELECT id FROM target_persons)
UNION ALL SELECT '  ├ beneficial_owners (cascade)', count(*) FROM public.beneficial_owners b
            WHERE b.entity_id IN (SELECT id FROM target_entities)
               OR b.person_id IN (SELECT id FROM target_persons)
UNION ALL SELECT '  ├ contacts (cascade)', count(*) FROM public.contacts c
            WHERE c.entity_id IN (SELECT id FROM target_entities)
UNION ALL SELECT '  ├ nar1_cases (cascade)', count(*) FROM public.nar1_cases n
            WHERE n.entity_id IN (SELECT id FROM target_entities)
UNION ALL SELECT '  ├ nnc1_cases (cascade)', count(*) FROM public.nnc1_cases n
            WHERE n.entity_id IN (SELECT id FROM target_entities)
UNION ALL SELECT '  └ audit_log rows referencing targets (NOT auto-deleted)', count(*)
            FROM public.audit_log a
            WHERE a.entity_id IN (SELECT id FROM target_entities);

-- Sample of what will be deleted (eyeball for false positives before proceeding):
WITH target_entities AS (
  SELECT id, company_name FROM public.entities
  WHERE vp_source_key IS NULL
    AND ( company_name ~ '^(Perf|PerfAddr|AuditProbe)[ ]?[0-9]'
       OR btrim(coalesce(company_name,'')) IN ('', '-', '--')
       OR lower(btrim(company_name)) = 'test' )
)
SELECT company_name FROM target_entities ORDER BY company_name LIMIT 50;


-- ========================= SECTION 2 — BACKUP ==============================
-- Run this in a shell BEFORE deleting (needs the DEV DATABASE_URL). Keep the
-- dump outside git (gshk/secrets/ is already .gitignored):
--
--   pg_dump "$DATABASE_URL" -Fc -f gshk/secrets/dev-backup-$(date +%Y%m%d).dump
--
-- Optional in-DB snapshot of just the target rows (fast rollback reference):
--   (uncomment to use)
-- CREATE TABLE IF NOT EXISTS _bak_entities_20260719 AS
--   SELECT * FROM public.entities WHERE vp_source_key IS NULL
--     AND ( company_name ~ '^(Perf|PerfAddr|AuditProbe)[ ]?[0-9]'
--        OR btrim(coalesce(company_name,'')) IN ('', '-', '--')
--        OR lower(btrim(company_name)) = 'test' );
-- CREATE TABLE IF NOT EXISTS _bak_persons_20260719 AS
--   SELECT * FROM public.persons WHERE vp_source_key IS NULL
--     AND ( full_name ~ '^(Perf|PerfAddr|AuditProbe|Probe)[ ]?[0-9]'
--        OR btrim(coalesce(full_name,'')) IN ('', '-', '--') );


-- ================= SECTION 3 — DELETE (transaction, ROLLBACK) ===============
-- Ends in ROLLBACK: run once to preview, review the verification counts, then
-- change the last line to COMMIT and run again to apply.
BEGIN;

CREATE TEMP TABLE _tgt_e ON COMMIT DROP AS
  SELECT id FROM public.entities
  WHERE vp_source_key IS NULL
    AND ( company_name ~ '^(Perf|PerfAddr|AuditProbe)[ ]?[0-9]'
       OR btrim(coalesce(company_name,'')) IN ('', '-', '--')
       OR lower(btrim(company_name)) = 'test' );

CREATE TEMP TABLE _tgt_p ON COMMIT DROP AS
  SELECT id FROM public.persons
  WHERE vp_source_key IS NULL
    AND ( full_name ~ '^(Perf|PerfAddr|AuditProbe|Probe)[ ]?[0-9]'
       OR btrim(coalesce(full_name,'')) IN ('', '-', '--') );

-- 3a. Clear non-cascade corporate-party links pointing AT a target entity
--     (prevents FK RESTRICT from migration 007 blocking the delete).
UPDATE public.entity_officers   SET corporate_entity_id = NULL WHERE corporate_entity_id IN (SELECT id FROM _tgt_e);
UPDATE public.shareholdings     SET corporate_entity_id = NULL WHERE corporate_entity_id IN (SELECT id FROM _tgt_e);
UPDATE public.beneficial_owners SET corporate_entity_id = NULL WHERE corporate_entity_id IN (SELECT id FROM _tgt_e);

-- 3b. Remove probe/test rows from the audit log (not covered by cascade).
DELETE FROM public.audit_log WHERE entity_id IN (SELECT id FROM _tgt_e);

-- 3c. Delete the parents — children cascade automatically.
DELETE FROM public.entities WHERE id IN (SELECT id FROM _tgt_e);
DELETE FROM public.persons  WHERE id IN (SELECT id FROM _tgt_p);

-- 3d. Verification — expect 0 remaining targets and 0 orphaned children.
SELECT 'entities remaining (should be 0)' AS check, count(*) FROM public.entities e
  WHERE e.vp_source_key IS NULL
    AND ( e.company_name ~ '^(Perf|PerfAddr|AuditProbe)[ ]?[0-9]'
       OR btrim(coalesce(e.company_name,'')) IN ('', '-', '--')
       OR lower(btrim(e.company_name)) = 'test' )
UNION ALL
SELECT 'orphan documents (should be 0)', count(*) FROM public.documents d
  LEFT JOIN public.entities e ON e.id = d.entity_id
  LEFT JOIN public.persons  p ON p.id = d.person_id
  WHERE (d.entity_id IS NOT NULL AND e.id IS NULL)
     OR (d.person_id IS NOT NULL AND p.id IS NULL);

-- >>> Review the counts above. Nothing has been saved yet. <<<
-- Change ROLLBACK to COMMIT and re-run this SECTION 3 to apply the cleanup.
ROLLBACK;

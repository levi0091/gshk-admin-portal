# PBI-38 ETL — Viewpoint → G-FlowDesk

Extract/transform/load from the legacy Viewpoint SQL Server backup into the
G-FlowDesk schema (created by Alembic `003_pbi38_viewpoint_schema.py`).

Field-level mapping (authoritative): `docs/field-mapping.md`
(and `gshk/outputs/viewpoint-analysis/new-schema/field-mapping.md`).

---

## Documents are OUT of ETL scope (client-confirmed 2026-07-04)

**Do NOT extract, transform, or load any Viewpoint document data.** The G-FlowDesk
document store is **greenfield** — empty at go-live; every document is generated
or uploaded in-app afterwards and stored in Supabase Storage
(`backend/services/storage_service.py` + `documents_service.py`).

Excluded Viewpoint tables — no ETL code path for any of these:

| Viewpoint table | Reason |
|---|---|
| `DocFiles` | document file index — not migrated |
| `DocCheckOut` | version/checkout state — not migrated |
| `DocQueueFiles` | generated/queued docs — not migrated |
| `DocNum` | per-company doc numbering — not migrated (`document_sequences` table was dropped) |

Consequences for the ETL:
- The load order has **no** `documents` / `document_versions` / `document_types`
  step. `document_types` is **seeded by the 003 migration**, not by ETL.
- The **reconciliation report must not expect document rows** — target document
  counts are 0 by design. Do not flag the empty document tables as a load gap.
- FK columns that point at `documents` (`person_identity_documents.scan_document_id`,
  `share_certificates.document_id`, `form_filings.document_id`) are loaded as
  **NULL** during ETL; they are populated later, in-app, once real documents exist.

Everything else in `field-mapping.md` (entities, persons, officers, shares,
business names, filings, audit history, addresses, tasks, etc.) is in scope.

## Checkpoint A — entities, persons, addresses, officers, secretaries, beneficial owners

Covers `addresses`, `persons`, `entities`, `person_identity_documents`,
`entity_officers`, `company_secretaries`, `beneficial_owners`. See
`docs/superpowers/plans/2026-07-04-viewpoint-etl-checkpoint-a.md` for the
full design (in particular: why `registered_address_id`/`residential_address_id`
are NULL after this checkpoint, and the `entities.status` live/ceased rule).

### Prerequisites

1. ViewPoint SQL Server restored and running on `localhost` (default instance,
   database name `ViewPoint`), reachable via Windows Integrated Auth.
2. `backend/.env` has `VIEWPOINT_SERVER`, `VIEWPOINT_DATABASE`, and the existing
   `DATABASE_URL` (Supabase dev).
3. Alembic is at head (`.venv\Scripts\alembic.exe upgrade head` from `backend/`)
   — this includes migration `004` which adds the `vp_source_key` unique
   indexes this ETL's upserts depend on.

### Running

```powershell
cd backend
.venv\Scripts\python.exe -m etl.run_checkpoint_a --dry-run   # validate only, no writes
.venv\Scripts\python.exe -m etl.run_checkpoint_a              # real run
```

Exit code is non-zero if any row was logged to the error log (unresolved FK,
ambiguous code, etc.) — check `etl/reports/checkpoint_a_<timestamp>.json` for
detail. A non-zero exit does **not** mean the whole run failed: rows without
errors are still loaded; the flagged rows need manual review.

### Re-running

Every load is `INSERT ... ON CONFLICT (vp_source_key) DO UPDATE` — safe to
re-run after fixing an issue; already-loaded rows are updated in place, not
duplicated.

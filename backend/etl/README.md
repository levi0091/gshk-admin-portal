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

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

`person_identity_documents` is loaded from **two** Viewpoint sources —
`IdentityRegister` (primary) and `Compliance` (passport/HKID columns,
secondary) — deduplicated against each other so a person with only a
Compliance-sourced ID doc is no longer missed.

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

## Checkpoint B — shares, business names, name changes

Covers `share_classes`, `business_names`, `entity_name_changes`,
`share_transactions` (full ledger), `share_certificates`, and the derived
`shareholdings`. See `docs/superpowers/plans/2026-07-05-viewpoint-etl-checkpoint-b.md`
for the full design.

### Prerequisites

1. Checkpoint A already run (entities + persons populated in Supabase dev) —
   Checkpoint B resolves `entity_id`/`person_id` against those tables.
2. Alembic at head (`.venv\Scripts\alembic.exe upgrade head` from `backend/`) —
   includes migration `005` (Checkpoint B `vp_source_key` indexes).

### Running

```powershell
cd backend
.venv\Scripts\python.exe -m etl.run_checkpoint_b --dry-run   # validates share_classes/business_names/entity_name_changes; the three share-detail tables need a real run (their share_class_id resolves against the share_classes write)
.venv\Scripts\python.exe -m etl.run_checkpoint_b              # real run
```

Key derivations: `shareholdings` is computed from the posted, non-`ISSUE`
`Share_Transactions` ledger (VP `C_MemberBase` logic); a member/class group
with net-zero balance is loaded with `is_current=false`. Share-class display
names are disambiguated with the VP class code when an entity has two classes
of the same name. Corporate shareholders carry `party_type='corporate'` in
`shareholdings`; in `share_transactions`/`share_certificates` a corporate holder
has `person_id=NULL` (those tables have no corporate-name column).

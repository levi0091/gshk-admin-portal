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

## Checkpoint C — contacts, charges, tasks, address history, filings, audit trail

Covers `contacts`, `charges`, `tasks`, `address_assignments` (+ the
`entities.registered_address_id` / `persons.residential_address_id`
backfill), `form_filings`, `audit_log` (`EventLog` + `RefStatus`), and the
`audit_form_filings` junction linking the two.

### Prerequisites

1. Checkpoints A and B already run (entities, persons, addresses, and
   share_classes populated in Supabase dev) — Checkpoint C resolves
   `entity_id`/`person_id`/`address_id` against those tables.
2. Alembic at head (`.venv\Scripts\alembic.exe upgrade head` from `backend/`)
   — includes migration `006` (adds `vp_source_key` to `audit_log` and
   `audit_form_filings`, plus the Checkpoint C partial-unique indexes).

### Running

```powershell
cd backend
.venv\Scripts\python.exe -m etl.run_checkpoint_c --dry-run   # validates contacts/charges/tasks/address_assignments/form_filings/audit_log; audit_form_filings + the address backfill need a real run (they resolve against this run's own writes)
.venv\Scripts\python.exe -m etl.run_checkpoint_c              # real run
```

### `audit_log` is insert-only — re-run semantics

`audit_log` is PBI-11's audit trail: **INSERT-only, never UPDATE or DELETE**.
It is loaded via `insert_rows_ignore_conflicts` (`ON CONFLICT (vp_source_key)
DO NOTHING`), not `upsert_rows`. The reconciliation report's `audit_log` line
reads `source=<rows produced this run>`, `loaded=<rows newly inserted this
run>`. On a first run against empty history these are equal; on a **re-run**
against already-imported Viewpoint history, `loaded` legitimately drops
towards 0 — that is **by design, not a failure**. Do not treat a re-run
`loaded < source` mismatch as a bug: reconcile against the DB's total
`audit_log` row count instead of expecting `loaded == source` on every
invocation.

`audit_form_filings`, in contrast, **is** a normal upsertable junction table
(`upsert_rows`, `ON CONFLICT DO UPDATE`) — a re-run can legitimately need to
fill in a previously-NULL `audit_log_id`/`form_filing_id` once the other side
resolves, so updates (not just first-inserts) are expected there.

### Address role codes (VP `RefAddress.AddrType` → `address_assignments.address_role`)

The VP `ADRT` reference table's codes are carried through verbatim as the
`address_role` value (no remapping):

| Code | Meaning |
|------|---------|
| `RO` | Registered Office |
| `RA` | Residential Address |
| `RC` | Correspondence |
| `BA` | Business Address |
| `MA` | Mailing Address |
| `AA` | Alt Residential Address |
| `AD` | Administration |
| `RB` | Business Registration |
| `S*` | Statutory register locations (various `S`-prefixed codes) |

### Primary address backfill

After `address_assignments` loads, `backfill_primary_addresses` runs two
`UPDATE ... FROM (SELECT DISTINCT ON ...)` statements:

- `entities.registered_address_id` ← the **current** (`cancelled_date IS
  NULL`) `RO`-role assignment for that entity, latest `effective_date` wins.
- `persons.residential_address_id` ← the **current** `RA`-role assignment
  for that person, latest `effective_date` wins.

This is the only source for those two FK columns — Viewpoint's own
`ContactAddrCode`/`ResAddress` shortcut columns are blank on every live row,
so the full `address_assignments` history is derived and then collapsed to
"whichever assignment is current and most recent" per entity/person. The
backfill only runs on a real run (it needs this run's `address_assignments`
writes) and is skipped, along with `audit_form_filings`, when `--dry-run` is
passed.

### `audit_form_filings` — linking audit history to form filings

Sourced from VP `EventsForm` (PK `EventNr` + `FQNumber`, both delivered as a
float/nvarchar pair from SQL Server). `vp_source_key` is `f"{int(EventNr)}:
{FQNumber}"`; `audit_log_id` resolves via the `EL:<int(EventNr)>` key format
Checkpoint C's own `EventLog` transform writes to `audit_log.vp_source_key`;
`form_filing_id` resolves via `form_filings.vp_source_key` (the raw
`FQNumber`). Both FKs are nullable in the target: if neither side resolves
the row is dropped and logged; if exactly one resolves the row is still
loaded with the other FK `NULL` (and logged); if both resolve it loads
clean. Because a later re-run of Checkpoint A/B/C could resolve a
previously-missing side, this table uses `upsert_rows`, not the insert-only
loader.

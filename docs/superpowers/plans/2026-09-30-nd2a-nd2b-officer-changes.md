# ND2A and ND2B Officer Changes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** File CR forms ND2A (appointment / cessation of directors and secretaries) and ND2B (change of officer particulars) from G-FlowDesk, through the same six-stage case workflow NAR1 uses, with CR's own PDF forms rendered accurately.

**Architecture:** ND2 cases are rows in `nar1_cases` distinguished by `form_code` (migration 050, already written and tested). A new services package `backend/services/officer_changes/` owns the change list, company rules, CR XML, signing, profile write-back and supporting documents; `backend/services/officer_change_form/` renders CR's ND2A/ND2B templates through NAR1's `appearance.bake`. Two routers mount under `/officer-changes`. The frontend adds one case page (`/officer-changes/:caseId`) plus entry points on the dashboard and both profiles.

**Tech Stack:** Python 3.12 · FastAPI · Supabase (PostgREST) · Alembic · pypdf + reportlab (via `services/nar1_form/appearance.py`) · pytest · Vite + React · Vitest + React Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-30-nd2a-nd2b-officer-changes-design.md` — read it before your task. Where this plan and the spec disagree, the spec wins.

**Already done (do not redo):** migration `backend/alembic/versions/050_officer_changes_nd2a_nd2b.py` and `backend/tests/test_migration_050.py`; the form-aware badge in `backend/services/nar1_case_status.py`; audit constants in `backend/services/audit_events.py` (`OFFICER_CHANGE_CODES`); dashboard columns in `backend/services/nar1_cases.py`; the `officer_change` document section; the two CR templates in `backend/services/officer_change_form/form/`.

## Global Constraints

- **Do not commit, stash, checkout, reset or run alembic.** Several implementers share this worktree at once. Touch only the files your task lists under **Files**; if you need a change in a file you do not own, put the request in your report instead of making it.
- Environment: `export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v20.20.2/bin:$PATH"`. Backend tests: `cd backend && uv run pytest -q -p no:cacheprovider <your test files>`. Frontend tests: `cd frontend && npm run test -- --run <your test files>`. Run only your own test files plus the existing test file of any existing module you modified — the full suites are run by the controller.
- The worktree has **no `.env`**. No test may reach Supabase, Resend, DNS or CR. Patch `get_supabase` / the service functions the way the neighbouring tests do (`backend/tests/conftest.py`).
- TDD: write the failing test, watch it fail, implement, watch it pass.
- Every endpoint is guarded by `require_permission(module, permission)` from `middleware/auth.py` with the permission in the spec §3 table. Every write route calls `audit_service.log_event()` before returning success, wrapped so a logging failure cannot fail the request. **Routers log audit events; the services in `officer_changes/` do not** (reused services that already log keep doing so).
- Never log, return or audit an e-Registry / e-Service password, its length or a hint of it.
- Services raise plain exceptions (`LookupError`, `ValueError`, or the task's own named exception); only routers raise `HTTPException`.
- Dates on the wire are `YYYY-MM-DD`; CR XML dates are `DD/MM/YYYY`. "Today" is Hong Kong's date.
- An address value anywhere in this feature is `{line1, line2, line3, city, state_region, postal_code, country}` — the shape `services/tpsi/forms/nar1_mapper._address` reads.
- `party_type` is `'individual' | 'corporate'`; `capacity` is `'director' | 'company_secretary'`; entry `kind` is `'cessation' | 'appointment' | 'change'`. No alternate directors anywhere.
- Frontend: brand tokens from the repo `CLAUDE.md` verbatim (Outfit; `--indigo #242C66`, `--carrot #F36C32`, …), existing classes first (`.card`, `.btn`, `.modal`, `.modal-footer`, `bw-*`/`bf-*`/`bc-*` badges). The wireframe is `/Users/tingy/Desktop/zenexflow/gshk-admin-portal/Wireframe/admin-portal-nd2/wireframe_v12.html` with screenshots in `/Users/tingy/Desktop/zenexflow/gshk-admin-portal/PRD/Pending/assets/nd2a-nd2b/S-*.png` (read-only, outside this worktree). Where the spec §1–§2 reverses the wireframe, the spec wins. Never put a button pair inside `.f-group`; every add/edit is a modal or drawer with a right-aligned footer.
- Match the surrounding code's comment density and naming. Comments say why, not what.
- Write your report to the path given in your dispatch and return only: status (`DONE` / `DONE_WITH_CONCERNS` / `BLOCKED`), files touched, one-line test summary, concerns.

## Review Focus

1. **An officer with no HKID and no passport, or no Chinese name.** The PDF and the XML must leave those boxes empty (XML: `NIL` only where CR's examples say so), never print `None`, and the PI sheet is omitted for a secretary with neither. Tested in Task 1/2 and Task 3.
2. **More officers than one page holds.** Three cessations, three natural-person appointments and two body-corporate appointments on one ND2A must yield Sheets A×2, B×2, C×1, one PI sheet per natural person, and page-3 counts that match. Tested in Task 1.
3. **A profile edited, then edited back.** The ND2B pending change must disappear; and an entry already on a case must lose the item on the next load without losing the effective dates typed for the items that remain. Tested in Task 4 and Task 5.
4. **Filing succeeded but a write-back step failed.** A CR receipt must never be reported as a failed filing: apply/document-filing errors are returned in the response and the case is still filed. Re-running must not duplicate an appointment or a document. Tested in Task 6 and Task 8.
5. **A joiner with no stored e-Registry credential.** e-Sign must be unavailable with the person named; nothing may call CR; the manual route must still work end to end without any CR call. Tested in Task 3 (`consent_plan`), Task 8 and Task 10.

---

## Shared contracts

These shapes cross task boundaries. They are binding; the scaffold (Task 0) writes them into stub modules whose signatures and docstrings every later task keeps.

### C-1 Particulars snapshot (produced by Task 4; read by Tasks 3, 5, 9)

```python
PERSON = {
  "party_type": "individual",
  "name_en": {"surname": str, "given_names": str},
  "name_zh": str,                       # "" when none
  "alias": {"alias_en": str, "alias_zh": str},
  "residential_address": ADDRESS | None,
  "correspondence_address": ADDRESS | None,   # None = same as residential
  "email": str,
  "hkid": str,                          # full number as stored, "" when none
  "passport": {"number": str, "issuing_country": str} | None,
  "tcsp": {"licence_no": str, "exemption_reason": str},
}
CORPORATE = {
  "party_type": "corporate",
  "name": {"name": str, "name_zh": str},
  "address": ADDRESS | None,            # its registered office
  "email": str,
  "tcsp": {"licence_no": str, "exemption_reason": str},
}
```

### C-2 ND2B item (stored in `officer_change_entries.items`)

```python
ITEM = {"key": str, "cr_item": str, "label": str,
        "old": <snapshot value>, "new": <snapshot value>,
        "old_text": str, "new_text": str,          # for the staff screen
        "effective_date": "YYYY-MM-DD" | None, "omitted": bool}
```

| `key` | `cr_item` | label | applies to |
|---|---|---|---|
| `name_zh` | a | Name in Chinese | person |
| `name_en` | b | Name in English | person |
| `alias` | c | Alias | person |
| `residential_address` | d | Residential address | person, **director only** |
| `correspondence_address` | e | Correspondence address | person |
| `email` | f | Email address | person |
| `hkid` | g | Hong Kong identity card number | person |
| `passport` | h | Passport | person |
| `tcsp` | i | TCSP licence | **secretary only**, person or corporate |
| `name` | a | Name | corporate |
| `address` | b | Address | corporate |
| `email` | c | Email address | corporate |

Correspondence rule: the *effective* correspondence address is `correspondence_address` when set, else `residential_address`. A baseline whose `correspondence_address` is `None` therefore produces item `e` whenever the residential address changes; a baseline with an explicit one never produces `e` (no editor exists for it — spec B-15).

### C-3 HTTP API (implemented by Tasks 7–8; called by Tasks 9–11 through `frontend/src/components/officerChange/api.js`)

All under `/officer-changes`; JSON unless stated; every route that changes the case returns the **composite** (C-4). Errors: 400 bad input, 403 permission, 404 unknown case, 409 with `detail: {message, reason}` for a refused state (`case_closed`, `not_editable`, `wrong_form`, `rules_blocking`, `esign_unavailable`, `not_validated`, `already_filed`).

| Method + path | Body | Permission |
|---|---|---|
| `POST ""` | `{entity_id, form_code: "Nd2a"\|"Nd2b", entry?: EntryIn}` → 201 `{case: Composite, reused: bool}` | `officer_changes:write` |
| `GET /pending?entity_id=&person_id=` | → `{cases: [{id, case_no, form_code, case_type, workflow_status, entity_id, company_name, entries: [{id, kind, capacity, party_name, person_id, corporate_entity_id, officer_id}]}]}` | `officer_changes:read` |
| `GET /{id}` | → Composite | `officer_changes:read` |
| `PATCH /{id}` | `{signing_method?: "esign"\|"manual", signatory_capacity?: str, restart_verification?: true}` | `officer_changes:write` |
| `POST /{id}/entries` | EntryIn | `officer_changes:write` |
| `PATCH /{id}/entries/{entry_id}` | EntryPatch | `officer_changes:write` |
| `DELETE /{id}/entries/{entry_id}` | — | `officer_changes:write` |
| `POST /{id}/entries/{entry_id}/kyc` | `{cleared: bool}` | `officer_changes:write` |
| `POST /{id}/entries/{entry_id}/documents` | multipart `file`, `document_type_code` | `officer_changes:write` |
| `DELETE /{id}/documents/{doc_id}` | — | `officer_changes:write` |
| `GET /{id}/documents/{doc_id}/download` | → `{url}` | `officer_changes:read` |
| `GET /{id}/preview?audience=client\|staff` | → `application/pdf` | `officer_changes:read` |
| `GET /{id}/verification/recipients` | → `{recipients: [{person_id, name, email, role, reason}], reply_by_default, deadline}` | `officer_changes:read` |
| `POST /{id}/verification/send` | `{emails: [str], respond_by}` → the same response shape `POST /cases/{id}/verification/send` returns (`sent`, `failed`, `deliveries`, …) | `officer_changes:write` |
| `GET /{id}/verification/delivery` | → as `GET /cases/{id}/verification/delivery` | `officer_changes:read` |
| `POST /{id}/verification/response` | `{approved: bool, note?: str}` | `officer_changes:write` |
| `POST /{id}/validate` | — (e-Sign route) | `tpsi:write` |
| `POST /{id}/mark-checked` | — (manual route) | `officer_changes:write` |
| `POST /{id}/sign` | empty body; any key is a 400 | `tpsi:write` |
| `POST /{id}/signed-form` | multipart `file` (PDF) | `officer_changes:write` |
| `POST /{id}/submit` | `{confirm: true}` | `tpsi:submit` |
| `POST /{id}/receipt` | multipart `file` | `tpsi:submit` |
| `POST /{id}/record-filing` | `{receipt: {caseNo, transactionDate, transactionTime?, refNo?}, confirm: true}` | `tpsi:submit` |
| `POST /{id}/undo` | `{confirm: true}` | `tpsi:submit` |
| `POST /{id}/close` | `{reason: str}` | `officer_changes:write` |

CR status *Check now* is the existing `POST /tpsi/cases/{case_id}/refresh-status`; the audit tab is the existing `GET /cases/{id}/audit`.

`EntryIn` = `{kind, party_type, person_id? | corporate_entity_id?, officer_id?, capacity, effective_date?, cessation_reason?, correspondence_same_as_residential?, correspondence_address?, section5_confirmed?, consent_person_id?, consent_capacity?}`. `EntryPatch` = any of those except `kind` and the party, plus `items?: [{key, effective_date?, omitted?}]` (ND2B: only those two fields of an item are writable).

Person endpoints (Task 4): `GET /persons/{id}/eservice-credential` → `{configured, eservice_user_id, eservice_person_name, has_password, updated_at}` (`persons:read`); `PUT` `{eservice_user_id, eservice_person_name, password?}` and `DELETE` (`persons:write`). `GET /persons/{id}/particulars-changes` → `{changes: [{entity_id, company_name, capacity, officer_id, items: [ITEM without dates], open_case: {id, case_no} | null}]}` (`persons:read`); `POST /persons/{id}/particulars-changes/dismiss` → `{dismissed: int}` (`persons:write`). The same two `particulars-changes` routes exist under `/companies/{id}` for a body corporate officer (`companies:read` / `companies:write`).

### C-4 Composite (built by Task 5 `cases.composite`)

Everything `services/nar1_cases.composite(case_id)` returns, plus:

```python
{
 "form_code": "Nd2a" | "Nd2b", "case_type": "ND2A" | "ND2B",
 "editable": bool,                      # entries may change: not yet sent to the client, not closed
 "deadline": {"date": str | None, "days": int | None, "overdue": bool, "basis": str},
 "reply_by_default": str | None,
 "entries": [ENTRY],
 "rules": {"summary": str, "checks": [{"code": str, "ok": bool, "text": str}], "blocking": bool},
 "route": {"esign_available": bool, "reasons": [str], "selected": "esign" | "manual" | None,
           "default": "esign" | "manual",
           "consents": [{"entry_id", "bean_id", "signer_person_id", "signer_name",
                         "eservice_user_id", "ready": bool, "reason": str | None, "signed_at": str | None}]},
 "officers": [{"officer_id", "role", "party_type", "person_id", "corporate_entity_id",
               "name", "appointed_date", "date_of_death": str | None,
               "pending": bool}],                                # current officers, for the pickers
 "documents": [DOC],
 "signatory": {"name": str, "is_corporate": bool, "capacities": [str],
               "default_capacity": str, "selected_capacity": str | None},
 "profile_changes": [{"entry_id", "text", "target": {"kind": "person" | "company", "id", "name"}}],
 "problems": [str],                     # why the CR form cannot be built yet; [] when it can
 "filing": {"id", "stage", "validated_at", "signed_at", "submitted_at"} | None,
 "applied_at": str | None, "undone_at": str | None,
}
ENTRY = {<every officer_change_entries column>,
         "party": {"name": str, "name_zh": str, "email": str, "profile_path": str, "missing": [str]},
         "consent_person_name": str | None,
         "summary": str,                # "Director · ceases 30 Sep 2026 · Resignation"
         "eservice": {"configured": bool, "has_password": bool, "eservice_user_id": str | None} | None,
         "documents": [DOC]}
DOC = {"id", "entry_id", "document_type_code", "type_label", "file_name", "uploaded_at",
       "destination": {"owner_kind": "person" | "entity", "owner_id", "name"},
       "filed": bool, "filed_document_id": str | None, "filed_at": str | None}
```

---

### Task 0: Scaffold the contracts

**Files:**
- Create (stubs, each later replaced by its owner): `backend/services/officer_change_form/__init__.py`; `backend/services/officer_changes/{prepare,signing,particulars,eservice,cases,rules,deadlines,recipients,emails,documents,apply}.py`; `frontend/src/components/officerChange/{StageClientVerification,StageDataVerification,StageSigning,StageSubmission,StageConfirmation,StageCrStatus,SupportingDocuments,ProfileChangesList}.jsx`
- Create (complete): `frontend/src/components/officerChange/api.js`, `frontend/src/components/officerChange/api.test.js`

- [ ] **Step 1:** For every function named under **Produces** in Tasks 1–6 below, write a stub in its module with the exact signature, a docstring stating the contract, and a body of `raise NotImplementedError("Task N")`. Exceptions and constants named there are defined for real.
- [ ] **Step 2:** Write each frontend stub as `export default function <Name>() { return null }`.
- [ ] **Step 3:** Write `api.js` exporting `officerChangeApi`, one method per row of C-3, built on `frontend/src/lib/api.js` (read it for the multipart and blob conventions): `create, pending, get, patch, addEntry, updateEntry, removeEntry, setKyc, uploadDocument, removeDocument, documentUrl, preview, recipients, send, delivery, recordResponse, validate, markChecked, sign, uploadSignedForm, submit, uploadReceipt, recordFiling, undo, close, refreshCrStatus`. `api.test.js` asserts each method's verb and path against a mocked `lib/api`.
- [ ] **Step 4:** `cd backend && uv run python -c "import services.officer_changes.cases, services.officer_changes.prepare, services.officer_changes.signing, services.officer_changes.particulars, services.officer_changes.eservice, services.officer_changes.rules, services.officer_changes.deadlines, services.officer_changes.recipients, services.officer_changes.emails, services.officer_changes.documents, services.officer_changes.apply, services.officer_change_form"` exits 0; `npm run test -- --run src/components/officerChange/api.test.js` passes.

---

### Task 1: ND2A PDF renderer and the shared form kit

**Files:**
- Create: `backend/services/officer_change_form/{__init__,kit,nd2a_map,nd2a}.py`
- Test: `backend/tests/officer_changes/test_form_kit.py`, `test_nd2a_form.py`, `test_nd2a_geometry.py`
- Read: `backend/services/nar1_form/{fill,appearance,field_map}.py`, `backend/tests/test_nar1_specimen_geometry.py`, the widget dump `<scratchpad>/nd2-widgets.txt`, `backend/tests/fixtures/cr-examples/validateForm/validate_ND2A*.xml`

**Interfaces:**
- Consumes: `nar1_form.appearance.bake(pdf_bytes, *, sizes, regular, centred, faces, strike, highlight)`, `nar1_form.fill.parse_validated_xml`, `fill.signature_date`, `fill.DEFAULT_PRESENTER`.
- Produces (in `officer_change_form/__init__.py`):
  - `class FormFillError(RuntimeError)`
  - `render(form_code: str, form_xml: str, *, section5_confirmed: bool = False, submitted_on="", presenter: dict | None = None, public_only: bool = False) -> bytes` — the flat PDF. `form_xml` is CR's form model as `form_xml.build` emits it or as CR returns it validated.
  - `render_fields(form_code, form_xml, **same) -> bytes` — before baking; tests only.
  - `page_plan(form_code, form_xml, *, public_only=False) -> list[dict]` — `[{"sheet": "1"|"2"|"3"|"A"|"B"|"C"|"PI", "template_page": int, "subject": str}]` in output order.
  - `kit.py`: the template-agnostic mechanics both forms share — add a template page with a per-page widget suffix, fill, bake with a form's size/centred/regular sets, split a `DD/MM/YYYY` date into its three boxes, strike a dropdown alternative, tick a checkbox.

**Requirements**
- Output pages: template pages 1–3 always; Continuation Sheet A (template p4) per cessation after the first; Sheet B (p5) per natural-person appointment after the first; Sheet C (p6) per body-corporate appointment after the first; one PI-ND2A (p7) per natural person appointed, omitted for a company secretary with neither HKID nor passport; the notes pages 8–17 never. Order: 1, 2, 3, A…, B…, C…, PI…. `public_only=True` drops PI sheets but page 3's count boxes still state how many the filed form carries.
- Typography is NAR1's, asserted by measurement in `test_nd2a_geometry.py` the way `test_nar1_specimen_geometry.py` does: every value Tinos Bold 10pt; the BR number in each page header 14pt; the company name 12pt; the presenter's block 10pt **regular**; left-aligned values start 9.4pt inside the widget rect; a single line's baseline is `y0 + (h − 0.72 × size) / 2`; centred only the header BRN, company name, date cells, identity-number boxes and page/sheet counts. CJK runs fall back to the embedded Noto face as NAR1's do. Never read `/DA` or `/Q` from the template.
- Public pages print **partial** identity numbers exactly as the XML carries them; the PI sheet prints the full HKID with its check digit in its own box, or the passport and issuing country, and the residential address.
- The signature Date box is `fill.signature_date(submitted_on)` — empty until filed. The presenter's Reference is `ND2A/<year of the earliest change>/<company name>`, shortened on a word boundary as NAR1's is.
- `section5_confirmed` ticks Section 5's box; nothing in the XML carries it.
- The output is flat: no AcroForm, no widget. `_assert_nothing_dropped` re-counts cessations, appointments and PI sheets in the output against the XML and raises `FormFillError` on a mismatch.
- A value that does not fit its box is shrunk by `appearance.layout` as NAR1 does; never truncated silently.

- [ ] **Step 1:** Build the widget→field map. Render a debug copy of each template page with every widget filled with its own short name, rasterise it (`uv run --with pymupdf python …`, 150 dpi) and **look at each PNG** to pair every widget with the printed label beside it. Record the map in `nd2a_map.py` as named constants per section (page 1 header/section 1/section 2 cessation; page 2 section 3; page 3 section 4, counts, section 5, signature, presenter; sheets A, B, C; PI), with the CR XML field each widget takes.
- [ ] **Step 2:** Write failing tests. `test_nd2a_form.py`: for each of the ten `validate_ND2A*.xml` fixtures, `page_plan` returns the expected sheets and `render` returns a PDF with that many pages, no `/AcroForm`, and the fixture's company name, BR number and officer name extractable as text. Review Focus 1 and 2 as written. `test_nd2a_geometry.py`: font name and size of every drawn span by section, left inset, baseline, centred fields (use the text-extraction approach of the NAR1 geometry test).
- [ ] **Step 3:** Implement `kit.py`, `nd2a.py`, `__init__.render/render_fields/page_plan` (the `Nd2b` branch raises `NotImplementedError("Task 2")`).
- [ ] **Step 4:** Tests pass. Then render every fixture plus one overflow case (3 cessations, 3 natural appointments, 2 corporate) to `<scratchpad>/pdf-check/nd2a-*.pdf`, rasterise every page and inspect each PNG against the blank template: every value in its own box, nothing overlapping a label, nothing clipped, struck alternatives correct. Fix what you see; list in the report what you inspected.

---

### Task 2: ND2B PDF renderer

**Files:**
- Create: `backend/services/officer_change_form/{nd2b_map,nd2b}.py`; modify `backend/services/officer_change_form/__init__.py` (the `Nd2b` branch only)
- Test: `backend/tests/officer_changes/test_nd2b_form.py`, `test_nd2b_geometry.py`
- Read: Task 1's `kit.py` and `nd2a.py`; `validate_ND2B*.xml` fixtures

**Interfaces:**
- Consumes: Task 1's `kit` and the `render` / `render_fields` / `page_plan` signatures.
- Produces: the `Nd2b` behaviour of those three functions.

**Requirements**
- Output pages: template pages 1–3 always (p1 section 1 and 2A; p2 section 2B; p3 section 3, counts, signature); Continuation Sheet A (p4) per natural person after the first; Sheet B (p5) per body corporate after the first; one PI-ND2B (p6) per natural person whose identity number or residential address changed; notes pages never. `public_only` as Task 1.
- Part A prints the officer **as registered** (the XML's existing-particulars fields, partial ID); Part B prints only the items the XML carries, each with its own effective date.
- Everything under Task 1's typography, flatness, signature-date, presenter (`ND2B/<year>/<company>`) and `_assert_nothing_dropped` requirements applies unchanged.

- [ ] **Step 1:** Widget→field map by the same visual method as Task 1 Step 1, in `nd2b_map.py`.
- [ ] **Step 2:** Failing tests: the four `validate_ND2B*.xml` fixtures render with the right page plan and extractable values; two natural persons + two corporates on one form yield Sheet A×1 and Sheet B×1 with matching counts; an ID-number change yields a PI sheet and an email-only change does not; geometry as Task 1.
- [ ] **Step 3:** Implement. **Step 4:** Tests pass; render to `<scratchpad>/pdf-check/nd2b-*.pdf`, rasterise and inspect every page as in Task 1 Step 4.

---

### Task 3: CR XML, mappers and signing

**Files:**
- Create: `backend/services/officer_changes/{form_xml,nd2a_mapper,nd2b_mapper,source,prepare,signing}.py`
- Test: `backend/tests/officer_changes/test_form_xml.py`, `test_nd2a_mapper.py`, `test_nd2b_mapper.py`, `test_prepare.py`, `test_signing.py`
- Read: `backend/services/tpsi/forms/{nar1,nar1_mapper,nar1_source}.py`, `backend/services/nar1_prepare.py`, `backend/services/tpsi/{filings,crypto,soap}.py`, all 14 ND2 fixtures under `backend/tests/fixtures/cr-examples/`, the worksheet's `ND2A`/`ND2B` sheets, `<scratchpad>/TPSI.html` (CR's reference signing program — `createEFormSignatureV2`), `<scratchpad>/tpsi.txt`

**Interfaces:**
- Consumes: C-1, C-2; `nar1_mapper._address`, `_signatory_block`, `_partial_hkid`, `_partial_passport`, `MappingError`; `nar1_source.load_entity_graph`; `eservice.metadata_for(person_ids) -> dict[str, dict]` and `eservice.load_for_signing(person_id) -> tuple[str, str, str] | None` (Task 4); `crypto.build_pin_sign(eform_xml, user_id, eservice_password, cr_public_key_pem, uri=…, sign_id=…)`.
- Produces:
  - `form_xml.build(form_code: str, data: dict) -> str` (elements in CR's worksheet order) and `form_xml.validate(form_code, data) -> list[str]` (mandatory + max length from the worksheet).
  - `nd2a_mapper.map_case(graph: dict, entries: list[dict], *, signatory_capacity: str | None = None, signing_identity: dict | None = None) -> dict`; `nd2b_mapper.map_case(...)` same signature. Pure; raise `MappingError` listing every problem.
  - `source.load_graph(entity_id: str, entries: list[dict]) -> dict` (async) — `load_entity_graph` plus every entry's party, their identity documents and addresses, and `graph["eservice"] = metadata_for(...)`.
  - `prepare.build_form_xml(case: dict, entries: list[dict], *, signing_identity: dict | None = None) -> str` (async; raises `MappingError`).
  - `prepare.mapping_problems(case, entries) -> list[str]` (async; `[]` when buildable; never raises).
  - `prepare.consent_plan(case, entries) -> list[dict]` (async) — one row per **new director** appointment in entry order, shaped as `route.consents` in C-4, `bean_id` `"S1"`, `"S2"`, …. `ready` only when the signer has a stored e-Registry user id, name and password. For a body-corporate director the signer is `consent_person_id`. Empty for every ND2B.
  - `signing.sign(client, filing_id: str, *, signatory_user_id: str, eservice_password: str, consents: list[dict]) -> dict` — `consents` is `[{"bean_id", "user_id", "password"}]`.
  - `signing.submit(client, filing_id: str, *, confirm: bool) -> dict` — the filing row with its receipt.

**Requirements**
- Element-for-element parity with CR's examples: for each of the 14 `validate_ND2*.xml` fixtures, build a graph + entries that describe the fixture and assert `form_xml.build(map_case(...))` yields the same element names, order and text under the form model (ignoring the values CR fills after validation).
- ND2A: cessation beans carry partial identity numbers, `rsnCes` (`R`/`D`), derived `dirAfterCesInd` `N` for a director; appointment beans carry the full `indvHkidNo` + `indvHkidChkDgt` or `indvPptNo` + `indvPptIssCtry` (`NIL` exactly where CR's examples use it), correspondence address = residential unless the entry says otherwise, `dirBeforeApptInd` `N` for a director and absent for a secretary; a director appointment carries `id="S<n>"`, `selectPersonId`/`selectPersonName` from the signer's stored e-Registry account; a body-corporate director carries `associatedPersonId/Name/CapacityDesc`, `selectAssoBrNo`, `selectPersonName`.
- ND2B: Part A from `entry["registered"]` (C-1, partial ID); Part B from `entry["items"]` where `omitted` is false, each with its `effective_date`; an item with no date is a `MappingError` naming the officer and the item.
- The form-level signatory block is `_signatory_block` unchanged.
- `signing.sign`: refuse a finished/closed case exactly as `filings.sign` does; build one `PinSign` per consent with `uri="#S<n>"` whose digest is over that bean as an XMLSerializer emits it (namespace injected the way `filings._extract_eform` does), inserted into `<cr:formDataSignatures>`; then the overall `#eForm` signature **last**; one `verifyPinSigning{Code}` call; store the result and stage as `filings.sign` does. It must **not** apply `filings.declared_signatory_id`'s mismatch check to a bean-level `selectPersonId`.
- `signing.submit`: requires `confirm is True` and stage signed; refuses a closed/finished case; performs whatever NAR1's chain performs between signing and the receipt (read `routers/tpsi.py` and `filings.submit` — including the e-Drive upload if the stage machine needs it), but makes **no balance read and no return-date or NAR1 drift check** — ND2A/ND2B are free and have no return date; writes the receipt back as `filings._write_back_receipt` does.
- No password in any log line, exception message or returned dict.

- [ ] **Step 1:** Failing tests for `form_xml` and both mappers against the fixtures, plus Review Focus 1 (no ID, no Chinese name) and 5 (`consent_plan` not ready, person named in `reason`).
- [ ] **Step 2:** Implement `form_xml`, `nd2a_mapper`, `nd2b_mapper`, `source`, `prepare`.
- [ ] **Step 3:** Failing tests for `signing` with a fake client: two consents produce `#S1`, `#S2` then `#eForm` in that order inside the right containers; digest input equals the serialised bean; one CR call; `submit` makes no balance call and refuses `confirm=False`.
- [ ] **Step 4:** Implement `signing`; all task tests pass; `uv run pytest -q -p no:cacheprovider tests/tpsi` still passes.

---

### Task 4: Particulars baseline, e-Registry credentials, profile endpoints

**Files:**
- Create: `backend/services/officer_changes/{particulars,eservice}.py`
- Modify: `backend/routers/persons.py`, `backend/routers/companies.py`
- Test: `backend/tests/officer_changes/test_particulars.py`, `test_eservice.py`, `backend/tests/test_persons_officer_changes.py`, `backend/tests/test_companies_officer_changes.py`
- Read: `backend/services/tpsi/{credentials,secrets}.py`, the person/identity-document/address routes in `routers/persons.py`, `PATCH /companies/{id}` and the registered-address route in `routers/companies.py`

**Interfaces:**
- Consumes: migration 050's `officer_cr_particulars` and `person_eservice_credentials`; `tpsi.secrets.encrypt/decrypt`; `audit_events.OFFICER_PARTICULARS_DISMISSED`, `PERSON_ESERVICE_CRED_SET`.
- Produces `particulars.py`:
  - `MAX_APPOINTMENTS_CAPTURED = 200`
  - `snapshot_person(person_id: str) -> dict`, `snapshot_corporate(entity_id: str) -> dict` (C-1)
  - `diff(baseline: dict, current: dict, *, capacity: str) -> list[dict]` — pure; C-2 items with `effective_date: None`, `omitted: False`
  - `describe(key: str, value) -> str`
  - `capture_before_edit(*, person_id: str | None = None, corporate_entity_id: str | None = None, user_id: str | None) -> int` — for every **current** appointment of that party with no baseline, store the snapshot as it stands now (`source='first_edit'`); returns how many; **never raises**; a party with more than `MAX_APPOINTMENTS_CAPTURED` current appointments captures nothing.
  - `baseline(entity_id: str, *, person_id=None, corporate_entity_id=None) -> dict | None`
  - `registered_view(entity_id, *, person_id=None, corporate_entity_id=None) -> dict` — the baseline, else the current snapshot
  - `pending_for_officer(entity_id, *, person_id=None, corporate_entity_id=None, capacity: str) -> list[dict]`
  - `pending_for_person(person_id) -> list[dict]`, `pending_for_corporate(entity_id) -> list[dict]` — the `changes` rows of C-3
  - `dismiss(*, person_id=None, corporate_entity_id=None, user_id) -> int` — baseline := current for every appointment that has one (`source='dismissed'`)
  - `set_baseline(entity_id, *, person_id=None, corporate_entity_id=None, particulars: dict, source: str, user_id) -> None`
  - `advance(entity_id, *, person_id=None, corporate_entity_id=None, items: list[dict], user_id) -> None` — write only the given items' `new` values into the baseline (`source='nd2b_filed'`)
- Produces `eservice.py`:
  - `metadata(person_id) -> dict` — `{configured, eservice_user_id, eservice_person_name, has_password, updated_at}`; `metadata_for(person_ids: list[str]) -> dict[str, dict]`
  - `save(person_id, *, eservice_user_id: str, eservice_person_name: str, password=UNSET, user_id) -> dict` (metadata; `UNSET` keeps the stored password)
  - `clear(person_id) -> bool`
  - `load_for_signing(person_id) -> tuple[str, str, str] | None` — `(user_id, person_name, password)` only when all three are stored
- Produces routes: the person and company endpoints listed under C-3.

**Requirements**
- `capture_before_edit` is called in every route that writes a tracked field, **before** the write: `PATCH /persons/{id}`, the identity-document create/update/delete routes, `PUT /persons/{id}/residential-address`, and for a body corporate `PATCH /companies/{id}` and its registered-address route. A failure inside it must not fail the edit.
- Editing a value and then restoring it yields no pending item (Review Focus 3): `diff` compares normalised values — trimmed, case-insensitive for names, address compared field by field with `None` and `""` equal.
- A person with no baseline has no pending change (spec B-10).
- The e-Registry password is Fernet-encrypted under `TPSI_CRED_KEY` and **no endpoint returns it, a hint of it or its length**. `PERSON_ESERVICE_CRED_SET` audit rows carry `eservice_user_id` only. A `PUT` with no stored password and no `password` is a 400.
- Route tests: happy path, 401/403, and one edge case each.

- [ ] **Step 1:** Failing tests for `diff` (each key of C-2's table, the correspondence rule both ways, capacity filtering, edit-and-restore) and the baseline lifecycle with a fake Supabase.
- [ ] **Step 2:** Implement `particulars.py`. **Step 3:** Failing tests then implementation for `eservice.py` (no plaintext in the stored row, `load_for_signing` `None` when incomplete).
- [ ] **Step 4:** Failing route tests, then the hooks and endpoints. **Step 5:** Task tests pass and `uv run pytest -q -p no:cacheprovider tests/test_persons*.py tests/test_companies*.py` still passes.

---

### Task 5: Case core — cases, rules, deadlines, recipients, email

**Files:**
- Create: `backend/services/officer_changes/{cases,rules,deadlines,recipients,emails}.py`
- Test: `backend/tests/officer_changes/test_cases.py`, `test_rules.py`, `test_deadlines.py`, `test_recipients.py`, `test_emails.py`
- Read: spec §2, §4, §5; PRD `/Users/tingy/Desktop/zenexflow/gshk-admin-portal/PRD/Pending/prd-nd2a-nd2b-officer-changes-2026-09-19.md` (company rules, email wording); `backend/services/nar1_cases.py`; `email_service.verification_email`

**Interfaces:**
- Consumes: `particulars.pending_for_officer`, `registered_view`, `snapshot_person` (Task 4); `eservice.metadata_for` (Task 4); `prepare.mapping_problems`, `prepare.consent_plan` (Task 3); `documents.list_for_case`, `apply.plan` (Task 6); `nar1_cases.composite`, `get_case`, `update_case`; RPC `next_case_no(p_prefix)`.
- Produces `cases.py`:
  - `FORM_CODES = ("Nd2a", "Nd2b")`; `class CaseRefused(Exception)` with `.reason: str` and `.message: str`
  - `create_case(*, entity_id: str, form_code: str, user_id: str) -> tuple[dict, bool]` — `(case, reused)`. Reuses the company's open case of that form that has not been sent to the client (spec B-12); otherwise inserts with `form_code`, `nar1_type` (`appointment_and_resignation` / `change_of_particulars`) and case number prefix `ND2A-<year>` / `ND2B-<year>`. Refuses a deleted company as `nar1_cases.create_case` does.
  - `get_case(case_id: str) -> dict` — `LookupError` when absent **or** when `form_code` is `Nar1`
  - `list_entries(case_id) -> list[dict]`
  - `editable(case: dict) -> bool`
  - `add_entry(case, payload: dict, *, user_id) -> dict`, `update_entry(case, entry_id, patch: dict, *, user_id) -> tuple[dict, dict]` (before, after), `remove_entry(case, entry_id) -> dict`, `set_kyc(case, entry_id, cleared: bool, *, user_id) -> dict` — the first three raise `CaseRefused("not_editable", …)` once sent; each recomputes `nar1_cases.filing_deadline`
  - `refresh_items(case, entries) -> list[dict]` — for every `change` entry on an editable case: re-diff against the profile, keep `effective_date` / `omitted` of items whose key survives, drop vanished items, append new ones, refresh `registered`; persist when anything moved
  - `composite(case_id: str, *, user: dict) -> dict` (async) — C-4
  - `open_cases_for(*, entity_id: str | None = None, person_id: str | None = None) -> list[dict]` — the `cases` rows of `GET /pending`
- Produces `rules.py`: `evaluate(officers_now: list[dict], entries: list[dict], *, company: dict) -> dict` — pure; the `rules` object of C-4.
- Produces `deadlines.py`: `hk_today() -> date`; `filing_deadline(entries) -> date | None` (earliest effective date among entries and non-omitted items, plus 15 days); `reply_by_default(deadline: date | None, today: date) -> date | None` (`max(deadline − 5 days, today + 2 days)`).
- Produces `recipients.py`: `default_recipients(case, entries) -> list[dict]` — ND2A: every current director and every incoming director; ND2B: the officer concerned; each `{person_id, name, email, role, reason}`, those with no address still returned with the reason.
- Produces `emails.py`: `changes_summary(entries) -> list[str]` and `officer_change_email(case: dict, entity: dict, entries: list[dict], *, approval_url: str | None, respond_by) -> tuple[str, str]` (subject, html).

**Requirements**
- Entry validation in `add_entry`/`update_entry` (raise `ValueError` naming the field): a cessation needs `officer_id` of a current officer of this company not already on the case, a date, and for a natural person a reason; an appointment needs a party not already a current officer in that capacity, a date, for a natural-person secretary nothing more, for a body-corporate **director** `consent_person_id` and `consent_capacity`; `correspondence_address` is required only when `correspondence_same_as_residential` is false; a `change` entry needs a current officer and takes its `items` and `registered` from `particulars`, never from the payload. ND2A cases take cessation/appointment only; ND2B cases take change only.
- Company rules (each a `check` with a stable `code`), evaluated on the officer list *after* the entries: at least one director; at least one director who is a natural person; a company secretary exists; a sole director is not also the secretary; a body-corporate secretary's sole director is not the company's sole director is **not** checked (no data). Breaches are `blocking`. Plus non-blocking notices: an effective date in the future; the filing deadline already passed.
- `changes_summary` and the email never print a full identity number or a home address (spec B-14): an address change reads "Residential address — changed"; a name change prints both names.
- The email is table-based with inline styles like `verification_email`, opens "Dear Client", is signed "Kind regards, Get Started HK Limited", names `email_service.RENEWAL_MAILBOX` for changes, prints the reply-by date through `email_service._deadline_text`, carries the Confirm button when `approval_url` is set and asks for a reply when it is `None`. It says the company's officers are changing and lists `changes_summary`; it does not say silence is consent — there is no auto-approval.
- `composite` never raises for a missing optional part: a failure inside `prepare`, `rules` or `documents` yields an entry in `problems`, not a 500.

- [ ] **Step 1:** Failing tests: `deadlines` (30 Sep change → 15 Oct; reply-by floor), `rules` (one test per check), `recipients`, `emails` (no ID number, no address line, button vs reply wording), `cases` (create/reuse, not-editable refusal, each validation rule, `refresh_items` for Review Focus 3).
- [ ] **Step 2:** Implement. **Step 3:** Task tests pass and `uv run pytest -q -p no:cacheprovider tests/test_nar1_cases*.py` still passes.

---

### Task 6: Supporting documents and profile write-back

**Files:**
- Create: `backend/services/officer_changes/{documents,apply}.py`
- Test: `backend/tests/officer_changes/test_documents.py`, `test_apply.py`
- Read: `backend/services/document_service.py`, `storage_service.py`, `routers/companies.py` `link_party` / `update_link`, how `company_secretaries` mirrors `entity_officers`

**Interfaces:**
- Consumes: `document_service.upload_document(owner_kind=…, owner_id=…, document_type_code=…, file_name=…, content=…, mime_type=…, title=…, user=…)`; `particulars.set_baseline`, `advance`, `snapshot_person`, `snapshot_corporate` (Task 4).
- Produces `documents.py`:
  - `SUPPORT_TYPES = ("resignation_letter", "board_resolution", "consent_to_act", "officer_change_support")`
  - `upload(case: dict, entry: dict, *, document_type_code: str, file_name: str, content: bytes, mime_type: str | None, user: dict) -> dict` (async) — stored under `officer-change/{case_id}/{entry_id}/…`; `ValueError` for another type, an empty file, or a case already filed
  - `list_for_case(case_id: str, entries: list[dict] | None = None) -> list[dict]` — C-4 `DOC` rows
  - `get(case_id: str, doc_id: str) -> dict | None`, `remove(case: dict, doc_id: str) -> dict` (`ValueError` once filed), `signed_url(doc: dict) -> str`
  - `destination(entry: dict) -> dict` — `{owner_kind: "person" | "entity", owner_id, name}`: the officer's own profile
  - `file_to_profiles(case: dict, entries: list[dict], *, user: dict) -> list[dict]` (async) — never raises; each row is a `DOC` plus `error: str | None`
- Produces `apply.py`:
  - `plan(case: dict, entries: list[dict]) -> list[dict]` — the `profile_changes` rows of C-4; pure given the entries' own `party` names
  - `apply_changes(case: dict, entries: list[dict], *, user: dict) -> dict` (async) — `{"applied": [...], "errors": [str]}`
  - `undo_changes(case: dict, entries: list[dict], *, user: dict) -> dict` (async) — same shape

**Requirements**
- `apply_changes`: a cessation sets the `entity_officers` row `is_current=false` with the cessation date and a `resignation_reason` from CR's reason, and the matching current `company_secretaries` row when the capacity is secretary; an appointment inserts an `entity_officers` row (and the `company_secretaries` mirror for a secretary), writes its id to `entry.officer_id`, and sets the appointment's baseline (`source='nd2a_filed'`, carrying the entry's correspondence address); a change writes nothing to the profile and calls `particulars.advance` with the non-omitted items. Each entry records exactly what was written in `entry.applied`; the case gets `changes_applied_at`.
- Idempotent (Review Focus 4): an entry with `applied` set is skipped; a second call after a partial failure finishes the rest and duplicates nothing.
- `undo_changes` reverses exactly what `applied` records — removes the appointment row it created, restores the ceased row, restores the prior baseline (`source='undo'`) — sets `changes_undone_at`, and clears `applied`.
- `file_to_profiles` files each unfiled case document through `document_service.upload_document` on `destination(entry)` and stores `filed_document_id`, `filed_document_version`, `filed_at`; a document already filed is skipped; one failure does not stop the rest.
- Every step catches per entry / per document and reports; nothing here raises after work has begun.

- [ ] **Step 1:** Failing tests: each entry kind applied and undone; partial failure then re-run; `file_to_profiles` idempotence and the per-document error row; `upload` refusals.
- [ ] **Step 2:** Implement. **Step 3:** Task tests pass.

---

### Task 7: Router — case, entries, documents, verification, public page

**Files:**
- Create: `backend/routers/officer_changes.py`
- Modify: `backend/main.py` (mount under `/officer-changes`), `backend/routers/public_approval.py`, `backend/routers/cases.py`, `backend/services/document_permissions.py`, `backend/jobs/auto_approve_nar1.py`
- Test: `backend/tests/test_officer_changes_router.py`, `backend/tests/test_officer_change_public_approval.py`, additions to the existing tests of each modified file
- Read: Tasks 1–6's modules; `routers/cases.py` verification routes (recipients, send, delivery, response), `_audit_target`, `_approval_link_base`, `_undeliverable`; `routers/public_approval.py`

**Interfaces:**
- Consumes: everything Tasks 1–6 produce.
- Produces: the C-3 rows from `POST ""` through `POST /{id}/verification/response`, plus `PATCH /{id}` and `POST /{id}/close`; helpers later imported by Task 8: `load_case(case_id) -> dict` (404 / wrong form), `refuse_if_closed(case)`, `audit(case, user, action_type, **kw)` (never raises), `respond(case_id, user) -> dict` (the composite).

**Requirements**
- Permissions and audit codes per spec §3. `OFFICER_CHANGE_ADDED/UPDATED/REMOVED`, `OFFICER_SUPPORT_DOC_UPLOADED/REMOVED`, `EMAIL_SENT`, `CLIENT_APPROVAL_RECEIVED`, `CASE_FIELD_UPDATED`, `NAR1_CASE_CLOSED` on the matching routes; audit rows use `entity_type="case"`, the case id as `entity_id` and the **company** id as `case_id`, as `_audit_target` does.
- `GET /{id}` calls `cases.refresh_items` first on an editable ND2B case.
- `GET /{id}/preview`: `audience=client` renders `public_only=True` (the default); `audience=staff` the full form. It renders from the latest filing's validated XML when one exists, else from `prepare.build_form_xml`; a `MappingError` is a 422 listing the problems.
- `POST /{id}/verification/send`: refuses when `rules.blocking` or when the form cannot be built (409 / 422); `respond_by` required and not in the past; one message per recipient with its own approval token (`nar1_approvals.issue(case_id=…, recipients=…, expires_at=<23:59:59 HK on respond_by>)`), the **public** PDF attached, `cc` and `reply_to` exactly as NAR1's send passes them, the DNS probe and malformed-address handling exactly as NAR1's (`failed` names both), `metadata.deliveries` written as NAR1's send writes it so the delivery route works unchanged. The non-production recipient lock is inside `email_service.send` and must not be bypassed.
- `PATCH /{id}` with `restart_verification: true` supersedes outstanding approval links and any live filing, clears the client's answer and makes the case editable again. `signing_method: "esign"` is refused (409 `esign_unavailable`) unless every `route.consents` row is ready.
- `POST /{id}/close`: reason required; refuses a filed case; supersedes filings and revokes links as NAR1's close does.
- Public page `GET/POST /public/officer-change-approval/{token}`: same guarantees as the NAR1 page (GET mutates nothing, no script, no credential asked), wording for an officer change, **Confirm** button; a token whose case is not ND2A/ND2B answers "no longer available", and the NAR1 page answers the same for an ND2 token. A confirmed token records the approval exactly as the NAR1 page does.
- `routers/cases.py`: `GET /cases` and `GET /cases/{id}` keep serving ND2 rows (the dashboard lists them; the page redirects on `form_code`); every NAR1 **write** route there refuses a non-`Nar1` case with 409 `reason: "wrong_form"`.
- `jobs/auto_approve_nar1.py` skips every case whose `form_code` is not `Nar1`.
- `document_permissions`: a document owned by an ND2 case (the signed form, the receipt) resolves to module `officer_changes`.
- Each route: happy path, 403, and an edge case.

- [ ] **Step 1:** Failing router tests (patching the service functions). **Step 2:** Implement the router and mount it. **Step 3:** Failing tests then changes for the public page, `cases.py` guards, the job and `document_permissions`. **Step 4:** Task tests and the existing tests of every modified file pass.

---

### Task 8: Router — validate, sign, submit, record, undo

**Files:**
- Create: `backend/routers/officer_change_filing.py`
- Modify: `backend/main.py` (mount under `/officer-changes`)
- Test: `backend/tests/test_officer_change_filing_router.py`
- Read: Task 7's router; `routers/tpsi.py` (how a CR client is built, how `TpsiError` kinds map to HTTP, the sign route's credential loading and its refusal of body keys); `routers/cases.py` manual-sign / manual-receipt / manual-submit

**Interfaces:**
- Consumes: Task 7's `load_case`, `refuse_if_closed`, `audit`, `respond`; `prepare.build_form_xml`, `prepare.consent_plan`, `signing.sign`, `signing.submit` (Task 3); `filings.create_filing`, `filings.rebuild_draft`, `filings.validate`; `eservice.load_for_signing` (Task 4); `tpsi.credentials.load_eservice`, `load_signatory_identity`; `documents.file_to_profiles`, `apply.apply_changes`, `apply.undo_changes` (Task 6); `document_service.upload_document`; `nar1_cases.validate_receipt`-style checks for the manual receipt.
- Produces: the C-3 rows `validate`, `mark-checked`, `sign`, `signed-form`, `submit`, `receipt`, `record-filing`, `undo`.

**Requirements**
- Every route first refuses a closed case and a case the client has not approved (409).
- `validate` (e-Sign route only; 409 `esign_unavailable` otherwise): build the XML with the signed-in user's signing identity, create or rebuild the filing (`form_code` `Nd2a`/`Nd2b`, `nar1_case_id` = the case), call `filings.validate`; CR faults come back in the shape `routers/tpsi.py` returns for NAR1 so the existing `FaultPanel` renders them.
- `mark-checked` (manual route): sets `data_checked_at/_by`; **no CR call**.
- `sign`: empty body — any key is a 400 that does not echo the value; loads the user's own e-Service credential (409 sending them to CR Credentials when absent); loads each consent's credential with `eservice.load_for_signing`, refusing 409 `esign_unavailable` naming the person when one is missing; calls `signing.sign`; stamps `consent_signed_at` on each consenting entry; audits `OFFICER_CONSENT_SIGNED` per consent (person and e-Registry user id only).
- `signed-form`: a PDF stored on the **company** as document type `nd2a`/`nd2b`, pointed to by `nar1_cases.manual_signed_document_id` (+ version) exactly as NAR1's manual-sign does; audits `OFFICER_SIGNED_FORM_UPLOADED`. It does not advance anything else.
- `submit`: `confirm` must be `true`; audits `TPSI_SUBMISSION_ATTEMPTED` before and `…_SUCCESS` / `…_FAILED` after; on success runs `apply.apply_changes` then `documents.file_to_profiles`, audits `OFFICER_CHANGES_APPLIED`, and returns the composite plus `{"write_back": {"errors": [...]}, "documents_filed": [...]}`. **A failure after CR's receipt never turns the response into an error** (Review Focus 4).
- `receipt` stores CR's receipt on the **case**; `record-filing` requires `confirm`, the signed form already uploaded, `caseNo` and `transactionDate` (`DD/MM/YYYY` or `YYYY-MM-DD`, not in the future), writes `manual_receipt` and `manual_submitted_at` through `nar1_cases.claim_manual_submission` so a double click cannot file twice, audits `OFFICER_FILING_RECORDED`, then runs the same write-back as `submit`.
- `undo`: only on a filed case whose `cr_doc_status_code` is a rejection and whose changes are applied and not undone; audits `OFFICER_CHANGES_UNDONE`.
- Each route: happy path, 403, and an edge case; one test proves the manual route reaches filed with the CR client never constructed (Review Focus 5).

- [ ] **Step 1:** Failing tests. **Step 2:** Implement and mount. **Step 3:** Task tests pass; `uv run pytest -q -p no:cacheprovider tests/test_officer_changes_router.py` still passes.

---

### Task 9: Frontend — case page, Changes card, drawers, Client Verification

**Files:**
- Create: `frontend/src/pages/OfficerChangeCasePage.jsx` (+ `.test.jsx`); `frontend/src/components/officerChange/{workflow.js, ChangesCard.jsx, CessationDrawer.jsx, AppointmentDrawer.jsx, ParticularsChangeCard.jsx, RulesPanel.jsx, StageClientVerification.jsx, officerChange.css}` each with a co-located test
- Modify: `frontend/src/App.jsx` (route `/officer-changes/:caseId`), `frontend/src/pages/CaseWorkflowPage.jsx` (redirect when the loaded case's `form_code` is `Nd2a`/`Nd2b`), `frontend/src/components/officerChange/api.js` if a method is missing
- Read: wireframe + screenshots S-08…S-13, S-20, S-24; `pages/CaseWorkflowPage.jsx`, `components/case/{CaseStepper,StageClientVerification,RecipientPicker,PdfPreview,VerificationDeliveryModal,workflow.js}`; `components/LinkPartyModal.jsx`

**Interfaces:**
- Consumes: `officerChangeApi` (Task 0), C-4; the five stage components of Task 10 by default import from `components/officerChange/`.
- Produces: the page; `workflow.js` exporting `STAGES`, `stageIndexFor(composite) -> number`, `stageDone(composite, i) -> bool`, `stageTone(composite)`; every stage component receives exactly `{ data, reload, can, goTo }` where `data` is the composite, `reload(next?)` replaces it with a returned composite or refetches, `can = {write, tpsiWrite, tpsiSubmit}`, `goTo(stageIndex)`.

**Requirements**
- Same header, stepper, badges, Close-case and audit tab as the NAR1 case page; six stages named as spec §5. The page opens on `stageIndexFor(data)`; a stage later than that is not reachable.
- Changes card (ND2A): two columns, *Leaving* and *Joining*, each row the entry's `summary`, a missing-items warning linking to `party.profile_path`, edit and remove (remove asks first). *Add cessation* / *Add appointment* open drawers carrying only the inputs of spec §2: cessation — officer (from `data.officers`, those already `pending` disabled), reason (pre-set to *Deceased* when the officer has a `date_of_death`, else *Resignation / Others*; not asked for a body corporate), date; appointment — person or body corporate picker (search the existing `/persons` and `/companies` list endpoints as `LinkPartyModal` does), capacity, date, the "Correspondence address is the same as the residential address" tick (on by default; the five address boxes appear only when unticked), Section 5 tick for a natural-person secretary only, *Consent signed by* (person + capacity) for a body-corporate director only. Read-only profile particulars are shown, never editable.
- ND2B card (`ParticularsChangeCard`): per officer, a read-only list of changed items `old_text → new_text`, one effective-date input per item, and *Omit* (confirm dialog: the change stays on the profile and stays pending). An officer with no pending change shows "No changes on the profile since CR was last told" with a link to the profile. *Add officer* picks from `data.officers`.
- `RulesPanel` lists `data.rules.checks`; a blocking breach disables *Send to client* and says why beside the button.
- Client Verification: preview of the public PDF (`PdfPreview`), recipients as chips (`RecipientPicker`), mandatory reply-by date pre-filled from `reply_by_default`, *Send to client* opening `VerificationDeliveryModal`; after sending, the recorded answer, *Record the client's answer* and *Restart verification* (confirm). No mention of auto-approval.
- `data.editable === false` makes the card read-only with the reason.
- Follow the frontend-design skill: the one memorable element on this page is the Leaving / Joining board; everything else stays as quiet as the NAR1 page.

- [ ] **Step 1:** Failing tests: page loads and shows the stepper and badge; drawers show exactly the spec §2 inputs per capacity/party; the correspondence boxes appear only when unticked; omit asks for confirmation; blocking rule disables send; read-only when not editable; `CaseWorkflowPage` redirects an ND2 case.
- [ ] **Step 2:** Implement. **Step 3:** Task tests and `src/pages/CaseWorkflowPage.test.jsx` pass.

---

### Task 10: Frontend — Data Verification through CR Status

**Files:**
- Create (replacing Task 0's stubs): `frontend/src/components/officerChange/{StageDataVerification,StageSigning,StageSubmission,StageConfirmation,StageCrStatus,SupportingDocuments,ProfileChangesList}.jsx` each with a co-located test; `frontend/src/components/officerChange/officerChangeStages.css`
- Read: wireframe + screenshots S-14…S-19; `components/case/{StageDataVerification,StageSigning,StageSubmission,StageConfirmation,StageCrStatus,FaultPanel,RefusalDetail,CheckRow}.jsx`

**Interfaces:**
- Consumes: `officerChangeApi`; props `{ data, reload, can, goTo }` (Task 9); C-4.
- Produces: the five stage components and the two shared lists.

**Requirements**
- **Data Verification.** One block per joiner and leaver: KYC tick (joiners), `SupportingDocuments` (type picker of the four support types, upload, list, remove), and for a new director the e-Registry state from `entry.eservice` with a link to the profile when missing. Signing capacity select from `data.signatory.capacities`. Route selector: *e-Sign* (disabled with `data.route.reasons` listed when unavailable) / *Manual (CR portal)*. e-Sign → **Validate with CR Portal** (`tpsiWrite`), faults through `FaultPanel`; manual → **Mark as checked**.
- **Signing.** e-Sign: the list of consent signatures to be applied (`data.route.consents`, who and from which e-Registry ID) and one **Apply signatures** button (`tpsiWrite`); no password field anywhere. Manual: upload the signed PDF; **ND2A shows no download button** (spec §5, answer 10) and says the form is prepared on CR's portal; ND2B keeps *Download form*. After the upload the stage **stays**, showing the uploaded file and a deliberate **Continue to Submission** button.
- **Submission.** `ProfileChangesList` of `data.profile_changes` in the future tense, and the supporting files grouped by destination profile ("will be saved to …"). e-Sign: two-step confirm then **File with CR** (`tpsiSubmit`). Manual: CR receipt form — CR case number, transaction date (both required), transaction time, CR document reference, receipt upload — then **Record filing** behind a confirm (`tpsiSubmit`). A `write_back.errors` list in the response is shown as a warning on a filed case, never as a failure.
- **Confirmation.** Receipt, *Profile updated* list (past tense, links), *Supporting documents saved* list with links to each profile.
- **CR Status.** CR's status badge and *Check now* as NAR1's; on a rejection with changes applied, **Undo profile update** (confirm, `tpsiSubmit`).
- Without the needed permission a control is absent or disabled with the reason, as the NAR1 stages do.

- [ ] **Step 1:** Failing tests per stage: route selector disabled with reasons; ND2A manual has no download button and ND2B has one; upload does not advance, Continue does; receipt form requires the two fields; write-back warning on a filed case; undo only on a rejection.
- [ ] **Step 2:** Implement. **Step 3:** Task tests pass.

---

### Task 11: Frontend — entry points on the dashboard and both profiles

**Files:**
- Modify: `frontend/src/components/NewCaseModal.jsx`, `CasesPane.jsx`, `pages/DashboardPage.jsx`, `pages/CompanyProfilePage.jsx`, `pages/PersonProfilePage.jsx`, `pages/RoleManagementPage.jsx`, `lib/navigation.js`, `lib/screenCapabilities.js`, and each one's existing test
- Create: `frontend/src/components/officerChange/{EServiceCredentialCard.jsx, ParticularsChangeAlert.jsx, ReportChangeMenu.jsx, PendingChangeChip.jsx, entryPoints.css}` each with a co-located test
- Read: wireframe + screenshots S-05, S-06, S-07, S-21, S-21b; `pages/CrCredentialsPage.jsx` (credential form conventions)

**Interfaces:**
- Consumes: `officerChangeApi.create`, `.pending`; the person and company endpoints of C-3 through `lib/api`.
- Produces: links to `/officer-changes/:id` for every ND2 case row.

**Requirements**
- New Case modal: a form picker — Annual Return (NAR1) · Appointment / cessation (ND2A) · Change of particulars (ND2B); the two ND2 options need `officer_changes:write` and go to `/officer-changes/:id` after `create`.
- Dashboard and `CasesPane`: Case Type shows NAR1 / ND2A / ND2B and is filterable; a Deadline column shows `filing_deadline` with "in N days" / "N days overdue" from `days_to_deadline` for ND2 rows and the existing anniversary text for NAR1 rows; ND2 rows link to `/officer-changes/:id`.
- Company profile: *Report a change* menu (Appoint or cease an officer → ND2A; Change an officer's particulars → ND2B); on each director/secretary tile row actions *Cease* and *Change particulars* that open the case with that entry pre-created; a "Change pending" chip linking to the open case for officers named in `pending`.
- Person profile: an **e-Registry account** card (`EServiceCredentialCard`) — user ID, name on the account, password (write-only input; the stored one is never shown, only "Password stored" / "No password stored"), Save and Remove, editable with `persons:write`, read-only otherwise, with one sentence saying it is used only to apply this person's own consent signature on an ND2A. A **dismissable alert** (`ParticularsChangeAlert`) when `particulars-changes` returns rows: which items changed for which company, *Start ND2B* (or *Open ND2B* when `open_case`), and *Dismiss* with a confirm explaining it is for data loaded from the previous system and cannot be recalled. The same alert on a body corporate's company profile.
- Roles screen lists the `officer_changes` module with read / write; `navigation.js` and `screenCapabilities.js` know the new route and module; the permission render matrix test still passes.

- [ ] **Step 1:** Failing tests for each new component and the changed behaviour of each modified one. **Step 2:** Implement. **Step 3:** Task tests and every modified file's existing test pass (the pre-existing failures listed in the controller's notes excepted).

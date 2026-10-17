# ND2A / ND2B — Levi's revisions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply Levi's 4–5 October revisions to the ND2A/ND2B build: no in-portal consent, GSHK's written resolution exactly, consent-signature status, auto-dismissal after an ND2B, and per-company identification and addresses.

**Architecture:** Removals first (e-consent, two manual checks, the resolution toggle), then the resolution renderer and its preview tabs, then signing status, then the ND2B dismissal, then a links layer (`services/officer_changes/links.py`, migration 053) that every reader of a director's ID and addresses goes through, then the Person Profile screens.

**Tech Stack:** FastAPI, Supabase/PostgREST, Alembic, reportlab, React + Vitest/RTL, pytest.

**Spec:** `docs/superpowers/specs/2026-10-05-nd2-levi-revisions-design.md`

## Global Constraints

- Every route: `require_permission`/`live_person`/`live_company`; every write audited, audit failure never blocks.
- No new audit codes (link changes `CASE_FIELD_UPDATED`; auto-dismiss `OFFICER_PARTICULARS_DISMISSED`).
- Migration 052 is edited in place (unapplied everywhere); 053 is new, revises 052, reversible with a guard.
- Resolution: Letter 612×792, Tinos 12 pt, Noto Sans TC 12 pt for Chinese, rules 1.44 pt at y 86.42 / 179.54, header baselines 112.9/128.8/144.6/160.5, line pitch 13.8 (15.9 with Chinese / header), signature x 77.4.
- A party with no links behaves exactly as before (NAR1 XML byte-identical).
- Backend tests never reach Supabase or DNS; frontend tests co-located.

## Review Focus

1. A person holding two roles in one company — links set on both officer rows, read as one.
2. A linked identity document deleted — the link falls back to the primary (FK `ON DELETE SET NULL`), no 500.
3. Resolution with a long company name or many directors — wraps and breaks pages rather than overflowing.
4. Consent refusal whose CR message names nobody — every consent row shows Error, none shows Signed.
5. Auto-dismissal when the other company's pending item has a DIFFERENT new value — left pending.

---

### Task 1: Remove the in-portal consent

**Files:**
- Delete: `backend/services/officer_changes/econsent.py`, `backend/routers/public_consent.py`, `backend/tests/officer_changes/test_econsent.py`, `backend/tests/test_public_consent.py`
- Modify: `backend/routers/public_approval.py`, `backend/routers/officer_changes.py`, `backend/services/officer_changes/{emails,cases,documents}.py`, `backend/services/audit_events.py`, `backend/alembic/versions/052_nd2_feedback.py`, `backend/services/officer_changes/prepare.py` (manual-route reason), frontend `officerChange/{api.js,ChangesCard.jsx,StageClientVerification.jsx}` and their tests
- Test: `backend/tests/officer_changes/test_emails.py`, `backend/tests/test_officer_changes_router.py`, `backend/tests/test_migration_052.py`, `frontend/src/components/officerChange/clientVerification.test.jsx`

- [ ] **Step 1: Failing tests** — `test_consent_routes_are_gone` (POST `/officer-changes/{id}/entries/{e}/econsent-pdf` → 404/405; GET `/public/consent/x` → 404); `test_email_has_no_consent_link` (no "Sign consent to act", no `/public/consent`); `test_052_has_no_consent_table` (`officer_change_consents`, `attach_resolution`, `OFFICER_ECONSENT` absent from 052's SQL); `test_no_account_reason_points_to_manual_route` (reason contains "manual route").
- [ ] **Step 2: Run, watch them fail.**
- [ ] **Step 3: Remove** the module, router, routes, email paragraph, composite `consent_mode`/`econsent`, audit codes, 052 objects; reword the consent-plan reason.
- [ ] **Step 4: Backend + frontend suites green.**
- [ ] **Step 5: Commit** `refactor(nd2): consent is CR's PIN signature — no in-portal consent link (Levi point 2)`

### Task 2: Manual checks without resolution or consent

**Files:** Modify `backend/services/officer_changes/checks.py`; Test `backend/tests/officer_changes/test_checks.py`, `frontend/src/components/officerChange/signingAndChecks.test.jsx`

- [ ] **Step 1: Failing tests** — `test_checks_are_kyc_and_letters_only` (an ND2A with one appointment + one resignation on the manual route yields codes `["kyc", "resignation_letter"]`).
- [ ] **Step 2–4:** fail → remove the two checks → green.
- [ ] **Step 5: Commit** `feat(nd2): manual checks are KYC and resignation letters (Levi point 3)`

### Task 3: The written resolution, exactly as GSHK's sample

**Files:** Rewrite `backend/services/officer_changes/resolution.py`; add `backend/services/nar1_form/fonts/NotoSansTC-Regular.ttf` (+ README/OFL note); Test `backend/tests/officer_changes/test_resolution.py`

**Interfaces:** Produces `render(case, entity, entries, officers) -> bytes` (unchanged signature), `paragraphs(entries) -> list[tuple[str, list[str]]]`, `signatories(entries, officers) -> list[str]`, `dated(entries) -> str | None`.

- [ ] **Step 1: Failing tests** — `test_page_is_letter`, `test_header_rules_and_baselines_match_sample` (±0.6 pt), `test_body_is_tinos_12`, `test_chinese_name_prints_in_noto_sans_tc`, `test_sample_case_wording` (exact strings incl. "Both changes shall also be filed…"), `test_one_change_says_this_change`, `test_secretary_wording`, `test_death_is_noted`, `test_dated_blank_when_dates_differ`, `test_signature_block_at_77_4`, `test_long_board_breaks_pages`.
- [ ] **Step 2–4:** fail → implement with reportlab canvas + manual line layout → green.
- [ ] **Step 5: Commit** `feat(nd2): written resolution built to GSHK's sample (Levi point 3)`

### Task 4: Both PDFs previewed and sent

**Files:** Modify `backend/routers/officer_changes.py` (send always attaches the resolution for an ND2A; PATCH loses `attach_resolution`), `frontend/.../StageClientVerification.jsx`, `AttachmentsCard.jsx`, `api.js`; Test router tests, `clientVerification.test.jsx`

- [ ] **Step 1: Failing tests** — `test_nd2a_send_attaches_resolution_always`, `test_nd2b_send_has_no_resolution`, `test_patch_refuses_attach_resolution`; RTL: `shows ND2A and Written Resolution tabs`, `ND2B shows no tabs`, `attachments card has no resolution toggle`.
- [ ] **Step 2–4:** fail → implement → green.
- [ ] **Step 5: Commit** `feat(nd2): client verification previews and sends the ND2A and its resolution together`

### Task 5: Consent signature status

**Files:** Modify `backend/services/officer_changes/cases.py` (consent rows get `status`, `error`), `frontend/.../StageSigning.jsx`, `EServiceCredentialCard.jsx`; Test `backend/tests/officer_changes/test_cases.py`, `signingAndChecks.test.jsx`

**Interfaces:** Produces `consent_status(row, filing) -> tuple[str, str | None]` in `cases.py`.

- [ ] **Step 1: Failing tests** — `test_consent_status_signed`, `test_consent_status_error_on_every_row_when_unattributed`, `test_consent_status_error_on_named_signer_only`, `test_consent_status_not_signed`; RTL `shows Signed / Error with CR's message`, `button reads Apply consent signature`.
- [ ] **Step 2–4:** fail → implement → green.
- [ ] **Step 5: Commit** `feat(nd2): consent signature shows Signed or CR's error per director (Levi point 5)`

### Task 6: NAR1 refuses after an ND2A moved the board

**Files:** Test `backend/tests/test_drift.py` (or the existing drift test module)

- [ ] **Step 1:** `test_nar1_submit_refused_after_nd2a_changed_directors` — a NAR1 validated with director A; graph now has director B; `_refuse_if_drifted` raises `DriftDetected` naming the director field. Expected to PASS on arrival (verification of existing behaviour) — ledger it as such.
- [ ] **Step 2: Commit** `test(nar1): an ND2A filed after validation stops the NAR1 submit`

### Task 7: ND2B auto-dismissal after one company is filed

**Files:** Modify `backend/services/officer_changes/particulars.py` (`dismiss_filed_elsewhere`), `backend/services/officer_changes/apply.py`; Test `backend/tests/officer_changes/test_particulars.py`, `test_apply.py`

**Interfaces:** Produces `dismiss_filed_elsewhere(*, person_id=None, corporate_entity_id=None, filed_entity_id: str, items: list[dict], user_id) -> list[dict]` returning `[{entity_id, items:[labels]}]`.

- [ ] **Step 1: Failing tests** — `test_same_change_dismissed_for_other_companies`, `test_different_value_left_pending`, `test_company_with_open_nd2b_left_alone`, `test_apply_nd2b_audits_auto_dismissal`.
- [ ] **Step 2–4:** fail → implement → green.
- [ ] **Step 5: Commit** `feat(nd2b): a change filed for one company stops being reported for the others`

### Task 8: Per-company links — schema and resolver

**Files:** Create `backend/alembic/versions/053_particulars_per_company.py`, `backend/services/officer_changes/links.py`; Modify `backend/services/tpsi/forms/{nar1_source,nar1_mapper}.py`, `backend/services/officer_changes/{particulars,source,nd2a_mapper}.py`; Test `backend/tests/test_migration_053.py`, `backend/tests/officer_changes/test_links.py`, NAR1 mapper + particulars tests

**Interfaces:** Produces `links.effective(person, officer, addresses, documents) -> {"residential_address_id", "correspondence_address_id", "documents"}`; `links.documents_for(docs, linked_id) -> list[dict]`.

- [ ] **Step 1: Failing tests** — `test_unlinked_follows_person`, `test_linked_passport_replaces_primary_passport_only`, `test_nar1_files_linked_passport_and_address`, `test_nar1_xml_unchanged_without_links`, `test_nd2b_diff_reports_linked_change_for_that_company_only`, `test_053_shape_and_downgrade_guard`.
- [ ] **Step 2–4:** fail → implement → green.
- [ ] **Step 5: Commit** `feat(registry): identification and addresses linked per company (053)`

### Task 9: Per-company particulars API

**Files:** Modify `backend/routers/persons.py`; Create `backend/services/person_particulars.py`; Test `backend/tests/test_person_particulars_router.py`

- [ ] **Step 1: Failing tests** — for each route in spec §6: happy path, 401/403, edge (address in use cannot be deleted; default cannot be deleted; unknown company 422; identity of another person 404); baseline captured for moved companies; audit row per write.
- [ ] **Step 2–4:** fail → implement → green.
- [ ] **Step 5: Commit** `feat(registry): API for per-company identification and addresses`

### Task 10: Person Profile — three cards

**Files:** Create `frontend/src/components/particulars/{ParticularsByCompany.jsx,AddressBookCard.jsx,IdentityLinksCard.jsx,CompanyPicker.jsx,particulars.css}` + tests; Modify `frontend/src/pages/PersonProfilePage.jsx` (+test); remove `CorrespondenceAddressCard.jsx` usage

- [ ] **Step 1: Failing tests** — lists each address with its companies; New opens the form and posts companies; Companies… moves a company; default cannot be removed; identity row shows companies and saves; read-only without `persons:write`.
- [ ] **Step 2–4:** fail → implement (frontend-design) → green; screenshot check.
- [ ] **Step 5: Commit** `feat(profile-ui): identification and addresses by company`

### Task 11: Notes for the next person

**Files:** Modify `CLAUDE.md`; status line on the 2026-10-02 spec.

- [ ] **Step 1:** document §1–§6 decisions; **Step 2:** commit `docs(nd2): Levi's revisions`.

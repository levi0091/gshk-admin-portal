# CR Status Removal and Confirmation Receipt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove CR status (poll, stage 6, CR codes) from NAR1/ND2A/ND2B and mail the client a receipt, with the confirmed documents, when they press Confirm & File.

**Architecture:** `filed` replaces six CR codes in the Python badge and the SQL view (migration 054 also patches rows and drops the columns). Frontend steppers go to five stages. A new `services/approval_receipt.py` builds the documents and sends `email_service.approval_receipt_email` from a background task queued by `public_approval._record`.

**Tech Stack:** FastAPI, Supabase/PostgREST, Alembic, React/Vite, pytest, Vitest/RTL.

**Spec:** `docs/superpowers/specs/2026-10-17-cr-status-removal-and-confirmation-receipt-design.md`

## Global Constraints

- Terminal code `filed`, label `Filed`. No `cr_*` workflow code survives outside migrations ≤ 053, audit labels, and `badge_from_row`'s legacy set.
- Five stages: `Client Verification, Data Verification, Signing, Submission, Confirmation`.
- Receipt: to the token's `recipient_email`; `cc=[email_service.CLIENT_CC]`, `reply_to=email_service.CLIENT_CC`; audit `EMAIL_SENT`, `metadata.template == "approval_receipt"`, actor `G-FlowDesk (automatic)`, `user_id=None`.
- Attachment names: NAR1 `NAR1-{case_no}[-RevN].pdf`; ND2A/ND2B `{ND2A|ND2B}-{case_no}[-RevN].pdf`; resolution `resolution.file_name(case)`. `-RevN` only from revision 2.
- Times printed `%d %B %Y at %H:%M HKT` (public_approval `_hkt`).
- Every test file run with `uv run pytest` / `VITE_SUPABASE_URL=http://x VITE_SUPABASE_ANON_KEY=d npx vitest run`.
- No audit row or audit code removed.

## Review Focus

1. A filed case on the dashboard before 054 runs (old view still emits `cr_*`): renders `Filed`, not a 500.
2. Two directors press Confirm in the same second: one receipt (only the claim winner's request queues one).
3. A NAR1 case sent before `verification_xml` existed (pre-046) confirmed via a still-live link: receipt goes without an attachment, says so by listing none, audit names the failure.
4. Non-production: the receipt reaches only TEST_RECIPIENTS, renewal@ dropped — via `send()`, not caller logic.
5. The delivery check after a receipt: still reports the verification send.

---

### Task 1: `filed` replaces the CR codes in the backend badge

**Files:** Modify `backend/services/nar1_case_status.py`, `backend/services/nar1_cases.py`, `backend/services/soft_delete.py`, `backend/services/officer_changes/cases.py` (if it reads cr fields), `backend/routers/officer_change_filing.py` (undo gate); tests `backend/tests/test_nar1_case_status.py`, `test_nar1_cases.py`, `test_soft_delete.py`, `test_officer_change_filing_router.py`, `test_cases_manual.py`, `test_companies_router.py`.

**Produces:** `nar1_case_status.FILED = "filed"`; `WORKFLOW_STATUSES = GSHK_STATUSES + (FILED, CLOSED)`; `TERMINAL_STATUSES = (FILED, CLOSED)`; `LEGACY_CR_CODES` (frozenset of the six old codes); `badge_from_row` maps a legacy code to `FILED`; composite no longer carries `cr_status`/`cr_status_checked_at`; `soft_delete.FINISHED_CASE_STATES = {"closed", "filed"}`; undo gate refuses `not filed` with `reason: "not_filed"`.

- [ ] Tests first: `test_a_filed_return_is_filed` (submitted / edrive / manual receipt → `filed`, label `Filed`); `test_closed_beats_filed`; `test_filed_is_never_overdue`; `test_badge_from_row_reads_a_legacy_cr_code_as_filed` (each of six → `filed`); `test_workflow_statuses_carry_no_cr_code`; `test_composite_has_no_cr_status`; `test_a_filed_case_is_finished_for_soft_delete`; `test_undo_refuses_an_unfiled_case` (409 `not_filed`) and `test_undo_works_on_a_filed_case_without_any_cr_answer`. Run → FAIL.
- [ ] Implement; delete the CR-code tests these replace. Run the six files → PASS. Commit.

### Task 2: the poll, Check now and docStatusEnquiry go

**Files:** Delete `backend/jobs/poll_cr_status.py`, `backend/services/nar1_cr_status.py`, `backend/services/tpsi/doc_status.py`, `backend/tests/test_poll_cr_status.py`, `test_nar1_cr_status.py`, `tests/tpsi/test_doc_status.py`, `tests/tpsi/test_refresh_cr_status_router.py`. Modify `backend/routers/tpsi.py` (drop both routes and imports), `backend/services/tpsi/reads.py` (drop `case_status`), `backend/services/tpsi/filings.py` (drop `STAGE_REGISTERED`, `mark_registered`), `backend/services/tpsi/soap.py` (comment), `backend/jobs/README.md`, `tests/tpsi/test_reads.py`, `tests/tpsi/test_tpsi_router.py`.

- [ ] Test first: `test_cr_status_routes_are_gone` — `POST /tpsi/cases/c1/refresh-status` and `GET /tpsi/doc-status` → 404/405 with auth; `test_filing_stages_have_no_registered`. Run → FAIL.
- [ ] Remove. `grep -rn "doc_status\|nar1_cr_status\|STAGE_REGISTERED\|mark_registered\|poll_cr_status" backend --include=*.py` outside alembic/ → nothing. Full backend suite → PASS. Commit.

### Task 3: migration 054

**Files:** Create `backend/alembic/versions/054_cr_status_removed.py`, `backend/tests/test_migration_054.py`. Modify DB tests that assert head state 054 changes: `test_migration_024.py`, `test_migration_043.py`, `test_migration_044.py`, `test_migration_050.py`, `test_migration_052.py`/`053` head checks.

**Produces:** `revision = "054"`, `down_revision = "053"`; `view_sql()` = 052's `view_sql()` with the filed branch `THEN 'filed'`, the three `c.cr_*` select lines removed, overdue finished list `'filed', 'closed'`; `previous_view_sql()` = 052's.

- [ ] Static tests (run without DB): `test_054_view_files_as_filed`, `test_054_view_selects_no_cr_column`, `test_054_overdue_ignores_filed_and_closed`, `test_054_trigger_is_rebuilt_before_columns_drop` (order of statements), `test_054_downgrade_restores_052_view`. DB tests (RUN_DB_TESTS): `registered` rows become `submitted`; columns gone; trigger touches `updated_at` on every update. Run static → FAIL; implement → PASS.
- [ ] Update 024/050 parity tables (`STAGE_REGISTERED` out, CR axis out, expected `filed`); retire 043/044 head-state assertions. Run the whole chain on a throwaway Postgres (pgserver, CI's bootstrap): upgrade head, DB tests, downgrade base. Commit.

### Task 4: frontend — five stages, `Filed`

**Files:** Modify `frontend/src/components/case/workflow.js`, `CaseStepper.jsx`, `StageConfirmation.jsx`, `pages/CaseWorkflowPage.jsx`, `components/CaseStatusBadge.jsx`, `components/CasesPane.jsx`, `pages/DashboardPage.jsx`, `components/officerChange/workflow.js`, `pages/OfficerChangeCasePage.jsx`, `components/officerChange/StageConfirmation.jsx` (Undo moves here), `components/officerChange/api.js`, `lib/screenCapabilities.js`, `index.css`; delete both `StageCrStatus.jsx`; tests alongside.

- [ ] Tests first: `STAGE_LABELS` has five, last `Confirmation`; `reachedStage(filed) === 5`; `stageDone(filed, 5)`; no `crStatus`/`stageTone` export; badge `filed` → `Filed`; dashboard filter offers `filed` and no `cr_*`; CasesPane filed → five ticks; officer page shows five tabs and opens a filed case on Confirmation; Undo on Confirmation for filed+applied with `tpsiSubmit`, dialog names CR's rejection, posts `/officer-changes/:id/undo`. Run → FAIL.
- [ ] Implement; keep breadcrumb `bc-link/bc-sep/bc-cur` CSS. Full frontend suite → PASS; `npm run build` → OK. Commit.

### Task 5: the receipt email (frontend-design skill)

**Files:** Modify `backend/services/email_service.py`; test `backend/tests/test_approval_receipt_email.py`.

**Produces:** `approval_receipt_email(case, entity, *, form_code, confirmed_by, confirmed_email, confirmed_at, revision, attachments) -> tuple[str, str]`.

- [ ] Tests first: subject `NAR1 Confirmation Received - {company}` / `Form ND2A …` / `Form ND2B …`, `[Rev. 2]` from revision 2; body has the HKT moment, the confirmer's name and address, case no, every attachment name, the "did not confirm" line naming renewal@, the GSHK footer; every value escaped; no `<style>`, no `display:flex`; no link other than `mailto:renewal@`. Run → FAIL; implement → PASS. Commit.

### Task 6: send it on Confirm & File

**Files:** Create `backend/services/approval_receipt.py`, `backend/tests/test_approval_receipt.py`; modify `backend/routers/public_approval.py`, `backend/routers/cases.py` (delivery reader skips `template` rows), `backend/tests/test_public_approval*.py`, `backend/tests/test_cases_verification.py`.

**Produces:** `approval_receipt.documents(case: dict) -> tuple[list[tuple[str, bytes]], list[dict]]` (files, failures); `async approval_receipt.send(case_id: str, approval: dict) -> None` (never raises).

- [ ] Tests first: NAR1 renders `verification_xml` with `incorporated_on`, named `NAR1-…-Rev2.pdf`; ND2A gives form + resolution; ND2B form only; no `verification_xml` → no file, one failure; render error → that file dropped, receipt still sent; send → `to=[recipient_email]`, cc/reply_to renewal@; `EMAIL_SENT` row with template; `send` swallows an `EmailError` and a render crash; public POST queues exactly one receipt on a claim, none on a replay, a stale link, a lost claim, or a GET; the delivery query filters `metadata->>template is null`. Run → FAIL; implement → PASS. Full suite. Commit.

### Task 7: notes for the next person

**Files:** `CLAUDE.md` (stage-6, CR vocabulary, 043/044 notes rewritten as removed; receipt paragraph), `backend/jobs/README.md` (done in Task 2), spec `2026-09-16-…` gets a "Reversed by" line.

- [ ] Write; `grep -n "CR Status\|cr_not_checked\|poll_cr_status" CLAUDE.md` shows only history lines. Commit.

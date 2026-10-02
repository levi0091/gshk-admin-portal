# ND2A / ND2B — Jacqueline's feedback (1 Oct 2026) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement every code change in the spec: deferred effective dates, in-system consent to act, written resolution plus email attachments, the manual-checks list, the compact rules box, PI sheets to the client, HKID NIL, the corporate-director e-Reg rule, the open-case alert, per-appointment correspondence address, the ND2B anniversary default, the ND2B waiver, per-company dismissal, and the e-Registry identity check.

**Architecture:** Extends the existing ND2A/ND2B build on branch `nd2a_nd2b` (services under `backend/services/officer_changes/`, routers `officer_changes.py` / `officer_change_filing.py` / `public_approval.py`, React under `frontend/src/components/officerChange/`). One migration (052) carries every schema change. The officer-change composite (`cases.composite`) stays the page's single read and gains fields; every write route still answers with it.

**Tech Stack:** FastAPI + supabase-py (PostgREST), Alembic, pypdf / pymupdf / reportlab, React 18 + Vite, Vitest + RTL, pytest.

**Spec:** `docs/superpowers/specs/2026-10-02-nd2-jacqueline-feedback-design.md`. Every task implicitly includes it; § numbers below refer to it.

## Global Constraints

- Work only in `/Users/tingy/Desktop/zenexflow/gshk-admin-portal/.claude/worktrees/nd2a-nd2b-officer-changes`, branch `nd2a_nd2b`. Commit per task. Never push.
- Shell prefix for uv/npm: `export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v20.20.2/bin:$PATH"`.
- Backend tests: `cd backend && uv run pytest -q -p no:cacheprovider <files>`. Frontend: `cd frontend && npm run test -- --run <files>`.
- No test may reach Supabase, Resend, DNS or CR. Officer-change service tests use `tests/officer_changes/fakes.py`.
- Every new route uses `require_permission(...)` (or `live_person`/`live_company` on those routers). Every write calls `audit(...)` / `log_event(...)` and never fails on an audit error.
- New audit codes are seeded by migration 052 with `origin='g_flowdesk'`, `category='officer_changes'`.
- The public pages run **no script**, their GET **writes nothing**, every miss renders the one "no longer available" page, and responses carry `Cache-Control: no-store`.
- The email body never prints a full identity number or a home address. Tables and inline styles only, every value escaped.
- Brand tokens are fixed (`--indigo #242C66`, `--carrot #F36C32`, `--bang #027248`, `--border #E2E4ED`, `--t-muted #7C80A3`, Outfit). New UI must follow the existing `card` / `card-hdr` / `oc-*` / `alert al-*` / `modal-confirm` classes. Use the `frontend-design` skill for Tasks 13–15.
- A control a role may not use is not drawn; a sentence names the grant instead (existing convention).
- Copy fixed by the spec is verbatim: the e-consent statement *"I consent to act as director of this company and confirm that I have attained the age of 18 years."*; the close reason *"Pending further instructions — no director would remain after these changes. The client has been told they may file Form ND4 themselves."*; the PI paragraph and the ND2B proceed sentence from §2.6 / §2.13.
- CR's address labels, verbatim: `Flat/Floor/Block etc.`, `Building (Name)`, `Street/Estate/Lot/Village etc.`, `District/City/Province/State/Postal Code etc.`, `Country/Region`.

## Review Focus

1. **A restart after a deferred date was filled in.** The next send must treat that date as one the client has seen (no longer deferred), so `PUT …/effective-date` refuses it. Test owned by Task 3.
2. **The incoming director opens the consent link after another director pressed Confirm.** The consent link must still work, because Confirm supersedes Confirm links only. Test owned by Task 9.
3. **The typed name differs only by case, spacing or word order** (e.g. "lee ka ho", "LEE  Ka Ho"). Case and spacing are accepted; a different name is refused with the case unchanged. Test owned by Task 9.
4. **A "Send with the email" attachment whose stored file cannot be downloaded.** The send refuses with 502 naming the file, and nothing is mailed, so the client never gets a letter promising an attachment it lacks. Test owned by Task 8.
5. **A person with no baseline for the company being dismissed.** Per-company dismissal returns `{"dismissed": 0}` and writes no audit row. Test owned by Task 12.

---

### Task 1: Migration 052 and audit codes

**Files:**
- Create: `backend/alembic/versions/052_nd2_feedback.py`
- Modify: `backend/services/audit_events.py` (after line 322)
- Test: `backend/tests/test_migration_052.py`

**Interfaces:**
- Produces: columns and table of spec §3; `audit_events.OFFICER_ECONSENT_LINK_SENT`, `OFFICER_ECONSENT_SIGNED`, `OFFICER_CONFIRMATION_WAIVED`. `revision = "052"`, `down_revision = "050"`.

- [ ] **Step 1: Write the failing test** — pure half only (string assertions over the module's `upgrade` SQL, the style of `test_migration_050.py`'s pure half), plus a `RUN_DB_TESTS`-gated half that upgrades, checks columns, and checks `officer_change_consents` is not readable by `anon`:

```python
def test_052_revises_050(): assert m.revision == "052" and m.down_revision == "050"
def test_052_adds_every_column():   # each "ADD COLUMN IF NOT EXISTS <name>" present
    for col in ("date_deferred", "send_with_email", "source", "uploaded_by_name",
                "attach_resolution", "registered_id_type", "registered_id_number"):
        assert f"ADD COLUMN IF NOT EXISTS {col}" in SQL
def test_052_entry_id_becomes_nullable(): assert "ALTER COLUMN entry_id DROP NOT NULL" in SQL
def test_052_consents_table_is_locked_down():
    assert "CREATE TABLE public.officer_change_consents" in SQL
    assert "token_hash" in SQL and "ENABLE ROW LEVEL SECURITY" in SQL
    assert "REVOKE ALL ON public.officer_change_consents FROM anon, authenticated" in SQL
def test_052_seeds_three_codes_as_g_flowdesk():
    for code in (ev.OFFICER_ECONSENT_LINK_SENT, ev.OFFICER_ECONSENT_SIGNED,
                 ev.OFFICER_CONFIRMATION_WAIVED):
        assert code in SQL
    assert "'g_flowdesk'" in SQL and "'officer_changes'" in SQL
def test_052_downgrade_refuses_while_data_exists():
    assert "RAISE EXCEPTION" in DOWN_SQL
```

- [ ] **Step 2: Run** `uv run pytest -q tests/test_migration_052.py` → FAIL (module missing).
- [ ] **Step 3: Write the migration.** Copy 050's `_NEW_TABLES` RLS/revoke pattern and its `audit_event_types` seed statement. The `source` CHECK covers `upload | econsent | generated`. `registered_id_type` CHECK is NULL or `hkid | passport`. `officer_change_consents` columns are exactly as in spec §3, with `entry_id` FK `ON DELETE CASCADE`, `document_id` FK to `officer_change_documents(id) ON DELETE SET NULL`, a UNIQUE index on `token_hash`, and an index on `(case_id)`. The downgrade raises if `officer_change_consents` has rows or `officer_change_documents` has `entry_id IS NULL` rows, then drops in reverse. Add the three constants to `audit_events.py`.
- [ ] **Step 4: Run** the test → PASS. Also run `uv run pytest -q tests/test_migration_050.py tests/test_audit_events*.py` → PASS.
- [ ] **Step 5: Commit** `feat(db): migration 052 — deferred dates, case documents, e-consent, e-Reg identity`.

---

### Task 2: Rules and dates — notices, board lines, defaults

**Files:**
- Modify: `backend/services/officer_changes/rules.py`, `backend/services/officer_changes/deadlines.py`
- Test: `backend/tests/officer_changes/test_rules.py`, `backend/tests/officer_changes/test_deadlines.py`

**Interfaces:**
- Produces:
  - `rules.evaluate(...)` result gains `"board": {"directors": [{"name": str, "party_type": str}], "secretaries": [{"name": str, "new": bool}]}` and `"lines": [str, str, str]`; check `dates_present` becomes `level="notice"`.
  - `rules.dates_missing(entries) -> list[str]` — party names (ND2B: "Name — label") of undated, non-omitted changes.
  - `deadlines.reply_by_default(deadline, today)` returns `today + 5 days` when `deadline is None`.
  - `deadlines.anniversary_default(incorporation_date, *, open_return_date=None, today=None) -> date | None`.
- Consumes: `officers_now` rows already carry `name`; entries in the composite carry `party.name`.

- [ ] **Step 1: Failing tests**

```python
def test_a_missing_date_no_longer_blocks_sending():
    r = run([appoint(person="P9", when=None)])
    assert check(r, "dates_present")["level"] == "notice" and r["blocking"] is False
def test_three_lines_name_the_board():
    board = [officer("O1","director",person="P1") | {"name": "CHAN Tai Man"},
             officer("O3","company_secretary",corp="GSHK") | {"name": "Get Started HK Limited"}]
    r = rules.evaluate(board, [appoint(person="P9", name="LEE Ka Ho")], company=PRIVATE, today=TODAY)
    assert r["lines"] == [
        "After these changes the company will have 2 directors (2 natural persons) and 1 secretary.",
        "Directors: CHAN Tai Man and LEE Ka Ho.",
        "A company secretary remains — Get Started HK Limited."]
def test_no_director_left_is_visible_in_board(): # cease both directors -> board["directors"] == []
def test_secretary_line_when_appointed_on_this_form(): # "Company secretary: X (appointed on this form)."
def test_secretary_line_when_none_remains(): # "No company secretary would remain."
def test_dates_missing_lists_undated_changes(): assert rules.dates_missing([...]) == ["LEE Ka Ho"]
def test_reply_by_defaults_to_five_days_without_a_deadline():
    assert deadlines.reply_by_default(None, date(2026,10,2)) == date(2026,10,7)
def test_anniversary_default_prefers_the_open_nar1(): 
    assert deadlines.anniversary_default("2019-03-12", open_return_date="2026-03-12",
                                         today=date(2026,10,2)) == date(2026,3,12)
def test_anniversary_default_within_42_days(): # inc 2019-09-01, today 2026-10-02 -> 2026-09-01
def test_anniversary_default_none_after_42_days(): # inc 2019-03-12, today 2026-10-02 -> None
def test_anniversary_default_never_future(): # inc 2019-10-20, today 2026-10-02 -> 2025-10-20 is >42d -> None
```

The `party.name` for an appointment comes from `appoint(..., name=...)` (extend the helper so `party["name"]` is set). Joining names: one name → "X"; two → "X and Y"; three or more → "X, Y and Z".

- [ ] **Step 2: Run** both test files → new tests FAIL.
- [ ] **Step 3: Implement.** `board_after` carries `name` (officers: `o["name"]`; entries: `e["party"]["name"]`) and `new` (True for appointments). `lines[0]` is the existing `summary`. `anniversary_default` computes this year's anniversary from the month and day (29 Feb → 28 Feb); if it is after today, it uses the previous year. It returns `open_return_date` (parsed) when given and not after today; otherwise the anniversary when `0 <= (today - anniv).days <= 42`; otherwise None.
- [ ] **Step 4: Run** → PASS; then run all of `tests/officer_changes/` → PASS. Fix `test_cases.py` expectations only where the reply-by default changed.
- [ ] **Step 5: Commit** `feat(nd2): dates are a notice at send; the rules box names the board`.

---

### Task 3: Deferred effective dates end to end

**Files:**
- Modify: `backend/services/officer_changes/cases.py`, `nd2a_mapper.py`, `nd2b_mapper.py`, `prepare.py`, `backend/routers/officer_changes.py`, `backend/routers/officer_change_filing.py`
- Test: `backend/tests/officer_changes/test_cases.py`, `test_nd2_mappers.py`, `backend/tests/test_officer_changes_router.py`, `backend/tests/test_officer_change_filing_router.py`

**Interfaces:**
- Consumes: `rules.dates_missing` (Task 2), `deadlines.anniversary_default` (Task 2).
- Produces:
  - `cases.mark_deferred(case_id) -> int` — called by the send route after a successful send: sets `date_deferred=True` on undated cessation/appointment entries, `deferred: true` on undated non-omitted ND2B items, and **clears** both on dated ones.
  - `cases.set_effective_date(case, entry_id, value: str, *, item_key: str | None = None, user_id) -> tuple[dict, dict]` (before, after). Raises `CaseRefused("not_deferred" | "signed" | "case_closed" | "already_filed")` and `ValueError` for a bad or future date.
  - Mapper kwarg `require_dates: bool` (default = `for_esign`): when False, a missing date emits no problem and the element is left empty.
  - Route `PUT /officer-changes/{id}/entries/{entry_id}/effective-date`, body `{"effective_date": "YYYY-MM-DD", "item_key": optional}` → composite. Permission `officer_changes:write`. Audit `CASE_FIELD_UPDATED` metadata `{"field": "effective_date", "item_key", **entry metadata}`.
  - `POST /mark-checked` accepts optional body `{"signing_method": "esign" | "manual"}` (default `manual`). For `esign` it requires a ready consent plan (409 `esign_unavailable`).
  - Composite field `dates_missing: [str]`.

- [ ] **Step 1: Failing tests**

```python
# cases
def test_appointment_and_cessation_accept_no_date(fake_sb): # add_entry without effective_date succeeds
def test_new_nd2b_item_is_dated_the_anniversary(fake_sb):  # entity incorporation 2019-09-01, today 2026-10-02 -> items[*].effective_date == "2026-09-01"
def test_mark_deferred_flags_only_undated(fake_sb):
def test_set_effective_date_refuses_a_date_the_client_saw(fake_sb): # CaseRefused reason "not_deferred"
def test_set_effective_date_refuses_the_future(fake_sb):  # ValueError
def test_set_effective_date_after_signing_is_refused(fake_sb): # filing stage signed -> "signed"; manual_signed_document_id set -> "signed"
def test_set_effective_date_supersedes_a_validated_filing(fake_sb, monkeypatch):
def test_restart_then_resend_makes_a_filled_date_seen(fake_sb): # Review Focus 1
# mappers
def test_nd2a_manual_xml_leaves_a_missing_date_empty(): # map_case(..., for_esign=False) no MappingError, dtResign == ""
def test_nd2a_esign_xml_requires_the_date(): # for_esign=True -> MappingError mentions "no date"
# routes
def test_put_effective_date_403_without_write(client):
def test_put_effective_date_happy_path_audits(client):
def test_record_filing_refuses_while_a_date_is_missing(client):  # 409 reason "dates_missing"
def test_signed_form_upload_refuses_while_a_date_is_missing(client):
def test_mark_checked_esign_keeps_the_route(client): # signing_method stays "esign", data_checked_at set
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
  - `cases`: remove the "Enter the date …" ValueErrors from `_new_row`, `_check_appointment` and `update_entry`; keep the reason checks. Load the anniversary default once per change entry. The entity comes from `entities.incorporation_date`, and the open NAR1 comes from `nar1_cases` rows with `form_code='Nar1'`, not closed, without `manual_receipt`, and its return date from `services.tpsi.fees.return_date_for(incorporation_date, ar_period_year)` (guard None). Apply it in `_new_row` (kind `change`) and `refresh_items` (new items only).
  - `set_effective_date`: the case must be sent (`verification_sent_at`), not closed, not filed. "Signed" means `nar1_cases.current_filing(case_id).stage == 'signed'` or `case.manual_signed_document_id`. The entry or item must carry `date_deferred` / `deferred`. If the current filing stage is `validated`, call `tpsi_filings.supersede_all_for_case(case_id)`. Re-store the deadline.
  - Mappers: thread `require_dates` through `cr_date` (new kwarg `required: bool`) in `_cessation`, `_natural_appointment`, `_corporate_appointment` and the ND2B item dates. `prepare.build_form_xml(..., require_dates=None)` passes `for_esign` when None.
  - Router send: after `nar1_cases.update_case(case_id, patch)`, call `svc.mark_deferred(case_id)`. `_restart` does not clear dates.
  - Filing router: `_refuse_if_dates_missing(case)` uses `rules.dates_missing(svc.list_entries(...))` → 409 `{"reason": "dates_missing", "message": "Enter the effective date of: …"}`. Call it in `signed_form`, `record_filing`, `validate` (before building) and `sign`.
- [ ] **Step 4: Run** the four test files plus all of `tests/officer_changes/` → PASS.
- [ ] **Step 5: Commit** `feat(nd2): effective dates may wait until signing (Jacqueline A1, B1)`.

---

### Task 4: HKID "NIL" for a passport-only appointee

**Files:**
- Modify: `backend/services/officer_changes/nd2a_mapper.py` (`full_ids`), `backend/services/officer_change_form/nd2a.py` (public appointment page values and `pi_values`), `backend/services/officer_change_form/nd2b.py` (PI hkid)
- Test: `backend/tests/officer_changes/test_nd2_mappers.py`, `test_nd2a_form.py`, `test_nd2b_form.py`

**Interfaces:** Produces the XML rule of spec §2.7. No signature changes.

- [ ] **Step 1: Failing tests**

```python
def test_passport_only_appointee_files_hkid_nil():
    bean = map_case(graph_with(passport="K1234567", country="GB"), [appointment], ...)["appOfNpBeans"][0]
    assert bean["indvHkidNo"] == "NIL" and "indvHkidChkDgt" not in bean
    assert bean["indvPptNo"] == "K1234567"
def test_hkid_holder_unchanged(): # indvHkidNo == "A123456", indvHkidChkDgt == "3", no indvPptNo
def test_pdf_prints_nil_in_the_hkid_box():  # render_fields(...): public appointment hkid widget == "NIL"; PI hkid_full == "NIL"
def test_nd2b_pi_prints_nil_for_a_removed_hkid():
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** In `full_ids`, when there is a passport and no HKID, set `f"{prefix}HkidNo": "NIL"`. In `nd2a.py`, the public page's partial-HKID box prints `"NIL"` when the bean's `indvHkidNo` is NIL, and `pi_values` keeps `"NIL"` (no check digit) instead of blanking it. `needs_pi` is unchanged. Do the same in `nd2b.py` line ~132.
- [ ] **Step 4: Run** → PASS (geometry tests included).
- [ ] **Step 5: Commit** `fix(nd2a): a director without an HKID is filed and printed as NIL (Jacqueline A9)`.

---

### Task 5: e-Sign eligibility — corporate directors and the e-Registry identity

**Files:**
- Modify: `backend/services/officer_changes/prepare.py` (`consent_plan`), `backend/services/officer_changes/eservice.py`, `backend/routers/persons.py` (`_eservice_body`, `put_eservice_credential`), `backend/routers/officer_change_filing.py` (`_CR_HINTS`)
- Test: `backend/tests/officer_changes/test_prepare.py`, `test_eservice.py`, `backend/tests/test_persons_officer_changes.py`, `backend/tests/test_officer_change_filing_router.py`

**Interfaces:**
- Produces:
  - `consent_plan` rows: for a body-corporate director, the reason is `"e-Registry accepts a body-corporate director's consent only for a Hong Kong company — {name} is incorporated in {country}. File this ND2A on the manual route."` when `prepare.is_hong_kong_company(corp: dict) -> bool` is False. Natural-person rows gain `"id_mismatch": str | None` (the warning text, partial numbers only).
  - `eservice.save(..., registered_id_type=UNSET, registered_id_number=UNSET)`; `_to_metadata` adds `registered_id_type`, `registered_id_number`; new `eservice.identity_mismatch(meta: dict, docs: list[dict]) -> str | None`.
  - `GET /persons/{id}/eservice-credential` adds `registered_id_mismatch: str | None`.

- [ ] **Step 1: Failing tests**

```python
def test_hk_company_by_place(): assert prepare.is_hong_kong_company({"incorporation_place": "HK"})
def test_hk_company_by_cr_number_when_no_place(): assert prepare.is_hong_kong_company({"cr_number": "1234567"})
def test_overseas_company_is_not(): assert not prepare.is_hong_kong_company({"incorporation_place": "VG", "cr_number": "1"})
async def test_consent_plan_refuses_an_overseas_corporate_director(fake_sb): # reason contains "only for a Hong Kong company" and "British Virgin Islands"
def test_identity_mismatch_names_partial_numbers():
    meta = {"registered_id_type": "passport", "registered_id_number": "X1234567"}
    docs = [{"id_type": "passport", "id_number": "Y7654321"}]
    msg = eservice.identity_mismatch(meta, docs)
    assert "X123" in msg and "Y765" in msg and "X1234567" not in msg
def test_no_mismatch_when_the_number_is_still_held(): # docs include X1234567 -> None
def test_put_credential_stores_registered_id_and_never_audits_it(client):  # audit metadata has no registered_id_number
def test_signer_mismatch_hint_mentions_the_eregistry_account(): # _explain adds hint text containing "e-Registry account still holds"
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** `is_hong_kong_company`: `resolve_country(incorporation_place)` equals CR's HK code (`cr_vocabularies.resolve_country`, compared to the code it returns for "HK"); with no place, `bool(cr_number)`. The country name for the message comes from `cr_vocabularies` (display name; fall back to the raw value). `consent_plan` loads the corporate rows for its corporate directors in one `in_` query. Partial numbers: HKID via `nar1_mapper._partial_hkid`, passport via `_partial_passport`, each followed by "…". `_eservice_body` accepts the two new keys and validates the type ∈ {hkid, passport} (400 naming the field). Append to the "signer does not match" hint: *" Or the e-Registry account still holds an old passport or HKID — CR does not update e-Registry when the register changes."*
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(nd2): e-Sign only for HK corporate directors; warn when e-Registry holds an old ID (A10, N1)`.

---

### Task 6: Manual checks

**Files:**
- Create: `backend/services/officer_changes/checks.py`
- Modify: `backend/services/officer_changes/cases.py` (`composite`), `backend/routers/officer_change_filing.py` (`validate`, `mark_checked`)
- Test: `backend/tests/officer_changes/test_checks.py`, `backend/tests/test_officer_change_filing_router.py`

**Interfaces:**
- Consumes: `documents.list_for_case` rows (`entry_id` may be None after Task 7; treat None as case-level), `consent_plan` (Task 5), e-consent records (Task 9 adds `econsent` docs with `source == "econsent"`; this task only counts `consent_to_act` documents, so Task 9 needs no change here).
- Produces: `checks.manual_checks(case: dict, entries: list[dict], docs: list[dict], *, route: str) -> list[dict]`. Each item is `{"code", "entry_id" | None, "label", "kind": "tick" | "document", "document_type": str | None, "ok": bool, "document": {id, file_name, uploaded_at} | None}`. Codes: `kyc`, `resignation_letter`, `written_resolution`, `consent_to_act`. Plus `checks.incomplete(items) -> list[str]` (labels). Composite field `manual_checks`.

- [ ] **Step 1: Failing tests**

```python
def test_kyc_per_appointment():  # label "KYC / WorldCheck cleared — LEE Ka Ho", ok follows kyc_cleared
def test_resignation_letter_per_cessation_not_by_death():  # R -> present; D -> absent
def test_written_resolution_once_per_nd2a_and_satisfied_by_any_board_resolution(): # case-level or entry-level doc
def test_consent_check_only_on_the_manual_route():  # route "esign" -> no consent_to_act items
def test_nd2b_has_no_checks(): assert checks.manual_checks(nd2b_case, entries, [], route="manual") == []
def test_validate_refuses_incomplete_checks(client): # 409 reason "checks_incomplete", message names "Resignation letter on file — WONG Mei Ling"
def test_mark_checked_refuses_incomplete_checks(client):
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the pure function. The route comes from `case["signing_method"] or route.default`. The latest document of each type wins. Gate `validate` and `mark_checked` with `_refuse_if_checks_incomplete(case)`.
- [ ] **Step 4: Run** → PASS. Update existing filing-router tests that validate/mark-checked a case with appointments so their fixtures carry KYC + documents.
- [ ] **Step 5: Commit** `feat(nd2): manual checks — KYC, resignation letter, written resolution, consent (A4)`.

---

### Task 7: Case documents, "send with the email", and the generated written resolution

**Files:**
- Create: `backend/services/officer_changes/resolution.py`
- Modify: `backend/services/officer_changes/documents.py`, `backend/routers/officer_changes.py`
- Test: `backend/tests/officer_changes/test_documents.py`, `backend/tests/officer_changes/test_resolution.py`, `backend/tests/test_officer_changes_router.py`

**Interfaces:**
- Produces:
  - `documents.upload(case, entry | None, *, ..., send_with_email=False, source="upload", uploaded_by_name=None)`; `documents.set_send_with_email(case, doc_id, value: bool) -> dict`; `documents.email_attachments(case_id) -> list[tuple[str, bytes]]` (raises `documents.AttachmentError(file_name)` when a download fails); `destination(None, case=case)` → the company.
  - `SUPPORT_TYPES` stays. Case-level uploads take `board_resolution` or `officer_change_support`.
  - `resolution.render(case: dict, entity: dict, entries: list[dict], officers: list[dict]) -> bytes` (PDF) and `resolution.file_name(case) -> str` = `"Written-Resolution-{case_no}.pdf"`.
  - Routes (all `officer_changes`): `POST /{id}/documents` (multipart: `file`, `document_type_code`, `send_with_email`) — write; `PATCH /{id}/documents/{doc_id}` body `{"send_with_email": bool}` — write; `GET /{id}/resolution` → PDF — read; `PATCH /{id}` accepts `attach_resolution: bool` — write.
  - Composite: `documents` rows gain `send_with_email`, `source`, `entry_id` (may be None); new `attach_resolution` (from the case).

- [ ] **Step 1: Failing tests**

```python
def test_case_level_upload_has_no_entry(fake_sb):
def test_case_level_document_is_filed_to_the_company(fake_sb):  # file_to_profiles -> owner_kind "entity", owner_id == case.entity_id
def test_email_attachments_returns_only_ticked_docs(fake_sb):
def test_email_attachments_raises_naming_the_file_on_download_failure(fake_sb): # Review Focus 4
def test_resolution_lists_each_change_and_the_filing_authority():
    text = pdf_text(resolution.render(case, entity, [cease_wong, appoint_lee], officers))
    assert "WRITTEN RESOLUTIONS OF THE DIRECTORS" in text
    assert "resignation of WONG Mei Ling as a director" in text
    assert "LEE Ka Ho" in text and "appointed as a director" in text
    assert "Form ND2A" in text
def test_resolution_signatories_are_directors_in_office_excluding_the_deceased():
def test_resolution_with_no_director_in_office_is_signed_by_the_incoming_directors():
def test_resolution_undated_change_reads_date_of_this_resolution():
def test_patch_attach_resolution_audits_field(client):
def test_case_document_routes_403_without_write(client):
```

`pdf_text` = `"".join(p.get_text() for p in pymupdf.open(stream=b))`.

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** The resolution uses reportlab `SimpleDocTemplate`, A4, Times-Roman 11pt, title block *"{COMPANY NAME}" / "(the \"Company\")" / "Business Registration No. {br}"*, heading *"WRITTEN RESOLUTIONS OF THE DIRECTORS"*, sub *"passed in writing pursuant to the Articles of Association of the Company"*. Numbered resolutions, in spec §2.3 order:
  * cessation R: *"THAT the resignation of {name} as a {capacity} of the Company with effect from {date} be and is hereby accepted."*
  * cessation D: *"THAT it be noted that {name} ceased to be a {capacity} of the Company on {date} by reason of death."*
  * appointment: *"THAT {name}, having consented to act, be and is hereby appointed as a {capacity} of the Company with effect from {date}."*
  * last: *"THAT any director or the company secretary of the Company be and is hereby authorised to sign and deliver Form ND2A to the Companies Registry and to update the statutory registers of the Company accordingly."*
  
  `{date}` is `%d %B %Y`, or the words "the date of these resolutions" when undated. Each signatory gets a signature line, their name and "Director". The footer reads *"Date: ____________"* and the case reference. Upload accepts `send_with_email` as a form string `"true"`/`"false"`. The send route (Task 8) consumes `email_attachments`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(nd2): written resolution and any document can go with the client email (A3)`.

---

### Task 8: The client email and the send — PI sheets, attachments, dates, ND2B wording

**Files:**
- Modify: `backend/services/officer_changes/emails.py`, `backend/routers/officer_changes.py` (`preview`, `send_verification`)
- Test: `backend/tests/officer_changes/test_emails.py`, `backend/tests/test_officer_changes_router.py`

**Interfaces:**
- Consumes: `documents.email_attachments`, `resolution.render`/`file_name` (Task 7); per-recipient consent info `{"mode": "esign" | "econsent" | None, "url": str | None, "name": str}` (Task 9 supplies `econsent` URLs; until then `mode` comes from `consent_plan`).
- Produces: `emails.officer_change_email(case, entity, entries, *, approval_url, respond_by, revision=None, attachments: list[str] = (), consent: dict | None = None) -> (subject, html)`. `preview?audience=client|staff` renders the full form; `audience=public` renders the public pages only.

- [ ] **Step 1: Failing tests**

```python
def test_undated_change_reads_to_be_confirmed(): # "with effect from a date to be confirmed when we file this notice"
def test_pi_paragraph_replaces_the_old_privacy_line():
    assert "protected-information sheet" in html and "not shown in this email or in the draft" not in html
def test_attachments_are_listed(): # "Attached:" and each file name, escaped
def test_esign_director_is_told_no_signature_needed(): # "No signature is needed from you"
def test_econsent_director_gets_the_sign_button(): # href == consent url, label "Sign consent to act"
def test_nd2b_says_we_will_proceed():  # "we will proceed with filing so that the Companies Registry receives this notice within the 15-day period"
def test_nd2a_never_says_we_will_proceed():
def test_send_attaches_full_form_resolution_and_ticked_docs(client, monkeypatch): # email_service.send called with 3 attachments; render called with public_only=False
def test_send_refuses_before_mailing_when_an_attachment_cannot_be_read(client): # 502, send never called
def test_preview_public_audience_is_public_only(client):
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Email changes are spec §2.1, §2.2, §2.6 and §2.13, verbatim. The consent paragraph sits after the change list. The ND2B proceed sentence follows the reply-by line. Attachments are listed beneath the reference block as *"Attached: a.pdf · b.pdf"*. In the send route, collect the attachments **before** issuing tokens: the form PDF (`public_only=False`), then the generated resolution when `case.attach_resolution` and ND2A, then `documents.email_attachments(case_id)`. An `AttachmentError` → 502 `"The email was not sent: {file} could not be read from storage."`. Pass `attachments=[names]` and the per-target `consent` to `officer_change_email`. Audit `EMAIL_SENT` metadata gains `"attachments": [names]`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(nd2): the client gets the PI sheets, every attachment and the right date wording (A8, B2)`.

---

### Task 9: Consent to act signed in G-FlowDesk (e-consent)

**Files:**
- Create: `backend/services/officer_changes/econsent.py`, `backend/routers/public_consent.py`
- Modify: `backend/main.py` (include router under `/public`), `backend/routers/officer_changes.py` (send issues links; `_restart` supersedes; composite consumer), `backend/services/officer_changes/cases.py` (composite: `econsents` per entry)
- Test: `backend/tests/officer_changes/test_econsent.py`, `backend/tests/test_public_consent.py`, `backend/tests/test_officer_changes_router.py`

**Interfaces:**
- Consumes: `nar1_approvals.hash_token`, `nar1_router._deadline_from`, `public_approval._render/_unavailable/_rate_limited/_client_ip/_hkt/_PAGE` (import, do not copy), `officer_change_form.render` + `page_plan`, `documents.upload(..., source="econsent", uploaded_by_name=...)`.
- Produces:
  - `econsent.eligible(entries, eservice_meta, emails: dict[person_id,str]) -> list[dict]`: new natural-person director entries with an email and no complete account.
  - `econsent.issue(case_id, entries: list[dict], *, revision: int, expires_at) -> dict[entry_id, token]`: supersedes the case's outstanding rows first.
  - `econsent.supersede(case_id) -> int`; `econsent.find(token) -> dict | None`; `econsent.status_for(case_id) -> dict[entry_id, {signed_at, signed_name}]`.
  - `econsent.sign(row, case, entry, *, typed_name, ip, user_agent) -> dict`: claims the row (`signed_at IS NULL` condition), renders the stamped PDF, uploads it, links `document_id`, returns `{"document_id" | None, "error" | None}`. Raises `econsent.NameMismatch` before writing anything.
  - `econsent.stamp(pdf: bytes, *, consent_index: int, name: str, when, ip, user_agent, case_no, revision) -> bytes`: the page carrying the N-th natural-person appointment (sheet "2" for N=1, the (N-1)-th "B" sheet after), the stamp drawn into the "Signed" box located with `page.search_for("Signed")` (the occurrence inside the consent box, i.e. the first on sheet 2/B), plus a signature-record page.
  - Public routes: `GET /public/officer-consent/{token}`, `POST /public/officer-consent/{token}` (form fields `full_name`, `agree`).
  - Composite: each director appointment gains `"consent_mode": "esign" | "econsent" | "paper"` and `"econsent": {"sent": bool, "signed_at", "signed_name"} | None`.

- [ ] **Step 1: Failing tests**

```python
def test_eligible_skips_directors_with_a_stored_account():
def test_issue_supersedes_previous_links(fake_sb):
def test_get_writes_nothing(client, fake_sb):   # no row changes, no audit
def test_page_runs_no_script(client): assert "<script" not in resp.text.lower()
def test_unknown_token_is_the_one_unavailable_page(client):
def test_sign_records_and_files_the_consent(client, fake_sb, monkeypatch): # signed_at set, officer_change_documents row source "econsent", type "consent_to_act", audit OFFICER_ECONSENT_SIGNED with ip
def test_name_check_ignores_case_and_spacing(client): # "lee  ka ho" accepted for "LEE Ka Ho"   (Review Focus 3)
def test_wrong_name_is_refused_and_nothing_changes(client):
def test_consent_still_works_after_another_director_confirmed(client): # case.client_approved True -> consent page still asks (Review Focus 2)
def test_closed_case_link_is_unavailable(client):
def test_restart_supersedes_consent_links(client):
def test_stamp_places_the_name_on_the_consent_page():
    out = econsent.stamp(nd2a_pdf_with_two_natural_appointments, consent_index=2, name="LEE Ka Ho", ...)
    doc = pymupdf.open(stream=out)
    assert "LEE Ka Ho" in doc[0].get_text() and "Signed electronically" in doc[0].get_text()
    assert "Signature record" in doc[-1].get_text()
def test_send_issues_consent_links_and_audits(client): # OFFICER_ECONSENT_LINK_SENT once per eligible director
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Name normalisation is `" ".join(s.split()).casefold()`, compared against the person's `full_name` and against `"{surname} {given_names}"`. The page copy is spec §2.2 verbatim: heading *"Consent to act as director"*, ledger (Company, BRN, Capacity "Director", Our reference, Effective date or "To be confirmed"), the statement, a text input labelled *"Type your full name to sign"*, a checkbox *"I confirm the statement above"*, button **Sign consent**, and the note *"This signature is recorded electronically in G-FlowDesk with the date, time and your IP address. If anything is wrong, do not sign — email renewal@getstarted.hk."*. POST success shows *"Thank you — your consent is recorded"*. Expiry is `expires_at` (reply-by 23:59:59 HKT). The form posts to the same path, so the token never appears in the HTML. Render the PDF from `case["verification_xml"]` (fall back to `prepare.build_form_xml`). A rendering failure still records the signature and returns `error`. The composite then shows the consent as signed, with *"PDF not produced"*, and Data Verification counts the check satisfied only when the document exists. Add a staff route `POST /officer-changes/{id}/entries/{entry_id}/econsent-pdf` (write) that regenerates it.
- [ ] **Step 4: Run** → PASS, plus `tests/test_public_approval.py` (unchanged behaviour).
- [ ] **Step 5: Commit** `feat(nd2): a new director signs the consent to act in G-FlowDesk (A2, A5)`.

---

### Task 10: ND2B — proceed without client confirmation

**Files:**
- Modify: `backend/routers/officer_changes.py`, `backend/services/nar1_approvals.py` (`SOURCE_STAFF_WAIVER`, `provenance`), `backend/routers/public_approval.py` (`_decided`)
- Test: `backend/tests/test_officer_changes_router.py`, `backend/tests/test_public_approval.py`

**Interfaces:**
- Produces: `POST /officer-changes/{id}/verification/proceed` body `{"reason": str}` (write; ND2B only; sent; no answer yet) → composite. `nar1_approvals.SOURCE_STAFF_WAIVER = "staff_waiver"`, and `provenance()` returns `{"source": "staff_waiver", "label": "Proceeding without the client's confirmation", "reason": …}` (reason read from the case's `client_approval_name`).

- [ ] **Step 1: Failing tests**

```python
def test_proceed_sets_approved_with_waiver_source(client): # client_approved True, source staff_waiver, audit OFFICER_CONFIRMATION_WAIVED with reason
def test_proceed_refused_on_nd2a(client): # 409 reason "nd2b_only"
def test_proceed_requires_a_reason(client): # 400
def test_proceed_403_without_write(client):
def test_public_page_still_asks_after_a_waiver(client): # case waived -> GET renders the ask page, POST records self_service
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Store the reason in `client_approval_name`, prefixed `"Waived: "` (no new column; the trail carries it verbatim in metadata). `_decided` returns None when `client_approval_source == 'staff_waiver'`. Restricting this by `form_code` is unnecessary, since only ND2B can be waived.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(nd2b): proceed without the client's confirmation, with a reason (BQ1)`.

---

### Task 11: Other open cases for the same company

**Files:**
- Modify: `backend/services/nar1_cases.py` (`other_open_cases`, `composite`), `backend/services/officer_changes/cases.py` (`composite`)
- Test: `backend/tests/test_nar1_cases*.py` (the existing composite test file), `backend/tests/officer_changes/test_cases.py`

**Interfaces:** Produces `nar1_cases.other_open_cases(entity_id: str, *, exclude: str) -> list[dict]`: rows `{id, case_no, case_type: "NAR1"|"ND2A"|"ND2B", form_code, workflow_status}`, excluding closed and filed (`manual_receipt` or filing stage in `CR_FILED_STAGES` or `changes_applied_at`). Both composites carry `other_open_cases`. A failure there is reported as `[]` plus stderr, never a 500.

- [ ] **Step 1: Failing tests:** `test_other_open_cases_excludes_self_closed_and_filed`, `test_nar1_composite_carries_other_open_cases`, `test_nd2_composite_carries_other_open_cases`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** with one `nar1_cases` query by `entity_id` and one filings query (`current_filing` per remaining row is acceptable; there are at most a handful).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(cases): every case names the company's other open filings (AQ3, BQ1)`.

---

### Task 12: Correspondence address per appointment, and per-company dismissal

**Files:**
- Modify: `backend/services/officer_changes/particulars.py`, `backend/services/officer_changes/apply.py`, `backend/routers/persons.py`, `backend/routers/companies.py`
- Test: `backend/tests/officer_changes/test_particulars.py`, `test_apply.py`, `backend/tests/test_persons_officer_changes.py`, `backend/tests/test_companies_officer_changes.py`

**Interfaces:**
- Produces:
  - `particulars._appointments` rows gain `correspondence_address_id`. `_pending` and `pending_for_officer` diff each appointment against `{**current, "correspondence_address": <that appointment's address or None>}`. `diff` reports an explicit baseline correspondence address when it differs from the appointment's effective one.
  - `particulars.dismiss(..., entity_id: str | None = None)` — only that appointment when given.
  - `particulars.capture_before_edit(..., entity_id: str | None = None)` — only that appointment when given.
  - `PUT /persons/{person_id}/appointments/{officer_id}/correspondence-address` (persons write), body = `AddressIn` fields **or** `{"same_as_residential": true}`. Uses `address_service.save(owner_table="entity_officers", owner_id=officer_id, owner_column="correspondence_address_id", ...)`; same-as-residential sets the column NULL. Audit as the residential route does (`_address_audit_entries`, subject the person, metadata `{"officer_id", "entity_id", "field": "correspondence_address"}`).
  - `GET /persons/{id}` adds `correspondence_addresses: [{officer_id, entity_id, company_name, role, address | None}]` for current director/secretary rows.
  - Both dismiss routes accept an optional JSON body `{"entity_id": str}`.
  - `apply` writes `correspondence_address_id` (a new `addresses` row from `entry.correspondence_address`) on the officer row it inserts when `correspondence_same_as_residential is False`; undo removes the row as before.

- [ ] **Step 1: Failing tests**

```python
def test_editing_one_appointments_correspondence_raises_e_for_that_company_only(fake_sb):
def test_same_as_residential_clears_the_explicit_address(fake_sb):
def test_explicit_baseline_equal_to_the_appointment_is_not_pending(fake_sb):
def test_dismiss_for_one_company_moves_only_that_baseline(fake_sb):
def test_dismiss_for_a_company_without_a_baseline_is_zero_and_unaudited(client): # Review Focus 5
def test_put_correspondence_address_403_without_write(client):
def test_put_correspondence_address_captures_baseline_first(client):
def test_person_get_lists_correspondence_addresses(client):
def test_nd2a_filing_writes_correspondence_address_id(fake_sb):
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** as in the Interfaces block. `_pending` loads the appointment addresses in one `in_` query. Keep `FOLLOWS_RESIDENTIAL` semantics: a baseline that follows the residential address compares against the appointment's effective address.
- [ ] **Step 4: Run** → PASS, plus the whole `tests/officer_changes/`.
- [ ] **Step 5: Commit** `feat(profile): a correspondence address per appointment, and dismiss for one company (AQ5, B4, BQ2)`.

---

### Task 13: Frontend — CR address format and the Person Profile

**Files:**
- Create: `frontend/src/lib/crAddress.js`, `frontend/src/lib/crAddress.test.js`, `frontend/src/components/CorrespondenceAddressCard.jsx`, `frontend/src/components/CorrespondenceAddressCard.test.jsx`
- Modify: `frontend/src/components/AddressBlock.jsx`, `frontend/src/pages/PersonProfilePage.jsx`, `frontend/src/components/officerChange/EServiceCredentialCard.jsx` (+ test), `frontend/src/components/officerChange/ParticularsChangeAlert.jsx` (+ test)

**Interfaces:**
- Produces: `CR_ADDRESS_LABELS` (5 labels, verbatim), `crAddressLines(address, countryLabel?) -> [{label, value}]` (value `''` when empty; district = city, state_region, postal_code joined by spaces), `countryName(code, lookups)`.
- Consumes: `GET /persons/{id}` `correspondence_addresses` and `PUT …/correspondence-address` (Task 12); credential metadata `registered_id_*`, `registered_id_mismatch` (Task 5); dismiss body `{entity_id}` (Task 12).

- [ ] **Step 0:** Invoke the `frontend-design` skill. Keep the existing card language: a correspondence row reads like a `role-item`, edits in a modal with a right-aligned `.modal-footer`.
- [ ] **Step 1: Failing tests:** `crAddressLines` returns the five labels in order, joins the district, and gives empty values for empty lines. The AddressBlock read-only view shows `Flat/Floor/Block etc.` and `Country/Region` with the country name. The card shows "Same as residential address" and an address in five lines; Edit opens a modal whose "Same as residential address" toggle hides the fields, and Save PUTs the right body. Without `persons:write` the Edit button is not drawn. The credential card saves `registered_id_type/number` and shows the mismatch warning. The alert has **Not for this company** posting `{entity_id}`.
- [ ] **Step 2: Run** them → FAIL.
- [ ] **Step 3: Implement.** In read-only mode, the Person Profile renders a `tile-sec-lbl` "Residential Address" above the address and the new card below the personal-information card.
- [ ] **Step 4: Run** the changed test files and `PersonProfilePage.test.jsx` → PASS.
- [ ] **Step 5: Commit** `feat(profile-ui): CR's address format; residential and correspondence shown apart (B3, B4, BQ2, N1)`.

---

### Task 14: Frontend — Client Verification

**Files:**
- Create: `frontend/src/components/officerChange/AttachmentsCard.jsx`, `frontend/src/components/officerChange/BoardSummary.jsx`
- Modify: `RulesPanel.jsx`, `StageClientVerification.jsx`, `ChangesCard.jsx`, `ParticularsChangeCard.jsx`, `AppointmentDrawer.jsx`, `CessationDrawer.jsx`, `api.js`, `frontend/src/components/case/CloseCaseModal.jsx` (`initialReason` prop), `officerChange.css`, tests in `officerChange.test.jsx`, `api.test.js`, `CloseCaseModal.test.jsx`

**Interfaces:**
- Consumes: composite `rules.lines`, `rules.board`, `documents` (`send_with_email`, `entry_id`), `attach_resolution`, `entries[].consent_mode/econsent`, `client_approval.source`, `other_open_cases`; routes from Tasks 7, 8, 10.
- Produces: `officerChangeApi.uploadCaseDocument(id, file, type, sendWithEmail)`, `setSendWithEmail(id, docId, value)`, `resolutionPdf(id)` (blob), `proceed(id, reason)`, `setEffectiveDate(id, entryId, date, itemKey)`, `markChecked(id, signingMethod)`.

- [ ] **Step 0:** Invoke `frontend-design`. The rules box becomes a quiet three-line "After these changes" summary (indigo rule on the left; breach lines in carrot). The attachments card matches `SupportingDocuments`' row style.
- [ ] **Step 1: Failing tests:**
  - The rules panel shows the three lines; a failing rule is visible without expanding; "Show all checks (n)" reveals the rest.
  - With `board.directors` empty, **Close case — pending further instructions** opens `CloseCaseModal` with the reason prefilled verbatim.
  - The attachments card uploads with the tick, toggles `send_with_email`, and the "Attach generated written resolution" tick PATCHes `attach_resolution`. Preview fetches `/resolution`.
  - The drawers save without a date; the hint reads *"Leave blank to fill in the most recent date at Signing."*.
  - An ND2B line shows the anniversary hint when its date equals the default.
  - ND2B waiting for the client shows **Proceed without confirmation**, which asks for a reason.
  - The send card copy mentions the PI sheets; the PDF pill reads "Client copy — full form incl. PI".
  - The change list shows the consent line per director appointment.
  - The ND2B before/after shows addresses as five labelled lines with "(blank)".
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `officerChange.test.jsx api.test.js CloseCaseModal.test.jsx OfficerChangeCasePage.test.jsx` → PASS.
- [ ] **Step 5: Commit** `feat(nd2-ui): client verification — compact rules, close pending, attachments, PI copy, waiver (A3, A6, A7, A8, B1, BQ1)`.

---

### Task 15: Frontend — Data Verification, Signing, Submission (ND2 and NAR1)

**Files:**
- Create: `frontend/src/components/officerChange/ManualChecks.jsx`, `frontend/src/components/officerChange/EffectiveDatesPanel.jsx`, `frontend/src/components/case/OtherOpenCases.jsx` (+ test)
- Modify: `StageDataVerification.jsx`, `StageSigning.jsx`, `StageSubmission.jsx` (officerChange), `workflow.js` (`stageIndexFor`), `frontend/src/components/case/StageSubmission.jsx` (NAR1), tests in `officerChange.test.jsx`, `frontend/src/components/case/stages.test.jsx`

**Interfaces:** Consumes composite `manual_checks`, `dates_missing`, `entries[].eservice.id_mismatch` / `route.consents[].id_mismatch`, `other_open_cases`, and the routes from Tasks 3, 6 and 9.

- [ ] **Step 0:** Invoke `frontend-design`. Manual checks follow the mock-up on p. 25: green-tinted row when done, checkbox mark, bold label, muted "Attached: file · uploaded date · Replace".
- [ ] **Step 1: Failing tests:**
  - Data Verification lists every check from `manual_checks`; a document check has Attach/Replace; Validate / Mark-as-checked are disabled while a check is open, and the reason prints beside them.
  - On e-Sign with `dates_missing`, the button reads **Continue to Signing** and calls `markChecked(id, 'esign')`.
  - The Signing (manual) dates panel is shown when `dates_missing` is non-empty; Upload is disabled until the dates are entered; entering a date calls `setEffectiveDate`.
  - Signing (e-Sign) with `data_checked_at` and not validated shows **Validate with CR** before **Apply signatures**.
  - The id-mismatch warning is shown on Signing.
  - `stageIndexFor` gives 3 for an e-Sign case with `data_checked_at` and no validated filing.
  - The ND2 and NAR1 Submission stages render `OtherOpenCases` with a link per case; nothing when the list is empty.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** The consent wording on Data Verification follows spec §2.2. The "option A / option B" text no longer exists anywhere (`grep -rn "option A" frontend/src` is empty).
- [ ] **Step 4: Run** the officerChange tests, `case/stages.test.jsx` and `OtherOpenCases.test.jsx` → PASS; then the whole frontend suite → only the 3 pre-existing `.env` failures.
- [ ] **Step 5: Commit** `feat(nd2-ui): manual checks, dates at signing, open-case alert at submission (A1, A4, AQ3, N1)`.

---

### Task 16: Documentation, full verification, review

**Files:**
- Modify: `CLAUDE.md` (one block under the ND2 notes: deferred dates, e-consent public route rules, PI sheets now emailed, HKID NIL, manual-check gating), `docs/superpowers/specs/2026-10-02-nd2-jacqueline-feedback-design.md` (status line)

- [ ] **Step 1:** Run the full backend suite → `0 failed`. Run the full frontend suite → only the 3 known `.env` failures. Run `npm run build` → OK.
- [ ] **Step 2:** Whole-branch review against the spec (superpowers:requesting-code-review), from `26647d8` to HEAD. Fix findings, each with a test.
- [ ] **Step 3: Commit** `docs(nd2): Jacqueline's feedback — notes for the next person`.

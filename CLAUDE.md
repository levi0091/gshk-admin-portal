# G-FlowDesk — Admin Portal (gshk-admin-portal)

Claude Code working instructions for this repo. Read this fully before touching any code.

<!-- ── SHARED BA MEMORY ─────────────────────────────────────────────── -->
<!-- Pull in project-wide context the BA maintains in the parent workspace. -->
<!-- Always read these before starting any feature work.                   -->
@../CLAUDE.md
@../gshk/CLAUDE.md
@../memory/terminology.md
@../memory/people.md
@../memory/gshk/context.md
@../memory/gshk/audit-system.md
<!-- ─────────────────────────────────────────────────────────────────── -->

---

## What this repo is

The G-FlowDesk Admin Portal — a ZenexFlow-built internal tool for GSHK's data resources team. Automates the HK company incorporation and NAR1 renewal workflow. This is an **internal-only** portal; GSHK staff are the users, not clients.

**Client:** GSHK (Get Started HK Limited)
**Delivery:** ZenexFlow (levi@zenexflow.com)

> **This repo's production branch is `master`**, not `main` — wherever this file says `main`, read `master`. `dev` auto-deploys to DEV, `master` to PROD.

---

## Working with the crew (subagents) on this repo — COST RULES (Levi, 2026-10-27)

Agents are expensive here: every dispatched agent loads this file and re-reads the same large modules (`services/tpsi/filings.py` ~1,900 lines, `routers/tpsi.py`, `routers/cases.py`). The NAR1 duplicate-submission fix used ~670k developer tokens over three review rounds on a single ticket. Operating card: `docs/agents/crew.md` (committed). Rules:

1. **Crew is for L/XL work only** — several independent tickets or a release gate. Small and medium fixes, merges and migrations are done **inline** by the main session; a bug is a failing test plus a fix, not a dispatch chain.
2. **Fan out by seam, or don't dispatch.** The `bug` and `S` routes run one developer by design. For multi-layer work use `M`/`L` and cut tickets by seam, each owning its files: (a) migration + audit codes, (b) backend service/router, (c) frontend, (d) tests/regression harness. Two tickets may not edit the same file. A ticket should fit ~150k tokens; if it touches more than ~8 files, split it.
3. **One review round.** Dispatch `crew:reviewer` once per ticket. Fixes for blocking findings are applied inline by the main session; a second reviewer pass only if a blocking finding touched a migration, money or auth path. Nits go to release notes, not another round.
4. **Keep context small.** Briefs are context pointers (paths, line ranges, SHAs), never pasted content. Agents read the ranges they need, not whole files; broad reads go to an `Explore` agent that returns a conclusion. Run targeted tests while working and the full suites **once**, at the end.
5. **Pick the model per dispatch** (`model` on the Agent call): `developer` and `reviewer` on `sonnet`, `opus` for a reviewer only on migrations, auth or money paths; `qa-engineer`, `release-manager`, `infra-engineer` on `haiku` unless they must write non-trivial tests. Do not dispatch `skill-scout` unless asked.
6. **Say what it will cost first.** Before dispatching anything expected to exceed ~200k tokens, or resuming a long agent, tell the user and let them choose inline vs agent. Never resume a stopped agent silently.

---

## Architecture

| Layer | Tech | Notes |
|-------|------|-------|
| Frontend | Vite + React | Hosted on Cloudflare Pages |
| Backend API | Python + FastAPI | Hosted on Railway |
| Dependency mgmt | uv | `pyproject.toml` + `uv.lock` — use `uv` for all installs, never bare `pip` |
| Backend testing | pytest | Every backend feature ships with unit tests — no exceptions |
| Frontend testing | Vitest + React Testing Library | Every React component/hook ships with tests |
| Database | Supabase (PostgreSQL) | Auth via Supabase Auth (email/password) |
| DB Migrations | Alembic | All schema changes via Alembic migrations — never edit schema manually |
| Email | **Resend** | Transactional emails — client verification, notifications. Sends from **`no-reply@getstarted.hk`** via the client's Resend account. **Working as of 2026-08-30:** Levi supplied a real `RESEND_API_KEY`, `getstarted.hk` is **verified** at Resend (`sending: enabled`, region `ap-northeast-1`), and a live send has been made end to end. |

> **Detail lives in `notes/email-and-test-environment.md`** — read it before changing email sending, the test-environment recipient lock, DNS probe, delivery polling, the verification letter, revisions, password reset, middleware order. What it holds, by headline:
> - `APP_ENV` is the single switch, and it is invisible from outside Railway.
> - MIDDLEWARE ORDER IN `main.py` IS LOAD-BEARING, and it reads backwards.
> - The test-environment recipient lock (Levi 2026-08-30).
> - `EMAIL_TRANSPORT` was REMOVED on 2026-08-30.
> - THE COPY IS `renewal@getstarted.hk`, AND THE CASE WORKER IS NO LONGER CC'd
> - It is on EVERY message, where the case worker's copy was on the first only.
> - `reply_to` is still the case worker, deliberately — but it is now the SAFETY NET, not the asked-for path.
> - The screen names the address, and a test stops the two drifting.
> - A CC is a recipient, so the non-production lock binds it too
> - Resend answers 200 for an address that cannot exist, so the send probes DNS first
> - It runs after both recipient branches, on purpose.
> - SILENCE IS PERMISSION.
> - What the pre-send check cannot do
> - Delivery is POLLED, not pushed — there is no webhook, and that is deliberate
> - The status vocabulary is Resend's `last_event`, sorted into three answers.
> - UNCERTAINTY IS ALWAYS "PENDING", NEVER "FAILED"
> - `GET /cases/{id}/verification/delivery`
> - The per-recipient map lives in `metadata.deliveries`
> - The Send button opens a sending splash, and it is time-bounded on purpose
> - It never blocks indefinitely.
> - A REDIRECTED SEND IS NEVER REPORTED AS DELIVERED, and this is the subtlest trap on the whole path.
> - So bounce detection cannot be exercised on DEV
> - The splash opens on the CLICK, not on the response.
> - No unit test may resolve a real domain.
> - The client-facing email is table-based with inline styles, on purpose
> - Its wording is `docs/Auto email - NAR1 Review_v2.pdf`, verbatim
> - THE "NO LINK AT ALL" RULE IS REVERSED
> - The reply path is no longer what the client is TOLD to use
> - The client's confirmation page shows the approved Warning panel
> - The client's deadline is MANDATORY and the case worker picks it
> - A malformed address no longer refuses the whole send
> - Every verification email after the first carries `[Rev. N]`, and an earlier revision's Confirm link is dead
> - SEND AGAIN RE-SENDS THE FROZEN COPY, UNDER THE SAME REV
> - A REVISED LETTER HAS ITS OWN WORDING
> - Two locks on the old link.
> - One message per recipient, not one message with several recipients.
> - The confirmation names the account by EMAIL.
> - `GET /auth/super-admins` is unauthenticated, and that is the point.
> - Confirm & File mails the client a RECEIPT (ND2, Levi 2026-10-17)
> - Three ND2 follow-ups (migration 055): a death asks for its date; secretary drawer lists GSHK first; e-Sign saves the signed form
> - ND2A / ND2B after Jacqueline's feedback (migrations 052, 053): the chain is `049 → 051 → 056 → 050 → 052 → 053 → 054 → 055 → 057`; blank effective dates; CR's consent signature IS the consent; the resolution is GSHK's own sample; manual checks gate Data Verification; identification and addresses are per COMPANY; an ND2B filed for one company stops the same change being reported for others

| AI | Claude API | Called from Railway backend only — never from frontend |

### URLs

| Environment | Frontend | Backend API |
|-------------|----------|-------------|
| DEV | `https://admin-dev.g-flowdesk.com` | `https://api-dev-admin.g-flowdesk.com` |
| PROD | `https://admin.g-flowdesk.com` | `https://api-admin.g-flowdesk.com` |

> **PROD's API hostname is `api-admin`, NOT `api-prod-admin`.** This table said the latter until 2026-09-08; it has never resolved (NXDOMAIN), while `api-admin.g-flowdesk.com/health` answers 200 with `"environment": "production"`. Verified again the day this was corrected. The wrong name is the kind that costs an hour, because a dead hostname looks exactly like a service that is down.

### Repo structure (target)

```
gshk-admin-portal/
├── frontend/          # Vite + React app (Cloudflare Pages)
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── lib/       # Supabase client, API helpers
│   │   └── main.jsx
│   ├── index.html
│   └── vite.config.js
├── backend/           # FastAPI app (Railway)
│   ├── main.py        # App entry point
│   ├── routers/       # One file per feature module
│   ├── services/
│   │   ├── audit_service.py   # << CROSS-CUTTING — see below
│   │   └── email_service.py
│   ├── middleware/
│   │   └── auth.py            # JWT validation + require_permission
│   ├── db/
│   │   └── supabase.py        # DB client init
│   ├── migrations/            # Alembic — all schema changes live here
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       ├── 0001_create_users_roles_permissions.py
│   │       ├── 0002_seed_super_admin_role.py
│   │       └── 0003_create_audit_log.py
│   ├── alembic.ini
│   ├── pyproject.toml     # uv — source of truth for dependencies
│   └── uv.lock            # committed — do not edit manually
└── CLAUDE.md
```

### Branch strategy

- `dev` → auto-deploys to DEV (Cloudflare Pages + Railway DEV service)
- `main` → auto-deploys to PROD
- Feature work goes on `dev`. Never push directly to `main`.

### Worktrees — the default for any new piece of work

**Start every new task in its own git worktree, branched from `dev`.** Not just when the tree is dirty — always. Claude Code sessions run concurrently, and two of them sharing one checkout is the failure this rule exists to prevent: one session's `git checkout` moves the branch under another session's feet, an in-flight edit gets stashed by someone else's rebase, and a half-finished refactor ends up in an unrelated commit. This has already bitten us — a PRD could not be committed because another session had uncommitted `nar1_form/fill.py` work in the shared checkout.

```
Use the EnterWorktree tool (name it for the task, e.g. registry-form-fidelity).
It creates .claude/worktrees/<name>/ and switches the session into it.
```

**`origin/HEAD` is unset on this repo and `master` != `dev`**, so a worktree may be created from the wrong base. Always re-point it immediately after creating one, before any work:

```bash
git fetch origin dev && git reset --hard origin/dev
```

Then set the worktree up — it does **not** inherit the parent checkout's dependencies or secrets:

```bash
cd backend  && uv sync          # .venv is per-worktree
cd frontend && npm ci           # node_modules is per-worktree
```

`.env` is gitignored and therefore **absent** in a fresh worktree. Backend unit tests are expected to pass without it — if a test needs `.env` to go green, that test is reaching a live service and is the bug (see the memory note on green-local/red-CI). Scripts that genuinely need credentials (ETL, Viewpoint probes, `scripts/`) must be run from a checkout that has `.env`, or be given one explicitly.

Run the baseline before writing any code, so a later failure is unambiguous:
`uv run pytest -q` and `npm run test -- --run`.

Leave with `ExitWorktree` (`keep` to preserve the work, `remove` to discard). Never `git worktree add` by hand — the harness cannot see or clean up worktrees it did not create.

---

## Credentials & secrets

**Supabase connection:** `../gshk/secrets/supabase.env` — read this for DB URL, anon key, service role key.
- This file is **local only**. It must never be committed. Ensure `gshk/secrets/` is in `.gitignore` on all repos.
- When doing any DB/migration/query work, load credentials from this file.

**Other secrets** live in Railway environment variables (DEV and PROD services) and must not be hardcoded.

---

## UI — Design system & wireframe

**This is the single source of truth for all Admin Portal UI:**
`../gshk/outputs/wireframes/admin-portal-nar1/wireframe.html`

Open and study the wireframe before building any screen. Do not invent layouts or components — match the wireframe exactly.

**Screens defined in wireframe (8):**
1. Login
2. Dashboard — company list (all companies, full lifecycle — not split by NAR1/NNC1)
3. Case / Company Detail
4. Post-Incorp Data Input Form
5. Client Verification (send email screen)
6. Revision View (case flagged for changes)
7. NAR Submission confirmation
8. Audit Trail (global, permission-gated — `audit_trail:read` required)

> Screens 8 (NNC1 Cases list) and 9 (NAR1 Cases list) were removed from the wireframe on 2026-06-21.
> Companies are now managed through their full lifecycle from a single Dashboard screen.

> **The case workflow stepper has FIVE stages again — CR Status is gone** (Levi 2026-10-17, reversing 2026-09-16). From September a sixth stage showed what CR's register said about a filed return, coloured its medallion by CR's answer (`stageTone`, `.step.tone-*`) and had a third badge family (`bc-*`). CR will not report a document's status after filing, so Confirmation — the receipt — is the last stage again for NAR1, ND2A and ND2B; a filed case opens on it with every stage ticked, and `.stepper` is `repeat(5, 1fr)`. Two badge families remain: `bw-*` (where the case is with GSHK; a filed case is `bw-filed`, green, label **Filed**) and `bf-*` (where the document got to in our own CR chain). `--peridot-ink` stays — the ND2 rules panel uses it.

**When building UI — use the `frontend-design` skill in Claude Code:**
The `frontend-design` skill is available in Claude Code and must be used when generating new screens or components for the Admin Portal. Reference the wireframe HTML as the design spec. All output must match the brand tokens below verbatim.

**Brand tokens (hardcode these — do not deviate):**

```css
--font: 'Outfit', sans-serif;            /* Google Fonts */
--indigo:   #242C66;   /* Primary / nav background */
--carrot:   #F36C32;   /* Accent / CTA */
--bg-page:  #F5F6FB;   /* Page background */
--bg-card:  #FFFFFF;   /* Card / panel background */
--t-head:   #1A2050;   /* Heading text */
--t-body:   #3A4060;   /* Body text */
--t-muted:  #7C80A3;   /* Labels / muted text */
--border:   #E2E4ED;   /* All borders */
--bang:     #027248;   /* Success / approved */
--peridot:  #FEE000;   /* Warning */
--carrot-10:#FEF0EB;   /* Accent tint (hover states, badges) */
--bang-10:  #E6F1ED;   /* Success tint */
```

### The visual standard (Levi 2026-10-30)

> **Eight font sizes and no others:** 10 uppercase labels, 11 hints and badges, 12 secondary text, 13 body and buttons, 14 emphasis, 16 modal titles, 20 page titles, 26 big numbers. No half-pixels.
>
> **One error red, `--danger` (`#B91C1C`).** `#C53030` was also in use and fails AA on its own tint (4.48:1). Reds and carrot-as-text come from `--danger*` and `--carrot-ink`, never a hex in JSX. `--carrot` stays a fill, the same reasoning as `--peridot-ink`.
>
> **An alert is `.alert.al-{info,success,warn,danger}`**, and `.alert::before` draws the tone's icon, so `.al-icon` glyphs are not shown. A load failure or a refused action is `al-danger`, a modal's refusal is `.modal-error` (last in the body, beside the button that caused it), a field's is `.f-error` with `aria-invalid` on the control. `.card-note` stays the quieter note that belongs to its card. Do not hand-roll a box with inline styles.
>
> **Spacing under a block:** 12px under a control row (tabs, toolbars), 16px under an alert or note. **Buttons:** `btn-sm` 30, default 36, `btn-lg` 44. A control row's hint is centred on its buttons, with the buttons on the right.
>
> **Left at brand values on purpose:** `--t-muted` text (3.84:1 on white) and small carrot labels such as "IN PROGRESS" and the required asterisk (3.0:1) both miss AA. They are verbatim brand tokens, so changing them is Levi's call.
>
> **ND2's single send offers Send again, as NAR1 does:** it mails the frozen `verification_xml` under the same revision and leaves the CR filing alone; a correction goes through Restart verification.

### Profile-screen conventions (the 2026-09-04 pass)

> **Detail lives in `notes/profile-screens.md`** — read it before changing the company/person profile screens, document sections, party pickers. What it holds, by headline:
> - Add and Edit offer the SAME fields, on both profiles.
> - Every field an editor can write must be rendered somewhere read-only.
> - `.f-group` is a COLUMN flex box — never put a button pair in one.
> - Documents render through `components/DocumentSections.jsx` on both profiles
> - OPEN, FOR LEVI TO SETTLE.
> - A share transfer is `is_current = false` on the outgoing holder, never a DELETE
> - A party picker is never a free-text id.

---

## Cross-cutting rules — MANDATORY on every PBI

These apply to **every** feature built in this repo without exception. They are not optional and are not limited to the PBIs that introduced them.

### 1. User Access Management (UAM) — PBI-12

Every API endpoint must be protected by the `require_permission(module, permission)` decorator from `middleware/auth.py`.

```python
# Every route handler follows this pattern:
@router.get("/companies")
async def list_companies(user=Depends(require_permission("companies", "read"))):
    ...

@router.post("/companies/{id}/submit")
async def submit_company(user=Depends(require_permission("companies", "write"))):
    ...
```

**Rules:**
- `read` permission → can view data in that module
- `write` permission → can create/update/trigger actions (including TPSI submissions) in that module
- Super Admin role bypasses all permission checks
- No endpoint may be left unguarded — unauthenticated or unauthorised access must return 401/403
- When adding a new module (e.g. `nnc1_data`), register the module identifier and seed role permissions in the DB before shipping

**Module identifiers (snake_case):**
| Module | Identifier | Permitted permission levels |
|--------|-----------|----------------------------|
| Companies | `companies` | `read`, `write` — **including the company's documents** |
| Persons | `persons` | `read`, `write` — **including the person's documents** |
| NAR1 | `nar1` | `read`, `write` |
| NNC1 Data | `nnc1_data` *(future)* | `read`, `write` |
| TPSI | `tpsi` | `read`, `write`, `submit` |
| Audit Trail | `audit_trail` | `read` **only** — no write or admin level exists |

> **Detail lives in `notes/uam-documents-module.md`** — read it before changing document permissions or the module list. What it holds, by headline:
> - `documents` IS NOT A MODULE (migration 040, Levi 2026-09-07).
> - `nar1` (migration 021)
> - The shared CR presenter credential is `super_admin` only
> - A NAR1 is signed with the logged-in user's own e-Service credential and no other
> - A READ MAY REPAIR A STALE SUBMIT CLAIM, and that is not a breach of "read means read"

### 2. Audit Trail — PBI-11

Every write operation must call `audit_service.log_event()` **before** returning a success response. No silent data changes.

```python
from services.audit_service import log_event

# Example — field edit
await log_event(
    case_id=case_id,
    user_id=user.id,
    user_display_name=user.display_name,
    action_type="CASE_FIELD_UPDATED",
    entity_type="case",
    entity_id=str(case_id),
    before_state={"field": "client_full_name", "old": old_value},
    after_state={"field": "client_full_name", "new": new_value},
)

# Example — TPSI submission attempt
await log_event(
    case_id=case_id,
    user_id=user.id,
    user_display_name=user.display_name,
    action_type="TPSI_SUBMISSION_ATTEMPTED",
    entity_type="tpsi",
    entity_id=str(case_id),
    metadata={"endpoint": "submitFormNar1", "response_status": response.status_code},
    # Strip credentials before logging — never log JWT tokens, passwords, or PINs
)
```

**Audit scope:** workflow events and base data changes for NAR1, NNC1, and entity (company/case) records only. User management events (login, deactivation) and read-only operations are **not** audited.

**Audit event types:**

| `action_type` | Scope | When to fire |
|--------------|-------|-------------|
| `CASE_STATUS_CHANGED` | Entity | Any case/company workflow status transition |
| `CASE_FIELD_UPDATED` | Entity | Any edit to a case data field — one entry per changed field |
| `AML_STATUS_CHANGED` | NAR1 / NNC1 | Admin updates AML screening status |
| `DOCUMENT_GENERATED` | NAR1 / NNC1 | Any document (AoA, FWR, NNC1, CoI, NAR1) generated |
| `EMAIL_SENT` | NAR1 / NNC1 | Any workflow email sent — **Resend**, via `services/email_service.py` |
| `TPSI_SUBMISSION_ATTEMPTED` | NAR1 / NNC1 | Before calling any TPSI submit endpoint |
| `TPSI_SUBMISSION_SUCCESS` | NAR1 / NNC1 | On successful TPSI response |
| `TPSI_SUBMISSION_FAILED` | NAR1 / NNC1 | On TPSI error |
| `CLIENT_APPROVAL_RECEIVED` | NAR1 / NNC1 | Client Yes/No response recorded |
| `TPSI_CRED_SET` | TPSI | A user's own CR credential first stored (migration 016) |
| `TPSI_CRED_ROTATE` | TPSI | A user's own CR credential replaced (migration 016) |
| `TPSI_CRED_CONFIG` | TPSI | The **shared** presenter credential set or rotated (migration 020) |
| `NAR1_MANUAL_SIGN_UPLOADED` | NAR1 | A wet-signed NAR1 scan uploaded against a case (migration 021) |
| `NAR1_MANUAL_RECEIPT_ENTERED` | NAR1 | An off-portal CR receipt recorded on a case (migration 021) |
| `NAR1_MANUAL_SUBMISSION_RECORDED` | NAR1 | A filing made off-portal declared complete (migration 021) |
| `NAR1_CASE_CLOSED` | NAR1 | A case ended because the client is not proceeding (migration 039) |
| `TPSI_DOC_STATUS_CHECKED` | TPSI | `docStatusEnquiry` asked about a filed return (migration 043). **No longer written** since the CR status poll was removed (054); seeded and labelled because rows exist |
| `NAR1_CR_STATUS_CHANGED` | NAR1 | CR's answer about a filed return moved (migration 043). **No longer written** (054); kept for the rows that exist |

> **Detail lives in `notes/audit-trail-details.md`** — read it before changing audit codes, audit_subject, the CLOSED case status, CR status removal, audit search indexes. What it holds, by headline:
> - A case can be CLOSED, and closing it is permanent
> - CLOSED is the eighth workflow status and the FIRST branch
> - Closing refuses a case CR already holds
> - Every write on the case then refuses with a 409 carrying `reason: "case_closed"`
> - THE WORKFLOW ENDS IN CR'S ANSWER, NOT IN A WORD OF OURS
> - CR's `documentStatus` vocabulary is OPEN, and that is a measurement.
> - THE URL SEGMENT AND THE OPERATION ARE DIFFERENT WORDS — `docStatusEnquiry` vs `cr:enquireDocStatus`
> - A CR FAULT WITH NO FAULT BEANS IS A 422, NOT A 502.
> - AN EMPTY `documentList` MEANS CR KNOWS THE CASE AND HAS LISTED NOTHING — IT IS NOT A BAD CASE NUMBER.
> - A SKIP STILL RECORDS `cr_status_checked_at`.
> - `trg_set_updated_at` OVERRIDES YOUR PATCH — IT IS `NEW.updated_at = now()`, UNCONDITIONALLY
> - `now()` IS THE TRANSACTION TIMESTAMP, so a DB test comparing it against itself proves nothing.
> - The four columns live on `nar1_cases`, not `tpsi_filings`
> - A CR rejection is NOT `submission_failed`.
> - New audit codes must be seeded into `audit_event_types` by a migration
> - Every audit row says WHICH MODULE and WHICH RECORD
> - Nothing needs to restate what `entity_type` already says.
> - THE MODULE FOLLOWS THE SUBJECT, AND THERE IS NO `documents` MODULE
> - `audit_log.case_id` keeps its meaning: it is the ENTITY id
> - Viewpoint history is backfilled by `python -m etl.backfill_audit_context`, not by the migration.
> - `ILIKE '%x%'` needs a trigram index, and the audit search had none
> - `subject_kind` is deliberately not filterable.

**Rules:**
- `audit_service.log_event()` failures must NOT block the primary operation — wrap in try/except and log to stderr
- Never log TPSI credentials: strip `Authorization`, `password`, `pin`, `token` from request/response before passing to audit log
- `CASE_FIELD_UPDATED` entries record field name + old + new value. Multi-field saves produce one log entry per changed field.
- Audit log is insert-only — no UPDATE or DELETE on `audit_log` table ever

### 3. CR field fidelity — the form contract owns what CR requires

**`backend/services/cr_forms/contract.py` is generated and committed, and it is the only answer to "does CR want this field, and how long may it be?"** It is built from CR's own worksheet by `scripts/build_cr_form_contract.py`; regenerate it rather than hand-editing, so a CR revision arrives as a reviewable diff. `tests/test_cr_form_contract.py` fails if any of the 294 NAR1/NNC1 leaf fields lacks a **disposition** (`mapped` / `derived` / `form_instance` / `unsourced`), if a `mapped` column is missing from the schema, or if a `form_instance`/`unsourced` entry has no written reason. **An omission has to be a decision somebody made, not a field nobody noticed.**

`GET /form-contract` serves the `mapped` subset — strictest length, mandatory-anywhere — and **both profile screens read their `maxLength`, required markers and highlighting from it** (`frontend/src/lib/formContract.js`). Do not hardcode a CR length or a required flag in a screen; the two would drift and the way you would find out is a rejected filing.

> **Detail lives in `notes/cr-field-fidelity-details.md`** — read it before changing CR vocabularies, lookups, country/currency fields. What it holds, by headline:
> - One owner per vocabulary.
> - This has now bitten twice, and the second time reached a real case.
> - Country fields are keyed by ISO alpha-2
> - Three vocabularies served from `/lookups` are NOT CR's, and their names say so
> - `cr_currency` is pinned before it is sorted:
> - "Present" is not "filable" — validate resolvability, not emptiness.

**Two levels of refusal, and they are not the same.**

- **Highlighting** (carrot, non-blocking): a mapped field that is mandatory-and-empty or over CR's length. The save still proceeds — most of these came out of Viewpoint that way, and refusing to store them would mean refusing to show them. `unsourced` fields are never highlighted.
- **Blocking** (`services/cr_forms/readiness.py`): **only** fields CR marks `Mandatory = Y`. This gates the **Open case** button, and as of 2026-09-02 it stops **457 of 5,930 client companies** — 252 with no registered-office country, 219 with no share class, 4 whose share class lacks `issued_amount`. That is deliberate (PRD OQ-2): it converts a failure discovered at CR, after a chargeable and irreversible submit, into one visible on the profile. **The reason prints beside the button**, never only in a page banner.

> Business nature is the field the blocking rule exists to keep out. It is `M=N` on both forms and Viewpoint holds none for any of its 5,028 rows, so blocking on it would freeze the entire book over something CR does not require.

**Grandfathering is the pattern for validating legacy columns.** `company_type` (CR's `P`/`N`/`G`), `owner_type`, `nature_of_control` and HKID check digits are all enforced on write **only when that field is itself being written**, and the value already stored is always allowed back. A bad legacy value must never block an unrelated edit. Creation is stricter than editing — a new row has no legacy to protect, so `POST /companies` takes only CR's codes.

> **An empty string on the wire CLEARS a column; `None` means "not mentioned"** (`PATCH /companies/{id}`, 2026-09-04). The profile used to drop `v === ''` before sending, so deleting a value and pressing Save did **nothing at all** and looked exactly like a save that worked — the old value came back on the next load. A blank is a real answer: a company can stop having a Chinese name, and a CR number typed into the wrong box has to be removable. `""` is normalised to `NULL` **once, before every validator**, or clearing Business Nature would be refused as an unknown CR code; clearing the code clears `business_nature_desc` with it, because the description is derived from the code and cannot outlive it.

> **`PUT /companies/{id}/company-phone` exists because `company_phone` was write-once.** It was accepted by `POST /companies`, written into `contacts`, printed on the profile — and then unreachable by any endpoint or control, so a number mistyped on the New Company form was permanent. Its own route rather than a field on `PATCH /companies`, for the same reason the registered address has one: it writes a different table. **`contacts.contact_value` is `telNo` at 8 characters in the contract and the mapper does not currently emit it** — the stored value carries the dial code (`+852 3500 1234`), so whoever wires `telNo` must strip it rather than assume the column fits.

`scripts/registry_reconciliation.py` (read-only, needs `.env`, never CI) prints what GSHK has to fix by hand: the blocked companies, the 31 identity documents whose number is not what its type says, and the fields that ship empty because nobody has the data. **It calls `filing_problems()` rather than reimplementing the rule in SQL** — a report that counts blocked companies differently from the code that blocks them is worse than no report.

### 4. The rendered NAR1's typography comes from a FILED return, never from the template

**`docs/Kanenas Holding Limited NAR1 2026.pdf` is the authority for how the generated form looks, and the blank `NAR1_fillable.pdf`'s widget properties are not.** That specimen is **not committed** — `docs/` is gitignored and it carries a real director's name, address and passport number — so the measurements are transcribed into the tests as constants rather than read from it at test time. CI never needs the file. `/DA` and `/Q` on that template are what Acrobat wrote for someone typing into the form by hand. They are not what CR's filing system prints, and taking them as a measurement has now cost two round-trips with the client.

The proof is in the template itself: **287 of its 298 text widgets carry an identical `/DA "/PMingLiU 12 Tf"`** — including the BR-number header CR prints at **14pt** and the presenter's block CR prints at **10pt regular**. A default wrong in both directions is not a measurement. `/Q 1` (centre) is on the business name, the mortgages box, every officer's name and every address line; CR **left-aligns all of them**.

What was measured off the filed return, and is now asserted end-to-end in `tests/test_nar1_specimen_geometry.py`:

| | |
|---|---|
| every ordinary value | Times New Roman **Bold, 10pt** |
| section 1, the company name | 12pt |
| the BR number in each page header | 14pt |
| the presenter's block | 10pt, **regular** — weight is the whole difference |
| a schedule's page numbers | the page FOOTER's **sans** face at 8pt, the only values not in Times |
| a left-aligned value | starts **10.3pt inside the printed rule** (9.4pt inside the widget `/Rect`, which sits 0.95pt inside its rule) |
| a centred value | centred on the box, for the fields in `fill.CENTRED_FIELDS` and no others |
| a single line's baseline | `y0 + (box height − 0.72 × size) / 2` |

**The face was never the problem.** Over 648 glyph advances on the specimen, Tinos differs from CR's embedded Times New Roman by at most 0.15pt and on average 0.03pt — the rounding in CR's own `/Widths`. If a value looks wrong, check the **size** first. `appearance.da_size()` and `_auto_size()` were deleted rather than left unused, precisely so nobody wires `/DA` back in.

**There is no rule to derive for alignment** — the same word, "Ordinary", is centred in section 11's table and left-aligned in Schedule 1's header. `fill.CENTRED_FIELDS` lists CR's layout group by group; extend it from the specimen, never from `/Q`.

**The Date beside the signature is the day CR RECEIVED the return, and is EMPTY until it has** (Levi 2026-09-22). An anniversary of 26 October and a filing on 1 November prints **01/11/2026**. `render(submitted_on=...)` — renamed from `signed_on`, so the old name cannot be passed by muscle memory — and every one of the four callers resolves it through **`nar1_cases.filed_on(filing, case)`**, never by reading a column itself.

> **Detail lives in `notes/nar1-rendering.md`** — read it before changing the rendered NAR1 (dates, presenter reference, flat PDF). What it holds, by headline:
> - This reverses "an absent value means today in Hong Kong"
> - Not `signed_at`.
> - Hong Kong, not UTC

**A box CR fills that the renderer used to leave empty** (Levi 2026-09-04), now filled by `fill.py` rather than by a caller that has to remember:

- **The presenter's Reference.** Now `NAR1/<year>/<company name>`, where the year is the **return's own made-up-to year** and not the calendar year — a 2026 return filed late in 2027 is still the 2026 return. The box is one line, 158.1pt usable, so a long name is **shortened on a word boundary with `...`** rather than handed to `layout()`, which would shrink it toward its 4pt floor with no second line to escape into. `PRESENTER_REFERENCE_MIN_SIZE = 7.0` is the floor for that fitting; a test re-measures the box off the template so a new revision fails rather than overflows.

**"Date to which this Return is Made Up" is CR's to write, and before CR has, it is the incorporation anniversary** (Levi 2026-09-18). `dateReturnMadeUp` is *"filled in by system after Web-Form validation"*: CR's validate example omits it and its submit example carries it. Do **not** add it to the mapper, since `request_xml` follows CR's validate example. When Client Verification became stage 1, the client started getting `request_xml`, and section 4, the Schedule 1 header and every continuation-sheet header went out **blank**. `fill.made_up_date()` now prints CR's value when there is one, and otherwise the incorporation anniversary in the return's own `yearAnnualReturn`, computed by `fees.return_date_for`, the same function the late fee and the early-filing gate use. On DEV it matched CR's own date on 41 of 41 validated filings. **Every `render()` caller must pass `incorporated_on=entity.get("incorporation_date")`**, which is not in the XML. `nar1_cases.entity_for` selects that column, and a test pins it, because route tests patch `entity_for` wholesale. With no incorporation date the boxes stay empty rather than invented.

**The shipped return is FLAT — it carries no form fields at all** (Levi 2026-09-14). `appearance.bake()` draws every value into the page and then **removes** every widget and the AcroForm. It used to only set each widget's Hidden flag, leaving `/V`, the template's `/Q 1` and a `/PMingLiU 12` appearance stream in place; desktop viewers honour Hidden, **iOS Quick Look does not**, and on a phone every value printed twice — ours, and a centred 12pt copy on top. **Never bring a field back into anything a client or CR sees.** `bake()` refuses (`AppearanceError`) a widget holding a value it cannot draw, rather than delete it silently. Tests that need a value's box or `/V` use `fill.render_fields()` — the same return before baking, which must never be sent to anybody. The removed widgets are swept by re-cloning from the root: pypdf's `compress_identical_objects(remove_unreferenced=True)` is one pass and kept all 222 of them.

### PRD requirement for new PBIs

Every PRD for a new PBI must include:
- **(a)** Which module identifier + permission level (`read`/`write`) the new endpoints require
- **(b)** Which new `action_type` values the PBI introduces to the audit log

---

## Build order

Start here. Do not build NAR1 or NNC1 features until this foundation is in place:

1. **PBI-12 first** — DB schema (`users`, `roles`, `role_permissions` tables + RLS), Supabase Auth integration, `require_permission()` middleware, user management API endpoints and UI
2. **PBI-11 second** — `audit_log` table + RLS, `audit_service.py` module, audit trail API endpoint and UI tab on case detail
3. Smoke test: auth works, permission middleware blocks unauthorised requests, audit entries write correctly
4. **Then** begin NAR1 feature work

**PBI-12 DB tables:**
- `users` — id (FK auth.users), display_name, email, role_id (FK), is_active, created_at
- `roles` — id, name (unique), created_at
- `role_permissions` — id, role_id (FK), module (text), permission (text: `read`|`write`)
- Seed: `super_admin` role + first Super Admin user on deploy

**PBI-11 DB table:**
- `audit_log` — id (UUID), created_at (timestamptz, default now()), case_id (FK), user_id (FK auth.users), user_display_name, action_type, entity_type, entity_id, before_state (jsonb), after_state (jsonb), metadata (jsonb)
- RLS: INSERT allowed for authenticated; no UPDATE or DELETE policies

---

## Database migrations — Alembic

**All schema changes must go through Alembic. Never edit schema manually in the Supabase dashboard.**

### Dependency management — uv

Use `uv` for all Python dependency operations. Never use bare `pip install`.

```bash
# Install all deps from lockfile (first time / CI)
uv sync

# Add a new dependency
uv add fastapi
uv add alembic
uv add --dev pytest          # dev-only dep

# Remove a dependency
uv remove some-package

# Run a command in the managed environment
uv run uvicorn main:app --reload
uv run alembic upgrade head
uv run pytest
```

`pyproject.toml` is the source of truth. `uv.lock` must be committed — it pins the exact environment.

### Alembic setup

```bash
uv add alembic
uv run alembic init backend/migrations
```

Configure `alembic.ini` and `migrations/env.py` to read the DB URL from `../gshk/secrets/supabase.env`.

### Workflow for every schema change

> **Windows only:** `uv run alembic` fails with DNS resolution errors on this machine. Always invoke alembic directly from the venv — never via `uv run`.

```powershell
# 1. Generate migration
.venv\Scripts\alembic.exe revision --autogenerate -m "describe_what_changed"

# 2. Review the generated file in migrations/versions/ before applying
# 3. Apply to DEV first
.venv\Scripts\alembic.exe upgrade head

# 4. Verify DEV is correct, then apply to PROD
# (set DATABASE_URL env var to PROD connection string)
.venv\Scripts\alembic.exe upgrade head
```

### Rules
- Migration files are committed to the repo — they are the source of truth for schema history
- Number migrations sequentially: `0001_`, `0002_`, etc.
- Seed data (super_admin role, initial user) goes in a dedicated migration, not application startup code
- `alembic downgrade` in PROD requires explicit sign-off from Ting Yu — flag before running
- Always run against DEV and confirm before touching PROD

---

## TPSI API — critical constraints

- `submitFormNar1` and `submitFormNnc1` are **chargeable and irreversible** — fee deducted from deposit account on submission
- Mandatory order: `validateForm` → `verifyPinSigning` → `submitForm`. Never skip steps.
- Always show PDF preview to admin and require explicit double-confirmation before `submitForm`
- TPSI token valid 30 minutes; one token per account at a time
- Test env: `apitest.cr.gov.hk` (Mon–Fri 10am–4pm HKT only)
- Credentials for TPSI stored in Railway env vars — never hardcoded

> **A NAR1 cannot be submitted before its return date** (Levi 2026-09-07). An annual return reports on the year ending at the company's return date — the anniversary of incorporation **in the return's own year** — so `filings.submit` refuses with `BeforeReturnDate` (a `SubmitGateError`, hence a 409 and a `TPSI_SUBMISSION_FAILED` row) **before any CR traffic at all, including the free balance read**, and before the drift check: "the data moved" is a confusing answer to "you are eleven months early". `preview` reports the same thing as `too_early` + `return_date` so the Submission screen withholds the button and prints the reason instead of arming an irreversible-looking control whose one outcome is a 409.
>
> `fees.annual_return_fee` already treated a future return date as uninterpretable, but that only downgraded the quote to the HK$3,480 ceiling — **the submit went ahead anyway**, so a case opened a year early could be validated, signed and filed, and the first thing to notice would have been CR, after the charge.
>
> **It fails OPEN when the date cannot be computed**, which is the one gate in that file that does. A missing incorporation date or an unreadable return year is not evidence that a return is early, refusing on it would block a filing due today over a blank field, and the fee already degrades to the ceiling for exactly those filings. `filings.return_date_of` returns `None` there, and `too_early` stays `False` while `return_date` is `None` — the screen must not read one as the other.

---

## Unit testing — mandatory on every PBI

**Every feature must ship with unit tests. No exceptions. Tests are part of the definition of done.**

### Backend — pytest

```
backend/
  tests/
    test_auth.py           # require_permission middleware
    test_audit_service.py  # audit log writes, credential scrubbing
    test_cases.py          # case CRUD, field update diffing
    test_users.py          # user management endpoints
    ...                    # one test file per router/service
```

```bash
# Run all backend tests
uv run pytest

# Run with coverage
uv run pytest --cov=. --cov-report=term-missing

# Run a specific file
uv run pytest tests/test_audit_service.py

# Parallel, as CI runs it (~5x faster; not for the RUN_DB_TESTS suite, which shares one DB)
uv run pytest -q -n logical --dist worksteal
```

> **A test id must not depend on a random value.** pytest-xdist collects the suite separately in every worker and refuses to run if the ids differ — `test_declared_signatory_id_is_none_when_no_person_is_named` was parametrized with XML embedding a certificate generated at import, so every worker named it differently. Give such a parametrize explicit `ids=`.
>
> **`tests/tpsi/conftest.py::tpsi_env` shares ONE RSA key per session.** Generating it per test cost ~50ms across ~800 tests — a third of the suite. A test that needs a distinct key uses `make_pem`, which still mints a fresh one per call.

**Rules:**
- Every new route handler gets at least: a happy-path test, a 401/403 test, and an edge-case test
- Every service function (audit, email, TPSI wrapper) gets unit tests with mocked dependencies
- Tests must not hit the real Supabase DB — use mocks or a test DB with fixtures
- `uv add --dev pytest pytest-asyncio pytest-cov httpx` — add these as dev dependencies

### Frontend — Vitest + React Testing Library

```
frontend/
  src/
    components/
      CaseDetail/
        CaseDetail.jsx
        CaseDetail.test.jsx    # co-located with component
    pages/
      Dashboard/
        Dashboard.jsx
        Dashboard.test.jsx
```

```bash
# Run all frontend tests
npm run test

# Watch mode during development
npm run test:watch
```

**Rules:**
- Every component and hook gets a test file co-located alongside it
- Test user interactions (clicks, form submissions) not implementation details
- `npm install --save-dev vitest @testing-library/react @testing-library/user-event jsdom` — add on project init

---

## CI/CD — GitHub Actions pipelines

### Pipeline 1: Push to `dev` — test then deploy

Triggered on every push to `dev`. **Deployment only proceeds if all tests pass.**

```yaml
# .github/workflows/dev.yml
name: Dev — Test & Deploy

on:
  push:
    branches: [dev]

jobs:
  test-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
        working-directory: backend
      - run: uv run pytest --cov=. --cov-report=term-missing
        working-directory: backend

  test-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: npm ci
        working-directory: frontend
      - run: npm run test
        working-directory: frontend

  deploy:
    needs: [test-backend, test-frontend]   # blocked until both pass
    runs-on: ubuntu-latest
    steps:
      - name: Deploy backend to Railway DEV
        # Railway deploy step here
      - name: Deploy frontend to Cloudflare Pages DEV
        # Cloudflare Pages deploy step here
```

### Pipeline 2: PR to `main` — tests must pass before merge is allowed

Triggered on pull requests targeting `main`. **Branch protection rule must require this check to pass — no bypassing.**

```yaml
# .github/workflows/pr-main.yml
name: PR to main — Test gate

on:
  pull_request:
    branches: [main]

jobs:
  test-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
        working-directory: backend
      - run: uv run pytest --cov=. --cov-report=term-missing
        working-directory: backend

  test-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: npm ci
        working-directory: frontend
      - run: npm run test
        working-directory: frontend
```

**GitHub branch protection settings (configure on repo creation):**
- `main`: require status checks `test-backend` and `test-frontend` to pass before merge
- `main`: require pull request — no direct pushes
- `dev`: no force pushes

---

## General rules

- Never commit secrets. `gshk/secrets/` must be in `.gitignore`.
- All business logic lives in the Railway backend. Frontend only calls the backend API — never Supabase directly (except auth token exchange).
- Claude API calls go through Railway backend only.
- Keep DEV and PROD environments fully isolated — no shared secrets, no shared DB.
- Never push to `main` directly. All changes go through `dev` first.

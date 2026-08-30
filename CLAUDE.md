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

> **The test-environment recipient lock (Levi 2026-08-30).** Whenever `APP_ENV` is not exactly `prod`, every message is delivered to a **hardcoded list** — `levi@zenexflow.com`, `roy@zenexflow.com`, `brian@getstarted.hk`, `vanis@getstarted.hk` (`services/email_service.py`, `TEST_RECIPIENTS`) — and to nobody else. It is a module constant, not configuration: the requirement was that it be *impossible*, not merely configured, for a client to be mailed from a test deployment, and DEV's Supabase carries 4,398 real director addresses. **`EMAIL_REDIRECT_TO` has been removed**; setting it again does nothing. The substitution happens inside `send()`, below every caller, and a second assertion re-checks the outgoing list immediately before the HTTP call.
>
> The Client Verification screen still shows and still selects the **real** director addresses — that fan-out is the thing being tested — and carries a note saying nothing will reach the client. The audit row records `intended_to` (the directors) and `to` (the four) separately, so the trail never claims a client was told.

> **`EMAIL_TRANSPORT` was REMOVED on 2026-08-30.** Its only value, `console`, stubbed mail out — stderr, nothing delivered, success reported — and existed solely because `RESEND_API_KEY` was a placeholder. With a real key in place that reason is spent, and protecting clients was never its job (the recipient lock above does that unconditionally). **`resend` is now the only transport, and setting `EMAIL_TRANSPORT` to anything raises at config time** rather than silently sending; the refusal names the removal so nobody hunts for a typo in a value that was correct last week. Audit rows written while it existed still read `transport: "console"`, meaning nothing was delivered, and the router still passes that through — do not normalise it away. **Do not reintroduce it:** if some future environment must suppress mail, suppress it somewhere that cannot report a delivery that did not happen.
>
> One verification email goes to **every current director** with an address on record (`nar1_cases.default_recipients`), not to a single contact. Directors with no address are still returned, carrying the reason, so a three-director board can never render as a two-director board.

> **The case worker is CC'd, and the client's reply is aimed at them** (Levi, 2026-08-30). `POST /cases/{id}/verification/send` copies `user["email"]` — the address from Supabase Auth, added to the resolved identity in `middleware/auth.py` — and sets `reply_to` to the same. **`reply_to` is the load-bearing half:** the message asks the client to reply and is sent from `no-reply@getstarted.hk`, so without it the one action the email requests reaches nobody. Read `user.get("email")`, never `user["email"]` — identities are cached for 30s and one written before the key existed must not break a send.
>
> **A CC is a recipient, so the non-production lock binds it too**: `_apply_test_cc_lock` **drops** it outside prod rather than redirecting (the four `TEST_RECIPIENTS` are already on `to`, and copying them again puts one mailbox on both lines). The guard before the HTTP call checks `to` **and** `cc`. The audit row records `cc` and `intended_cc` separately, so a dropped copy is never logged as a delivered one.

> **The client-facing email is table-based with inline styles, on purpose** (`email_service.verification_email`). Outlook renders mail through Word: no flexbox, no grid, and no `<style>` block you can rely on. Outfit does not load in most clients, so the fallback stack *is* the typography. The message carries **no link at all** — the client confirms by replying, and a mail about someone's company filings that contains a link is the exact shape of the phishing it would train them to trust. Tests in `test_email_service.py` assert each of these; do not "modernise" the markup.
| AI | Claude API | Called from Railway backend only — never from frontend |

### URLs

| Environment | Frontend | Backend API |
|-------------|----------|-------------|
| DEV | `https://admin-dev.g-flowdesk.com` | `https://api-dev-admin.g-flowdesk.com` |
| PROD | `https://admin.g-flowdesk.com` | `https://api-prod-admin.g-flowdesk.com` |

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
| Companies | `companies` | `read`, `write` |
| Persons | `persons` | `read`, `write` |
| Documents | `documents` | `read`, `write`, `delete` |
| NAR1 | `nar1` | `read`, `write` |
| NNC1 Data | `nnc1_data` *(future)* | `read`, `write` |
| TPSI | `tpsi` | `read`, `write`, `submit` |
| Audit Trail | `audit_trail` | `read` **only** — no write or admin level exists |

> The old `nar1_data` module was removed (migration 015) — the portal manages companies through their full lifecycle, and a distinct "NAR1 data" surface was never built. `/auth/me` is gated on authentication only (`require_user`), not a business module, so a role can hold any subset of modules and still log in.

> **`nar1` (migration 021)** gates the NAR1 *case* surface — the case record, its workflow status, client verification, and the manual signing flow. It is deliberately not `companies:*`: a role that may edit a company profile is not thereby entitled to drive a statutory filing. It is **not** a revival of `nar1_data` above, which was a data-entry surface that never existed.
>
> Two NAR1 writes sit on a **different** module on purpose, because they spend money or commit a filing: `POST /cases/{id}/manual-submit` requires `tpsi:submit`, as the e-Sign submit does. See the audit codes below.

> **The shared CR presenter credential is `super_admin` only** (migration 020, decision OQ-C 2026-08-16). One CR filing identity is shared by the whole portal — `GET`/`PUT /tpsi/shared-credential` are gated on the `super_admin` role itself, not on a `tpsi` permission level, so holding `tpsi:write` does not let a user repoint every future filing at another CR account. **This reverses PBI-44's per-user presenter model** (see `PRD/Done/prd-tpsi-integration-nnc1-nar1-2026-07-31.md` §7.3). The **e-Service signing** credential remains per-user — signing is a personal act.

> **A NAR1 is signed with the logged-in user's own e-Service credential and no other** (Levi, Q1 2026-08-30). `POST /tpsi/filings/{id}/sign` takes an **empty body**; `signatory_user_id` and `eservice_password` are declared on `SignIn` only so they can be **refused with a 400** — `extra="forbid"` alone leaks, because FastAPI's 422 echoes the rejected input and would return the signing password. A user with no stored e-Service password cannot sign at all and is sent to CR Credentials. **This withdraws spec D4**, under which a client director supplied their password live at signing.
>
> `filings.sign()` also refuses when the return *names* someone else (`SignatoryMismatch` → 409). That only fires on the natural-person path: CR's worksheet says `selectPersonId` is *"Empty if sign by Body Corporate"*, so for every real GSHK client — whose secretary is GSHK Ltd — the return names the corporate secretary, carries no person id, and the e-Service credential in the `PinSign` block is the only record of which human signed. **Untested against live CR:** this assumes GSHK staff accounts are authorised by CR because GSHK Ltd is the appointed secretary. If CR requires the signing account to be personally appointed (`ERR_MSG_SIGNATORY_NOT_AUTH`), this makes NAR1 unsignable rather than safer.

> `audit_trail` is intentionally read-only at the permission level. Do not add a `write` permission for this module under any circumstances.

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

> `CLIENT_APPROVAL_RECEIVED` was scoped NNC1-only in the original PBI-11 table. BE-3 fires it for **NAR1** too: an admin records the client's Yes/No against the case. The event predates any inbound-mail handling — R1 has none, so a human relays the reply and records it under `nar1:write`.
>
> The three `NAR1_MANUAL_*` codes describe the **off-portal** path, where the return is signed on paper and filed outside the portal. `NAR1_MANUAL_SUBMISSION_RECORDED` is the declaring act and is gated on `tpsi:submit`, because it closes the case as filed exactly as a real CR submission does — and because it makes the e-Sign chain refuse afterwards, so it must not be reachable by a role that could not have submitted in the first place.

> **New audit codes must be seeded into `audit_event_types` by a migration**, with `origin='g_flowdesk'` and `category` set **explicitly** — the column default is `origin='viewpoint'`, which would mislabel every G-FlowDesk code as inherited Viewpoint history. There is **no FK** from the audit rows to this table, so an unseeded code does not fail loudly: it writes fine and then renders unlabelled in the trail. Migration 022 exists because exactly that happened to `CASE_STATUS_CHANGED` and `CASE_FIELD_UPDATED`.

**Rules:**
- `audit_service.log_event()` failures must NOT block the primary operation — wrap in try/except and log to stderr
- Never log TPSI credentials: strip `Authorization`, `password`, `pin`, `token` from request/response before passing to audit log
- `CASE_FIELD_UPDATED` entries record field name + old + new value. Multi-field saves produce one log entry per changed field.
- Audit log is insert-only — no UPDATE or DELETE on `audit_log` table ever

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
```

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

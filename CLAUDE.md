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

> **`APP_ENV` is the single switch, and it is invisible from outside Railway.** Set it to exactly `prod` only on the PROD services. Anything else — including unset — is non-production, which is the safe direction. **`GET /health` reports the derived answer** (`"environment": "production" | "non-production"`), unauthenticated, so this is checkable in one request without a token or Railway access. Check it after every deploy: on 2026-08-30 the **DEV** service was running `APP_ENV=prod`, which disarmed the recipient lock below while sitting on 4,398 real director addresses, and the only visible symptom was a TEST badge that never appeared in the header.

> **The test-environment recipient lock (Levi 2026-08-30).** Whenever `APP_ENV` is not exactly `prod`, every message is delivered to a **hardcoded list** — `levi@zenexflow.com`, `roy@zenexflow.com`, `brian@getstarted.hk`, `vanis@getstarted.hk` (`services/email_service.py`, `TEST_RECIPIENTS`) — and to nobody else. It is a module constant, not configuration: the requirement was that it be *impossible*, not merely configured, for a client to be mailed from a test deployment, and DEV's Supabase carries 4,398 real director addresses. **`EMAIL_REDIRECT_TO` has been removed**; setting it again does nothing. The substitution happens inside `send()`, below every caller, and a second assertion re-checks the outgoing list immediately before the HTTP call.
>
> The Client Verification screen still shows and still selects the **real** director addresses — that fan-out is the thing being tested — and carries a note saying nothing will reach the client. The audit row records `intended_to` (the directors) and `to` (the four) separately, so the trail never claims a client was told.

> **`EMAIL_TRANSPORT` was REMOVED on 2026-08-30.** Its only value, `console`, stubbed mail out — stderr, nothing delivered, success reported — and existed solely because `RESEND_API_KEY` was a placeholder. With a real key in place that reason is spent, and protecting clients was never its job (the recipient lock above does that unconditionally). **`resend` is now the only transport, and setting `EMAIL_TRANSPORT` to anything raises at config time** rather than silently sending; the refusal names the removal so nobody hunts for a typo in a value that was correct last week. Audit rows written while it existed still read `transport: "console"`, meaning nothing was delivered, and the router still passes that through — do not normalise it away. **Do not reintroduce it:** if some future environment must suppress mail, suppress it somewhere that cannot report a delivery that did not happen.
>
> One verification email goes to **every current director** with an address on record (`nar1_cases.default_recipients`), not to a single contact. Directors with no address are still returned, carrying the reason, so a three-director board can never render as a two-director board.

> **The case worker is CC'd, and the client's reply is aimed at them** (Levi, 2026-08-30). `POST /cases/{id}/verification/send` copies `user["email"]` — the address from Supabase Auth, added to the resolved identity in `middleware/auth.py` — and sets `reply_to` to the same. **`reply_to` is the load-bearing half:** the message asks the client to reply and is sent from `no-reply@getstarted.hk`, so without it the one action the email requests reaches nobody. Read `user.get("email")`, never `user["email"]` — identities are cached for 30s and one written before the key existed must not break a send.
>
> **A CC is a recipient, so the non-production lock binds it too**: `_apply_test_cc_lock` **drops** it outside prod rather than redirecting (the four `TEST_RECIPIENTS` are already on `to`, and copying them again puts one mailbox on both lines). The guard before the HTTP call checks `to` **and** `cc`. The audit row records `cc` and `intended_cc` separately, so a dropped copy is never logged as a delivered one.

> **The client-facing email is table-based with inline styles, on purpose** (`email_service.verification_email`). Outlook renders mail through Word: no flexbox, no grid, and no `<style>` block you can rely on. Outfit does not load in most clients, so the fallback stack *is* the typography. Tests in `test_email_service.py` assert each of these; do not "modernise" the markup.
>
> **Its wording is `docs/Confirmation NAR1 Notice.pdf`, verbatim** (Levi 2026-09-01) — the letter GSHK already sends by hand, with the company, the director and the dates substituted. The three page references (**Page 2** share capital, **Page 5** director's details, **Schedule 1** shareholder's details) are **hardcoded and correct**, because CR's form is static and a section keeps its page whether or not it has content. They are only true while the renderer emits all nine pages; if it ever goes back to dropping empty ones, this letter misdirects every client.
>
> **THE "NO LINK AT ALL" RULE IS REVERSED** (Levi 2026-09-01). It read: *"the client confirms by replying, and a mail about someone's company filings that contains a link is the exact shape of the phishing it would train them to trust."* The reasoning still stands; what changed is that replying by hand was the **only** way to answer, so every approval waited on a staff member reading a mailbox and a client who never replied left a case parked with nothing recorded. The message now carries a **Confirm** button (`routers/public_approval.py`). What answers the original objection, rather than going around it: the link's `GET` **mutates nothing** and says so, so the mail-security gateway that fetches every link cannot approve anything; the page asks for **no credential, no password, no payment detail**, so there is nothing on it worth phishing for; and the reply path is **unchanged** — a client who disagrees still replies and staff still record it through `POST /cases/{id}/verification/response`. `approval_url` is `None` when the deployment cannot build one, and the message then reads exactly as it did before.
>
> **One message per recipient, not one message with several recipients.** This also reverses a stated decision (*"a board of three directors is one message with three recipients ... one Resend failure cannot leave two directors informed and the third not"*). A shared link in a shared message would let any director approve in another director's name, which is a misattribution in a statutory record. The cost — partial failure — is handled by naming exactly which addresses failed (`failed_to`) rather than pretending the send was atomic. The case worker is CC'd on the **first** message only; `reply_to` is on **every** one.
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

### 3. CR field fidelity — the form contract owns what CR requires

**`backend/services/cr_forms/contract.py` is generated and committed, and it is the only answer to "does CR want this field, and how long may it be?"** It is built from CR's own worksheet by `scripts/build_cr_form_contract.py`; regenerate it rather than hand-editing, so a CR revision arrives as a reviewable diff. `tests/test_cr_form_contract.py` fails if any of the 294 NAR1/NNC1 leaf fields lacks a **disposition** (`mapped` / `derived` / `form_instance` / `unsourced`), if a `mapped` column is missing from the schema, or if a `form_instance`/`unsourced` entry has no written reason. **An omission has to be a decision somebody made, not a field nobody noticed.**

`GET /form-contract` serves the `mapped` subset — strictest length, mandatory-anywhere — and **both profile screens read their `maxLength`, required markers and highlighting from it** (`frontend/src/lib/formContract.js`). Do not hardcode a CR length or a required flag in a screen; the two would drift and the way you would find out is a rejected filing.

> **One owner per vocabulary.** CR's Country, District, Business Nature, Currency, Capacity, Company Type and record-type lists live in `services/tpsi/forms/cr_vocabularies.py` and `services/cr_forms/record_types.py`, and are served through `/lookups` as `cr_*`. **Never seed them into `lookup_values`, and never point a CR-validated field at one** — either makes a second copy that can drift from the one deciding whether a filing is accepted. `lookup_values` keeps Viewpoint's vocabularies for the fields CR never sees (`place_of_birth`, `gender`, `nationality`).
>
> **This has now bitten twice, and the second time reached a real case.** `lookup_values.currency` offers 162 ISO codes where CR takes 54, four of them non-ISO (RMB/NTD/WON/NIS) — a renminbi share class was offered `CNY`, which CR has never heard of. Worse, the **address Country dropdown fed on `lookup_values.country`**: 270 Viewpoint rows, **20 of which resolve to no CR code at all** — US states, UK constituent countries, Labuan, Zaire, and three labelled *only in Chinese*. An operator picked the Chinese Hong Kong, it stored `HK-CH`, every check passed, and the NAR1 died at Data Verification with *"no CR region code is known for country 'HK-CH'"*.
>
> **Country fields are keyed by ISO alpha-2** (`cr_country`), because that is what `addresses.country` holds in all 141 of its distinct values — serving CR's three-letter codes would orphan every row. `cr_vocabularies.to_alpha2()` normalises anything CR can resolve onto that key.

> **"Present" is not "filable" — validate resolvability, not emptiness.** Both the write path (`address_service.validate`) and the gate (`readiness.filing_problems`) must ask the question `nar1_mapper` will ask, through the same resolver. Checking only that a country was non-empty is exactly what let `HK-CH` open a case. Same for currency: in the CR list, not merely present. Verified against DEV — all four companies holding an unresolvable country are now caught by the gate, with the mapper's own message.
>
> Beware `country.upper() == "HK"`-style comparisons: `resolve_country()` first, then compare to the CR code. The raw-string form silently skipped the Hong Kong district check for the 7 rows spelt `HKG` or `Hong Kong`.

**Two levels of refusal, and they are not the same.**

- **Highlighting** (carrot, non-blocking): a mapped field that is mandatory-and-empty or over CR's length. The save still proceeds — most of these came out of Viewpoint that way, and refusing to store them would mean refusing to show them. `unsourced` fields are never highlighted.
- **Blocking** (`services/cr_forms/readiness.py`): **only** fields CR marks `Mandatory = Y`. This gates the **Open case** button, and as of 2026-09-02 it stops **457 of 5,930 client companies** — 252 with no registered-office country, 219 with no share class, 4 whose share class lacks `issued_amount`. That is deliberate (PRD OQ-2): it converts a failure discovered at CR, after a chargeable and irreversible submit, into one visible on the profile. **The reason prints beside the button**, never only in a page banner.

> Business nature is the field the blocking rule exists to keep out. It is `M=N` on both forms and Viewpoint holds none for any of its 5,028 rows, so blocking on it would freeze the entire book over something CR does not require.

**Grandfathering is the pattern for validating legacy columns.** `company_type` (CR's `P`/`N`/`G`) and HKID check digits are both enforced on write **only when that field is itself being written**, and the value already stored is always allowed back. A bad legacy value must never block an unrelated edit. Creation is stricter than editing — a new row has no legacy to protect, so `POST /companies` takes only CR's codes.

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

**Two boxes CR fills that the renderer used to leave empty** (Levi 2026-09-04). Both are now filled by `fill.py` rather than by a caller that has to remember:

- **The Date beside the signature.** `render(signed_on=...)` used to default to blank on the reasoning that *"a date printed beside an unsigned signature block would assert something untrue"* — but **neither caller ever passed one**, so every return the portal has produced went to a director, and would have gone to CR, with an empty Date box, which reads as an unfinished form. `fill.signature_date()` now returns **today in Hong Kong** for an absent value. A real signature still wins: both routers pass `tpsi_filings.signed_at` once CR's PIN signing has succeeded, so a copy downloaded a week later carries the day it was *signed*. **Hong Kong, not UTC** — Railway and Supabase both run UTC, and a return generated at 02:00 in the office is 18:00 the previous day there.
- **The presenter's Reference.** Now `NAR1/<year>/<company name>`, where the year is the **return's own made-up-to year** and not the calendar year — a 2026 return filed late in 2027 is still the 2026 return. The box is one line, 158.1pt usable, so a long name is **shortened on a word boundary with `...`** rather than handed to `layout()`, which would shrink it toward its 4pt floor with no second line to escape into. `PRESENTER_REFERENCE_MIN_SIZE = 7.0` is the floor for that fitting; a test re-measures the box off the template so a new revision fails rather than overflows.

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

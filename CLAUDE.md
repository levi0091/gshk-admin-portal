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

> **MIDDLEWARE ORDER IN `main.py` IS LOAD-BEARING, and it reads backwards.** `add_middleware` inserts at the FRONT of the stack, so the middleware added **last** ends up **outermost**. `api_errors.install(app)` must therefore be called **before** `app.add_middleware(CORSMiddleware, …)`, or the whole thing is decoration.
>
> Why it matters: an unhandled exception in a FastAPI app is answered by Starlette's `ServerErrorMiddleware`, which sits **above** the user middleware. That reply carries no `Access-Control-Allow-Origin`, so the browser refuses to hand it to the page at all — `fetch` **rejects** rather than resolving, and `lib/api.js` prints *"Could not reach the server … the API may be down or still starting up"* for a server that answered in 40ms. **Registering an `Exception` handler does not fix this**: Starlette hands that handler to `ServerErrorMiddleware` itself, so the nicer reply is produced in exactly the same place. Only a middleware **inside** CORS works, which is what `ErrorEnvelopeMiddleware` is.
>
> A Postgres constraint violation (`22P02`, `23503`, `22001`, …) is a fact about the **submitted data**, so it comes back as a **422 quoting the constraint** — re-sending the identical request cannot succeed, and the operator has to be told which value. Everything else is a bug: one fixed sentence to the caller, the traceback to stderr where Railway keeps it. This is how "Could not reach the server" was diagnosed on 2026-09-04: a free-text Share Class box sent `"1"` at a `uuid` column, and the message named the one thing that was not wrong.

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
> **An administrator can reset a colleague's password, and it works exactly like creation** (`POST /users/{id}/reset-password`, `super_admin` only). The portal generates the password, mails it via `email_service.password_reset_email`, and sets `must_change_password` — so **the password is in the mail and in Supabase Auth's hash, and nowhere else**: not the response, not a log line, not an audit row. **The order is Auth, then flag, then mail, and nothing after the Auth call may raise.** By then the user's old password is already gone, and a 500 would report a failed reset to the administrator while the colleague was in fact locked out; the flag and the mail are therefore best-effort and *reported* (`must_change_password`, `reset_email_sent`, `reset_email_error`, `reset_email_redirected`), which the screen turns into "press it again once mail is working". It refuses a **deactivated** account (409 — banned in Auth, so the mail would be a live credential for an account that cannot sign in) and one with **no email** (409, before changing anything — no route out means no reset). **Not audited**, like every other user-management event; adding a code without seeding it would render unlabelled in the trail.
>
> **The confirmation names the account by EMAIL.** Two rows can carry the same display name, the mistake has no undo, and the address is the identifier that is actually unique.

> **`GET /auth/super-admins` is unauthenticated, and that is the point.** The login screen used to hardcode `levi@zenexflow.com` in both notices — the delivery contractor, not GSHK's administrators — so a locked-out GSHK user wrote to the wrong company and promoting somebody to `super_admin` changed nothing on screen. It returns the display name and email of **active super admins only** — never the rest of the user list, no ids, no `is_active` for anybody else, no `must_change_password` — takes **no parameter**, changes nothing, and is cached 5 minutes so reloading the login page is not a query generator. **A failure returns an empty list, never a 500**, and the screen then names nobody ("contact a Super Admin") rather than naming somebody wrong. Read it with `api.publicGet`, never `api.get` — the latter throws when there is no session, which is every visitor to that screen.

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

### Profile-screen conventions (the 2026-09-04 pass)

> **Add and Edit offer the SAME fields, on both profiles.** Six fields the company profile could edit had no box on the New Company form and four on New Person — so creating a record from a client's own paperwork meant creating a half-record, saving it, reopening it and typing the rest into a second form with different labels, three of which are on the certificate the operator is reading from at that moment. Both add modals now render their optional fields through the **same `FormField` descriptors the profile uses**, so a lookup added to one appears in the other rather than being copied.
>
> **Every field an editor can write must be rendered somewhere read-only.** `case_notes`, a director's `position` and `resignation_reason`, and a secretary's `resignation_reason` were all editable and displayed nowhere: typing one and saving it looked identical to not typing it. A field that only appears while editing is a field nobody can check.

> **`.f-group` is a COLUMN flex box — never put a button pair in one.** The share-capital editor rendered its Cancel and Save inside `.f-group.full.hdr-actions`, which stacked them vertically and centred them, the only pair of buttons in the app not side by side at the bottom right. Every add/edit in this app is a **modal with a right-aligned `.modal-footer`** (`LinkPartyModal`, `AddCompanyModal`, `UploadDocumentModal`, and now `ShareClassModal`); a new editor follows that shape.

> **Documents render through `components/DocumentSections.jsx` on both profiles** — one card per `document_types.category` (each with its own upload button, which scopes the type picker), then one **Document History** listing every version tagged `CURRENT` / `SUPERSEDED` / `REMOVED`. The type is a **coloured chip keyed to the type code** (`typeColour`), so one document reads the same in its section and in the history; **colour is reinforcement, never the message** — every chip also spells the type out, which is why the eight chip colours are kept away from `--carrot` (needs attention) and `--bang` (approved). A version's Download button passes its **version number**: without it every button signed the current version's path, so v1 and v2 both handed back v3 under three different names.
>
> **OPEN, FOR LEVI TO SETTLE.** Item 13 of the 2026-09-04 review asks for the company profile to have *"no ... multiple sections for different document types. just split based on history and current 2 sections"*, which is the opposite of the per-section layout that landed the same day quoting *"this is the same for the body corporation upload document features"*. The layout is left as it is because collapsing it would cost the per-section upload picker (what stops a document being filed under the wrong type) and the Remove button. The rest of item 13 — the type made prominent and coloured — is done.

> **A share transfer is `is_current = false` on the outgoing holder, never a DELETE** (Levi's Q9). `nar1_mapper._schedule_1` skips a holding with `is_current` false, so ceasing a member drops them from the return exactly as removing the row would — while keeping the row, which is what makes the transfer legible in the audit trail and keeps the register showing who held the shares before. Remove is for a link that should never have existed; the confirmation **names the party and says what is lost**, because the two acts share one button. The same `Status: Current / Former` control is on every party modal, and the front end must send a **real boolean** — `is_current: "false"` is a non-empty string, which Python reads as true.

> **A party picker is never a free-text id.** Share Class was a text box labelled "Share Class ID" over a `uuid NOT NULL REFERENCES share_classes(id)` column; the dropdown is now **this company's own classes**, passed down from the profile rather than re-fetched, and the API refuses a class belonging to another company by name. The Directors modal likewise does **not** offer `company_secretary`: that tile reads `entity_officers` with `role != company_secretary`, so choosing it made the row vanish from the tile you were editing and reappear further down the page — which reads as a save that deleted the record.

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
| `NAR1_CASE_CLOSED` | NAR1 | A case ended because the client is not proceeding (migration 039) |

> `CLIENT_APPROVAL_RECEIVED` was scoped NNC1-only in the original PBI-11 table. BE-3 fires it for **NAR1** too: an admin records the client's Yes/No against the case. The event predates any inbound-mail handling — R1 has none, so a human relays the reply and records it under `nar1:write`.
>
> The three `NAR1_MANUAL_*` codes describe the **off-portal** path, where the return is signed on paper and filed outside the portal. `NAR1_MANUAL_SUBMISSION_RECORDED` is the declaring act and is gated on `tpsi:submit`, because it closes the case as filed exactly as a real CR submission does — and because it makes the e-Sign chain refuse afterwards, so it must not be reachable by a role that could not have submitted in the first place.

> **A case can be CLOSED, and closing it is permanent** (Levi 2026-09-05). `POST /cases/{id}/close` (`nar1:write`) ends a case the client is not proceeding with; **there is no reopen route, and that is the feature, not an omission** — with one, "permanent" would be a label on a button rather than a property of the system, and every guard below would be advisory. A case closed by mistake is corrected by opening a NEW case, which leaves both the mistake and the correction in the trail.
>
> `nar1_cases.closed_at / closed_by / closed_reason` (migration 039) hold the evidence, and **`closed_at IS NOT NULL` is the predicate everywhere** — service, SQL view and every guard — so there is one fact rather than a flag plus a timestamp that can disagree. **The reason is REQUIRED**: everything else about a closure can be reconstructed later, and why cannot. It is `nar1:write`, not `tpsi:submit` — closing spends no money and commits no filing, which is what that module protects.
>
> **CLOSED is the eighth workflow status and the FIRST branch** of both `nar1_case_status._code` and `nar1_case_registry`'s SQL (the parity test in `tests/test_migration_024.py` now drives 480 states, closed among them). A closed case is never `workflow_overdue`: chasing an abandoned case is exactly the noise closing removes.
>
> **Closing refuses a case CR already holds** (409) — relabelling a lodged statutory return as one the client abandoned is a false statement about the register — and it **supersedes every live filing** rather than refusing one. `filings._check_gate` PASSES on a signed row, so a signed filing left on a closed case is one chargeable, irreversible call from filing a return the client cancelled. It also revokes every outstanding client Confirm link. Both cleanups are **best-effort and reported** (`filings_superseded`, `approval_links_revoked`): the case is closed the instant its UPDATE lands, and a 500 there would report a failed close over a case that is genuinely shut.
>
> **Every write on the case then refuses with a 409 carrying `reason: "case_closed"`** — `PATCH /cases/{id}` (a no-op included), the three manual-path routes, both verification routes, `POST /tpsi/filings/prepare`, and `filings._refuse_if_case_finished` on sign/e-Drive/submit. The public approval page answers "no longer available" without saying why, and the 14-day auto-approval job skips first on closure — it approves on SILENCE, and a closed case is silent by definition.

> **New audit codes must be seeded into `audit_event_types` by a migration**, with `origin='g_flowdesk'` and `category` set **explicitly** — the column default is `origin='viewpoint'`, which would mislabel every G-FlowDesk code as inherited Viewpoint history. There is **no FK** from the audit rows to this table, so an unseeded code does not fail loudly: it writes fine and then renders unlabelled in the trail. Migration 022 exists because exactly that happened to `CASE_STATUS_CHANGED` and `CASE_FIELD_UPDATED`, and **migration 034 because it had happened again** — `GF_DOC_UPLOADED`, `GF_DOC_VERSION`, `GF_DOC_DELETED`, `GF_FLAGS_CHANGED` and `GF_SHAREHOLDER_REMOVED` are all in migration 012's `_NATIVE` list and were all missing from DEV, so every document event has been rendering with a blank Action since PBI-39.

> **Every audit row says WHICH MODULE and WHICH RECORD** (migration 034, `services/audit_subject.py`). Levi 2026-09-04: *"in a lot of actions it is not clear what case or company or person it is referring to."* Four columns, denormalized for the same reasons `company_name` is — the trail has to stay readable after the record is deleted, and filterable without a join over 226k rows:
>
> | | |
> |---|---|
> | `module` | `post_incorporation` · `body_corporate` · `natural_person` · `cr_filing` — **the sidebar's own names**, because that is the vocabulary the operator already has |
> | `subject_kind` | `case` · `company` · `person` |
> | `subject_id` | the record's own id, so the cell is a link. A **uuid** column: declaring it text in a filter spec resolves `eq` to `ilike` and 500s the listing |
> | `subject_ref` | the identifier a human quotes |
>
> The cell reads **`name (ref)`** — `Kanenas Holding Limited (69123456)`, `Ilze TSERKEZIS (A123456(7))` — except for a **case, which inverts**: `NAR-2026-0042 (Kanenas Holding Limited)`, because a workflow row is about one filing of one year and not about the company in general. `company_name` is unchanged and carries the NAME half in all three; it has always held a person's name on person rows.
>
> **Nothing needs to restate what `entity_type` already says.** `audit_service` runs `audit_subject.derive()` over every row it builds, so a route that has nothing special to say still writes a row the trail can name; an explicit value always wins. The two polymorphic types (`address`, `document`) hang off a company OR a person, so **those callers must say which** — a person's address is written with the PERSON id in `case_id`, and a bare "case_id is not null" test reads that as a company and links to a 404.
>
> **THE MODULE FOLLOWS THE SUBJECT, AND THERE IS NO `documents` MODULE** (migration 037, Levi 2026-09-04 — this reverses 034, which shipped one). A document is not a thing that happens to nobody: it is uploaded *against* a person, a company or a case, so it is filed under **that record's** module — `natural_person` for an id scan on a director, `body_corporate` for a certificate on a company, `post_incorporation` for a CR receipt on a case. `audit_subject._MODULE_FOR_KIND` is the single rule, and it is why `document` and `address` carry no module of their own in `_BY_ENTITY_TYPE`.
>
> The screen showed the defect within a day of 034 shipping: an id scan uploaded against Brian YIU rendered under **Documents**, directly above an edit to Brian YIU under **Natural Person** — same person, same afternoon, two filter values. A module exists so *"everything that happened to this director"* is one question; a `documents` module split every record's history in two and made the operator guess in advance which events went where. **A row with no `subject_kind` keeps no module rather than being assigned one** — we cannot tell whose document it was, and a guess would put it in a filter result an operator would then read as that person's history.
>
> **`audit_log.case_id` keeps its meaning: it is the ENTITY id** (`routers/cases.py::_audit_target`), and `subject_id` is a different thing. Two TPSI routes used to write `nar1_case_id` into it, which put every CR filing event in an id space no company-scoped query returns; 034 repairs those from `tpsi_filings`, which is the only authoritative source for both ids.
>
> **Viewpoint history is backfilled by `python -m etl.backfill_audit_context`, not by the migration.** The single UPDATE that resolves 226k imported rows runs past Supabase's statement timeout, and even raised would hold an alembic transaction open long enough to lose the connection — which is why that script exists at all. Run it after 034 and after any fresh Viewpoint import. It resolves **89.5% of DEV's imported rows**; the remaining 23,841 carry no KeyCode, so they get no module and no subject rather than an invented one. **No imported row is ever labelled `post_incorporation` or `cr_filing`** — Viewpoint recorded neither.

> **`ILIKE '%x%'` needs a trigram index, and the audit search had none** (migration 035). Measured on DEV over all 226,825 rows: the search box **timed out on a real BRN** — and had been doing so before any of this work — while a common word came back fine, so the more precisely an operator knew what they wanted the more likely the screen was to answer "Failed to fetch". `pg_trgm` was available on Supabase but not installed. Eight GIN trigram indexes (one per column the router puts an `ilike` on) plus a composite `(module, subject_kind, created_at DESC)` took every filter the screen can send under a second, for **+75 MB on a 722 MB table**. `tests/test_migration_035.py` asserts the PLANS, not timings, and fails if `_FILTERABLE` ever offers `contains` on a column with no trigram index.
>
> **`subject_kind` is deliberately not filterable.** PostgREST compiles `in.()` to `= ANY(array)`, which the planner will not resolve against the composite index — so two ANDed enum filters walk the whole table in date order, and a pair matching *nothing* has no early exit (25s to render "no rows"). The Module filter already answers every question the screen asks. Add it only together with the `btree_gin` index that makes the pair safe.

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
>
> **Three vocabularies served from `/lookups` are NOT CR's, and their names say so** (2026-09-04). `share_class_name` (Ordinary / Ordinary A / Ordinary B / Preference) is an **open** list — CR validates nothing on `clsOfShares`, which is free text of 100 characters on both forms, so the screen pairs the dropdown with an "Other…" free-text escape and the API refuses nothing. What it buys is spelling: `share_classes` has a `UNIQUE (entity_id, class_name)`, so "Ordinary" and "ORDINARY" typed on two different days become two classes of one class and Schedule 1 files the same members twice under both. `bo_owner_type` and `bo_nature_of_control` (`services/cr_forms/control_nature.py`) are the Companies Ordinance's, not CR's — **nothing in `contract.py` maps any NAR1 or NNC1 field to `beneficial_owners.*`** — and they are deliberately not prefixed `cr_`, because a `cr_` name invites someone to map one onto a form. Both are grandfathered on write, like `company_type`.
>
> **`cr_currency` is pinned before it is sorted:** EUR, HKD, USD first, then the rest alphabetically. Same reasoning as Private-first in `cr_company_type` and Hong-Kong-first on the address form. The list stays complete; HKD stops being 22nd of 54, behind AED, AFA and ALL.

> **"Present" is not "filable" — validate resolvability, not emptiness.** Both the write path (`address_service.validate`) and the gate (`readiness.filing_problems`) must ask the question `nar1_mapper` will ask, through the same resolver. Checking only that a country was non-empty is exactly what let `HK-CH` open a case. Same for currency: in the CR list, not merely present. Verified against DEV — all four companies holding an unresolvable country are now caught by the gate, with the mapper's own message.
>
> Beware `country.upper() == "HK"`-style comparisons: `resolve_country()` first, then compare to the CR code. The raw-string form silently skipped the Hong Kong district check for the 7 rows spelt `HKG` or `Hong Kong`.

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

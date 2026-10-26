# Crew operating card

_Read by every crew persona before acting. Repo rules outrank crew defaults. Last verified: 2026-10-27 (re-run of /crew:setup)._

> Committed (`!/docs/agents/` in `.gitignore`), so every worktree has it. Feature folders under `.scratch/` stay local and ignored.

## Efficiency rules (read before dispatching — Levi 2026-10-27, tokens cost real money here)

The same rules are in `CLAUDE.md` ("Working with the crew"); this is the dispatcher's checklist.

- **Route choice decides parallelism.** `S` and `bug` run ONE developer by design. Only `M` and `L` cut the spec into tickets and run developers in parallel across the frontier. If the work spans layers, use `M`/`L` and cut tickets by seam, each owning its files and none sharing a file: (a) migration + audit codes, (b) backend service/router, (c) frontend, (d) tests/regression harness. If it is small enough for one ticket, do it inline instead of dispatching.
- **Size a ticket to ~150k tokens** (≤ ~8 files). Big modules to avoid whole-file reads of: `backend/services/tpsi/filings.py`, `backend/routers/tpsi.py`, `backend/routers/cases.py`, `frontend/src/pages/CaseWorkflowPage.jsx`. Brief with line ranges; use an `Explore` agent for broad reads.
- **One review round per ticket.** Blocking fixes are applied inline by the conductor; re-review only for migrations, auth or money paths.
- **Models per dispatch** (`model` on the Agent call): developer, reviewer = `sonnet`; reviewer = `opus` only for migrations/auth/money; qa-engineer, release-manager, infra-engineer = `haiku` unless writing real tests. No `skill-scout` unless asked.
- **Full suites once, at the end;** targeted tests while working (`uv run pytest -q tests/<file>.py`, `npx vitest run <file>`).
- **Tell the user the expected cost before dispatching more than ~200k tokens, or before resuming a stopped agent.**

## Commands

All commands need `export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v20.20.2/bin:$PATH"` first — this machine's tool shell has no `uv`/`npm` on PATH.

| Purpose | Command | Verified |
|---|---|---|
| Install dependencies | `cd backend && uv sync --python 3.12` · `cd frontend && npm ci` | yes |
| Test, all (backend) | `cd backend && uv run pytest -q` (~2 min; `master` has no xdist — `-n` is unrecognised there; `testpaths = ["tests"]`, so worktrees are not swept) | yes, 2817 passed / 317 skipped on 275637e |
| Test, one file (backend) | `cd backend && uv run pytest -q tests/<file>.py` | yes |
| Test, all (frontend) | `cd frontend && npm run test -- --run` (~15 s) | yes, 1345 passed / 66 skipped. 3 files (`AddressBlock.test.jsx`, `__address_visual__.test.jsx`, `case/PdfPreview.test.jsx`) fail at import with `supabaseUrl is required` in a worktree with no `.env` — pre-existing, not a regression; ignore them there |
| Typecheck | none configured (JS frontend, untyped Python) | n/a |
| Lint | none configured | n/a |
| Build (frontend) | `cd frontend && npm run build` | yes (only the >500 kB chunk warning) |
| Run the app | `cd backend && uv run uvicorn main:app --reload` (needs `.env`) · `cd frontend && npm run dev` | unverified — needs secrets |

`uv sync` with no `--python 3.12` picks 3.14 and fails on psycopg2-binary (memory note `worktree-uv-python-pin`). Backend unit tests must pass with no `.env`; a test that needs it is reaching a live service and is the bug (CLAUDE.md).

## Branches

- **Base branch for crew work:** `master` for this hotfix (PROD runs `master`; `dev` carries unreleased `nd2a_nd2b` work). Normal feature work branches from `dev` (CLAUDE.md "Branch strategy").
- **Protected (crew never pushes or merges into these):** `master` ("main" in CLAUDE.md — this repo's production branch is `master`), `dev`. "`dev`: no force pushes" (CLAUDE.md, branch protection).
- **Ship path:** "`dev` → auto-deploys to DEV (Cloudflare Pages + Railway DEV service)"; "`main` → auto-deploys to PROD"; "Never push directly to `main`. All changes go through `dev` first." (CLAUDE.md).

## Rules that gate the crew

- **PRD rule:** required for PBIs — "PRD-first before any build work"; PRDs must state "(a) required module + permission level, (b) new audit event types introduced, and (c) key test cases" (../CLAUDE.md). This hotfix's defect ticket carries (a)–(c) in place of a PRD, by Levi's instruction to treat it as top priority.
- **Blocked paths (read-only):** `inputs/` and `GSHK Documents/` ("NEVER write to inputs/ or GSHK Documents/"), `gshk/secrets/`, `backend/services/cr_forms/contract.py` (generated — "regenerate it rather than hand-editing"), `uv.lock` ("do not edit manually"), `.github/workflows/`.
- **Design system:** wireframe `../gshk/outputs/wireframes/admin-portal-nar1/wireframe.html` and the brand tokens in CLAUDE.md, verbatim.
- **Voice for human-facing text:** the repo's own — long-form commit bodies that explain WHY, dated decisions attributed to Levi, no marketing tone. Commit trailer per the session's attribution reminder.
- **Other repo rules:**
  - "Every API endpoint must be protected by the `require_permission(module, permission)` decorator."
  - "Every write operation must call `audit_service.log_event()` before returning a success response." New audit codes "must be seeded into `audit_event_types` by a migration, with `origin='g_flowdesk'` and `category` set explicitly."
  - "All schema changes must go through Alembic." Migration numbering: `master` and PROD are at head `056` (the NAR1 duplicate-submission fix, applied on PROD 2026-10-27). The ND2A/ND2B migrations (050, 052–055) are NOT applied anywhere and 050 still revises 051 — re-landing them needs 050 re-parented onto 056 plus a final migration restating the case view with 056's stages. PROD migrations: `alembic upgrade` only, and BEFORE the code deploys when new code writes a value the old CHECK refuses.
  - "`submitFormNar1` and `submitFormNnc1` are chargeable and irreversible." No test may call CR or Resend or resolve DNS for real.
  - "Tests must not hit the real Supabase DB."
  - Middleware order in `main.py` is load-bearing (CLAUDE.md).

## Release

- **Versioning:** none (no tags, no version file).
- **Changelog:** none; commit messages and PR bodies are the record.
- **Deploy target and how:** push to `dev` → DEV; merge PR into `master` → PROD. Migrations are applied by hand with `alembic upgrade head` against DEV, then PROD ("Always run against DEV and confirm before touching PROD").
- **Rollback:** revert the merge commit; "`alembic downgrade` in PROD requires explicit sign-off from Ting Yu — flag before running".

## Tracker

Issues and feature folders: see `docs/agents/issue-tracker.md` (local markdown under `.scratch/`). Domain glossary: `GLOSSARY.md` (none yet). ADRs: `docs/adr/` (none yet).

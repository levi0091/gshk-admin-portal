# Scheduled jobs — what they do and how to run them on Railway

One job.

| Job | What it does | When |
|---|---|---|
| `jobs.auto_approve_nar1` | Approves a NAR1 the client never answered, 14 days after the verification email went out. | Daily, midnight Hong Kong |

It is entered with `python -m jobs.auto_approve_nar1`, prints a one-line summary
to stdout, and exits non-zero **only on a real failure** — a run with nothing to
do is a success, because a cron service that alerts on an ordinary night trains
everyone to ignore it.

> **`jobs.poll_cr_status` WAS REMOVED on 2026-10-17** (Levi: CR will not report
> a document's status after filing through `docStatusEnquiry`, so there is
> nothing to poll). **Delete the `cron-poll-cr-status` service on Railway, DEV
> and PROD.** Until it is deleted it fails on every run with
> `No module named jobs.poll_cr_status`, which is harmless but noisy. The CR
> Status stage and the six CR badges went with it; a filed case now reads
> **Filed** (migration 054).

---

## Migration 054 — AFTER the code deploys, not before

054 drops the CR-status columns, turns any `registered` filing back into
`submitted`, and rewrites `nar1_case_registry` so a filed case reads `filed`.
**Code first, then the migration**, as 043 was: the new backend reads the old
view's CR codes as `filed` (`nar1_case_status.LEGACY_CR_CODES`), while the old
backend has no label for `filed` and would 500 the dashboard. So: merge, wait
for Railway to finish deploying (`curl …/health`), then `alembic upgrade head`
— DEV first, confirm the dashboard loads, then PROD.

---

## Why these are separate Railway services

A Railway **cron service** runs one command on a schedule and exits. That is
what we want, and an in-process scheduler inside the API is what we do not:

* An in-process timer fires **once per replica**. The moment Railway scales the
  API past one instance, every overdue case is approved twice — and `audit_log`
  is insert-only, so the second row can never be taken back.
* CR issues **one token per account at a time**. Two replicas logging in as the
  shared presenter would invalidate each other's session mid-run.

A GitHub Actions schedule was the other option and was rejected: it needs a
service credential in repo secrets and fires at whichever URL it was configured
with, which is exactly how a DEV job ends up writing to PROD.

---

## Setting up a cron service (do this twice: DEV and PROD)

Railway's cron scheduler runs in **UTC**. Hong Kong is UTC+8 all year — there is
no daylight saving — so subtract 8 hours from the Hong Kong time you want.

### 1. Create the service

In the Railway project that already holds the API service for that environment:

* **+ New → GitHub Repo → `gshk-admin-portal`**
* Settings → **Source** → set **Root Directory** to `backend`
* Settings → **Source** → set **Branch**: `dev` for the DEV project, `master`
  for PROD. This must match the API service beside it, or the job runs
  different code from the API it shares a database with.

### 2. Name it for what it does

`cron-auto-approve-nar1`. The name is what appears in
the deploy log and in the alert if one fails, and "worker-2" tells nobody
anything at 2am.

### 3. Set the start command

Settings → **Deploy → Custom Start Command**:

```
python -m jobs.auto_approve_nar1
```

### 4. Set the schedule

Settings → **Deploy → Cron Schedule**:

| Job | Environment | Cron (UTC) | Hong Kong time |
|---|---|---|---|
| `auto_approve_nar1` | DEV and PROD | `0 16 * * *` | 00:00 daily |

**Why `auto_approve_nar1` is at exactly midnight.** The 14-day window is
counted in whole days from the day the verification email went out, and the job
approves on the client's *silence*. Running it at the start of the Hong Kong day
means a client who replies during business hours on day 14 is always the one
recorded, never the job.

### 5. Give it the environment

The job needs the **same database variables as the API service beside it**. In Railway, open the cron
service's **Variables** tab and reference the API service rather than retyping:

```
APP_ENV                   = ${{admin-api.APP_ENV}}
DATABASE_URL              = ${{admin-api.DATABASE_URL}}
SUPABASE_URL              = ${{admin-api.SUPABASE_URL}}
SUPABASE_SERVICE_ROLE_KEY = ${{admin-api.SUPABASE_SERVICE_ROLE_KEY}}
RESEND_API_KEY            = ${{admin-api.RESEND_API_KEY}}
TPSI_BASE_URL             = ${{admin-api.TPSI_BASE_URL}}
TPSI_TLS_VERIFY           = ${{admin-api.TPSI_TLS_VERIFY}}
TPSI_CRED_KEY             = ${{admin-api.TPSI_CRED_KEY}}
TPSI_CR_PUBLIC_KEY        = ${{admin-api.TPSI_CR_PUBLIC_KEY}}
```

Replace `admin-api` with the actual name of the API service in that project.

`auto_approve_nar1` does not send email and does not touch CR, so it needs
neither `RESEND_API_KEY` nor the TPSI block. Setting them anyway is harmless and
means one list to copy; drop them if you would rather the service could not.

### 6. Turn off everything a web service needs and a cron job does not

* No **public domain** — Settings → Networking, remove it if Railway added one.
* No **health check path**. A cron service exits by design; a health check makes
  Railway mark every successful run as a crash.
* **Replicas: 1.** The double-approval this whole arrangement exists to prevent.

---

## Checking it works, before waiting a day

Railway runs a cron service's command once on deploy. So the first run happens
the moment you save — read that log.

### A healthy `auto_approve_nar1`

```
[auto_approve_nar1] 2026-09-17T16:00:03+00:00: approved 0, skipped 0, failed 0
```

Zero approved is the normal night. When it does something:

```
[auto_approve_nar1] 2026-09-17T16:00:03+00:00: approved 2, skipped 1, failed 0
  skipped 9f3c…: the client already answered
```

### Run one by hand

From a checkout that has `backend/.env` filled in for the environment you want:

```powershell
cd backend
.venv\Scripts\python.exe -m jobs.auto_approve_nar1
```

It is idempotent: running it twice in an hour changes nothing the second time.

## What the job refuses to touch, and why

It writes to statutory records, so the exclusions are the feature. The full
list is in the module's docstring; the short version:

**`auto_approve_nar1` will not approve** a case that is closed, one the client
already answered, one where no verification was ever sent, one already filed (at
CR or off-portal), or one whose approval link was superseded by a restart.
Approving any of those would put a client decision the client never made into an
insert-only trail — in the last case, *after* the filing it supposedly
authorised.

## When something goes wrong

| Log line | What it means | What to do |
|---|---|---|
| `failed N` with a case id | One case failed; the rest of the run completed. | The id is a `nar1_cases.id`; open that case. |
| `No module named jobs.poll_cr_status` | The removed CR-status cron service is still on Railway. | Delete that service (see the top of this file). |

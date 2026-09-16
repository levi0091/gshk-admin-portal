# Scheduled jobs — what they do and how to run them on Railway

Two jobs. Neither runs anywhere yet; both are set up the same way, and the
setup is about fifteen minutes each.

| Job | What it does | When |
|---|---|---|
| `jobs.auto_approve_nar1` | Approves a NAR1 the client never answered, 14 days after the verification email went out. | Daily, midnight Hong Kong |
| `jobs.poll_cr_status` | Asks CR (`docStatusEnquiry`) what it has done with every return that is filed and not yet registered or rejected. | Every 15 minutes on PROD; every 15 minutes on weekday daytimes on DEV |

Both are entered with `python -m jobs.<name>`, both print a one-line summary to
stdout, and both exit non-zero **only on a real failure** — a run with nothing
to do is a success, because a cron service that alerts on an ordinary night
trains everyone to ignore it.

---

## Before you start: apply migration 043 — AFTER the code deploys, not before

`poll_cr_status` writes four columns that migration 043 adds. Without it the job
fails on its first write, and the dashboard's Workflow column has no CR statuses
to show.

**THE ORDER IS CODE FIRST, THEN THE MIGRATION, and it matters here more than
usual.** 043 does not merely add columns: it rewrites `nar1_case_registry` so
filed cases stop reporting `completed` and start reporting `cr_not_checked`.
That is a value the *previous* backend has no label for, and
`nar1_case_status.badge_from_row` raises `KeyError` on a code it cannot label —
so running the migration against an environment still serving 042-era code
**500s the dashboard for every page that contains a filed case**. Measured on
DEV on 2026-09-16: 10 of 42 cases would have been in that state.

So:

1. Merge to `dev` (or `master`), and **wait for Railway to finish deploying**.
   Confirm with `curl https://api-dev-admin.g-flowdesk.com/health`.
2. Then run the migration.

```powershell
# from backend/, with DATABASE_URL pointing at the environment you are updating
.venv\Scripts\alembic.exe current      # expect 042
.venv\Scripts\alembic.exe upgrade head # -> 043
.venv\Scripts\alembic.exe current      # confirm 043
```

DEV first, confirm the dashboard still loads, then PROD.

**Check `alembic current` before upgrading** — if it is already ahead of 042,
another session took that number and 043 needs renumbering before it goes
anywhere.

> A red Backend CI means Railway never deploys, so step 1 never completes and
> step 2 must not be started. Check `gh run list --branch dev` first.

**What changes on the existing book.** Every filed case gets NULL in the new
columns, which the view reads as `cr_not_checked` — "filed, and nobody has asked
CR yet", which is precisely true of all of them. Nothing is backfilled: writing
anything else would be inventing a CR answer for a call that has never been
made. The first `poll_cr_status` run resolves them.

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

## Setting up a cron service (do this four times: two jobs × DEV and PROD)

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

`cron-auto-approve-nar1` and `cron-poll-cr-status`. The name is what appears in
the deploy log and in the alert if one fails, and "worker-2" tells nobody
anything at 2am.

### 3. Set the start command

Settings → **Deploy → Custom Start Command**:

```
python -m jobs.auto_approve_nar1
```

```
python -m jobs.poll_cr_status
```

### 4. Set the schedule

Settings → **Deploy → Cron Schedule**:

| Job | Environment | Cron (UTC) | Hong Kong time |
|---|---|---|---|
| `auto_approve_nar1` | DEV and PROD | `0 16 * * *` | 00:00 daily |
| `poll_cr_status` | PROD | `*/15 * * * *` | every 15 min, always |
| `poll_cr_status` | DEV | `*/15 0-8 * * 1-5` | every 15 min, 08:00–16:45, Mon–Fri |

**Railway's scheduler is UTC and Hong Kong is UTC+8 with no daylight saving**,
so the DEV window is written as hours `0-8` and comes out as 08:00–16:45 Hong
Kong. The weekday field needs no shifting: 00:00–09:00 UTC Monday is still
Monday in Hong Kong, so `1-5` means the same days at both ends.

**Why the last DEV run is 16:45 and not 17:00.** Cron cannot say "every 15
minutes up to and including 17:00" in one expression, and Railway takes one
expression per service. `0-9` would run on to 17:45, past the window; `0-8`
stops at 16:45. On DEV it makes no practical difference — see the window note
below.

**Why `auto_approve_nar1` is at exactly midnight.** The 14-day window is
counted in whole days from the day the verification email went out, and the job
approves on the client's *silence*. Running it at the start of the Hong Kong day
means a client who replies during business hours on day 14 is always the one
recorded, never the job.

**Why every 15 minutes is affordable.** `docStatusEnquiry` is free — CR's spec
§6.5.1 says "No Charge required" — and three things keep the cost of the
schedule near zero rather than 96× a daily one:

* A run with no outstanding case **never opens a CR session at all**: the client
  is built after the query, and once the book has settled that is most runs.
* The TPSI token lives in Postgres for 30 minutes (`services/tpsi/tokens.py`),
  so consecutive runs **share one login**. This matters beyond politeness —
  repeated CR auth failures lock the account, and the fewer logins, the smaller
  the blast radius when the shared password expires mid-day.
* The audit heartbeat moved from **per case** to **per run** the day this
  schedule was set, and a run that asked CR nothing writes no row at all. Left
  as it was, DEV's ten filed cases alone would have written about 350,000 rows a
  year — more than the entire Viewpoint import — onto a table whose search
  needed trigram indexes to answer in under a second. `NAR1_CR_STATUS_CHANGED`
  is unaffected: it is still one row per case per actual move, and it is the row
  anybody goes looking for.

**Why DEV is weekdays only, inside office hours.** CR's **test** service answers
the form APIs between 10:00 and 16:00 Hong Kong, weekdays. Login and balance
answer there 24/7, and `docStatusEnquiry` may well too — CR does not document
it — so the requested 08:00–17:00 window is kept rather than narrowed to CR's,
and the runs outside 10:00–16:00 cost a query that usually returns nothing. PROD
files against CR's live service, which has no window, so it runs around the
clock.

### 5. Give it the environment

The job needs the **same variables as the API service beside it**, because it
talks to the same database and the same CR account. In Railway, open the cron
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

**`TPSI_CRED_KEY` is the one that must match exactly.** It is the Fernet key the
shared presenter password is encrypted with. A cron service with a different key
cannot decrypt the credential, so `poll_cr_status` reports "the shared CR
credential could not be used" on every run and never polls anything.

**`APP_ENV` decides which CR the job talks to.** Referencing the API's value is
what keeps them in step. A DEV cron service that inherited `APP_ENV=prod` would
poll CR's live service — which happened to the DEV API itself on 2026-08-30.

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

### A healthy `poll_cr_status`

```
[poll_cr_status] 2026-09-17T01:15:02+00:00: looked at 6, checked 6, changed 1, skipped 0, failed 0
  CHANGED NAR-2026-0001: cr_not_checked -> cr_registered (CR said 'Registered')
```

`looked at 6, checked 0, skipped 6` is also fine — it means the six open cases
were not filed yet, which is what it says next to each one. At a 15-minute
cadence most runs read `looked at 0` once the book has settled; that is the job
working, and it costs no CR login.

**What a broken one looked like, so it is recognisable next time.** On
2026-09-16 every case came back:

```
  FAILED  1f60636c-…: Message part {http://interfaces.service.webservice
                      .icris3e.cr.gov.hk/}docStatusEnquiry was not recognized.
                      (Does it exist in service WSDL?)
```

That is CR's SOAP stack, not CR's business rules: the request named an operation
CR does not publish. The URL segment is `docStatusEnquiry` and the operation is
`enquireDocStatus` — different words for one call, which `services/tpsi/reads.py`
now says out loud. Per-case isolation is why the run reported it once per case
and finished rather than stopping at the first.

### Run one by hand

From a checkout that has `backend/.env` filled in for the environment you want:

```powershell
cd backend
.venv\Scripts\python.exe -m jobs.poll_cr_status
.venv\Scripts\python.exe -m jobs.auto_approve_nar1
```

Both are idempotent: running one twice in an hour changes nothing the second
time. `poll_cr_status` re-asks CR and writes the same answer; the only new row
is the run's own `TPSI_DOC_STATUS_CHECKED` entry, which is what it is for.

### Check it from the portal

* **Audit Log**, filtered to `TPSI_DOC_STATUS_CHECKED`, should gain rows dated
  today under **G-FlowDesk (automatic)** — **one per run that actually asked CR
  something**, carrying that run's counts. A run with nothing outstanding writes
  none, on purpose: 96 rows a day saying "there was nothing to poll" is not a
  heartbeat, and for that case Railway's own cron log is the place to look.
* **Audit Log**, filtered to `NAR1_CR_STATUS_CHANGED`, is the one to actually
  watch: one row per case, only when CR's answer moved.
* **A filed case's CR Status stage** should stop saying "Not yet checked with
  CR".

---

## What each job refuses to touch, and why

Both jobs write to statutory records, so the exclusions are the feature. The
full list is in each module's docstring; the short version:

**`auto_approve_nar1` will not approve** a case that is closed, one the client
already answered, one where no verification was ever sent, one already filed (at
CR or off-portal), or one whose approval link was superseded by a restart.
Approving any of those would put a client decision the client never made into an
insert-only trail — in the last case, *after* the filing it supposedly
authorised.

**`poll_cr_status` will not ask CR about** a case that is not filed, one CR has
already registered or rejected, a closed case, or one with no CR case number on
its receipt. It also refuses to write when CR's reply names **several
documents** under one case number and none can be identified as this annual
return: attributing another form's rejection to this NAR1 would put a red badge
on a return that is perfectly fine.

---

## When something goes wrong

| Log line | What it means | What to do |
|---|---|---|
| `the shared CR credential could not be used` | No shared presenter record, or `TPSI_CRED_KEY` does not match the API's. | Settings → CR Credentials in the portal; then compare the two variables. |
| `CR WAS NOT USABLE: …` | CR was unreachable or refused the login. The run stopped rather than failing 300 cases identically. | Check `/tpsi/balance` from the portal. **Do not re-run repeatedly** — repeated CR auth failures lock the account. |
| `NOTE: the page was full` | More outstanding cases than one run's cap. | Nothing. The next run takes the remainder. |
| `FAILED  <id>: …` | One case failed; the rest of the run completed. | The id is a `nar1_cases.id`; open that case. |

`poll_cr_status` exits **1** when CR could not be used at all, and **0** when it
simply found nothing to do. That distinction is the one worth alerting on.

# CR Status — stage 6, the workflow vocabulary, and the two batch jobs

**Date:** 2026-09-16 · **Author:** Levi (BA/Lead) via Claude Code · **Status:** design

Five defects and requests, reported off a live DEV case (NAR-2026-0001,
Wealthix Limited, CR case 151120654, filed 16/09/2026):

1. Confirmation sits at **IN PROGRESS** on a case CR has already receipted.
2. There is no stage that reports **what CR did with the document afterwards**.
3. The dashboard's Workflow column ends at **Completed**, which is not a CR fact.
4. Nothing polls `docStatusEnquiry`, so the CR-side answer never arrives.
5. The 14-day client auto-approval job exists but is not scheduled anywhere.

---

## 0. What CR's `documentStatus` actually is — measured, not assumed

`TPSI API Interface v1.0.14.docx` §6.5 defines `docStatusEnquiry` and its
response. `documentStatus` is declared **`String`, length 20, remark "Document
Status"** — and **the specification enumerates no values at all.** The response
examples in §6.5.5 are screenshots, and `TPSIT User Guideline v1.0.5.docx`
contains the word "status" zero times.

The only CR strings this repo has ever held are the two in
`tests/tpsi/test_reads.py`: **`Registered`** and **`Pending`**.

**Therefore the vocabulary is treated as OPEN.** CR's exact words are stored and
displayed verbatim; a *treatment* code is derived from them by one normaliser,
and a string nobody anticipated lands on `cr_unknown` — grey, with CR's own
words on the badge — rather than on a wrong colour or on nothing at all. This is
the same posture `RECEIPT_VOCABULARY` already takes ("CR has more codes than any
receipt GSHK has seen").

### The six treatments

| code | CR says | colour | why |
|---|---|---|---|
| `cr_not_checked` | *nothing yet — never polled* | grey | the honest answer before the job has run |
| `cr_pending` | `Pending`, `Received`, `Submitted`, `In Progress`, `Processing` | indigo/blue | CR holds it, no decision |
| `cr_approved` | `Approved`, `Accepted`, `Vetted` | peridot/yellow | CR decided yes, not yet on the register |
| `cr_registered` | `Registered` | bang/green | on the register — the terminal good state |
| `cr_rejected` | `Rejected`, `Refused`, `Returned`, `Withdrawn`, `Cancelled` | red | CR will not register it |
| `cr_unknown` | anything else | grey | CR's own words are shown |

`cr_not_checked` and `cr_pending` are **separate on purpose**. "We have not
asked CR" and "CR told us it is pending" are different facts, and collapsing
them would let a deployment with no cron job report a CR answer it never
received. It is also exactly what Levi asked for as the pre-batch-job fallback:
*"step 6 CR status as pending in grey"*.

`Withdrawn`/`Cancelled` sit under `cr_rejected` rather than getting a code of
their own: the operator action is identical (the return is not on the register;
something has to be re-filed), and a seventh badge for a string CR may never
send is a column nobody can read.

---

## 1. Storage — four columns on `nar1_cases` (migration 043)

```
cr_doc_status        text         CR's own words, verbatim, or NULL
cr_doc_status_code   text         the normalised treatment (CHECK-constrained)
cr_status_checked_at timestamptz  when CR last answered
cr_document_ref_no   text         CR's documentRefNo, so a re-query is exact
```

**Why store the derived code and not re-derive it.** `nar1_case_registry`
(migration 024) restates the workflow derivation *in SQL*, because PostgREST
cannot sort, filter or count an expression. The normaliser is fuzzy
case-insensitive word matching; restating that in SQL would be a second
implementation free to drift from the first. Storing the code means the view
reads a **stored fact** — exactly as it reads `filing_stage` — and there is one
normaliser, in Python, on the single write path
(`services/nar1_cr_status.refresh`).

**Why `nar1_cases` and not `tpsi_filings`.** D-6 gives CR facts to
`tpsi_filings`, and this *is* a CR fact — for the e-Sign path. A return signed
on paper and filed off-portal has a CR case number
(`manual_receipt->>'caseNo'`) and **no submitted filing row**: its filing is
still sitting at `validated`. Writing "CR registered it" onto a row whose own
stage says it was never sent would be a record that contradicts itself, and the
manual path is half of R1, not a corner case. The case is the one thing both
paths have, and `manual_receipt` — CR's own receipt — is already precedent for
a CR fact living there.

**`tpsi_filings.stage` is NOT overloaded.** When CR answers `Registered` the
poller *does* promote `submitted → registered` — that is what stage 018 already
means. When CR answers `Rejected` the stage stays `submitted`, because it is
true: the return **was** filed and **was** charged, and CR refused it
afterwards. `submission_failed` means `submitFormNar1` itself refused and
nothing was charged; conflating the two would tell an operator no money moved
when it did.

---

## 2. The workflow vocabulary — `completed` is replaced by five CR codes

Levi: *"completed should not be there.. it should be the steps throughout the
workflow plus the final CR statuses."*

```
data_verification · client_verification · awaiting_client · client_rejected
signing · submission
cr_not_checked · cr_pending · cr_approved · cr_registered · cr_rejected
closed
```

`completed` is **removed from the vocabulary**, not aliased. A code that no row
can carry but that every filter, count and test still offers is worse than one
that is gone: it renders an always-zero tab and invites somebody to write it.

`nar1_case_status._code()` gains, in place of its two `completed` branches:

```
closed_at                              -> closed
manual_receipt OR stage in FILED       -> the CR code (below)
  cr_doc_status_code, when set         -> that code
  otherwise                            -> cr_not_checked
...unchanged below...
```

`TERMINAL_STATUSES` (the overdue overlay, and the dashboard's "neither queue"
rule) becomes every `cr_*` code plus `closed`. A filed return is not overdue,
whatever CR has since said about it — being *rejected* by CR is a different
alarm, and it is the badge's own job to raise it.

`ACTION_STATUSES` on the dashboard gains **`cr_rejected`**: a return CR refused
is work waiting on GSHK, and it is the single most urgent row on the screen.
`cr_not_checked`, `cr_pending` and `cr_approved` go in **`PENDING_STATUSES`**
beside `awaiting_client` — waiting on someone else. `cr_registered` and `closed`
stay in neither.

Migration 043 rebuilds `nar1_case_registry` branch-for-branch, as 039 did, and
`tests/test_migration_024.py` drives the new axis through the live view.

---

## 3. Stage 5 (Confirmation) and stage 6 (CR Status)

`workflow.stageDone(c, 5)` currently reads `form_status.code === 'registered'`,
a stage **nothing ever wrote** — which is precisely why the screenshot shows
step 5 orange on a case holding a CR receipt. It becomes `isSubmitted(c)`: the
Confirmation stage's own work is that the receipt exists, and it does.

Stage 6 is added to `STAGE_LABELS` as **CR Status**, reachable only once the
return is filed (`reachedStage` returns 6 when `isSubmitted`), and `done` only
on `cr_registered` — the one CR answer that means the statutory job is finished.

`.stepper` moves from `repeat(5, 1fr)` to `repeat(6, 1fr)`, the mobile
breakpoint with it.

**The step medallion carries the CR colour.** A grey `cr_not_checked`, a blue
`cr_pending`, a yellow `cr_approved`, a green `cr_registered`, a red
`cr_rejected` — so the state is legible from the stepper without opening the
stage. This is the one place a step is coloured by data rather than by
reached/done, and it is why `CaseStepper` takes a `tone` per step rather than
growing a special case for index 6.

`StageCrStatus.jsx` shows: the CR badge, CR's own words, when it was last
checked, the CR case / document reference, and — for `tpsi:read` holders — a
**Check now** button that polls immediately and persists the answer. The
previously-removed "Check CR status" button was removed for three reasons
(nothing persisted, nothing ever reached `registered`, the case was already
done); all three are now false, and the fourth objection — that it spends a CR
authentication per press — is answered by the poller being the normal path and
the button being the exception.

---

## 4. `POST /tpsi/cases/{id}/refresh-status` and the poller

One service function, `services/nar1_cr_status.py::refresh(client, case, filing)`,
is the **only** writer of the four columns. The route and the job both call it,
so a hand-check and a nightly run cannot disagree.

* **Permission:** `tpsi:read`. The level reflects the effect on CR and on money,
  and this has neither — `docStatusEnquiry` is free. Precedent for a
  case-subject route on a TPSI module is `POST /cases/{id}/manual-submit`
  (`tpsi:submit`). It is a **POST, not a GET**, because it writes: a GET that
  changes a statutory record is one a mail gateway or a browser prefetch would
  fire for you.
* **Audit:** `TPSI_DOC_STATUS_CHECKED` on every check — the heartbeat whose
  absence is how you find out the cron service stopped; `NAR1_CR_STATUS_CHANGED`
  only when the code actually moved, so "when did CR register this" is
  answerable by filtering rather than by reading a month of heartbeats. Both
  seeded by migration 043 with `origin='g_flowdesk'` and an explicit `category`.
* **Enquiry key:** CR's own case number (`receipt.caseNo` on either path).
  Never BR-number-plus-date-range — that returns every document the company has
  filed in the window and would attribute another form's status to this NAR1.
  When one case number carries several documents and none can be identified as
  this return, **nothing is written** and the refusal is reported.
* **Stage promotion:** `submitted → registered` on the e-Sign path only
  (`filings.mark_registered`, conditional inside the UPDATE). A CR *rejection*
  never becomes `submission_failed` — that means `submitFormNar1` refused and
  nothing was charged, which is the opposite of what happened.

`jobs/poll_cr_status.py` selects only cases that are **filed and not yet
terminal** — exactly Levi's rule, *"only check for things after submission and
not yet confirmed or rejected"* — logs in once through the shared presenter
credential, and walks them with per-case isolation and a stated row cap, in the
shape `auto_approve_nar1.py` already established. Its selection uses
`or_(code.is.null, code.not.in.(…))`: a bare `not.in` is NULL for a NULL column
and would have skipped **every case in the book**, reported "nothing to do", and
polled nothing.

---

## 5. The two cron services — runbook

`backend/jobs/README.md` (committed; `docs/` is gitignored repo-wide) carries
the step-by-step Railway setup for both jobs, per environment, with the
verification command for each and what a healthy log line looks like.

---

## Testing

| | |
|---|---|
| `tests/tpsi/test_doc_status.py` | every mapping, unknown strings, blank, case/whitespace, rule order |
| `tests/test_nar1_cr_status.py` | the exclusions, document disambiguation, stage promotion, audit split |
| `tests/test_poll_cr_status.py` | the NULL-safe selection, terminal skip, per-case isolation, one login, exit code |
| `tests/tpsi/test_refresh_cr_status_router.py` | 200/403/404/409/503, and that a refusal opens no CR session |
| `tests/test_nar1_case_status.py` | the six CR codes, `cr_not_checked` fallback, closed still wins, no `completed` |
| `tests/test_migration_024.py` | a sixth axis through the live view — 2,880 states (RUN_DB_TESTS) |
| `workflow.test.js` | `stageDone(5)`, `stageDone(6)`, `reachedStage` → 6, `stageTone` |
| `stages.test.jsx` | StageCrStatus in all six states, and Confirmation's new headline |
| `CaseStatusBadge.test.jsx` | the six new badges, `cr_unknown` renders CR's words |
| `CaseWorkflowPage.test.jsx` | opens on stage 6, Confirmation ticks, the medallion tone |
| `DashboardPage.test.jsx` | the new filter options and both tiles' membership |
| `__visual__.test.jsx` | six CR-state cards and six steppers, shot at 1180, 720 and 400px |

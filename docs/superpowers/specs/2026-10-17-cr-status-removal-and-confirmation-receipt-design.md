# CR status removed; a confirmation receipt for the client — design

Levi, 2026-10-17. Two changes, both shipping with `nd2a_nd2b`.

> "remove CR portal status polling and the CR status step from the NAR1
> workflow and the future workflows ... CR portal ... will not send updated
> statuses of documents via the /docEnquiry api ... At best we will know that
> the submission was successful and we get payment details and receipt ... you
> have to remove that stage 6 and patch the existing records. leave the audit
> trail"
>
> "after a director or secretary or any client click on the confirm file & sign
> button in the weblink ... they should get an email confirmation that they
> have signed the document on what date and time and attach the document(s) in
> that email also ... the same for ND2A, ND2B or NAR1 client verification step.
> cc renewal@getstarted.hk"

This reverses `2026-09-16-cr-status-stage-and-batch-jobs-design.md` (the
CR-status half; the auto-approval job is unaffected) and migrations 043/044.

## 1. What a filed case is now

A case whose return CR has received (e-Sign `submitted`, `edrive`, or an
off-portal receipt) has workflow status **`filed`**, label **"Filed"**, drawn
green. It replaces all six CR codes (`cr_not_checked`, `cr_pending`,
`cr_approved`, `cr_registered`, `cr_rejected`, `cr_unknown`) everywhere: the
Python badge, the SQL view, the dashboard filters and tiles, the company
profile's case list, and the soft-delete "finished" set. `filed` is terminal:
it is never overdue and never in a work queue. `closed` still beats it.

The stepper has **five** stages again. Confirmation is the last. A filed case
opens on Confirmation with all five ticked. The same for ND2A/ND2B.

## 2. What is removed

| Removed | Why it existed |
|---|---|
| `jobs/poll_cr_status.py`, its README sections | the 15-minute Railway cron |
| `services/nar1_cr_status.py`, `services/tpsi/doc_status.py` | the poll and its vocabulary |
| `reads.case_status` (`docStatusEnquiry`) | the only CR call they made |
| `POST /tpsi/cases/{id}/refresh-status`, `GET /tpsi/doc-status` | Check now; the ad-hoc lookup (no caller in the frontend) |
| `filings.mark_registered`, `STAGE_REGISTERED` | the poll's promotion of the filing row |
| Stage 6 screens (NAR1 and officer change), the CR tone, `bc-*` CSS, `checkCrStatus`, `refreshCrStatus` | the screen half |

Kept: the audit codes `TPSI_DOC_STATUS_CHECKED`, `NAR1_CR_STATUS_CHANGED` and
`TPSI_STATUS` stay seeded and named in `audit_events.py` — rows exist and the
trail must keep labelling them. No audit row is touched.

## 3. Migration 054 — patching the existing records

Revises 053.

1. `nar1_case_registry` rebuilt from 052's view: the filed branch returns
   `'filed'`; the three `cr_*` columns leave the select; the overdue rule's
   finished list is `('filed', 'closed')`.
2. `UPDATE tpsi_filings SET stage = 'submitted' WHERE stage = 'registered'` —
   the poll was the only writer of `registered`.
3. `trg_set_updated_at` on `nar1_cases` back to unconditional (044 reverted —
   its WHEN clause names a column step 4 drops, so this comes first).
4. Drop `nar1_cases.cr_doc_status`, `cr_doc_status_code`, `cr_status_checked_at`,
   `cr_document_ref_no` and their CHECK.

Downgrade re-adds the columns (empty) and the CHECK, restores 044's trigger
and 052's view. It does not restore `registered` stages: that answer came from
the poll, which the downgraded code would run again.

**Deploy order is code first, then 054** (the README's convention). The new
`badge_from_row` reads any old CR code as `filed`, so the window between the
deploy and the migration renders, rather than 500s.

## 4. ND2A/ND2B Undo

Undo was gated on CR's `cr_rejected`, which no longer exists. It moves to the
Confirmation stage and is offered on any filed case with an applied change not
yet undone (`tpsi:submit`). The confirmation dialog states the operator is
recording that the Companies Registry rejected the change. The route refuses an
unfiled case (409, `not_filed`).

## 5. The confirmation receipt

**When.** Once, when a client's own press of Confirm & File on the emailed link
claims the approval (`public_approval._record`, NAR1 and officer change alike).
Not on a replayed press, a staff-relayed answer, the 14-day auto-approval or an
ND2B waiver — nobody pressed anything there.

**To.** The address on the approval token (the director who pressed). CC
`renewal@getstarted.hk` and reply-to it, exactly as the verification letter.
The non-production recipient lock applies inside `email_service.send`.

**Attached.** What the client confirmed, named as the verification email named
it (`-RevN` from Rev. 2):

* NAR1 — the frozen `verification_xml`, rendered as the send renders it.
* ND2A — the form (full, PI sheets) from `verification_xml`, and the written
  resolution.
* ND2B — the form from `verification_xml`.

Not the supporting uploads: the client confirmed the form, not their passport
scan. A document that cannot be rendered is left off; the receipt still goes,
lists only what it carries, and the audit row names what failed.

**How.** A background task after the confirmation page is returned, so the
director never waits on a PDF render or Resend. It never raises. It writes one
`EMAIL_SENT` row (system actor `G-FlowDesk (automatic)`) with
`metadata.template = "approval_receipt"`, and the delivery check
(`GET …/verification/delivery`) skips rows carrying a `template`, so a receipt
can never be read back as the verification send.

**Says.** "confirmed", the word on the button, not "signed" — GSHK's PIN
signature at CR is a different act. The moment is printed in Hong Kong time,
as the approval page prints it. The receipt names who confirmed and from which
address, the form, revision and reference, says nothing more is needed, and
tells the reader to write to renewal@ at once if they did not confirm it — the
link is unauthenticated, and the receipt is how a forwarded email is noticed.
Table-based, inline styles, the verification letter's tokens and footer.

## Rulings

* R-1 `filed` / "Filed" / green is the terminal status — the receipt is what we
  know; "completed" was retired on 2026-09-16 and stays retired. Cost: one label.
* R-2 Five stages for ND2A/ND2B too ("and the future workflows").
* R-3 `GET /tpsi/doc-status` goes as well: same CR call, no frontend caller.
  Cost: an operator using it from a REST client loses it.
* R-4 054 drops the four columns rather than leaving them dead. History survives
  in the audit trail (`NAR1_CR_STATUS_CHANGED` rows). Cost: CR's last word per
  case is no longer one column away.
* R-5 `registered` filings become `submitted`. Cost: none known — `registered`
  was only ever written by the poll.
* R-6 Soft delete treats `filed` as finished (was: only `cr_registered`). A
  company whose last case is filed can be removed without first asking CR.
* R-7 Undo stays, operator-declared, on Confirmation (§4). Cost if unwanted: one
  button and one gate.
* R-8 `badge_from_row` tolerates old CR codes for the deploy window (§3).
* R-9 Receipt only on the client's own press (§5 When).
* R-10 Attach the confirmed forms, not supporting uploads.
* R-11 A render failure drops that attachment, not the receipt.
* R-12 `EMAIL_SENT` + `template`, not a new code: CLAUDE.md mandates
  `EMAIL_SENT` for every workflow email, and the trail's Email Sent filter
  should show receipts.
* R-13 "confirmed", not "signed".
* R-14 Background task, after the page.
* R-15 The receipt carries the "if this was not you" line.

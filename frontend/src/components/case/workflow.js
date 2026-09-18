/**
 * The NAR1 case workflow's shared rules — pure functions, no React.
 *
 * Extracted so the gate can be tested directly. The stage gate decides whether
 * a statutory return can be signed and filed, so it is the last thing that
 * should only be reachable through five rendered components.
 */

// CLIENT VERIFICATION IS FIRST (Levi 2026-09-17: "we need client validation to
// be 1st step ... users send the email way ahead of time to the client and then
// make the necessary changes ... before validating with CR portal after that
// first step").
//
// The old order let the client approve `validated_xml`, the exact bytes CR had
// accepted, so nobody approved a form CR would refuse minutes later. What it
// cost was the calendar: the client is the slow party, and asking them last
// meant their corrections arrived after the data work rather than before it.
// See services/nar1_case_status.py, which is the same decision in the backend,
// and migration 046, which is it again in SQL.
export const STAGE_LABELS = [
  'Client Verification',
  'Data Verification',
  'Signing',
  'Submission',
  'Confirmation',
  // THE SIXTH STAGE (Levi 2026-09-16). The first five are OUR process and end
  // at "we handed it over"; this one is CR's, and it begins there. A NAR1 that
  // submitFormNar1 accepted and charged for is not yet on the register — CR
  // vets it and can still refuse it.
  'CR Status',
]

/**
 * The CR status the case is currently wearing.
 *
 * The backend sends `cr_status` as a composite object (see
 * `services/tpsi/doc_status.describe`). A case read before migration 043, or
 * one whose payload predates this field, gets the honest default rather than a
 * blank: filed returns have always been in this state, nobody had asked CR.
 */
export function crStatus(c) {
  const status = c?.cr_status
  if (status && typeof status === 'object' && status.code) return status
  return { code: 'cr_not_checked', label: 'Awaiting CR status',
           cr_text: null, terminal: false }
}

/**
 * The colour a CR answer is drawn in — one word, used by the stepper medallion
 * and by the stage card's own rail so the two can never disagree.
 *
 * Five treatments over six codes: `cr_unknown` shares grey with
 * `cr_not_checked` because neither tells you anything actionable, and the badge
 * itself carries CR's own words to tell them apart. Adding a sixth colour for
 * "CR said something we could not read" would spend a colour on a state whose
 * whole content is the text beside it.
 */
export const CR_TONE = {
  cr_not_checked: 'wait',
  cr_pending: 'info',
  cr_approved: 'warn',
  cr_registered: 'ok',
  cr_rejected: 'bad',
  cr_unknown: 'wait',
}

/**
 * What a CR answer MEANS for this case, in the operator's terms.
 *
 * The label says what CR called it; this says what to do about it. They are
 * different jobs and a badge cannot do both.
 */
export const CR_MEANING = {
  // NO CADENCE IN THIS TEXT. These sentences say what the STATUS means; how
  // often the portal asks is one fact, it lives in the action bar, and it
  // differs between deployments — DEV only polls inside CR's test window. Said
  // in both places it would drift, and "the nightly check" was already wrong
  // the day the schedule became every 15 minutes.
  cr_not_checked:
    'The return is with the Companies Registry. Nothing has asked CR what it '
    + 'has done with it yet — the scheduled check does that, or you can check now.',
  cr_pending:
    'CR has the return and has not decided. Nothing is needed from GSHK; the '
    + 'scheduled check will pick up the answer.',
  cr_approved:
    'CR has accepted the return and has not yet placed it on the register. '
    + 'Nothing is needed from GSHK.',
  cr_registered:
    'The annual return is on the register. This case is finished.',
  cr_rejected:
    'CR will not register this return. The fee was already taken, so a '
    + 'corrected return has to be filed as a new case — check what CR sent '
    + 'before re-filing.',
  cr_unknown:
    'CR answered with a status this portal does not recognise. Its exact '
    + 'wording is shown above; treat that as the answer and report it so the '
    + 'status can be added.',
}

/** CR form stages that mean the snapshot exists and is usable. */
const VALIDATED_STAGES = new Set([
  'validated', 'signed', 'submitted', 'registered', 'edrive',
])

/** A filing CR has already accepted. Re-validating one of these is refused. */
const CR_HOLDS = new Set(['submitted', 'registered', 'edrive'])

/**
 * Has the return been signed off, by whichever route was chosen?
 *
 * A wet signature is not evidence for an e-filing and vice versa, so the two
 * routes answer this from different facts and never stand in for each other.
 */
export function signedOff(c) {
  return c.signing_method === 'manual'
    ? Boolean(c.manual_signed_document_id || c.manual_signed_document_version)
    : c.form_status?.code === 'signed'
      || CR_HOLDS.has(c.form_status?.code)
}

/**
 * Is this case permanently closed?
 *
 * `closed_at`, not a badge code: the timestamp is the fact the backend stores
 * and every one of its own guards reads, and matching on
 * `workflow_status.code === 'closed'` would be a second definition that can
 * disagree with it — on a case whose badge came back as a bare string, say.
 *
 * There is no reopen, here or anywhere: closing is irreversible by design
 * (Levi 2026-09-05), which is exactly why this is a plain read of a fact and
 * not a state the screen can talk itself out of.
 */
export function isClosed(c) {
  return Boolean(c?.closed_at)
}

export function isValidated(c) {
  return VALIDATED_STAGES.has(c.form_status?.code)
}

export function isSubmitted(c) {
  return Boolean(c.manual_submitted_at) || CR_HOLDS.has(c.form_status?.code)
}

/**
 * Is there anything for `Restart verification` to undo — and may it?
 *
 * TWO things a restart discards, and either is enough (Levi 2026-09-19): the
 * copy SENT to the client, and a snapshot CR has VALIDATED. This used to ask
 * only the second, which was the whole question while Client Verification came
 * after CR. Since the client moved to stage 1 (2026-09-17) a case is sent long
 * before CR sees it — and the send locks the return year behind a note saying
 * "Restart verification to choose a different year" while no such button was
 * on the page.
 *
 * The client fields are the ones `PATCH /cases/{id} {restart_verification}`
 * clears; a validated snapshot is the one it supersedes. Never once the return
 * is filed (the backend refuses with a 409) or the case is closed.
 */
export function canRestart(c) {
  if (!c || isClosed(c) || isSubmitted(c)) return false
  const asked = Boolean(c.verification_sent_at || c.client_response_at)
    || (c.client_approved !== null && c.client_approved !== undefined)
  return asked || isValidated(c)
}

/**
 * The furthest stage this case may enter. Mirrors v11's `cmReached()`.
 *
 * Note step 1: the manual path does NOT bypass Client Verification (OQ-4).
 * Signing a return on paper does not make the client's approval optional —
 * a statutory filing still goes out in the client's name.
 */
export function reachedStage(c) {
  if (!c) return 1
  // A closed case has no reachable stage. `CaseWorkflowPage` renders the closed
  // panel instead of the stepper, so nothing asks — but this must not answer
  // "6" to whatever does, because every button behind the later stages writes.
  if (isClosed(c)) return 0
  // The client unlocks the data work, not the other way round (2026-09-17).
  // Stage 1 is always open; stage 2 waits on an approval. A client who never
  // answers is released by the 14-day auto-approve job, so this cannot deadlock
  // a case — see backend/jobs/auto_approve_nar1.py.
  if (!(c.verification_sent_at && c.client_approved)) return 1
  if (!isValidated(c)) return 2
  if (!signedOff(c)) return 3
  if (!isSubmitted(c)) return 4
  // Filing unlocks BOTH remaining stages at once, because they are two views of
  // the same event: the receipt proves the return was delivered, and CR's
  // status is what happened to it afterwards. There is no action between them
  // to gate on, and locking stage 6 behind a "done" flag on stage 5 would hide
  // a CR rejection behind a receipt nobody needs to read twice.
  return 6
}

/**
 * Why this case cannot be sent for client verification, or null.
 *
 * Mirrors `routers/cases._verification_gate` for the reasons the browser can
 * see. The backend still decides — this only stops the screen from offering a
 * button whose one outcome is a 409, which is what an operator experiences as
 * "I pressed Send and nothing happened".
 *
 * Order matters: a filed return satisfies `isValidated` too, and "not validated
 * yet" would be a lie about a return CR is already holding.
 */
export function verificationBlock(c) {
  if (!c) return null
  if (c.manual_submitted_at || c.manual_receipt) {
    return 'This case was completed off-portal, so there is nothing left for '
      + 'the client to approve.'
  }
  // NOT a "block" any more (Levi 2026-08-31). On a case CR already holds,
  // Client Verification is history: the stage shows a green tick, the send
  // happened, the client answered. Warning that asking them now would be
  // pointless is a caution about something nobody is attempting, on a screen
  // whose every other line says the work is done.
  //
  // The send is still not offered there — StageClientVerification withholds it
  // on `isSubmitted`, so this does not put a dead button back on the screen.
  //
  // TWO BLOCKS WERE REMOVED HERE (2026-09-17), mirroring
  // `routers/cases._verification_gate`. They refused a return CR had not
  // validated, and one whose last validation had failed:
  //
  //   'This return has not been validated by the Companies Registry yet.'
  //   'The last validation of this return failed.'
  //
  // Both were right while this was the SECOND stage. It is now the first, so CR
  // has not seen the return by construction and either message would refuse
  // every send the new order asks for. There is nothing left for the browser to
  // pre-empt: what remains of the gate is about cases that are already finished,
  // and `isSubmitted` withholds the button on those.
  return null
}

/** Is this stage's own work finished? Drives the green ticks. */
export function stageDone(c, i) {
  if (!c) return false
  switch (i) {
    // Swapped with stage 2 on 2026-09-17, with the stages themselves.
    case 1: return Boolean(c.client_approved)
    case 2: return isValidated(c)
    case 3: return signedOff(c)
    case 4: return isSubmitted(c)
    // CONFIRMATION IS DONE WHEN THE RECEIPT EXISTS (Levi 2026-09-16: "when the
    // workflow is completed and we get a receipt from CR portal, the progress
    // bar is still indicating in-progress for confirmation stage").
    //
    // It used to read `form_status.code === 'registered'` — a stage NOTHING
    // EVER WROTE, so step 5 was permanently orange on a case whose receipt was
    // on screen above it. `registered` is now written (by the CR poller), but
    // it belongs to stage 6: this stage's own work is that the return was
    // delivered and the receipt recorded, and it was.
    case 5: return isSubmitted(c)
    // And this one is CR's. `cr_registered` is the single answer that means the
    // statutory job is finished; every other CR answer, refusal included,
    // leaves the stage un-ticked and coloured by `stageTone` below.
    case 6: return crStatus(c).code === 'cr_registered'
    default: return false
  }
}

/**
 * The colour of one stepper medallion, when the DATA decides it rather than our
 * progress through the workflow. `null` everywhere but stage 6.
 *
 * This is the one place a step is not drawn from reached/done, and that is the
 * point: the last step is not ours. An operator should be able to read the
 * register's verdict off the progress bar without opening the stage.
 */
export function stageTone(c, i) {
  if (i !== 6 || !c || !isSubmitted(c)) return null
  return CR_TONE[crStatus(c).code] || 'wait'
}

/**
 * What a failed request means, and what the operator should do about it.
 *
 * The four cases are genuinely different actions, not four wordings of "it
 * broke" — see the delivered contract §5.4.
 */
/** What to do about each kind of CR refusal. Keyed by `_handle`'s `kind`. */
const CR_REFUSAL_HINTS = {
  account_locked:
    'The Companies Registry has LOCKED or CLOSED this e-Service account. Do not '
    + 'try again — further attempts keep it locked. The account holder must '
    + 'contact CR to have it reinstated.',
  signature:
    'CR accepted the return but refused the signature. The signatory needs an '
    + 'individual e-Service account that CR has associated with THIS company, '
    + 'in a capacity allowed to sign. Editing the return will not fix this.',
  validation:
    'CR checked the return and rejected it. Fix the details it lists on the '
    + 'company profile, then validate again — validation is free.',
  // A refusal from CR's SOAP STACK rather than from its business rules: the
  // request did not match what CR publishes, so nothing about the case is
  // wrong and nothing on this screen can fix it. Saying "fix what it reported"
  // here would send an operator hunting through a company profile for a fault
  // that is in our own XML — which is what happened on 2026-09-16, when the
  // message naming the bug did not survive the edge either.
  fault:
    'The Companies Registry rejected the REQUEST, not the return. Nothing was '
    + 'filed and nothing was charged, and nothing on the case needs changing. '
    + 'Quote the message above — this one is ours to fix.',
  default:
    'The Companies Registry refused this. Fix what it reported — do not simply retry.',
}

/**
 * What to do when CR could not be USED at all. Keyed by `_handle`'s `kind`,
 * which the backend sets from `TpsiUnavailableError`.
 *
 * Only ONE of these is the test-service window, and it is not the one that
 * looks like it. A timeout never means "outside the window": CR's test login
 * and balance endpoints answer 24/7 and only the FORM APIs are windowed, so a
 * call that never completed did not hit a closed one. Saying otherwise sent a
 * PROD operator away to wait until Monday for a network fault.
 */
const CR_UNAVAILABLE_HINTS = {
  test_window:
    'This deployment files against the Companies Registry TEST service, which '
    + 'answers Monday to Friday, 10:00–16:00 Hong Kong time. Try again inside '
    + 'that window.',
  unreachable:
    'The request to the Companies Registry did not complete — nothing was '
    + 'filed and nothing was charged. This is a connection fault, not a '
    + 'closed service window, so retrying shortly is reasonable. If it keeps '
    + 'happening, check CR Credentials and whether CR itself is up.',
  service_error:
    'The Companies Registry answered with an error of its own rather than a '
    + 'refusal of this return. Nothing was filed and nothing was charged. Try '
    + 'again shortly; if it persists it is CR-side.',
  malformed:
    'The Companies Registry answered with something this portal could not '
    + 'read. Nothing was filed and nothing was charged. Do not keep retrying — '
    + 'report it, because the reply needs looking at.',
  default:
    'The Companies Registry could not be used. Nothing was filed and nothing '
    + 'was charged.',
}

/**
 * A CR refusal recorded on the case, in `describeError`'s shape — or null.
 *
 * ONE ERROR SURFACE, NOT TWO (Levi 2026-08-31). A rejection used to be drawn
 * twice on the same screen: the page banner showed the request that had just
 * failed, and the stage's own FaultPanel showed the identical faults read back
 * off `form_status`. Two copies of one refusal read as two different problems,
 * and neither told you which to fix first.
 *
 * The banner is now the only place a CR refusal appears, which means it has to
 * be able to show one recorded EARLIER as well as one that just happened —
 * otherwise reloading the page leaves a "Rejected at validation" badge with no
 * reason anywhere on screen.
 */
const PERSISTED_FAILURES = {
  validation_failed: {
    message: 'The Companies Registry rejected this return.',
    hint: 'CR returns every problem at once, so fix them all before '
      + 're-validating. Nothing was charged — validateFormNar1 is free.',
  },
  signing_failed: {
    message: 'The Companies Registry refused the signature.',
    hint: CR_REFUSAL_HINTS.signature,
  },
  submission_failed: {
    message: 'The Companies Registry refused the submission.',
    hint: CR_REFUSAL_HINTS.default,
  },
}

export function persistedFailure(c) {
  const status = c?.form_status
  if (!status?.failed) return null
  // A banner with an empty list under it is worse than the badge alone.
  const problems = Array.isArray(status.faults) && status.faults.length
    ? status.faults : null
  if (!problems) return null
  const known = PERSISTED_FAILURES[status.code]
  return {
    message: known?.message || 'The Companies Registry refused this filing.',
    problems,
    // No `kind`: what CR sent is stored, but the classification `_handle` made
    // at the time is not, and inventing one here could bold "Account locked"
    // over a refusal that was nothing of the sort.
    kind: null,
    hint: known?.hint || CR_REFUSAL_HINTS.default,
    retry: false,
  }
}

/**
 * The three refusals the pre-submit gate can produce, in the operator's words.
 *
 * They are three different situations with three different remedies, and the
 * screen used to render all of them as one sentence spliced together with
 * colons and semicolons (Levi 2026-09-03). What each `message` must do is say
 * WHAT HAPPENED in one line; the evidence goes in the cards below it, and the
 * `remedy` says what to do next.
 *
 * `restart` is the load-bearing flag. Restarting verification rebuilds the
 * return from today's record — which fixes a mismatch and fixes an unfilable
 * record once the profile is corrected, and fixes NOTHING when the check
 * itself could not run. Offering it there sends someone to discard a
 * CR-signed snapshot for a problem discarding cannot touch.
 */
const GATE_REFUSALS = {
  drift: {
    message: 'The company record changed after this return was approved.',
    remedy: 'Check which record is right. If the company profile is the '
      + 'correct one, restart verification — that rebuilds the return from '
      + "today's record and sends it to the client to approve again.",
    restart: true,
  },
  record_unusable: {
    message: 'The company record can no longer produce a NAR1.',
    remedy: 'Correct these details on the company profile, then restart '
      + 'verification to rebuild the return. The Companies Registry would '
      + 'reject the filing as it stands, after taking the fee.',
    restart: true,
  },
  check_failed: {
    message: 'The return could not be checked against the company record.',
    remedy: 'Filing stays blocked until the check can run. Restarting '
      + 'verification will not help — this is not a problem with the return.',
    restart: false,
  },
}

export function describeError(err) {
  const message = err?.message || 'Something went wrong.'
  // Every specific reason the backend gathered, carried through so the caller
  // can list them all. `api.describeApiError` puts them here; without them a
  // 400 can only say "something is wrong somewhere", which is what the NAR1
  // workflow used to do.
  const problems = Array.isArray(err?.problems) && err.problems.length
    ? err.problems : null
  // Spec §6's field-by-field drift, carried the same way `problems` is. The
  // page renders one comparison card per entry; a sentence cannot show two
  // values per row.
  const differences = Array.isArray(err?.differences) && err.differences.length
    ? err.differences : null

  switch (err?.status) {
    case 400:
      return {
        message,
        problems,
        hint: problems
          ? null   // the list says it better than any sentence could
          : 'Correct the highlighted details and try again.',
        retry: false,
      }
    case 403:
      return { message, problems, hint: 'Your role does not allow this action.', retry: false }
    // 409 IS THE SUBMIT GATE, mostly. Four different refusals arrive here and
    // they used to share one hint — "The case is not in a state that allows
    // this yet" — printed underneath whatever the backend had said. Beneath a
    // message that already names the country code CR will not take, that
    // sentence is not a second piece of information; it is the same refusal,
    // said less well (Levi 2026-09-03).
    case 409: {
      // THE CASE IS OVER. Its own branch, above the gate, because every other
      // 409 on this screen describes something that can be put right — and
      // this one cannot. The backend's message already says what happened and
      // what to do instead (open a new case), so a second sentence underneath
      // it would only be the same refusal, said less well.
      if (err?.reason === 'case_closed') {
        return { message, problems: null, reason: 'case_closed',
                 hint: null, offerRestart: false, retry: false }
      }
      const gate = GATE_REFUSALS[err?.reason]
      if (gate) {
        return {
          // OUR headline, not the backend's. The gate's own message is a
          // developer sentence ("the company record has changed and can no
          // longer be made into a NAR1, so it was not submitted"); what the
          // operator needs on the first line is the situation, with the
          // detail in the cards below.
          message: gate.message,
          problems,
          differences,
          reason: err.reason,
          // Constant across all three, and first: an operator who has just
          // pressed a button marked "deducts HK$2,610" needs to know that did
          // not happen before they read anything else.
          reassurance: 'Nothing was sent to the Companies Registry and '
            + 'nothing was charged.',
          remedy: gate.remedy,
          offerRestart: gate.restart,
          hint: null,
          retry: false,
        }
      }
      return {
        message,
        problems,
        hint: /password/i.test(message)
          ? 'The shared TPSI password needs changing in Settings → CR Credentials before this can proceed.'
          // Only when the message did not already explain itself. The gate
          // says things like "filing is 'draft' — it must be signed", and a
          // generic restatement under a specific reason is noise.
          : (problems ? null : 'The case is not in a state that allows this yet.'),
        retry: false,
      }
    }
    // A CR REFUSAL. 422 since 2026-08-31, not 502: CR was reached and answered
    // — it just said no. While this was a 5xx, Cloudflare and Railway replaced
    // the JSON body with their own HTML error page, `api.js` fell back to
    // `resp.statusText`, and the operator read "Bad Gateway" where CR had
    // actually said "Br No does not exist."
    // An unlabelled refusal still lands here and still gets CR_REFUSAL_HINTS
    // .default — "do not simply retry" is the safe advice when we cannot tell
    // WHICH refusal it was, and it is the one this endpoint family can produce.
    // (FastAPI's own 422 for a malformed body would read a little
    // CR-flavoured, but that is a caller bug that should never reach an
    // operator, and the advice it gives is not harmful.)
    case 422:
      return {
        message,
        problems,
        kind: err?.kind || null,
        // Never auto-retry: CR locks an account after repeated auth failures,
        // and a chargeable submit must not be fired twice on a guess.
        //
        // The three refusals need three different remedies, in three different
        // places. Saying "fix what it reported" to someone whose CR account is
        // locked is advice they cannot act on, and repeating the attempt is
        // exactly what keeps it locked.
        hint: CR_REFUSAL_HINTS[err?.kind] || CR_REFUSAL_HINTS.default,
        retry: false,
      }
    // CR could not be REACHED, or refused our login — the transport failed
    // rather than the return. It must not claim CR rejected anything, and it
    // must NOT auto-retry: a repeated auth failure is exactly what makes CR
    // lock the account.
    case 502:
      return {
        message,
        problems,
        hint: 'The Companies Registry could not be reached. Nothing was filed and nothing was charged. If this repeats, stop — a repeated login failure is what locks a CR account.',
        retry: false,
      }
    // CR WAS NOT USABLE. Which is not one situation, and the remedies differ.
    //
    // This used to offer the test-service window unconditionally, so a PROD
    // operator whose call timed out was told to try again between 10:00 and
    // 16:00 on a weekday — advice for a window their deployment does not have.
    // The backend says which case this is (`TpsiUnavailableError.kind`),
    // because nothing on this side can: TPSI_ENV overrides APP_ENV so that
    // PROD may file against CR test during the pilot, and then the window DOES
    // apply to a portal whose header says nothing about being a test one.
    case 503:
      return {
        message,
        problems,
        kind: err?.kind || null,
        hint: CR_UNAVAILABLE_HINTS[err?.kind] || CR_UNAVAILABLE_HINTS.default,
        retry: true,
      }
    default:
      return { message, problems, hint: null, retry: true }
  }
}

/**
 * Stages whose XML may still be rebuilt from the live company record.
 * Mirrors `services/tpsi/filings.REBUILDABLE_STAGES` — the backend enforces it
 * inside the UPDATE; this only decides whether asking is worthwhile.
 */
const REBUILDABLE_STAGES = new Set(['draft', 'validation_failed'])

/**
 * Should the return be rebuilt before CR is asked again?
 *
 * Yes for a case with no filing, and for one CR has not validated. `validate`
 * re-sends the STORED request_xml, so re-validating without rebuilding sends
 * bytes CR has already refused and reports the same answer as though nothing
 * had been fixed.
 *
 * No once the snapshot is frozen: from `validated` onward the case reads its
 * own snapshot, and rewriting it under a client who has approved it is the
 * "show one document, file another" failure the verification gate exists to
 * prevent. `Restart verification` is how a snapshot is discarded.
 */
export function rebuildBeforeValidate(c) {
  if (!c?.filing_id) return true
  return REBUILDABLE_STAGES.has(c.form_status?.code)
}

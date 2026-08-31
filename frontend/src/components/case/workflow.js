/**
 * The NAR1 case workflow's shared rules — pure functions, no React.
 *
 * Extracted so the gate can be tested directly. The stage gate decides whether
 * a statutory return can be signed and filed, so it is the last thing that
 * should only be reachable through five rendered components.
 */

export const STAGE_LABELS = [
  'Data Verification',
  'Client Verification',
  'Signing',
  'Submission',
  'Confirmation',
]

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

export function isValidated(c) {
  return VALIDATED_STAGES.has(c.form_status?.code)
}

export function isSubmitted(c) {
  return Boolean(c.manual_submitted_at) || CR_HOLDS.has(c.form_status?.code)
}

/**
 * The furthest stage this case may enter. Mirrors v11's `cmReached()`.
 *
 * Note step 2: the manual path does NOT bypass Client Verification (OQ-4).
 * Signing a return on paper does not make the client's approval optional —
 * a statutory filing still goes out in the client's name.
 */
export function reachedStage(c) {
  if (!c) return 1
  if (!isValidated(c)) return 1
  if (!(c.verification_sent_at && c.client_approved)) return 2
  if (!signedOff(c)) return 3
  if (!isSubmitted(c)) return 4
  return 5
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
  if (CR_HOLDS.has(c.form_status?.code)) {
    return 'The Companies Registry already holds this return. Asking the '
      + 'client to approve it now is a request their answer cannot change.'
  }
  if (c.form_status?.code === 'validation_failed') {
    return 'The last validation of this return failed. Re-validate it on Data '
      + 'Verification before sending it to the client.'
  }
  if (!c.filing_id || !isValidated(c)) {
    return 'This return has not been validated by the Companies Registry yet. '
      + 'Validate it on Data Verification first — otherwise the client would '
      + 'be approving a form that may be rejected minutes later.'
  }
  return null
}

/** Is this stage's own work finished? Drives the green ticks. */
export function stageDone(c, i) {
  if (!c) return false
  switch (i) {
    case 1: return isValidated(c)
    case 2: return Boolean(c.client_approved)
    case 3: return signedOff(c)
    case 4: return isSubmitted(c)
    case 5: return c.form_status?.code === 'registered'
    default: return false
  }
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
  default:
    'The Companies Registry refused this. Fix what it reported — do not simply retry.',
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

export function describeError(err) {
  const message = err?.message || 'Something went wrong.'
  // Every specific reason the backend gathered, carried through so the caller
  // can list them all. `api.describeApiError` puts them here; without them a
  // 400 can only say "something is wrong somewhere", which is what the NAR1
  // workflow used to do.
  const problems = Array.isArray(err?.problems) && err.problems.length
    ? err.problems : null

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
    case 409:
      return {
        message,
        problems,
        hint: /password/i.test(message)
          ? 'The shared TPSI password needs changing in Settings → CR Credentials before this can proceed.'
          : 'The case is not in a state that allows this yet.',
        retry: false,
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
    case 503:
      return {
        message,
        problems,
        hint: 'The CR test service answers Monday to Friday, 10:00–16:00 Hong Kong time. Try again inside that window.',
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

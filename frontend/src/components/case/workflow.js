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
    case 502:
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

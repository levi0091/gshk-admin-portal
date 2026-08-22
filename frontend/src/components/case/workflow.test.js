import { describe, it, expect } from 'vitest'
import {
  STAGE_LABELS, reachedStage, stageDone, signedOff, isValidated, isSubmitted,
  describeError,
} from './workflow.js'

// A case at the very start: nothing validated, nothing sent, nothing signed.
const fresh = (over = {}) => ({
  id: 'c1', signing_method: null, form_status: null,
  verification_sent_at: null, client_approved: null,
  manual_submitted_at: null, ...over,
})

const withStage = (stage, over = {}) =>
  fresh({ form_status: { code: stage }, ...over })

describe('the stage gate', () => {
  it('has five stages', () => {
    expect(STAGE_LABELS).toHaveLength(5)
    expect(STAGE_LABELS[0]).toBe('Data Verification')
    expect(STAGE_LABELS[4]).toBe('Confirmation')
  })

  it('holds a brand-new case at Data Verification', () => {
    expect(reachedStage(fresh())).toBe(1)
  })

  it('will not let an unvalidated case reach Client Verification', () => {
    // Everything else is in place — only the CR snapshot is missing.
    const c = fresh({ verification_sent_at: '2026-08-01', client_approved: true })
    expect(reachedStage(c)).toBe(1)
  })

  it('opens Client Verification once CR has validated the return', () => {
    expect(reachedStage(withStage('validated'))).toBe(2)
  })

  it('will not let a case reach Signing until the CLIENT has approved', () => {
    // Sent but unanswered.
    expect(reachedStage(withStage('validated', { verification_sent_at: '2026-08-01' }))).toBe(2)
    // Answered NO.
    expect(reachedStage(withStage('validated', {
      verification_sent_at: '2026-08-01', client_approved: false,
    }))).toBe(2)
  })

  it('does NOT let the manual route bypass client approval (OQ-4)', () => {
    // Signing on paper does not make the client's approval optional — the
    // filing still goes out in the client's name.
    const c = withStage('validated', {
      signing_method: 'manual',
      manual_signed_document_id: 'doc-1',
      client_approved: false,
      verification_sent_at: '2026-08-01',
    })
    expect(reachedStage(c)).toBe(2)
  })

  const approved = over => withStage('validated', {
    verification_sent_at: '2026-08-01', client_approved: true, ...over,
  })

  it('opens Signing once the client has approved', () => {
    expect(reachedStage(approved())).toBe(3)
  })

  it('will not let an unsigned case reach Submission', () => {
    expect(reachedStage(approved())).toBe(3)
  })

  it('opens Submission when the e-Sign route has a CR signature', () => {
    const c = approved({ form_status: { code: 'signed' } })
    expect(reachedStage(c)).toBe(4)
  })

  it('opens Submission when the manual route has an uploaded signed form', () => {
    const c = approved({ signing_method: 'manual', manual_signed_document_id: 'doc-1' })
    expect(reachedStage(c)).toBe(4)
  })

  it('does not accept a CR signature as sign-off on the MANUAL route', () => {
    // A wet signature is not evidence for an e-filing and vice versa. A case
    // switched to manual needs the uploaded form, whatever CR once held.
    const c = approved({ signing_method: 'manual', form_status: { code: 'signed' } })
    expect(signedOff(c)).toBe(false)
    expect(reachedStage(c)).toBe(3)
  })

  it('reaches Confirmation once the return is filed, by either route', () => {
    expect(reachedStage(approved({ form_status: { code: 'submitted' } }))).toBe(5)
    expect(reachedStage(approved({
      signing_method: 'manual', manual_signed_document_id: 'd',
      manual_submitted_at: '2026-08-20T00:00:00Z',
    }))).toBe(5)
  })

  it('treats a null case as the very beginning rather than throwing', () => {
    expect(reachedStage(null)).toBe(1)
    expect(reachedStage(undefined)).toBe(1)
  })
})

describe('what counts as validated / signed / submitted', () => {
  it('counts every stage at or past validation as validated', () => {
    for (const s of ['validated', 'signed', 'submitted', 'registered', 'edrive']) {
      expect(isValidated(withStage(s)), s).toBe(true)
    }
  })

  it('does not count a draft or a failure as validated', () => {
    for (const s of ['draft', 'validation_failed', 'signing_failed', 'submission_failed']) {
      expect(isValidated(withStage(s)), s).toBe(false)
    }
  })

  it('counts a return CR already holds as submitted', () => {
    for (const s of ['submitted', 'registered', 'edrive']) {
      expect(isSubmitted(withStage(s)), s).toBe(true)
    }
    expect(isSubmitted(withStage('signed'))).toBe(false)
  })

  it('accepts either signed-document key on the manual route', () => {
    // The composite endpoint names the version explicitly; older payloads
    // carry only the id.
    expect(signedOff(fresh({ signing_method: 'manual', manual_signed_document_id: 'd' }))).toBe(true)
    expect(signedOff(fresh({ signing_method: 'manual', manual_signed_document_version: 2 }))).toBe(true)
    expect(signedOff(fresh({ signing_method: 'manual' }))).toBe(false)
  })
})

describe('stageDone — the green ticks', () => {
  it('ticks a stage only when its own work is finished', () => {
    const c = withStage('validated', {
      verification_sent_at: '2026-08-01', client_approved: true,
    })
    expect(stageDone(c, 1)).toBe(true)   // validated
    expect(stageDone(c, 2)).toBe(true)   // client said yes
    expect(stageDone(c, 3)).toBe(false)  // not signed
    expect(stageDone(c, 4)).toBe(false)  // not filed
    expect(stageDone(c, 5)).toBe(false)  // not registered
  })

  it('does not tick Client Verification when the client declined', () => {
    const c = withStage('validated', {
      verification_sent_at: '2026-08-01', client_approved: false,
    })
    expect(stageDone(c, 2)).toBe(false)
  })

  it('ticks Confirmation only once CR has registered the return', () => {
    expect(stageDone(withStage('submitted'), 5)).toBe(false)
    expect(stageDone(withStage('registered'), 5)).toBe(true)
  })
})

describe('describeError — four failures, four different actions', () => {
  const err = (status, message = 'boom') => Object.assign(new Error(message), { status })

  it('treats 400 as something to correct inline', () => {
    const d = describeError(err(400))
    expect(d.retry).toBe(false)
    expect(d.hint).toMatch(/correct/i)
  })

  it('points an expired TPSI password at Settings', () => {
    const d = describeError(err(409, 'TPSI password has expired'))
    expect(d.hint).toMatch(/CR Credentials/)
  })

  it('reads a non-password 409 as a state problem, not a password one', () => {
    const d = describeError(err(409, 'this case already has a recorded submission'))
    expect(d.hint).not.toMatch(/CR Credentials/)
  })

  it('NEVER offers to retry a CR fault', () => {
    // CR locks an account after repeated auth failures, and a chargeable submit
    // must not be fired twice on a guess.
    const d = describeError(err(502, 'form data has been tampered'))
    expect(d.retry).toBe(false)
    expect(d.hint).toMatch(/do not simply retry/i)
  })

  it('explains the CR TEST window on a 503, and allows a later retry', () => {
    const d = describeError(err(503))
    expect(d.retry).toBe(true)
    expect(d.hint).toMatch(/10:00–16:00/)
    expect(d.hint).toMatch(/Monday to Friday/)
  })

  it('says something useful for an error with no status at all', () => {
    const d = describeError(new Error('network down'))
    expect(d.message).toBe('network down')
    expect(d.retry).toBe(true)
  })
})

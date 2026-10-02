// Where an officer-change case is, for the stepper. Derived from the composite
// every render (GET /officer-changes/:id), never stored, so the page cannot
// drift from what the backend knows — the same rule the NAR1 page follows.
//
// The six stages are NAR1's (spec §5). What differs is how a case moves through
// stages 2-4: on the e-Sign route CR's filing stage moves it; on the manual
// route "Mark as checked" and the uploaded signed form do, because nothing is
// sent to CR until the operator records the filing made on CR's portal.
import { officerChangeCaps } from '../../lib/screenCapabilities.js'

export const STAGES = [
  'Client Verification',
  'Data Verification',
  'Signing',
  'Submission',
  'Confirmation',
  'CR Status',
]

export const FORM_TITLE = {
  Nd2a: 'Appointment / cessation of officers',
  Nd2b: 'Change of officer particulars',
}

const FILED_STAGES = new Set(['submitted', 'registered', 'edrive'])

export function isFiled(c) {
  return Boolean(c?.manual_receipt || c?.changes_applied_at
    || FILED_STAGES.has(c?.filing?.stage))
}

export function isClosed(c) {
  return Boolean(c?.closed_at)
}

export function isManual(c) {
  return c?.signing_method === 'manual'
}

/** The furthest stage the case has reached (1-based); 0 for a closed case. */
export function stageIndexFor(c) {
  if (!c || isClosed(c)) return 0
  // Filed reaches CR Status at once, as NAR1's `reachedStage` does: that is
  // where "Check now" lives, and Confirmation has no act that completes it.
  // A freshly filed case is often not listed by CR for days.
  if (isFiled(c)) return 6
  if (c.client_approved !== true) return 1
  if (isManual(c)) {
    if (c.manual_signed_document_id) return 4
    if (c.data_checked_at) return 3
    return 2
  }
  const stage = c.filing?.stage
  if (stage === 'signed') return 4
  if (stage === 'validated') return 3
  return 2
}

/** Stage `i` is finished (it gets the tick). */
export function stageDone(c, i) {
  if (!c || isClosed(c)) return false
  if (isFiled(c)) return i <= 5 || (i === 6 && c.cr_status?.code === 'cr_registered')
  return i < stageIndexFor(c)
}

/** Days to the filing deadline, as the header and the dashboard say it. */
export function deadlineText(deadline) {
  if (!deadline?.date) return null
  const days = deadline.days
  if (days == null) return null
  if (days < 0) return { text: `${-days} day${days === -1 ? '' : 's'} overdue`, overdue: true }
  if (days === 0) return { text: 'Due today', overdue: false }
  return { text: `Due in ${days} day${days === 1 ? '' : 's'}`, overdue: false }
}

/** Which permissions the stages read — `officerChangeCaps`, in the stages' words. */
export function capsFor(can) {
  const caps = officerChangeCaps(can)
  return {
    write: caps.editCase,
    tpsiWrite: caps.validate,
    tpsiSubmit: caps.submit,
    tpsiRead: caps.checkCrStatus,
  }
}

/** Where a case row opens: ND2A / ND2B on their own screen, NAR1 on its own. */
export function casePath(row) {
  const code = row?.form_code || ({ ND2A: 'Nd2a', ND2B: 'Nd2b' })[row?.case_type]
  return code === 'Nd2a' || code === 'Nd2b' ? `/officer-changes/${row.id}` : `/cases/${row.id}`
}

/** A refusal from the API as one short sentence plus any listed problems. */
export function errorOf(e) {
  const detail = e?.detail
  const message = (detail && typeof detail === 'object' ? detail.message : null)
    || e?.message || 'Something went wrong.'
  const problems = (detail && typeof detail === 'object' && Array.isArray(detail.problems))
    ? detail.problems : (Array.isArray(e?.problems) ? e.problems : [])
  return { message, problems }
}

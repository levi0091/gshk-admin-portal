/**
 * "Is a NAR1 case holding a frozen snapshot of this company's data?"
 *
 * Validation freezes an immutable snapshot: from that point the PDF the client
 * sees, the signature and the filing all read the snapshot, NOT the live
 * profile. So an edit to the profile after validation does not update the
 * return — it just makes the two disagree, silently, until someone compares a
 * receipt against a company record months later.
 *
 * The portal does not block the edit. The wireframe is explicit that the edit
 * is allowed and the case snapshot is untouched; what it requires is that the
 * operator be TOLD, and say so, before saving.
 *
 * One helper rather than a check per form, because Company Information,
 * addresses, officers, shareholders and share classes all feed the same return
 * — and a guard on four of five is a guard on none.
 */

//: Workflow states that mean a snapshot exists. `data_verification` does not:
//: nothing has been validated, so there is nothing to disagree with. Mirrors
//: services/nar1_case_status.py — a case is past data verification exactly
//: when its filing reached a live stage.
//: The five middle badges of nar1_case_status.WORKFLOW_STATUSES. The two that
//: are absent are absent deliberately: `data_verification` has no snapshot to
//: disagree with, and `completed` is filed and closed — warning about it would
//: train people to click through the warning.
const FROZEN = new Set([
  'client_verification',
  'awaiting_client',
  'client_rejected',
  'signing',
  'submission',
])

/** Workflow status arrives as a composite object OR a bare code string. */
function codeOf(status) {
  if (!status) return null
  return typeof status === 'string' ? status : status.code || null
}

/**
 * The cases that would disagree with an edit made now.
 * `completed` is excluded on purpose: that return is filed and closed, and
 * warning about it would train people to click through the warning.
 */
export function liveCases(company) {
  return (company?.cases?.nar1 || []).filter(c => FROZEN.has(codeOf(c.workflow_status)))
}

/** A sentence naming what is at stake, or null when nothing is. */
export function liveCaseWarning(company) {
  const live = liveCases(company)
  if (live.length === 0) return null

  const names = live.map(c => c.case_no).filter(Boolean)
  const label = names.length
    ? `${names.length === 1 ? 'Case' : 'Cases'} ${names.join(', ')}`
    : `${live.length} on-going NAR1 ${live.length === 1 ? 'case' : 'cases'}`
  const stage = live[0]?.workflow_status
  const stageLabel = typeof stage === 'object' ? stage?.label : null

  return {
    cases: live,
    title: 'This edit conflicts with a live case',
    body: `${label} ${live.length === 1 ? 'is' : 'are'} using a frozen snapshot ` +
      `of this company's data${stageLabel ? `, currently at ${stageLabel}` : ''}. ` +
      'Your edit changes the profile only — the case snapshot is not touched, ' +
      'so the return that was validated, sent to the client or filed with CR ' +
      'will no longer match this record. To change the return itself, restart ' +
      'verification on the case.',
  }
}

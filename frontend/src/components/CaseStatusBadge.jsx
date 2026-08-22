/**
 * The two NAR1 case status vocabularies — kept apart on purpose.
 *
 * `WorkflowBadge` answers "where is this case in GSHK's process" (7 values).
 * `FormBadge` answers "what has the Companies Registry done with the filing"
 * (10 stages). wireframe_v11 shows them side by side on the same row, and the
 * backend derives them from two different records (D-6, the single-writer
 * split: `tpsi_filings.stage` owns CR facts, `nar1_cases` owns client facts).
 *
 * Merging them loses information in both directions — a case can be at
 * "Signing" in our process while CR still holds nothing at all — so they get
 * separate class families (`bw-*` / `bf-*`) and separate components. Do not
 * collapse these into one badge.
 *
 * Labels mirror `services/nar1_case_status.WORKFLOW_LABELS` and
 * `services/tpsi/filings.FORM_STATUS_LABELS`. The backend already sends the
 * derived code; these maps only turn a code into wording and a colour.
 */

export const WORKFLOW_LABEL = {
  data_verification: 'Data Verification',
  client_verification: 'Client Verification',
  awaiting_client: 'Awaiting Client',
  client_rejected: 'Client Rejected',
  signing: 'Signing',
  submission: 'Submission',
  completed: 'Completed',
}

// Carrot = act on me · Indigo = waiting on someone else · Green = done
// · Red = refused. Same semantics as the dashboard filter tabs.
export const WORKFLOW_CLASS = {
  data_verification: 'bw-data',
  client_verification: 'bw-verify',
  awaiting_client: 'bw-awaiting',
  client_rejected: 'bw-rejected',
  signing: 'bw-sign',
  submission: 'bw-submit',
  completed: 'bw-done',
}

export const FORM_LABEL = {
  draft: 'Not yet sent to CR',
  validated: 'Validated by CR',
  validation_failed: 'Rejected at validation',
  signed: 'Signed',
  signing_failed: 'Rejected at signing',
  submitted: 'Filed with CR',
  submission_failed: 'Rejected at submission',
  registered: 'Registered by CR',
  superseded: 'Superseded by a later attempt',
  edrive: 'Sent to CR e-Drive',
}

// Ten stages, seven treatments: the three failure stages share one red, because
// what the reader needs at a glance is "CR refused it" — the label says at which
// step. `edrive` has no class of its own in v11 (R-2 removed the e-Drive option
// from the UI), but the backend can still carry the stage on an older filing,
// so it borrows the "reached CR" green and relies on its label to be precise.
export const FORM_CLASS = {
  draft: 'bf-draft',
  validated: 'bf-validated',
  validation_failed: 'bf-failed',
  signed: 'bf-signed',
  signing_failed: 'bf-failed',
  submitted: 'bf-submitted',
  submission_failed: 'bf-failed',
  registered: 'bf-registered',
  superseded: 'bf-superseded',
  edrive: 'bf-submitted',
}

export function WorkflowBadge({ status }) {
  if (!status) return <span className="td-muted">—</span>
  return (
    <span className={`badge ${WORKFLOW_CLASS[status] || 'bw-data'}`}>
      {WORKFLOW_LABEL[status] || status}
    </span>
  )
}

export function FormBadge({ stage }) {
  // No filing yet is a real, common state — the case exists before anything is
  // sent to CR — so it reads as an em dash, not as an error or a fake "draft".
  if (!stage) return <span className="td-muted">—</span>
  return (
    <span className={`badge ${FORM_CLASS[stage] || 'bf-draft'}`}>
      {FORM_LABEL[stage] || stage}
    </span>
  )
}

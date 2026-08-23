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

/**
 * The workflow badge.
 *
 * The backend sends a composite OBJECT, not a code: `badge_from_row()` on the
 * dashboard and `derive()` on the case screen both return
 * `{code, label, off_portal, overdue}`. Rendering that object directly is what
 * blanked admin-dev — React error #31, "Objects are not valid as a React
 * child", which unmounts the whole tree.
 *
 * A bare code string is still accepted: it is the shape a caller would
 * reasonably reach for, and being strict about it buys nothing.
 *
 * The server's `label` wins over the local map when present — the backend
 * derives the badge from two records and is the authority on what it says.
 * The map remains for a bare code and as the fallback.
 *
 * `off_portal` means the filing went to CR's e-Drive: finished, but not by us.
 * v11 has no badge for it (Levi 2026-08-02, e-Drive is not offered), so it is
 * shown as a marker beside the badge rather than a status of its own.
 * `overdue` is deliberately not rendered — migration 019 floors
 * days_to_anniversary at -42, so it is permanently false by design, and the
 * dashboard's own column states the overdue fact precisely.
 */
export function WorkflowBadge({ status }) {
  if (!status) return <span className="td-muted">—</span>

  const code = typeof status === 'string' ? status : status.code
  const label = (typeof status === 'string' ? null : status.label)
    || WORKFLOW_LABEL[code] || code
  const offPortal = typeof status === 'string' ? false : Boolean(status.off_portal)

  if (!code) return <span className="td-muted">—</span>

  return (
    <>
      <span className={`badge ${WORKFLOW_CLASS[code] || 'bw-data'}`}>{label}</span>
      {offPortal && (
        <span className="badge bf-superseded" title="Filed through CR's e-Drive, outside G-FlowDesk">
          Off-portal
        </span>
      )}
    </>
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

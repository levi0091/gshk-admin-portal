// Two vocabularies share this map because four of their codes are the same word
// meaning the same thing: `entity_status` (the Company Registry's Status
// column) and `case_status` (the dashboard's). The remaining codes are
// disjoint, so one lookup serves both. The dashboard's Status column FILTER
// reads its option labels from here too — a badge reading "draft" beside a
// checkbox reading "Draft" is one vocabulary pretending to be two.
export const STATUS_LABEL = {
  pre_incorporation: 'Pre-Incorporation', pending_aml: 'Pending AML',
  pending_client: 'Pending Client', to_verify: 'To Verify',
  revision_required: 'Revision Required', submitted_to_cr: 'Submitted to CR',
  cr_approved: 'CR Approved', client_approved: 'Client Approved',
  client_rejected: 'Client Rejected', live: 'Live', ceased: 'Ceased',
  // case_status (migration 003)
  draft: 'Draft', ready_to_submit: 'Ready to Submit', submitted: 'Submitted',
  approved: 'Approved', rejected: 'Rejected',
}

export const STATUS_CLASS = {
  pre_incorporation: 'b-pre-incorp', live: 'b-live', ceased: 'b-ceased',
  pending_aml: 'b-pending-aml', to_verify: 'b-to-verify',
  client_rejected: 'b-client-rejected', pending_client: 'b-pending-client',
  submitted_to_cr: 'b-submitted-cr', cr_approved: 'b-cr-approved',
  client_approved: 'b-cr-approved', revision_required: 'b-client-rejected',
  draft: 'b-ceased', ready_to_submit: 'b-to-verify',
  submitted: 'b-submitted-cr', approved: 'b-cr-approved',
  rejected: 'b-client-rejected',
}

/** Every `case_status` the enum can hold, in workflow order. */
export const CASE_STATUSES = [
  'draft', 'pending_aml', 'pending_client', 'to_verify', 'revision_required',
  'ready_to_submit', 'submitted', 'approved', 'rejected',
]

/** Every `entity_status` the enum can hold. */
export const ENTITY_STATUSES = [
  'pre_incorporation', 'pending_aml', 'pending_client', 'to_verify',
  'revision_required', 'submitted_to_cr', 'cr_approved', 'client_approved',
  'client_rejected', 'live', 'ceased',
]

/** `[{ value, label }]` for a column filter's checkbox list. */
export function statusOptions(codes) {
  return codes.map(value => ({ value, label: STATUS_LABEL[value] || value }))
}

export default function StatusBadge({ status }) {
  if (!status) return <span className="td-muted">—</span>
  return (
    <span className={`badge ${STATUS_CLASS[status] || 'b-ceased'}`}>
      {STATUS_LABEL[status] || status}
    </span>
  )
}

/** Is Client / Is Corporate Party pills (Company Registry). */
export function FlagBadges({ isClient, isCorporateParty }) {
  if (!isClient && !isCorporateParty) return <span className="td-muted">—</span>
  return (
    <>
      {isClient && <span className="reg-badge reg-badge-client">Client</span>}
      {isCorporateParty && <span className="reg-badge reg-badge-corp">Corporate Party</span>}
    </>
  )
}

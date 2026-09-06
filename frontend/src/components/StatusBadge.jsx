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

/**
 * What a COMPANY's status can be, as opposed to what the column can hold.
 *
 * Levi 2026-09-04: "this is company status so some of these values dont make
 * sense". He is right — `entity_status` is one column doing two jobs. Three of
 * its values describe a company (not yet incorporated, on the register, struck
 * off); the other eight describe how far an INCORPORATION got, and a company
 * only wears one of those before it exists. Offering "Pending AML" as a company
 * status invites a question the register cannot answer.
 *
 * The picker shows these three. The SERVER still accepts all eleven
 * (`routers/companies._ALL_STATUSES`), because they are the column's real
 * domain and refusing a legal value would make a stored row unfindable through
 * an API that has no other way to name it. Measured on DEV the day this
 * shipped: 5,985 live, 12 ceased, 1 pre-incorporation, and not one row in any
 * of the other eight.
 *
 * `ENTITY_STATUSES` — a second copy of all eleven — used to sit here and went
 * with this change: nothing read it once the picker narrowed, and a duplicated
 * enum domain is a list that goes stale unnoticed. `STATUS_LABEL` above still
 * labels all eleven, because a company stored in one of them must still render
 * its badge.
 */
export const COMPANY_STATUSES = ['live', 'pre_incorporation', 'ceased']

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

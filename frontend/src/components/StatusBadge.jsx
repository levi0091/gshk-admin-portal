export const STATUS_LABEL = {
  pre_incorporation: 'Pre-Incorporation', pending_aml: 'Pending AML',
  pending_client: 'Pending Client', to_verify: 'To Verify',
  revision_required: 'Revision Required', submitted_to_cr: 'Submitted to CR',
  cr_approved: 'CR Approved', client_approved: 'Client Approved',
  client_rejected: 'Client Rejected', live: 'Live', ceased: 'Ceased',
}

export const STATUS_CLASS = {
  pre_incorporation: 'b-pre-incorp', live: 'b-live', ceased: 'b-ceased',
  pending_aml: 'b-pending-aml', to_verify: 'b-to-verify',
  client_rejected: 'b-client-rejected', pending_client: 'b-pending-client',
  submitted_to_cr: 'b-submitted-cr', cr_approved: 'b-cr-approved',
  client_approved: 'b-cr-approved', revision_required: 'b-client-rejected',
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

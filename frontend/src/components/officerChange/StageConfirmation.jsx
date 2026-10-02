import ProfileChangesList from './ProfileChangesList.jsx'
import { formatDateTime } from '../../lib/format.js'

/**
 * Stage 5 (answer 13): CR's receipt, and in the past tense what was written to
 * the profiles and which supporting documents were saved where.
 */
export default function StageConfirmation({ data, goTo }) {
  const receipt = data.receipt || data.manual_receipt || {}
  return (
    <>
      <div className="card">
        <div className="card-title">Filed with the Companies Registry</div>
        <div className="kv-row"><span className="kv-key">CR case number</span>
          <span className="kv-val">{receipt.caseNo || '—'}</span></div>
        <div className="kv-row"><span className="kv-key">Transaction date</span>
          <span className="kv-val">{receipt.transactionDate || '—'}
            {receipt.transactionTime ? ` ${receipt.transactionTime}` : ''}</span></div>
        {receipt.refNo && <div className="kv-row"><span className="kv-key">Document reference</span>
          <span className="kv-val">{receipt.refNo}</span></div>}
        <div className="kv-row"><span className="kv-key">Route</span>
          <span className="kv-val">{data.signing_method === 'manual' ? 'Manual (CR portal)' : 'e-Sign via CR'}</span></div>
        {data.applied_at && <div className="kv-row"><span className="kv-key">Profiles updated</span>
          <span className="kv-val">{formatDateTime(data.applied_at)}</span></div>}
      </div>
      <ProfileChangesList changes={data.profile_changes} documents={data.documents} done />
      <div className="oc-send-row">
        <button className="btn btn-primary" onClick={() => goTo(6)}>Continue to CR Status →</button>
      </div>
    </>
  )
}
